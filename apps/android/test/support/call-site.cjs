'use strict';
// A stand-in for the call server, for browser and emulator tests only: it serves the real call page
// files (tools/vertex_live/static and the face images) with a fixed /status and a /live WebSocket that
// says "ready" and then only counts what it receives. No model, no memory, no network beyond 127.0.0.1.
//
// Emulator tests (TC-110 to TC-112, TC-116) run it on a fixed port and log what reaches it:
//   node test/support/call-site.cjs 8787
//   adb reverse tcp:8787 tcp:8787   (the test build opens http://localhost:8787, a secure context)
const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

const REPO = path.resolve(__dirname, '..', '..', '..', '..');
const STATIC = path.join(REPO, 'tools', 'vertex_live', 'static');
const FACES = path.join(REPO, 'marong', 'call', 'static', 'face', 'v1');
const APP_WWW = path.join(REPO, 'apps', 'android', 'www');
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.webp': 'image/webp', '.txt': 'text/plain; charset=utf-8' };
const WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

function fileFor(pathname) {
  const pick = (base, name) => {
    const full = path.resolve(base, name);
    return full.startsWith(base + path.sep) ? full : null;
  };
  if (pathname === '/') return path.join(STATIC, 'index.html');
  if (pathname.startsWith('/face/v1/')) return pick(FACES, pathname.slice('/face/v1/'.length));
  if (pathname.startsWith('/__app/')) return pick(APP_WWW, pathname.slice('/__app/'.length));
  return pick(STATIC, pathname.slice(1));
}

function frame(text) {
  const payload = Buffer.from(text, 'utf8');
  const length = payload.length;
  const header = length < 126 ? Buffer.from([0x81, length])
    : length < 65536 ? Buffer.from([0x81, 126, length >> 8, length & 255])
    : (() => { const h = Buffer.alloc(10); h[0] = 0x81; h[1] = 127; h.writeBigUInt64BE(BigInt(length), 2); return h; })();
  return Buffer.concat([header, payload]);
}

// Reads client frames (always masked) and hands complete ones to onFrame(opcode, payload).
function readFrames(socket, onFrame) {
  let pending = Buffer.alloc(0);
  socket.on('data', (chunk) => {
    pending = Buffer.concat([pending, chunk]);
    for (;;) {
      if (pending.length < 2) return;
      const opcode = pending[0] & 15;
      let length = pending[1] & 127;
      let offset = 2;
      if (length === 126) { if (pending.length < 4) return; length = pending.readUInt16BE(2); offset = 4; }
      else if (length === 127) { if (pending.length < 10) return; length = Number(pending.readBigUInt64BE(2)); offset = 10; }
      const masked = (pending[1] & 128) !== 0;
      const total = offset + (masked ? 4 : 0) + length;
      if (pending.length < total) return;
      const mask = masked ? pending.subarray(offset, offset + 4) : null;
      const payload = Buffer.from(pending.subarray(total - length, total));
      if (mask) for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i & 3];
      pending = pending.subarray(total);
      onFrame(opcode, payload);
    }
  });
}

// chat: the status /chat/api/me answers (the call page shows its '글 대화' link only on 200, SPEC-124).
// ready: more fields for the 'ready' message, such as {ring: true} for Marong's own call (SPEC-136), or a function
// of the /live address that returns them.
async function startCallSite({ status = {}, port = 0, log = () => {}, chat = 404, ready = {} } = {}) {
  const received = [];
  const upgrades = [];
  const audio = { frames: 0, bytes: 0 };
  const requests = [];
  const sockets = new Set();
  const server = http.createServer((req, res) => {
    const { pathname } = new URL(req.url, 'http://127.0.0.1');
    requests.push(`${req.method} ${pathname}`);
    if (pathname === '/status') {
      res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
      res.end(JSON.stringify({ ready: true, active: false, webRTC: false, memoryConnected: false, ...status }));
      return;
    }
    if (pathname === '/chat/api/me') {
      res.writeHead(chat, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
      res.end(JSON.stringify(chat === 200 ? { name: '현경', textMax: 2000 } : { code: 'unauthenticated' }));
      return;
    }
    if (req.method === 'POST') { res.writeHead(204); res.end(); return; }
    const file = fileFor(decodeURIComponent(pathname));
    if (!file || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end('not found'); return; }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    fs.createReadStream(file).pipe(res);
  });
  server.on('upgrade', (req, socket) => {
    const { pathname } = new URL(req.url, 'http://127.0.0.1');
    const key = req.headers['sec-websocket-key'];
    if (pathname !== '/live' || !key) { socket.destroy(); return; }
    upgrades.push(req.url);
    sockets.add(socket);
    log(`/live opened (${sockets.size} open)`);
    socket.on('close', () => {
      sockets.delete(socket);
      log(`/live closed (${sockets.size} open)`);
    });
    socket.on('error', () => {});
    const accept = crypto.createHash('sha1').update(key + WS_GUID).digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    const extra = typeof ready === 'function' ? ready(req.url) : ready;
    socket.write(frame(JSON.stringify({ type: 'ready', callId: 'test-call', memoryConnected: false, ...extra })));
    readFrames(socket, (opcode, payload) => {
      if (opcode === 1) {
        const message = JSON.parse(payload.toString('utf8'));
        received.push(message);
        if (message.type !== 'playback_stats') log(`/live received ${message.type}`);
      } else if (opcode === 2) {
        audio.frames++;
        audio.bytes += payload.length;
      }
      else if (opcode === 8) { socket.end(Buffer.from([0x88, 0])); }
      else if (opcode === 9) socket.write(Buffer.concat([Buffer.from([0x8a, payload.length]), payload]));
    });
  });
  await new Promise((resolve) => server.listen(port, '127.0.0.1', resolve));
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    received,
    upgrades,
    requests,
    audio,
    openSockets: () => sockets.size,
    async close() {
      for (const socket of sockets) socket.destroy();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

module.exports = { startCallSite, REPO };

if (require.main === module) {
  const log = (line) => console.log(`${new Date().toTimeString().slice(0, 8)} ${line}`);
  startCallSite({ port: Number(process.argv[2] || 8787), log }).then((site) => {
    log(`stand-in call site on ${site.url}`);
    let last = 0;
    setInterval(() => {
      const bytes = site.audio.bytes;
      if (site.openSockets() > 0 || bytes !== last) log(`/live open: ${site.openSockets()}, microphone audio in the last 10 s: ${bytes - last} bytes`);
      last = bytes;
    }, 10000);
  });
}
