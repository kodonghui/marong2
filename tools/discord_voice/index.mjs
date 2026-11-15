import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { request } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import {
  AudioPlayerStatus, NoSubscriberBehavior, StreamType, VoiceConnectionStatus,
  createAudioPlayer, createAudioResource, entersState, joinVoiceChannel,
} from '@discordjs/voice';
import { Client, Events, GatewayIntentBits, PermissionFlagsBits } from 'discord.js';
import OpusScript from 'opusscript';
import WebSocket from 'ws';
import { CallPlayback, DISCORD_FRAME_BYTES, FRAME_MS, microphonePcm } from './audio.mjs';

const appId = process.env.MARONG_DISCORD_APP_ID;
const configured = JSON.parse(process.env.MARONG_DISCORD_VOICE_ROOMS ?? 'null');
const idFields = ['guild_id', 'channel_id', 'user_id'];
const validId = id => typeof id === 'string' && /^[1-9][0-9]{16,19}$/.test(id);
if (!validId(appId) || !Array.isArray(configured) || !configured.length ||
    configured.some(room => !room || Object.keys(room).length !== idFields.length ||
      idFields.some(field => !validId(room[field]))) ||
    idFields.some(field => new Set(configured.map(room => room[field])).size !== configured.length)) {
  throw new Error('invalid Discord voice configuration');
}
const rooms = new Map(configured.map(({ guild_id, channel_id, user_id }) =>
  [guild_id, { guildId: guild_id, channelId: channel_id, ownerId: user_id,
    current: null, clientId: randomUUID(), retry: null, joining: false, callStarted: false, hungUp: false }]));

const RELAY = 'ws+unix:///run/marong-discord-voice/live.sock:/live';
const SOCKET = '/run/marong-discord-voice/live.sock';
const client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates] });
let stopping = false;
let gatewayReady = false;

function log(event, fields = {}) {
  console.info(JSON.stringify({ event, ...fields }));
}

function eligible(guild, { ownerId, channelId }) {
  if (stopping || !gatewayReady || !guild?.available) return false;
  if (guild.voiceStates.cache.get(ownerId)?.channelId !== channelId) return false;
  return !guild.voiceStates.cache.some(state =>
    state.channelId === channelId && state.id !== ownerId && state.id !== appId);
}

function headersFor({ ownerId, guildId, channelId }, id) {
  return { 'X-Marong-Client-Id': id, 'X-Marong-Discord-User': ownerId,
    'X-Marong-Discord-Guild': guildId, 'X-Marong-Discord-Channel': channelId };
}

function finishCall(room, id) {
  const end = request({ socketPath: SOCKET, path: '/end', method: 'POST',
    headers: headersFor(room, id), timeout: 12_000 }, response => {
    response.resume();
    if (response.statusCode !== 204) log('relay_finish_failed', { status: response.statusCode });
  });
  end.on('timeout', () => end.destroy());
  end.on('error', () => log('relay_finish_failed'));
  end.end();
}

function available(room) {
  return new Promise(resolve => {
    const check = request({ socketPath: SOCKET, path: '/available', method: 'GET',
      headers: headersFor(room, room.clientId), timeout: 5_000 }, response => {
      response.resume();
      resolve(response.statusCode === 204);
    });
    check.on('timeout', () => check.destroy());
    check.on('error', () => resolve(false));
    check.end();
  });
}

function schedule(guild, room, ms = 2_000) {
  if (room.hungUp || room.retry !== null || room.current || !eligible(guild, room)) return;
  room.retry = setTimeout(() => {
    room.retry = null;
    reconcile(guild);
  }, ms);
}

