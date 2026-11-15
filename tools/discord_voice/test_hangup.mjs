// The Discord bot's side of Marong's hang-up, with Discord, the relay and Opus
// replaced by small fakes: no network, token or audio device is used.
// After the relay's 'hangup' the bot stops sending the microphone, plays the
// goodbye out, ends the call with 'stop', leaves the room and stays out until
// the owner leaves and enters again.
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { register } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as wait } from 'node:timers/promises';

const fakes = {
  'discord.js': `import { EventEmitter } from 'node:events';
    export const Events = { ClientReady: 'ready', VoiceStateUpdate: 'voiceStateUpdate', ShardDisconnect: 'shardDisconnect',
      ShardResume: 'shardResume', ShardReady: 'shardReady', GuildUnavailable: 'guildUnavailable',
      GuildAvailable: 'guildAvailable', GuildDelete: 'guildDelete', Error: 'error' };
    export const GatewayIntentBits = { Guilds: 1, GuildVoiceStates: 2 };
    export const PermissionFlagsBits = { ViewChannel: 1n, Connect: 2n, Speak: 4n };
    export class Client extends EventEmitter {
      constructor() { super(); this.guilds = { cache: new Map() }; globalThis.fake.client = this; }
      async login() {} isReady() { return true; } destroy() {}
    }`,
  '@discordjs/voice': `import { EventEmitter } from 'node:events';
    export const VoiceConnectionStatus = { Ready: 'ready', Disconnected: 'disconnected', Destroyed: 'destroyed' };
    export const AudioPlayerStatus = { Idle: 'idle' };
    export const NoSubscriberBehavior = { Stop: 'stop' };
    export const StreamType = { Opus: 'opus' };
    export async function entersState() {}
    export function joinVoiceChannel(options) {
      const connection = new EventEmitter();
      const input = new EventEmitter(); input.destroy = () => {};
      Object.assign(connection, { state: { status: 'ready' }, voicePrivacyCode: '1234', subscribe: () => ({}),
        receiver: { subscribe: () => input },
        destroy() { connection.state = { status: 'destroyed' }; globalThis.fake.left.push(options.channelId); } });
      globalThis.fake.joined.push({ channel: options.channelId, input });
      return connection;
    }
    export function createAudioPlayer() {
      const player = new EventEmitter();
      return Object.assign(player, { state: { status: 'playing' }, play() {}, stop() {} });
    }
    export function createAudioResource(stream) { globalThis.fake.playbacks.push(stream); return {}; }`,
  'opusscript': `export default class OpusScript {
      static Application = { AUDIO: 1, VOIP: 2 };
      encode(frame) { return frame; } decode(packet) { return packet; } delete() {}
    }`,
  'ws': `import { EventEmitter } from 'node:events';
    export default class WebSocket extends EventEmitter {
      static OPEN = 1;
      constructor(url, options) { super(); Object.assign(this, { url, options, readyState: 1, bufferedAmount: 0, sent: [] });
        globalThis.fake.sockets.push(this); }
      send(data) { this.sent.push(data); } close() { this.readyState = 3; } terminate() { this.readyState = 3; }
    }`,
  'node:http': `import { EventEmitter } from 'node:events';
    export function request(options, respond) {
      const outgoing = new EventEmitter();
      outgoing.destroy = () => {};
      outgoing.end = () => { globalThis.fake.requests.push(options.path);
        queueMicrotask(() => respond({ statusCode: 204, resume() {} })); };
      return outgoing;
    }`,
};
const urls = Object.fromEntries(Object.entries(fakes).map(([name, code]) =>
  [name, 'data:text/javascript,' + encodeURIComponent(code)]));
register('data:text/javascript,' + encodeURIComponent(`
  const urls = ${JSON.stringify(urls)};
  export async function resolve(specifier, context, next) {
    if (urls[specifier] && context.parentURL?.endsWith('/index.mjs')) return { url: urls[specifier], shortCircuit: true };
    return next(specifier, context);
  }`));

const APP = '100000000000000001', GUILD = '100000000000000011', CHANNEL = '100000000000000012', OWNER = '100000000000000013';
globalThis.fake = { joined: [], left: [], sockets: [], playbacks: [], requests: [] };
const credentials = mkdtempSync(join(tmpdir(), 'marong-voice-'));
writeFileSync(join(credentials, 'discord-token'), 'synthetic');
Object.assign(process.env, { MARONG_DISCORD_APP_ID: APP, CREDENTIALS_DIRECTORY: credentials,
  MARONG_DISCORD_VOICE_ROOMS: JSON.stringify([{ guild_id: GUILD, channel_id: CHANNEL, user_id: OWNER }]) });
