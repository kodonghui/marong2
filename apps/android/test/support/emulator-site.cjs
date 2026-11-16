'use strict';
// The stand-in Marong site for emulator tests of app notifications and Marong's own call (docs/app-chat.md TC-135,
// docs/app-ring.md TC-147). One origin, like marong.corthex-hq.com behind its tunnel: /chat and /chat/* go to the chat
// stand-in (chat-site.cjs), everything else, the /live WebSocket included, to the call stand-in (call-site.cjs).
// A device report changes what /chat/api/me says the way the bot does with MARONG_APP_RING=1 (app_push.py), and the
// reported FID goes to a local file for the test sender, never to the log. No model, no database, nothing beyond
// 127.0.0.1.
//
//   node test/support/emulator-site.cjs 8787 fid.txt
//   adb reverse tcp:8787 tcp:8787   (the test build opens http://localhost:8787)
//
// Lines typed into it while it runs: `say <text>`, `remind <text>` and `missed <text>` add Marong's message to the
// chat (as a 선톡, a reminder or the missed-call note), `answer <seconds>` makes Marong take up each message sent from
// the app after a second (읽음, 대답 중) and answer it after that many seconds (`answer off` stops it, docs/app-chat.md
// TC-158), `state` prints what the site holds, `quit` stops it.
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const readline = require('node:readline');
const { startChatSite } = require('./chat-site.cjs');
const { startCallSite } = require('./call-site.cjs');

const ANSWER_TEXT = '응, 잘 받았어! 대역 서버 답이야.';
const RING_IN_URL = /[?&]ring=[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:&|$)/;
const DEVICE_PATH = /^\/chat\/api\/devices\/[0-9a-f-]{36}$/;

/** Where Marong's messages and calls go for one phone's report, as app_push.py decides with the ring on. */
function route(report) {
  const fid = typeof report.fid === 'string' && report.fid ? report.fid : null;
  const delivery = report.notifications !== 'granted' ? { to: 'discord', reason: 'notifications_off' }
    : !fid ? { to: 'discord', reason: 'no_fid' }
    : { to: 'app', reason: 'app_on' };
  const ring = report.ring && typeof report.ring === 'object' ? report.ring : null;
  const fullScreen = ring && typeof ring.fullScreen === 'string' ? ring.fullScreen === 'granted' : null;
  const ringRoute = delivery.to !== 'app' ? { to: 'discord', reason: delivery.reason, fullScreen }
    : !ring ? { to: 'discord', reason: 'old_app', fullScreen }
    : ring.channel !== 'enabled' ? { to: 'discord', reason: 'ring_off', fullScreen }
    : { to: 'app', reason: 'app_on', fullScreen };
  return { fid, delivery, ring: ringRoute };
}

