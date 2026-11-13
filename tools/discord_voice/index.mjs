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

const guildId = process.env.MARONG_DISCORD_GUILD_ID;
const channelId = process.env.MARONG_DISCORD_VOICE_CHANNEL_ID;
const ownerId = process.env.MARONG_DISCORD_VOICE_USER_ID;
const appId = process.env.MARONG_DISCORD_APP_ID;
if (![guildId, channelId, ownerId, appId].every(id => /^[1-9][0-9]{16,19}$/.test(id ?? ''))) {
  throw new Error('invalid Discord voice configuration');
}

const RELAY = 'ws+unix:///run/marong-discord-voice/live.sock:/live';
const SOCKET = '/run/marong-discord-voice/live.sock';
const client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates] });
let current = null;
let clientId = randomUUID();
let retry = null;
let stopping = false;
let guildAvailable = false;
let callStarted = false;

function log(event, fields = {}) {
  console.info(JSON.stringify({ event, ...fields }));
}

function eligible(guild) {
  if (stopping || !guildAvailable || !guild?.available) return false;
  if (guild.voiceStates.cache.get(ownerId)?.channelId !== channelId) return false;
  return !guild.voiceStates.cache.some(state =>
    state.channelId === channelId && state.id !== ownerId && state.id !== appId);
}

function headersFor(id) {
  return { 'X-Marong-Client-Id': id, 'X-Marong-Discord-User': ownerId,
    'X-Marong-Discord-Guild': guildId, 'X-Marong-Discord-Channel': channelId };
}

function finishCall(id) {
  const end = request({ socketPath: SOCKET, path: '/end', method: 'POST',
    headers: headersFor(id), timeout: 12_000 }, response => {
    response.resume();
    if (response.statusCode !== 204) log('relay_finish_failed', { status: response.statusCode });
  });
  end.on('timeout', () => end.destroy());
  end.on('error', () => log('relay_finish_failed'));
  end.end();
}

function schedule(guild, ms = 2_000) {
  if (retry !== null || current || !eligible(guild)) return;
  retry = setTimeout(() => {
    retry = null;
    reconcile(guild);
  }, ms);
}

function close(session, reason, explicit = false) {
  if (session.closed) return;
  session.closed = true;
  clearInterval(session.padding);
  clearTimeout(session.voiceLoss);
  clearTimeout(session.providerSetup);
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
  if (current === session) current = null;
  schedule(session.guild);
}

function sendMic(session, frame) {
  const ws = session.ws;
  if (!session.providerReady || !eligible(session.guild) || ws?.readyState !== WebSocket.OPEN) return;
  if (ws.bufferedAmount > 12_800) {
    session.counts.input_drops++;
    return;
  }
  ws.send(frame, { binary: true });
}

function attachInput(session) {
  const input = session.connection.receiver.subscribe(ownerId);
  session.input = input;
  input.on('data', (opus) => {
    if (session.closed || !eligible(session.guild)) return;
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

function attachRelay(session) {
  const ws = new WebSocket(RELAY, {
    headers: headersFor(session.clientId), handshakeTimeout: 5_000, maxPayload: 256_000,
  });
  session.ws = ws;
  session.providerSetup = setTimeout(() => {
    if (!session.providerReady) close(session, 'vertex_not_ready');
  }, 40_000);
  ws.on('message', (data, binary) => {
    if (session.closed || !eligible(session.guild)) return;
    if (binary) {
      if (++session.counts.vertex_chunks === 1) log('vertex_audio_received');
      session.playback.add(data);
      return;
    }
    let item;
    try { item = JSON.parse(data); } catch { return; }
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

async function begin(guild) {
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
  const session = { guild, connection, encoder, decoder, playback, player, counts, clientId,
    lastMic: -Infinity, providerReady: false, closed: false };
  current = session;
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
    if (session.closed || !eligible(guild)) return close(session, 'no_participant');
    if (!connection.voicePrivacyCode) {
      // DAVE may complete immediately after the transport becomes ready.
      for (let attempt = 0; attempt < 15 && !connection.voicePrivacyCode && !session.closed; attempt++) {
        await delay(200);
      }
    }
    if (session.closed || !eligible(guild)) return close(session, 'no_participant');
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

function reconcile(guild) {
  if (guild?.id !== guildId) return;
  if (!eligible(guild)) {
    clearTimeout(retry);
    retry = null;
    const left = guildAvailable && guild.available &&
      guild.voiceStates.cache.get(ownerId)?.channelId !== channelId;
    if (current) close(current, left ? 'participant_left' : 'voice_paused', left);
    if (left && callStarted) {
      finishCall(clientId);
      clientId = randomUUID();
      callStarted = false;
    }
    return;
  }
  if (!current && retry === null) {
    callStarted = true;
    begin(guild).catch(() => {
      if (current) close(current, 'voice_failed');
      else schedule(guild);
    });
  }
}

client.once(Events.ClientReady, async ready => {
  try {
    if (ready.user.id !== appId) throw new Error('unexpected bot');
    const guild = ready.guilds.cache.get(guildId);
    const channel = guild?.channels.cache.get(channelId);
    const permissions = channel?.permissionsFor(ready.user.id);
    if (!channel?.isVoiceBased() || !permissions?.has([
      PermissionFlagsBits.ViewChannel, PermissionFlagsBits.Connect, PermissionFlagsBits.Speak,
    ])) throw new Error('missing voice permissions');
    guildAvailable = true;
    log('discord_voice_gateway_ready');
    reconcile(guild);
  } catch {
    log('discord_voice_configuration_error');
    ready.destroy();
    process.exitCode = 1;
  }
});
client.on(Events.VoiceStateUpdate, (before, after) => {
  if (after.guild.id !== guildId) return;
  if (after.id !== appId && (before.channelId === channelId || after.channelId === channelId)) reconcile(after.guild);
});
client.on(Events.ShardDisconnect, () => {
  guildAvailable = false;
  reconcile(client.guilds.cache.get(guildId));
});
function gatewayAvailable() {
  guildAvailable = true;
  reconcile(client.guilds.cache.get(guildId));
}
client.on(Events.ShardResume, gatewayAvailable);
client.on(Events.ShardReady, () => {
  if (client.isReady()) gatewayAvailable();
});
client.on(Events.GuildUnavailable, guild => {
  if (guild.id === guildId) reconcile(guild);
});
client.on(Events.GuildAvailable, reconcile);
client.on(Events.Error, () => log('discord_gateway_error'));

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => {
    stopping = true;
    clearTimeout(retry);
    if (current) close(current, 'service_stop');
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
