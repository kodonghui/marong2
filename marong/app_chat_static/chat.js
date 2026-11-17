'use strict';
// 마롱이 글 대화(docs/app-chat.md SCR-107·109, SPEC-124, SPEC-148·149). Text goes in with textContent only.
(() => {
  // The call page's rule: the cream day theme 08:00–20:00 Korean time, night otherwise.
  const hour = 3_600_000, day = 24 * hour, morning = 8 * hour, evening = 20 * hour;
  const root = document.documentElement;
  const themeColor = document.querySelector('meta[name="theme-color"]');
  const colorScheme = document.querySelector('meta[name="color-scheme"]');
  let timer;
  function syncTheme() {
    clearTimeout(timer);
    const seoulTime = (Date.now() + 9 * hour) % day;
    const cream = seoulTime >= morning && seoulTime < evening;
    const theme = cream ? 'chestnut' : 'night';
    if (root.dataset.theme !== theme) {
      root.dataset.theme = theme;
      if (themeColor) themeColor.content = cream ? '#fbf6ee' : '#121729';
      if (colorScheme) colorScheme.content = cream ? 'light' : 'dark';
    }
    const next = seoulTime < morning ? morning : seoulTime < evening ? evening : day + morning;
    timer = setTimeout(syncTheme, Math.min(next - seoulTime, 60_000));
  }
  syncTheme();
  window.addEventListener('pageshow', syncTheme);
  window.addEventListener('focus', syncTheme);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') syncTheme(); });
})();