console.info = () => {};
await import('./index.mjs');

class States extends Map { some(test) { return [...this.values()].some(test); } }
const channel = { isVoiceBased: () => true, permissionsFor: () => ({ has: () => true }) };
const guild = { id: GUILD, available: true, voiceStates: { cache: new States() },
  channels: { cache: new Map([[CHANNEL, channel]]) }, voiceAdapterCreator: {} };
const { client } = globalThis.fake;
client.guilds.cache.set(GUILD, guild);
const move = channelId => {
  const before = guild.voiceStates.cache.get(OWNER) ?? { channelId: null };
  const after = { id: OWNER, channelId, guild };
  guild.voiceStates.cache.set(OWNER, after);
  client.emit('voiceStateUpdate', before, after);
};
const until = async (check, what, ms = 3_000) => {
  for (const started = Date.now(); Date.now() - started < ms; await wait(20)) if (check()) return;
  throw new Error('timed out: ' + what);
};
const packet = sequence => {
  const pcm = Buffer.alloc(9_600, 1);  // 200 ms at 24 kHz
  const head = Buffer.alloc(24);
  head.write('MRG2'); head.writeUInt32BE(1, 4); head.writeUInt32BE(1, 8); head.writeUInt32BE(sequence, 12);
  head.writeUInt32BE(pcm.length / 2, 20);
  return Buffer.concat([head, pcm]);
};

try {
  guild.voiceStates.cache.set(OWNER, { id: OWNER, channelId: CHANNEL, guild });
  client.emit('ready', { user: { id: APP }, guilds: client.guilds, destroy() {} });
  await until(() => globalThis.fake.sockets.length === 1, 'first call');
  const ws = globalThis.fake.sockets[0];
  assert.equal(ws.options.headers['X-Marong-Hangup'], '1', 'bot does not ask for the hang-up tool');
  const stream = globalThis.fake.playbacks[0];
  let spoken = 0;  // frames that carry goodbye audio (the fake Opus encoder passes PCM through)
  stream.on('data', frame => { if (frame.some(value => value !== 0)) spoken++; });
  ws.emit('message', Buffer.from(JSON.stringify({ type: 'ready' })), false);
  const { input } = globalThis.fake.joined[0];
  input.emit('data', Buffer.alloc(3_840));
  const microphone = () => ws.sent.filter(item => typeof item !== 'string').length;
  await until(() => microphone() > 0, 'microphone before the hang-up');

  // A 1.2 s goodbye arrives (60 frames of 20 ms), then the relay says hang up.
  for (let sequence = 1; sequence <= 6; sequence++) ws.emit('message', packet(sequence), true);
  ws.emit('message', Buffer.from(JSON.stringify({ type: 'audio_end', epoch: 1, turn: 1 })), false);
  ws.emit('message', Buffer.from(JSON.stringify({ type: 'hangup', epoch: 1, pendingMs: 0 })), false);
  const sentBefore = microphone();
  input.emit('data', Buffer.alloc(3_840));
  await wait(250);
  assert.equal(microphone(), sentBefore, 'microphone kept going during the goodbye');
  assert.equal(globalThis.fake.left.length, 0, 'left before the goodbye played');
  await until(() => globalThis.fake.left.length === 1, 'leaving after the goodbye');
  assert.equal(spoken, 60, 'left before the goodbye was played out');
  assert(ws.sent.includes(JSON.stringify({ type: 'stop' })), 'call not ended with stop');
  assert.equal(ws.readyState, 3);

  // Same room, owner still there: no rejoin, also not on later voice updates or the retry timer.
  move(CHANNEL);
  await wait(2_300);
  assert.equal(globalThis.fake.joined.length, 1, 'rejoined right after hanging up');
  assert(!globalThis.fake.requests.includes('/end'), 'stop already ended the call');

  // Leaving and entering again starts the next call.
  move(null);
  await wait(50);
  move(CHANNEL);
  await until(() => globalThis.fake.joined.length === 2, 'next call after re-entering');
  assert.equal(globalThis.fake.sockets[1].options.headers['X-Marong-Client-Id'] !== ws.options.headers['X-Marong-Client-Id'], true,
    'next call reused the ended call id');
  console.log('PASS: X-Marong-Hangup, no microphone during the goodbye, goodbye played before leaving, one stop, '
    + 'stays out while the owner stays, next call after leaving and entering again');
  process.exit(0);
} catch (error) {
  console.error(error);
  process.exit(1);
}