function close(session, reason, explicit = false) {
  if (session.closed) return;
  session.closed = true;
  clearInterval(session.padding);
  clearTimeout(session.voiceLoss);
  clearTimeout(session.providerSetup);
  clearTimeout(session.hangupTimer);
  session.input?.destroy();
  session.player.stop(true);
  session.playback.destroy();
  session.encoder.delete();
  session.decoder.delete();
  if (session.connection.state.status !== VoiceConnectionStatus.Destroyed) session.connection.destroy();
  if (session.ws?.readyState === WebSocket.OPEN) {
    if (explicit) session.ws.send(JSON.stringify({ type: 'stop' }));
    session.ws.close();
  } else session.ws?.terminate();
  log('voice_ended', { reason, ...session.counts });
  if (session.room.current === session) session.room.current = null;
  schedule(session.guild, session.room);
}

function sendMic(session, frame) {
  const ws = session.ws;
  if (session.hangingUp || !session.providerReady || !eligible(session.guild, session.room) || ws?.readyState !== WebSocket.OPEN) return;
  if (ws.bufferedAmount > 12_800) {
    session.counts.input_drops++;
    return;
  }
  ws.send(frame, { binary: true });
}

function attachInput(session) {
  const input = session.connection.receiver.subscribe(session.room.ownerId);
  session.input = input;
  input.on('data', (opus) => {
    if (session.closed || !eligible(session.guild, session.room)) return;
    let pcm;
    try {
      pcm = microphonePcm(Buffer.from(session.decoder.decode(opus)));
    } catch {
      session.counts.decode_errors++;
      return;
    }
    if (!pcm.length) return;
    session.lastMic = performance.now();
    if (++session.counts.decoded === 1) log('discord_microphone_received');
    sendMic(session, pcm);
  });
  input.on('error', () => {
    if (!session.closed) close(session, 'discord_receive_failed');
  });

  // Discord may stop emitting Opus when the user stops speaking. Real-time
  // silence lets Vertex's existing server VAD finish that turn.
  const silence = Buffer.alloc(640);
  session.padding = setInterval(() => {
    const elapsed = performance.now() - session.lastMic;
    if (elapsed >= FRAME_MS * 1.5 && elapsed < 1_000) sendMic(session, silence);
  }, FRAME_MS);
}

// Marong ends the call when the owner asked for it (the relay checks the
// words). Let the goodbye play out, leave, and stay out until the owner leaves
// the room: entering it again starts the next call.
function hangUp(session) {
  if (session.closed || session.hangingUp) return;
  session.hangingUp = true;
  const { room } = session;
  room.hungUp = true;
  const started = performance.now();
  const check = () => {
    session.hangupTimer = null;
    if (session.closed) return;
    // A late goodbye chunk reopens the turn; play it without waiting for more.
    session.playback.finish();
    const waited = performance.now() - started;
    if (!(session.playback.idle && waited >= 300) && waited < 15_000) {
      session.hangupTimer = setTimeout(check, 100);
      return;
    }
    // Discord clients still hold a few frames after the last one is sent.
    session.hangupTimer = setTimeout(() => {
      if (session.closed) return;
      close(session, 'marong_hung_up', true);
      room.clientId = randomUUID();
      room.callStarted = false;
    }, 400);
  };
  check();
}

function attachRelay(session) {
  const ws = new WebSocket(RELAY, {
    headers: { ...headersFor(session.room, session.clientId), 'X-Marong-Hangup': '1' },
    handshakeTimeout: 5_000, maxPayload: 256_000,
  });
  session.ws = ws;
  session.providerSetup = setTimeout(() => {
    if (!session.providerReady) close(session, 'vertex_not_ready');
  }, 40_000);
  ws.on('message', (data, binary) => {
    if (session.closed || !eligible(session.guild, session.room)) return;
    if (binary) {
      if (++session.counts.vertex_chunks === 1) log('vertex_audio_received');
      session.playback.add(data);
      return;
    }
    let item;
    try { item = JSON.parse(data); } catch { return; }
    if (item.type === 'call_busy') return close(session, 'caller_busy');
    if (item.type === 'hangup') return hangUp(session);
    if (item.type === 'audio_reset' || item.type === 'interrupted') {
      session.playback.clear(item.epoch);
      return;
    }
    if (item.type === 'audio_end') session.playback.finish();
    if (item.type === 'ready') {
      session.providerReady = true;
      clearTimeout(session.providerSetup);
      log('vertex_ready', { resumed: Boolean(item.resumed), memory: Boolean(item.memoryConnected) });
    }
    if (item.type === 'reconnecting') session.providerReady = false;
  });
  ws.on('unexpected-response', (_request, response) => {
    response.resume();
    log('relay_rejected', { status: response.statusCode });
    close(session, 'relay_rejected');
  });
  ws.on('error', () => close(session, 'relay_error'));
  ws.on('close', () => close(session, 'relay_closed'));
}