async function startEmulatorSite({ port = 8787, fidFile = null, log = () => {} } = {}) {
  const chat = await startChatSite({ waitMs: 25_000 });
  const call = await startCallSite({ log, ready: (url) => ({ ring: RING_IN_URL.test(url) }) });
  chat.state.me.body = { ...chat.state.me.body, delivery: { to: 'discord', reason: 'no_device' },
    ring: { to: 'discord', reason: 'no_device', fullScreen: null } };
  const chatPort = Number(new URL(chat.url).port);
  const callPort = Number(new URL(call.url).port);
  const reports = [];
  const agent = new http.Agent({ keepAlive: true });
  const tunnels = new Set();

  function report(raw) {
    let body;
    try { body = JSON.parse(raw); } catch { return; }
    const { fid, delivery, ring } = route(body);
    chat.state.me.body = { ...chat.state.me.body, delivery, ring };
    reports.push({ at: new Date().toISOString(), fid: Boolean(fid), notifications: body.notifications,
      ring: body.ring || null, appVersion: body.appVersion });
    if (fid && fidFile) fs.writeFileSync(fidFile, `${fid}\n`, { mode: 0o600 });
    const r = body.ring || {};
    log(`device report: app ${body.appVersion}, FID ${fid ? 'yes' : 'no'}, notifications ${body.notifications}, `
      + `ring channel ${r.channel}, full screen ${r.fullScreen} -> messages ${delivery.to} (${delivery.reason}), `
      + `calls ${ring.to} (${ring.reason})`);
  }

  const front = http.createServer((req, res) => {
    const { pathname, search } = new URL(req.url, 'http://127.0.0.1');
    const toChat = pathname === '/chat' || pathname.startsWith('/chat/');
    if (req.method === 'GET' && (pathname === '/' || pathname === '/chat/')) log(`page ${pathname}${search}`);
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => {
      const body = Buffer.concat(chunks);
      if (toChat && req.method === 'PUT' && DEVICE_PATH.test(pathname)) report(body.toString('utf8'));
      const upstream = http.request({ host: '127.0.0.1', port: toChat ? chatPort : callPort, method: req.method,
        path: req.url, headers: req.headers, agent }, (answer) => {
        res.writeHead(answer.statusCode, answer.headers);
        answer.pipe(res);
      });
      upstream.on('error', () => {
        if (!res.headersSent) res.writeHead(502);
        res.end();
      });
      res.on('close', () => upstream.destroy());
      upstream.end(body);
    });
  });
  front.on('upgrade', (req, socket, head) => {
    const { pathname } = new URL(req.url, 'http://127.0.0.1');
    if (pathname !== '/live') { socket.destroy(); return; }
    log(`/live asked${RING_IN_URL.test(req.url) ? ' with ring' : ''}: ${req.url.replace(/client=[^&]*/, 'client=…')}`);
    const upstream = net.connect(callPort, '127.0.0.1', () => {
      let head0 = `${req.method} ${req.url} HTTP/1.1\r\n`;
      for (let i = 0; i < req.rawHeaders.length; i += 2) head0 += `${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}\r\n`;
      upstream.write(`${head0}\r\n`);
      if (head && head.length) upstream.write(head);
      socket.pipe(upstream).pipe(socket);
    });
    // Both servers keep half-closed sockets open, so one side ending or failing ends the other.
    const both = [socket, upstream];
    for (const side of both) {
      tunnels.add(side);
      side.on('error', () => {});
      side.on('end', () => both.forEach((s) => s.destroy()));
      side.on('close', () => { tunnels.delete(side); both.forEach((s) => s.destroy()); });
    }
  });
  await new Promise((resolve) => front.listen(port, '127.0.0.1', resolve));
  return {
    url: `http://127.0.0.1:${front.address().port}`,
    chat,
    call,
    reports,
    async close() {
      for (const side of tunnels) side.destroy();
      front.closeAllConnections?.();
      await new Promise((resolve) => front.close(resolve));
      agent.destroy();
      await call.close();
      await chat.close();
    },
  };
}

/** Marong takes up each message sent from the app after a second and answers after `seconds` (0: never). */
function answerAfter(chat, seconds) {
  chat.state.reply = seconds > 0 ? { pickupMs: 1000, afterMs: Math.max(1500, seconds * 1000), text: ANSWER_TEXT } : null;
}

module.exports = { startEmulatorSite, route, answerAfter, ANSWER_TEXT };

if (require.main === module) {
  const log = (line) => console.log(`${new Date().toTimeString().slice(0, 8)} ${line}`);
  const fidFile = process.argv[3] || 'fid.txt';
  startEmulatorSite({ port: Number(process.argv[2] || 8787), fidFile, log }).then((site) => {
    log(`stand-in Marong site on ${site.url} (chat and call), FID file ${fidFile}`);
    let last = 0;
    setInterval(() => {
      const bytes = site.call.audio.bytes;
      if (site.call.openSockets() > 0 || bytes !== last) {
        log(`/live open: ${site.call.openSockets()}, microphone audio in the last 10 s: ${bytes - last} bytes`);
      }
      last = bytes;
    }, 10_000);
    const kinds = { say: 'proactive', remind: 'reminder', missed: 'ring' };
    readline.createInterface({ input: process.stdin }).on('line', (line) => {
      const [word, ...rest] = line.trim().split(' ');
      if (kinds[word] && rest.length) {
        const message = site.chat.add('marong', rest.join(' '), { kind: kinds[word] });
        log(`chat: Marong's ${kinds[word]} message ${message.id} added`);
      } else if (word === 'answer' && rest.length) {
        const seconds = rest[0] === 'off' ? 0 : Number(rest[0]);
        if (Number.isFinite(seconds) && seconds >= 0) {
          answerAfter(site.chat, seconds);
          log(seconds ? `chat: Marong reads each sent message after 1 s and answers after ${seconds} s` : 'chat: no answers');
        }
      } else if (word === 'state') {
        const { me, messages, devices, posted, openWaits } = site.chat.state;
        log(`state: messages ${JSON.stringify(me.body.delivery)}, calls ${JSON.stringify(me.body.ring)}, `
          + `${devices.length} device reports, ${messages.length} chat messages, ${posted.length} sent from the app, `
          + `${openWaits} open waits, /live ${site.call.upgrades.length} opened (${site.call.openSockets()} open), `
          + `microphone ${site.call.audio.bytes} bytes`);
      } else if (word === 'quit') {
        site.close().then(() => process.exit(0));
      } else if (word) {
        log('lines: say <text> | remind <text> | missed <text> | answer <seconds>|off | state | quit');
      }
    });
  });
}
