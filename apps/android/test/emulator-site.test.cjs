'use strict';
// The emulator tests' stand-in site (test/support/emulator-site.cjs): one origin for the chat and the call page, device
// reports change where Marong's messages and calls go like app_push.py, the FID goes to its file and never to the log,
// and /live passes through with the ring (docs/app-chat.md TC-135, docs/app-ring.md TC-147 preparation).
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { startEmulatorSite, route } = require('./support/emulator-site.cjs');

const INSTALL = '3f2c1b0a-9d8e-4f7a-8b6c-5d4e3f2a1b0c';
const RING = '0f8fad5b-d9cb-469f-a165-70867728950e';
const FID = 'fid-synthetic-0001';

function report(over = {}) {
  return { fid: FID, notifications: 'granted', appVersion: '0.2.0', ring: { channel: 'enabled', fullScreen: 'granted' },
    ...over };
}

/** Opens /live through the site and returns the first message the server sends. */
function firstLiveMessage(url, search) {
  const { port } = new URL(url);
  return new Promise((resolve, reject) => {
    const socket = net.connect(Number(port), '127.0.0.1');
    const key = crypto.randomBytes(16).toString('base64');
    let data = Buffer.alloc(0);
    socket.on('connect', () => socket.write(`GET /live${search} HTTP/1.1\r\nHost: localhost:${port}\r\nUpgrade: websocket\r\n`
      + `Connection: Upgrade\r\nSec-WebSocket-Key: ${key}\r\nSec-WebSocket-Version: 13\r\n\r\n`));
    socket.on('data', (chunk) => {
      data = Buffer.concat([data, chunk]);
      const end = data.indexOf('\r\n\r\n');
      if (end < 0) return;
      const status = data.subarray(0, data.indexOf('\r\n')).toString();
      const frame = data.subarray(end + 4);
      if (frame.length < 2 || frame.length < 2 + (frame[1] & 127)) return;
      socket.destroy();
      resolve({ status, message: JSON.parse(frame.subarray(2, 2 + (frame[1] & 127)).toString('utf8')) });
    });
    socket.on('error', reject);
  });
}

test('the stand-in site serves the call page and the chat on one origin, and follows the device report', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'marong-emulator-site-'));
  const fidFile = path.join(dir, 'fid.txt');
  const lines = [];
  const site = await startEmulatorSite({ port: 0, fidFile, log: (line) => lines.push(line) });
  t.after(async () => { await site.close(); fs.rmSync(dir, { recursive: true, force: true }); });

  const call = await fetch(`${site.url}/`);
  assert.equal(call.status, 200);
  assert.match(await call.text(), /<script[^>]+app\.js/);
  const chat = await fetch(`${site.url}/chat/`);
  assert.equal(chat.status, 200);
  assert.match(await chat.text(), /chat\.js/);

  let me = await (await fetch(`${site.url}/chat/api/me`)).json();
  assert.deepEqual([me.delivery.to, me.delivery.reason, me.ring.reason], ['discord', 'no_device', 'no_device']);

  const put = await fetch(`${site.url}/chat/api/devices/${INSTALL}`, { method: 'PUT',
    headers: { 'Content-Type': 'application/json', Origin: 'http://localhost:8787' },
    body: JSON.stringify(report({ ring: { channel: 'enabled', fullScreen: 'denied' } })) });
  assert.equal(put.status, 201);
  assert.deepEqual(await put.json(), { delivery: { to: 'app', reason: 'app_on' },
    ring: { to: 'app', reason: 'app_on', fullScreen: false } });
  me = await (await fetch(`${site.url}/chat/api/me`)).json();
  assert.equal(me.ring.to, 'app');
  assert.equal(fs.readFileSync(fidFile, 'utf8'), `${FID}\n`);
  assert.equal(site.chat.state.devices[0].origin, 'http://localhost:8787', 'the report reaches the chat as it was sent');
  assert.ok(lines.some((line) => line.includes('FID yes')), lines.join('\n'));
  assert.ok(!lines.join('\n').includes(FID), 'the FID never goes to the log');

  const ringing = await firstLiveMessage(site.url, `?client=test&hangup=1&ring=${RING}`);
  assert.match(ringing.status, / 101 /);
  assert.equal(ringing.message.type, 'ready');
  assert.equal(ringing.message.ring, true);
  const plain = await firstLiveMessage(site.url, '?client=test&hangup=1');
  assert.equal(plain.message.ring, false);
  assert.ok(lines.some((line) => line.includes('/live asked with ring')));
  assert.equal(site.call.upgrades.length, 2);
});

test('where messages and calls go for each kind of report, as app_push.py with the ring on', () => {
  assert.deepEqual(route(report()).ring, { to: 'app', reason: 'app_on', fullScreen: true });
  assert.deepEqual(route(report({ notifications: 'denied' })).delivery, { to: 'discord', reason: 'notifications_off' });
  assert.equal(route(report({ notifications: 'denied' })).ring.reason, 'notifications_off');
  assert.deepEqual(route(report({ fid: null })).delivery, { to: 'discord', reason: 'no_fid' });
  assert.deepEqual(route(report({ ring: undefined })).ring, { to: 'discord', reason: 'old_app', fullScreen: null });
  assert.deepEqual(route(report({ ring: { channel: 'disabled', fullScreen: 'granted' } })).ring,
    { to: 'discord', reason: 'ring_off', fullScreen: true });
  assert.deepEqual(route(report({ ring: { channel: 'disabled', fullScreen: 'granted' } })).delivery,
    { to: 'app', reason: 'app_on' });
});
