'use strict';
// A stand-in for the bot's in-app chat (marong/app_chat.py), for browser tests of the chat page only
// (docs/app-chat.md TC-132). It serves the real page files (marong/app_chat_static) and answers API-101 to
// API-105 from a script the test controls: who signs in, the stored messages, what a send gets back, when Marong
// reads a message, is "writing" and what she says, and what a device report gets back. No model, no database,
// nothing beyond 127.0.0.1.
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

const REPO = path.resolve(__dirname, '..', '..', '..', '..');
const STATIC = path.join(REPO, 'marong', 'app_chat_static');
const FACES = path.join(REPO, 'marong', 'call', 'static', 'face', 'v1');
const FILES = { '/chat/': ['index.html', 'text/html'], '/chat/chat.js': ['chat.js', 'text/javascript'],
  '/chat/chat.css': ['chat.css', 'text/css'] };
const ME = { name: '현경', textMax: 2000, delivery: { to: 'discord', reason: 'no_device' },
  ring: { to: 'discord', reason: 'ring_disabled', fullScreen: null } };

/** '2026-11-15T21:30:00+09:00' for a Date, in Korean time like the server. */
function seoul(date) {
  const shifted = new Date(date.getTime() + 9 * 3_600_000);
  return `${shifted.toISOString().slice(0, 19)}+09:00`;
}