const $ = (id) => document.getElementById(id);
const API = '/chat/api';
const PAGE = 30;
const FACE = '/face/v1/01-neutral.webp';
const URL_RE = /https?:\/\/[^\s<>"'()]+/g;
const TAGS = {proactive: '먼저 톡', reminder: '일정 알림', ring: '약속 전화', hello: '먼저 건 전화'};
const WEEK = ['일', '월', '화', '수', '목', '금', '토'];
const PROBLEM_TEXT = {
  cross_site: '이 화면에서 다시 해 줘.',
  db_unavailable: '잠깐 문제가 생겼어. 조금 있다가 다시 해 줘.',
  internal: '잠깐 문제가 생겼어. 다시 해 볼래?',
};

const ui = {
  log: $('log'), list: $('messages'), more: $('more'), typing: $('typing'), state: $('state'),
  text: $('text'), send: $('send'), form: $('composer'), notice: $('notice'), connection: $('connection'),
  menu: $('menu'), menuButton: $('menu-button'),
};
const app = {
  ready: false, blocked: null, me: null, device: null,
  first: null, last: 0, hasMore: false, loadingMore: false,
  waiting: false, waitControl: null, backoff: 0, typing: false,
  read: 0, answered: 0, // '읽음': my messages after `answered` up to `read` (SPEC-148)
  until: 0, countdown: null,
  shown: new Map(),   // message id -> li
  pending: new Map(), // clientId -> {text, li}
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const inApp = () => Boolean(window.__marongApp);

async function api(path, options = {}) {
  const headers = {Accept: 'application/json'};
  if (options.body) headers['Content-Type'] = 'application/json';
  let res;
  try {
    res = await fetch(API + path, {...options, headers, credentials: 'same-origin', redirect: 'manual', cache: 'no-store'});
  } catch (error) {
    if (error && error.name === 'AbortError') return {status: -1};
    return {status: 0};
  }
  // Access sent its sign-in page instead of our answer (an expired session): sign in again.
  if (res.type === 'opaqueredirect') return {status: 401, body: {code: 'unauthenticated'}};
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  return {status: res.status, body, retryAfter: Number(res.headers.get('Retry-After')) || 0};
}

// ── blocking states (SCR-107) ────────────────────────────────

function relogin() {
  let last = 0;
  try { last = Number(sessionStorage.getItem('marong.chat.relogin')) || 0; } catch { last = 0; }
  if (Date.now() - last > 30_000) {
    try { sessionStorage.setItem('marong.chat.relogin', String(Date.now())); } catch { /* reload anyway */ }
    location.reload();
    return;
  }
  block('login');
}

const BLOCKS = {
  login: ['다시 들어와 줘', '로그인이 끝났어. 다시 들어가면 이어서 이야기할 수 있어.', {retry: '다시 들어가기'}],
  not_allowed: ['이 계정으로는 마롱이랑 이야기할 수 없어', '통화할 때 쓰는 계정으로 들어와 줘.', {link: ['통화 화면으로', '/']}],
  no_dm: ['디스코드 DM에서 마롱이한테 먼저 말 걸어 줘',
    '글 대화는 디스코드 DM과 같은 대화라서, DM을 한 번 보내고 나면 여기서도 이어서 이야기할 수 있어.',
    {link: ['통화 화면으로', '/']}],
  broken: ['잠깐 문제가 생겼어', '조금 있다가 다시 해 볼래?', {retry: '다시 해 보기'}],
  loading: ['불러오는 중이야', '', {}],
};

function block(kind, extra) {
  const [title, text, action] = BLOCKS[kind];
  app.blocked = kind === 'loading' || kind === 'broken' ? null : kind;
  ui.state.hidden = false;
  ui.log.hidden = true;
  ui.form.hidden = kind !== 'loading';
  $('state-title').textContent = title;
  $('state-text').textContent = extra ? `${text} (${extra})` : text;
  const link = $('state-link'), retry = $('state-retry');
  link.hidden = !action.link;
  if (action.link) { link.textContent = action.link[0]; link.href = action.link[1]; }
  retry.hidden = !action.retry;
  if (action.retry) retry.textContent = action.retry;
  if (app.blocked) stopWaiting();
  syncSend();
}

function unblock() {
  ui.state.hidden = true;
  ui.log.hidden = false;
  ui.form.hidden = false;
}

/** true: the caller may go on. Blocking answers change the whole screen. */
function handle(result) {
  const code = result.body && result.body.code;
  if (result.status === 401) { relogin(); return false; }
  if (result.status === 403 && (code === 'not_allowed' || code === 'no_dm')) { block(code); return false; }
  return true;
}

// ── messages ─────────────────────────────────────────────────

function dayLabel(at) {
  const [y, m, d] = at.slice(0, 10).split('-').map(Number);
  return `${y}년 ${m}월 ${d}일 ${WEEK[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]}요일`;
}

function seoulNow() {
  return new Date(Date.now() + 9 * 3_600_000).toISOString().slice(0, 16);
}

function linkify(target, text) {
  let at = 0;
  for (const match of text.matchAll(URL_RE)) {
    let url = match[0].replace(/[.,!?;:~]+$/, '');
    if (match.index > at) target.append(text.slice(at, match.index));
    let href = null;
    try {
      const parsed = new URL(url);
      if (parsed.protocol === 'https:' || parsed.protocol === 'http:') href = parsed.href;
    } catch { href = null; }
    if (href) {
      const a = document.createElement('a');
      a.href = href;
      a.textContent = url;
      if (new URL(href).origin !== location.origin) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
      target.append(a);
    } else {
      target.append(url);
    }
    at = match.index + url.length;
  }
  if (at < text.length) target.append(text.slice(at));
}

function item(message) {
  const li = document.createElement('li');
  const me = message.from === 'me';
  li.className = `message ${me ? 'me' : 'marong'}`;
  li.dataset.day = message.at.slice(0, 10);
  if (message.id) li.dataset.id = String(message.id);
  const dayLine = document.createElement('p');
  dayLine.className = 'day';
  const daySpan = document.createElement('span');
  daySpan.textContent = dayLabel(message.at);
  dayLine.append(daySpan);
  const row = document.createElement('div');
  row.className = 'row';
  const face = document.createElement('span');
  face.className = 'face';
  const img = document.createElement('img');
  img.src = FACE; img.alt = ''; img.width = 30; img.height = 30;
  face.append(img);
  const body = document.createElement('div');
  body.className = 'body';
  const picture = !me && message.picture ? topicPicture(message.picture) : null;
  const bubble = document.createElement('p');
  bubble.className = 'bubble';
  linkify(bubble, message.text);
  const meta = document.createElement('p');
  meta.className = 'meta';
  const tag = me ? (message.via === 'discord' ? '디스코드' : null) : TAGS[message.kind];
  if (tag) {
    const span = document.createElement('span');
    span.className = 'tag';
    span.textContent = tag;
    meta.append(span);
  }
  const time = document.createElement('time');
  time.dateTime = message.at;
  time.textContent = message.at.slice(11, 16);
  meta.append(time);
  if (picture) body.append(picture);
  body.append(bubble, meta);
  row.append(face, body);
  li.append(dayLine, row);
  return li;
}

// A picture topic's picture above Marong's words (SCR-107#picture): an empty box while it loads, gone if it cannot.
function topicPicture(picture) {
  if (typeof picture.src !== 'string' || !/^\/chat\/topics\/v[0-9]{1,3}\/[a-z0-9-]{1,40}\.webp$/.test(picture.src)) {
    return null;
  }
  const img = document.createElement('img');
  img.className = 'picture waiting';
  img.alt = typeof picture.alt === 'string' ? picture.alt : '';
  img.width = 240; img.height = 240;
  img.decoding = 'async';
  img.addEventListener('load', () => img.classList.remove('waiting'), {once: true});
  img.addEventListener('error', () => img.remove(), {once: true});
  img.src = picture.src;
  return img;
}

function refreshDays() {
  let previous = null;
  for (const li of ui.list.children) {
    li.querySelector('.day').hidden = li.dataset.day === previous;
    previous = li.dataset.day;
  }
  const empty = ui.list.children.length === 0;
  let hint = $('empty');
  if (empty && !hint) {
    hint = document.createElement('p');
    hint.id = 'empty';
    hint.className = 'empty';
    hint.textContent = '마롱이한테 먼저 말 걸어 볼래?';
    ui.log.insertBefore(hint, ui.typing);
  } else if (!empty && hint) {
    hint.remove();
  }
}

function nearBottom() {
  return ui.log.scrollHeight - ui.log.scrollTop - ui.log.clientHeight < 120;
}

function toBottom() {
  ui.log.scrollTop = ui.log.scrollHeight;
}

/** Keep the list in id order; bubbles still being sent (no id yet) stay at the end. */
function place(li, id) {
  for (const other of ui.list.children) {
    if (!other.dataset.id || Number(other.dataset.id) > id) {
      ui.list.insertBefore(li, other);
      return;
    }
  }
  ui.list.append(li);
}

/** Show messages from the server once each, in id order; a pending bubble with the same text becomes that message. */
function add(messages) {
  const stick = nearBottom();
  let added = false;
  for (const message of messages) {
    if (app.shown.has(message.id)) continue;
    if (message.from === 'me') {
      for (const [clientId, entry] of app.pending) {
        if (entry.text === message.text && entry.li.classList.contains('sending')) {
          app.pending.delete(clientId);
          entry.li.remove();
          break;
        }
      }
    }
    const li = item(message);
    app.shown.set(message.id, li);
    place(li, message.id);
    app.last = Math.max(app.last, message.id);
    app.first = app.first === null ? message.id : Math.min(app.first, message.id);
    if (message.from === 'marong') setTyping(false);
    added = true;
  }
  if (added) {
    refreshDays();
    markRead();
    if (stick) toBottom();
  }
  return added;
}

function setTyping(on) {
  const stick = nearBottom();
  app.typing = Boolean(on);
  ui.typing.hidden = !app.typing;
  if (app.typing && stick) toBottom();
}

/** '읽음' under each of my messages Marong read and has not answered yet (SPEC-148). An older server sends neither. */
function setRead(body) {
  if (!body || !Number.isInteger(body.readUpTo) || !Number.isInteger(body.answeredUpTo)) return;
  app.read = body.readUpTo;
  app.answered = body.answeredUpTo;
  markRead();
}

function markRead() {
  const stick = nearBottom();
  for (const [id, li] of app.shown) {
    if (!li.classList.contains('me')) continue;
    const on = id > app.answered && id <= app.read;
    const label = li.querySelector('.read');
    if (on && !label) {
      const span = document.createElement('span');
      span.className = 'read';
      span.textContent = '읽음';
      li.querySelector('.meta').insertBefore(span, li.querySelector('time'));
    } else if (!on && label) {
      label.remove();
    }
  }
  if (stick) toBottom();
}

async function loadOlder() {
  if (app.loadingMore || !app.hasMore || app.first === null || app.blocked) return;
  app.loadingMore = true;
  ui.more.hidden = false;
  const r = await api(`/messages?before=${app.first}&limit=${PAGE}`);
  ui.more.hidden = true;
  app.loadingMore = false;
  if (r.status !== 200) { handle(r); return; }
  const height = ui.log.scrollHeight;
  const top = ui.log.scrollTop;
  app.hasMore = r.body.hasMore;
  for (const message of r.body.messages) {
    if (app.shown.has(message.id)) continue;
    const li = item(message);
    app.shown.set(message.id, li);
    place(li, message.id);
    app.first = Math.min(app.first, message.id);
  }
  refreshDays();
  markRead();
  ui.log.scrollTop = top + (ui.log.scrollHeight - height);
}

// ── waiting for new messages (API-104) ───────────────────────

function setConnection(ok) {
  ui.connection.hidden = ok;
}

function stopWaiting() {
  if (app.waitControl) app.waitControl.abort();
}

async function waitLoop() {
  if (app.waiting || !app.ready || app.blocked || document.visibilityState === 'hidden') return;
  app.waiting = true;
  try {
    while (app.ready && !app.blocked && document.visibilityState !== 'hidden') {
      const control = new AbortController();
      app.waitControl = control;
      const guard = setTimeout(() => control.abort(), 40_000);
      const began = Date.now();
      const after = app.last;
      const r = await api(`/messages/wait?after=${after}&typing=${app.typing ? 1 : 0}&read=${app.read}`,
        {signal: control.signal});
      clearTimeout(guard);
      app.waitControl = null;
      if (r.status === -1) continue; // aborted: the loop condition decides
      if (r.status === 200) {
        setConnection(true);
        app.backoff = 0;
        const typing = app.typing, read = app.read;
        const added = add(r.body.messages);
        setTyping(r.body.typing);
        setRead(r.body);
        // Nothing new at once: another open screen took this wait over. Do not take it straight back.
        const echoedNewMessage = r.body.messages.some(message => message.id > after);
        if (!added && !echoedNewMessage && app.typing === typing && app.read === read && Date.now() - began < 1_000) await sleep(3_000);
        continue;
      }
      if (!handle(r)) break;
      setConnection(false);
      app.backoff = Math.min(app.backoff ? app.backoff * 2 : 5_000, 60_000);
      await sleep(app.backoff);
    }
  } finally {
    app.waiting = false;
  }
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') stopWaiting();
  else waitLoop();
});

// ── sending (API-103) ────────────────────────────────────────

function syncSend() {
  const limited = Date.now() < app.until;
  ui.send.disabled = !app.ready || Boolean(app.blocked) || limited || !ui.text.value.trim();
}

function notice(text) {
  const stick = nearBottom(); // the notice takes room from the log: keep its end in view
  ui.notice.hidden = !text;
  ui.notice.textContent = text || '';
  if (stick) toBottom();
}

function limit(seconds) {
  app.until = Date.now() + seconds * 1_000;
  clearInterval(app.countdown);
  const tick = () => {
    const left = Math.ceil((app.until - Date.now()) / 1_000);
    if (left <= 0) {
      clearInterval(app.countdown);
      notice('');
      syncSend();
      return;
    }
    notice(`너무 빨라! ${left}초 뒤에 보내 줘.`);
    syncSend();
  };
  tick();
  app.countdown = setInterval(tick, 1_000);
}

function pendingItem(clientId, text) {
  const li = item({id: 0, from: 'me', text, at: seoulNow(), via: 'app', kind: 'chat'});
  li.classList.add('sending');
  li.querySelector('time').textContent = '보내는 중';
  app.pending.set(clientId, {text, li});
  ui.list.append(li);
  refreshDays();
  toBottom();
  return li;
}

function failed(clientId, why) {
  const entry = app.pending.get(clientId);
  if (!entry) return;
  const {li} = entry;
  li.classList.remove('sending');
  li.classList.add('failed');
  const meta = li.querySelector('.meta');
  meta.textContent = '';
  const label = document.createElement('span');
  label.textContent = why || '못 보냄';
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.className = 'retry';
  retry.textContent = '다시 보내기';
  retry.addEventListener('click', () => {
    if (Date.now() < app.until || app.blocked) return;
    li.classList.remove('failed');
    li.classList.add('sending');
    meta.textContent = '';
    const time = document.createElement('time');
    time.textContent = '보내는 중';
    meta.append(time);
    post(clientId);
  });
  const stick = nearBottom();
  meta.append(label, retry);
  if (stick) toBottom();
}

async function post(clientId) {
  const entry = app.pending.get(clientId);
  if (!entry) return;
  const r = await api('/messages', {method: 'POST', body: JSON.stringify({clientId, text: entry.text})});
  if (r.status === 200 || r.status === 202) {
    const still = app.pending.get(clientId);
    if (still) { app.pending.delete(clientId); still.li.remove(); }
    add([r.body.message]);
    notice('');
    waitLoop();
    return;
  }
  if (!handle(r)) return;
  const code = r.body && r.body.code;
  if (r.status === 429) {
    // Keep what was written: back into the box, and the button waits (SCR-107).
    app.pending.delete(clientId);
    entry.li.remove();
    refreshDays();
    if (!ui.text.value.trim()) { ui.text.value = entry.text; grow(); }
    limit(r.retryAfter || 60);
    return;
  }
  failed(clientId, r.status === 0 ? '못 보냄(연결 끊김)' : '못 보냄');
  if (code && PROBLEM_TEXT[code]) {
    notice(PROBLEM_TEXT[code] + (code === 'internal' && r.body.traceId ? ` (${r.body.traceId})` : ''));
  }
}

function grow() {
  ui.text.style.height = 'auto';
  ui.text.style.height = `${Math.min(ui.text.scrollHeight + 2, 160)}px`;
  syncSend();
}

ui.text.addEventListener('input', grow);
ui.form.addEventListener('submit', (event) => {
  event.preventDefault();
  const text = ui.text.value.trim();
  if (!text || ui.send.disabled) return;
  const clientId = crypto.randomUUID();
  ui.text.value = '';
  grow();
  pendingItem(clientId, text);
  post(clientId);
  ui.text.focus();
});
ui.log.addEventListener('scroll', () => { if (ui.log.scrollTop < 80) loadOlder(); }, {passive: true});

// ── where notifications go (SCR-109) ─────────────────────────

const DELIVERY = {
  app_on: () => (inApp() ? '이 폰으로 받고 있어.' : '마롱이 앱 알림으로 받고 있어.'),
  notifications_off: () => '알림이 꺼져 있어서 디스코드 DM으로 받고 있어.',
  not_seen: () => '앱을 오래 안 열어서 디스코드 DM으로 받고 있어. 앱을 열면 다시 이 폰으로 와.',
  no_fid: () => '이 폰은 앱 알림을 못 받아서 디스코드 DM으로 받고 있어.',
  no_device: () => (inApp() ? '디스코드 DM으로 받고 있어.' : '디스코드 DM으로 받고 있어. 알림은 마롱이 앱에서 받을 수 있어.'),
  fcm_off: () => '지금은 디스코드 DM으로 받고 있어.',
};

// Marong's own call (docs/app-ring.md SPEC-140): where it rings, and what this phone can fix.
const RING = {
  app: '약속 전화는 이 폰이 울려.',
  appNoFullScreen: '약속 전화는 이 폰이 울려. 잠금 화면에는 전체 화면 대신 위에 뜨는 알림으로 와.',
  off: '전화 알림이 꺼져 있어서 약속 전화는 디스코드 DM으로 통화하자고 보내.',
  discord: '약속 전화는 디스코드 DM으로 통화하자고 보내.',
  browser: '약속 전화 벨은 마롱이 앱에서 울려. 앱이 없으면 디스코드로 알려 줄게.',
};

const bridgeCan = (name) => Boolean(window.__marongApp && typeof window.__marongApp[name] === 'function');

function showMenu() {
  const me = app.me;
  if (!me) return;
  const why = me.delivery.reason;
  $('menu-delivery').textContent = (DELIVERY[why] || DELIVERY.fcm_off)();
  const settings = $('menu-settings');
  settings.hidden = !(why === 'notifications_off' && bridgeCan('openNotificationSettings'));
  const ring = $('menu-ring');
  const ringSettings = $('menu-ring-settings');
  const fullScreen = $('menu-full-screen');
  const samsung = $('menu-samsung');
  ringSettings.hidden = true;
  fullScreen.hidden = true;
  samsung.hidden = true;
  ring.hidden = me.ring.reason === 'ring_disabled';
  if (ring.hidden) return;
  if (!inApp()) {
    ring.textContent = RING.browser;
    return;
  }
  if (me.ring.to === 'app') {
    const noFullScreen = me.ring.fullScreen === false;
    ring.textContent = noFullScreen ? RING.appNoFullScreen : RING.app;
    fullScreen.hidden = !(noFullScreen && bridgeCan('openFullScreenSettings'));
    samsung.hidden = !(app.device && app.device.samsung === true);
  } else if (me.ring.reason === 'ring_off' || me.ring.reason === 'notifications_off') {
    ring.textContent = RING.off;
    ringSettings.hidden = !settings.hidden || !bridgeCan('openNotificationSettings');
  } else {
    ring.textContent = RING.discord;
  }
}

async function refreshMenu() {
  if (bridgeCan('deviceState')) {
    window.__marongApp.deviceState().then((device) => {
      app.device = device || null;
      showMenu();
    }, () => {});
  }
  const r = await api('/me');
  if (r.status === 200) { app.me = r.body; showMenu(); } else handle(r);
}

ui.menuButton.addEventListener('click', () => {
  const open = ui.menu.hidden;
  ui.menu.hidden = !open;
  ui.menuButton.setAttribute('aria-expanded', String(open));
  if (!open) return;
  showMenu();
  refreshMenu();
});
$('menu-settings').addEventListener('click', () => {
  try { window.__marongApp.openNotificationSettings(); } catch { /* old app */ }
});
$('menu-ring-settings').addEventListener('click', () => {
  try { window.__marongApp.openNotificationSettings(app.me && app.me.ring.reason === 'ring_off' ? 'ring' : undefined); } catch { /* old app */ }
});
$('menu-full-screen').addEventListener('click', () => {
  try { window.__marongApp.openFullScreenSettings(); } catch { /* old app */ }
});
// The app reported a changed phone (back from Android's settings): show the new state.
window.addEventListener('marongdevice', () => { if (!ui.menu.hidden) refreshMenu(); });
$('state-retry').addEventListener('click', () => (app.blocked === 'login' ? location.reload() : start()));

// ── start ────────────────────────────────────────────────────

async function showDiary() {
  const entry = $('diary-entry');
  if (!entry) return;
  $('diary-button')?.remove();
  try {
    const response = await fetch('/chat/diary/api/latest', {cache: 'no-store', credentials: 'same-origin'});
    if (!response.ok) return;
    const diary = await response.json();
    if ((diary.enabled === true || diary.date) && !$('diary-button')) {
      entry.after(entry.content.cloneNode(true));
    }
  } catch {
    // The diary is optional while its tables are unavailable.
  }
}

async function start() {
  app.ready = false;
  block('loading');
  const me = await api('/me');
  if (!handle(me)) return;
  if (me.status !== 200) { block('broken', me.body && me.body.traceId); return; }
  app.me = me.body;
  ui.text.maxLength = me.body.textMax;
  const page = await api(`/messages?limit=${PAGE}`);
  if (!handle(page)) return;
  if (page.status !== 200) { block('broken', page.body && page.body.traceId); return; }
  try { sessionStorage.removeItem('marong.chat.relogin'); } catch { /* fine */ }
  unblock();
  app.hasMore = page.body.hasMore;
  setRead(page.body);
  add(page.body.messages);
  refreshDays();
  toBottom();
  app.ready = true;
  syncSend();
  void showDiary();
  waitLoop();
}

start();
