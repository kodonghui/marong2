'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(__dirname + '/static/rtc-client.js', 'utf8');

function fixture() {
  const calls = {play: 0, start: 0, gesture: 0, audible: 0, faults: []};
  class Room {
    constructor() { this.canPlaybackAudio = true; }
    on() {}
    async startAudio() { calls.start++; }
    async disconnect() {}
  }
  const element = {paused: true, setAttribute() {}, async play() { calls.play++; throw new Error('blocked'); },
    pause() {}, remove() {}};
  const box = {
    LivekitClient: {Room, RoomEvent: {}, Track: {Kind: {Audio: 'audio'}}},
    document: {createElement: () => element, body: {append() {}}},
    setInterval() {}, clearInterval() {}, callbacks: reason => calls.faults.push(reason),
  };
  vm.createContext(box);
  vm.runInContext(source, box);
  const client = vm.runInContext("new MarongRTC({state:'running'}, () => {}, callbacks)", box);
  client.track = {getRTCStatsReport: async () => new Map()};
  client.receiving = true;
  client.onGesture = () => calls.gesture++;
  client.onAudible = () => calls.audible++;
  return {client, element, calls};
}

test('TC-580: audibly received media retries once, then switches to PCM after 2 seconds', async () => {
  const {client, calls} = fixture();
  for (let i = 0; i < 3; i++) await client.checkPlayback();
  assert.equal(calls.play, 1);
  assert.equal(calls.start, 1);
  assert.deepEqual(calls.faults, []);
  await client.checkPlayback();
  assert.deepEqual(calls.faults, ['rtc_silent']);
  assert.equal(client.silentMs, 2000);
});

test('TC-581: a suspended audio context requests a gesture and leaves the transport alone', async () => {
  const {client, calls} = fixture();
  client.context.state = 'suspended';
  for (let i = 0; i < 5; i++) await client.checkPlayback();
  assert.equal(calls.gesture, 5);
  assert.equal(client.silentMs, 0);
  assert.deepEqual(calls.faults, []);
});

test('TC-583: progressing playout statistics and browsers without statistics both work', async () => {
  const {client, element, calls} = fixture();
  element.paused = false;
  let samples = 0;
  client.track.getRTCStatsReport = async () => new Map([
    ['playout', {type: 'media-playout', totalSamplesCount: samples += 24000}],
  ]);
  for (let i = 0; i < 120; i++) await client.checkPlayback();
  assert.equal(calls.audible, 119);
  assert.deepEqual(calls.faults, []);
  client.nextTurn();
  client.track.getRTCStatsReport = async () => new Map();
  await client.checkPlayback();
  assert.equal(calls.audible, 120);
  assert.equal(client.playout, 'unsupported');
});