async function startChatSite({ waitMs = 1500 } = {}) {
  const state = {
    me: { status: 200, body: ME },          // GET /chat/api/me
    messages: [],                           // the room, oldest first
    sends: [],                              // what POST /chat/api/messages answers next: 'ok' | 429 | 500
    typing: false,                          // Marong writing (the wait's typing)
    read: 0,                                // readUpTo: my newest message Marong read (SPEC-148)
    answered: 0,                            // answeredUpTo: my newest message Marong answered
    marks: true,                            // false: a server from before '읽음', with no readUpTo/answeredUpTo
    reply: null,                            // after an accepted send: {afterMs, text, pickupMs?} or null
    postDelayMs: 0,                         // how long a send takes to answer
    posted: [],                             // every POST body, in order
    waits: [],                              // every wait query string, in order
    openWaits: 0,
    nextId: 1,
    meCount: 0,                             // GET /chat/api/me answered
    devices: [],                            // every PUT /chat/api/devices/{installId}, in order
    deviceStatus: 201,                      // what the next device report gets: 200 | 201 | 401
    pictures: {},                           // picture topics by address (/chat/topics/v1/<name>.webp → a file)
    pictureDelayMs: 0,                      // how long a picture takes to come (SCR-107#picture-loading)
  };
  const waiters = new Set();

  function add(from, text, extra = {}) {
    const message = { id: state.nextId++, from, text, at: seoul(new Date()), via: 'app', kind: 'chat', ...extra };
    state.messages.push(message);
    wake();
    return message;
  }

  function wake() {
    for (const waiter of [...waiters]) waiter();
  }

  function setTyping(on) {
    state.typing = on;
    wake();
  }

  /** Like an answer taking my message up: read up to it, and writing. */
  function takeUp(id) {
    state.read = Math.max(state.read, id);
    state.typing = true;
    wake();
  }

  /** Marong's answer to my message `id`: answered up to it; writing goes on while a later message waits. */
  function answer(id, text, { typing = false } = {}) {
    state.answered = Math.max(state.answered, id);
    state.read = Math.max(state.read, id);
    state.typing = typing;
    return add('marong', text);
  }

  function marks() {
    return state.marks ? { readUpTo: state.read, answeredUpTo: state.answered } : {};
  }

  function json(res, status, body, headers = {}) {
    res.writeHead(status, { 'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json',
      'Cache-Control': 'no-store', ...headers });
    res.end(JSON.stringify(body));
  }

  function problem(res, status, code, headers) {
    json(res, status, { type: `http://127.0.0.1/problems/${code.replace(/_/g, '-')}`, title: code, status, code,
      traceId: '0123456789abcdef' }, headers);
  }

  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    const { pathname } = url;
    if (FILES[pathname]) {
      const [name, type] = FILES[pathname];
      res.writeHead(200, { 'Content-Type': `${type}; charset=utf-8`, 'Cache-Control': 'no-store' });
      res.end(fs.readFileSync(path.join(STATIC, name)));
      return;
    }
    if (pathname.startsWith('/face/v1/')) {
      const file = path.resolve(FACES, pathname.slice('/face/v1/'.length));
      if (file.startsWith(FACES + path.sep) && fs.existsSync(file)) {
        res.writeHead(200, { 'Content-Type': 'image/webp' });
        res.end(fs.readFileSync(file));
        return;
      }
    }
    if (pathname.startsWith('/chat/topics/')) {  // API-140 (docs/04-functional-spec/call-first.md SPEC-274)
      const file = state.pictures[pathname];
      setTimeout(() => {
        if (!file || !fs.existsSync(file)) { problem(res, 404, 'no_picture'); return; }
        res.writeHead(200, { 'Content-Type': 'image/webp', 'Cache-Control': 'public, max-age=31536000, immutable' });
        res.end(fs.readFileSync(file));
      }, state.pictureDelayMs);
      return;
    }
    if (pathname === '/chat/api/me' && req.method === 'GET') {
      state.meCount++;
      if (state.me.status !== 200) { problem(res, state.me.status, state.me.code || 'unauthenticated'); return; }
      json(res, 200, state.me.body);
      return;
    }
    if (pathname === '/chat/api/messages' && req.method === 'GET') {
      if (state.me.status !== 200) { problem(res, state.me.status, state.me.code || 'unauthenticated'); return; }
      const limit = Number(url.searchParams.get('limit')) || 30;
      const before = Number(url.searchParams.get('before')) || Infinity;
      const older = state.messages.filter((m) => m.id < before);
      json(res, 200, { messages: older.slice(-limit), hasMore: older.length > limit, ...marks() });
      return;
    }
    if (pathname === '/chat/api/messages' && req.method === 'POST') {
      let raw = '';
      req.on('data', (chunk) => { raw += chunk; });
      req.on('end', () => setTimeout(() => {
        const body = JSON.parse(raw);
        state.posted.push({ ...body, origin: req.headers.origin || null });
        const next = state.sends.shift() || 'ok';
        if (next === 429) { problem(res, 429, 'too_many_messages', { 'Retry-After': '3' }); return; }
        if (next === 500) { problem(res, 500, 'internal'); return; }
        const same = state.messages.find((m) => m.clientId === body.clientId);
        if (same) { json(res, 200, { message: same }); return; }
        const message = add('me', body.text.trim(), { clientId: body.clientId });
        json(res, 202, { message });
        const reply = state.reply;
        if (reply) {
          // Like the server: read and 'writing' once the answer holds the room, answered with her reply.
          setTimeout(() => takeUp(message.id), reply.pickupMs ?? 100);
          setTimeout(() => answer(message.id, reply.text), reply.afterMs);
        }
      }, state.postDelayMs));
      return;
    }
    const device = pathname.match(/^\/chat\/api\/devices\/([0-9a-f-]{36})$/);
    if (device && req.method === 'PUT') {
      let raw = '';
      req.on('data', (chunk) => { raw += chunk; });
      req.on('end', () => {
        state.devices.push({ installId: device[1], body: JSON.parse(raw), origin: req.headers.origin || null,
          type: req.headers['content-type'] || null });
        if (state.deviceStatus >= 400) { problem(res, state.deviceStatus, 'unauthenticated'); return; }
        json(res, state.deviceStatus, { delivery: state.me.body.delivery, ring: state.me.body.ring });
      });
      return;
    }
    if (pathname === '/chat/api/messages/wait' && req.method === 'GET') {
      const after = Number(url.searchParams.get('after'));
      const shown = url.searchParams.get('typing') === '1';
      const shownRead = url.searchParams.has('read') ? Number(url.searchParams.get('read')) : null;
      state.waits.push(url.search);
      state.openWaits++;
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        waiters.delete(check);
        clearTimeout(timer);
        state.openWaits--;
        if (!res.writableEnded && !res.destroyed) {
          json(res, 200, { messages: state.messages.filter((m) => m.id > after), typing: state.typing, ...marks() });
        }
      };
      const check = () => {
        if (state.messages.some((m) => m.id > after) || state.typing !== shown
          || (state.marks && shownRead !== null && state.read !== shownRead)) finish();
      };
      const timer = setTimeout(finish, waitMs);
      req.on('close', () => { if (!done) { done = true; waiters.delete(check); clearTimeout(timer); state.openWaits--; } });
      waiters.add(check);
      check();
      return;
    }
    res.writeHead(404);
    res.end('not found');
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    state,
    add,
    setTyping,
    takeUp,
    answer,
    async close() {
      server.closeAllConnections?.();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

module.exports = { startChatSite, seoul, ME, REPO };