function canJoin(guild, room) {
  const channel = guild?.channels.cache.get(room.channelId);
  return channel?.isVoiceBased() && channel.permissionsFor(appId)?.has([
    PermissionFlagsBits.ViewChannel, PermissionFlagsBits.Connect, PermissionFlagsBits.Speak,
  ]);
}

async function begin(guild, room) {
  const { guildId, channelId, clientId } = room;
  const connection = joinVoiceChannel({ guildId, channelId, adapterCreator: guild.voiceAdapterCreator,
    selfDeaf: false, selfMute: false, daveEncryption: true });
  const encoder = new OpusScript(48_000, 2, OpusScript.Application.AUDIO);
  const decoder = new OpusScript(48_000, 2, OpusScript.Application.VOIP);
  const player = createAudioPlayer({ behaviors: { noSubscriber: NoSubscriberBehavior.Stop } });
  const counts = { decoded: 0, decode_errors: 0, vertex_chunks: 0, frames: 0, input_drops: 0,
    output_overflow: 0, output_underflow: 0, turn_played: 0 };
  const playback = new CallPlayback(frame => {
    if (frame.some(value => value !== 0) && ++counts.frames === 1) log('discord_playback_started');
    return Buffer.from(encoder.encode(frame, DISCORD_FRAME_BYTES / 4));
  }, metric => {
    counts[metric]++;
    if (metric === 'turn_played' && counts[metric] === 1) log('discord_first_turn_played');
  });
  const session = { guild, room, connection, encoder, decoder, playback, player, counts, clientId,
    lastMic: -Infinity, providerReady: false, closed: false };
  room.current = session;
  player.on('error', () => close(session, 'discord_playback_failed'));
  playback.on('error', () => close(session, 'audio_encoding_failed'));
  connection.on('error', error => {
    log('discord_voice_error', { code: typeof error.code === 'number' ? error.code : undefined });
  });
  connection.on('stateChange', (_, state) => {
    if (session.closed) return;
    if (state.status === VoiceConnectionStatus.Ready) {
      clearTimeout(session.voiceLoss);
      session.voiceLoss = null;
      log('discord_voice_ready', { dave: Boolean(connection.voicePrivacyCode) });
    } else if (state.status === VoiceConnectionStatus.Disconnected && !session.voiceLoss) {
      session.voiceLoss = setTimeout(() => {
        if (connection.state.status !== VoiceConnectionStatus.Ready) close(session, 'discord_voice_lost');
      }, 8_000);
    }
  });
  try {
    await entersState(connection, VoiceConnectionStatus.Ready, 20_000);
    if (session.closed || !eligible(guild, room)) return close(session, 'no_participant');
    if (!connection.voicePrivacyCode) {
      // DAVE may complete immediately after the transport becomes ready.
      for (let attempt = 0; attempt < 15 && !connection.voicePrivacyCode && !session.closed; attempt++) {
        await delay(200);
      }
    }
    if (session.closed || !eligible(guild, room)) return close(session, 'no_participant');
    if (!connection.voicePrivacyCode) return close(session, 'dave_not_ready');
    const subscription = connection.subscribe(player);
    if (!subscription) return close(session, 'discord_subscribe_failed');
    player.play(createAudioResource(playback, { inputType: StreamType.Opus }));
    if (player.state.status === AudioPlayerStatus.Idle) return close(session, 'discord_playback_idle');
    attachInput(session);
    attachRelay(session);
    log('discord_dave_ready');
  } catch {
    close(session, 'discord_join_failed');
  }
}

async function startWhenAvailable(guild, room) {
  room.joining = true;
  const clientId = room.clientId;
  try {
    if (!canJoin(guild, room) || !await available(room)) return;
    if (!eligible(guild, room) || room.clientId !== clientId) return;
    room.callStarted = true;
    await begin(guild, room);
  } catch {
    if (room.current) close(room.current, 'voice_failed');
  } finally {
    room.joining = false;
    schedule(guild, room, 5_000);
  }
}

function reconcile(guild) {
  const room = rooms.get(guild?.id);
  if (!room) return;
  if (!eligible(guild, room)) {
    clearTimeout(room.retry);
    room.retry = null;
    const left = gatewayReady && guild.available &&
      guild.voiceStates.cache.get(room.ownerId)?.channelId !== room.channelId;
    if (left) room.hungUp = false;
    if (room.current) close(room.current, left ? 'participant_left' : 'voice_paused', left);
    if (left && (room.callStarted || room.joining)) {
      if (room.callStarted) finishCall(room, room.clientId);
      room.clientId = randomUUID();
      room.callStarted = false;
    }
    return;
  }
  // After Marong hung up, the owner leaves and enters the room again to call.
  if (room.hungUp) return;
  if (!room.current && !room.joining && room.retry === null) void startWhenAvailable(guild, room);
}

client.once(Events.ClientReady, ready => {
  try {
    if (ready.user.id !== appId) throw new Error('unexpected bot');
    const readyRooms = [...rooms.values()].filter(room => canJoin(ready.guilds.cache.get(room.guildId), room)).length;
    if (!readyRooms) throw new Error('missing voice permissions');
    log('discord_voice_gateway_ready', { rooms: readyRooms, configured: rooms.size });
    gatewayAvailable();
  } catch {
    log('discord_voice_configuration_error');
    ready.destroy();
    process.exitCode = 1;
  }
});
client.on(Events.VoiceStateUpdate, (before, after) => {
  const room = rooms.get(after.guild.id);
  if (!room) return;
  if (after.id !== appId && (before.channelId === room.channelId || after.channelId === room.channelId)) reconcile(after.guild);
});
client.on(Events.ShardDisconnect, () => {
  gatewayReady = false;
  for (const guildId of rooms.keys()) reconcile(client.guilds.cache.get(guildId));
});
function gatewayAvailable() {
  gatewayReady = true;
  for (const guildId of rooms.keys()) reconcile(client.guilds.cache.get(guildId));
}
client.on(Events.ShardResume, gatewayAvailable);
client.on(Events.ShardReady, () => {
  if (client.isReady()) gatewayAvailable();
});
client.on(Events.GuildUnavailable, reconcile);
client.on(Events.GuildAvailable, reconcile);
client.on(Events.GuildDelete, guild => {
  const room = rooms.get(guild.id);
  if (!room) return;
  clearTimeout(room.retry);
  room.retry = null;
  if (room.current) close(room.current, 'guild_removed');
});
client.on(Events.Error, () => log('discord_gateway_error'));

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => {
    stopping = true;
    for (const room of rooms.values()) {
      clearTimeout(room.retry);
      if (room.current) close(room.current, 'service_stop');
    }
    client.destroy();
  });
}

try {
  const token = (await readFile(`${process.env.CREDENTIALS_DIRECTORY}/discord-token`, 'ascii')).trim();
  await client.login(token);
} catch {
  log('discord_voice_login_failed');
  client.destroy();
  process.exitCode = 1;
}
