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
const updateBannerReady = (() => {
  if (!(window.__marongApp?.version >= 3) || !$('update-banner')) return Promise.resolve();
  const deadline = performance.now() + 500;
  let timer;
  return Promise.race([
    import('/chat/update-banner.js?v=20261123').then(({ mountUpdateBanner }) =>
      mountUpdateBanner($('update-banner'), deadline, render => {
        const stick = app.ready && nearBottom();
        render();
        if (stick) toBottom();
      })),
    new Promise(resolve => { timer = setTimeout(resolve, 500); }),
  ]).catch(() => {}).finally(() => clearTimeout(timer));
})();
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
  until: 0, countdown: null, dailyBlocked: false,
  shown: new Map(),   // message id -> li
  pending: new Map(), // clientId -> {text, li}
  profileActive: false, seenKey: null,
  face: FACE,
};
const webNotifications = window.MarongWebNotifications;
let visibleReplyQueue = Promise.resolve();
const onScreenReplies = new Set();

function reportReply(id, view) {
  visibleReplyQueue = visibleReplyQueue.catch(() => {}).then(() => (view === 'hidden' || onScreenReplies.has(id))
    ? webNotifications.request('/reply-view', 'POST', {messageId: id, view}) : undefined);
}

const visibleReplies = webNotifications?.supported && 'IntersectionObserver' in window
  ? new IntersectionObserver(entries => {
    for (const entry of entries) {
      const id = entry.target.dataset.id;
      if (entry.isIntersecting && document.visibilityState === 'visible') {
        if (!onScreenReplies.has(id)) { onScreenReplies.add(id); reportReply(id, 'visible'); }
      } else if (onScreenReplies.delete(id)) reportReply(id, 'hidden');
    }
  }, {root: ui.log, threshold: 0.5})
  : null;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const inApp = () => Boolean(window.__marongApp);
async function discoverPersona() {
  try {
    const result = await fetch('/chat/persona/api/card', {credentials: 'same-origin', cache: 'no-store', redirect: 'manual'});
    if (result.status === 200 && !document.querySelector('a[href="/chat/persona/"]')) {
      const link = document.createElement('a');
      link.className = 'icon-button'; link.href = '/chat/persona/'; link.textContent = '나';
      link.setAttribute('aria-label', '친구 약속');
      document.querySelector('.actions').prepend(link);
    }
  } catch {}
}

async function api(path, options = {}, root = API) {
  const headers = {Accept: 'application/json'};
  if (options.body) headers['Content-Type'] = 'application/json';
  let res;
  try {
    res = await fetch(root + path, {...options, headers, credentials: 'same-origin', redirect: 'manual', cache: 'no-store'});
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

function relogin(result) {
  if (result?.body?.code === 'login_required') {
    try {
      sessionStorage.setItem('marong.session.return', location.pathname + location.search + location.hash);
      sessionStorage.setItem('marong.session.draft', ui.text.value || app.pending.values().next().value?.text || '');
    } catch { /* the browser can block sessionStorage */ }
    location.replace('/chat/login?expired=1');
    return;
  }
  let last = 0;
  try { last = Number(sessionStorage.getItem('marong.chat.relogin')) || 0; } catch { last = 0; }
  if (Date.now() - last > 30_000) {
    try { sessionStorage.setItem('marong.chat.relogin', String(Date.now())); } catch { /* reload anyway */ }
    location.reload();
    return;
  }
  block('login');
}

let ringExpiry;
let outfitLayers = [];
const LAYER = /^\/chat\/decor\/v[0-9]{1,3}\/[a-z0-9-]{3,40}\/[a-z_]+\.png$/;

function showLayers(face) {
  face.querySelectorAll('.face-layer').forEach(image => image.remove());
  for (const url of outfitLayers) {
    const layer = document.createElement('img');
    layer.className = 'face-layer';
    layer.src = url;
    layer.alt = '';
    layer.addEventListener('error', () => layer.remove(), {once: true});
    face.append(layer);
  }
}

async function refreshProfile() {
  if (!$('menu-profile')) return;
  const result = await api('/profile');
  if (result.status !== 200) return;
  app.profileActive = true;
  const profile = result.body;
  const usage = profile.usageToday;
  if (app.dailyBlocked && usage && (usage.limit === null || usage.units < usage.limit || usage.tickets > 0)) {
    app.dailyBlocked = false;
    notice('');
    syncSend();
  }
  const brand = document.querySelector('.brand');
  if (brand && brand.firstChild?.nodeType === Node.TEXT_NODE) brand.firstChild.textContent = profile.botName;
  document.title = profile.botName + ' · 글 대화';
  const nextFace = profile.character?.faceUrl || FACE;
  if (nextFace !== app.face) {
    app.face = nextFace;
    for (const image of document.querySelectorAll('.message.marong .face img:not(.face-layer), #typing .face img:not(.face-layer)')) {
      image.src = app.face;
    }
  }
  outfitLayers = ['body', 'neck', 'head'].map(slot => profile.character?.outfit?.[slot]?.layerUrl)
    .filter(url => typeof url === 'string' && LAYER.test(url));
  for (const face of document.querySelectorAll('.message.marong .face, #typing .face')) showLayers(face);
  const headerFace = $('header-pet-face');
  if (headerFace) {
    headerFace.hidden = !profile.character;
    headerFace.replaceChildren();
    if (profile.character) {
      const image = document.createElement('img');
      image.alt = '';
      image.src = app.face;
      headerFace.append(image);
      showLayers(headerFace);
    }
  }
  $('menu-profile').hidden = false;
  $('menu-friends').hidden = !profile.features.friends;
  for (const id of ['menu-shop', 'menu-closet']) {
    if ($(id)) $(id).hidden = !profile.features.decor;
  }
  const ring = $('ring-accept');
  clearTimeout(ringExpiry);
  const until = Date.parse(profile.pendingRing?.until || '');
  ring.hidden = !Number.isFinite(until) || until <= Date.now();
  if (!ring.hidden) {
    ring.href = '/?ring=' + encodeURIComponent(profile.pendingRing.ringId);
    ringExpiry = setTimeout(() => { ring.hidden = true; }, until - Date.now());
  }
  return profile;
}

const BLOCKS = {
  login: ['다시 들어와 줘', '로그인이 끝났어. 다시 들어가면 이어서 이야기할 수 있어.', {retry: '다시 들어가기'}],
  not_allowed: ['이 계정으로는 마롱이랑 이야기할 수 없어', '통화할 때 쓰는 계정으로 들어와 줘.', {link: ['통화 화면으로', '/']}],
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
  if (result.status === 401) { relogin(result); return false; }
  if (result.status === 403 && (code === 'not_allowed' || code === 'no_dm')) { block('not_allowed'); return false; }
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
  img.src = me ? FACE : app.face; img.alt = ''; img.width = 30; img.height = 30;
  face.append(img);
  if (!me) showLayers(face);
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
  if (picture) {
    if (typeof message.picture.reaction === 'string' && message.picture.reaction) {
      const badge = document.createElement('p');
      badge.className = 'meta';
      badge.textContent = '새 ' + message.picture.reaction + '!';
      body.append(badge);
    }
    body.append(picture);
  }
  body.append(bubble, meta);
  if (!me && message.card) showCard(li, body, message);
  row.append(face, body);
  li.append(dayLine, row);
  return li;
}

function showCard(li, body, message) {
  const card = message.card;
  const version = card && [card.id, card.status, card.answer].join(':');
  if (li.dataset.cardVersion === version) return;
  body.querySelector('.persona-options')?.remove();
  li.dataset.cardVersion = version || '';
  if (!card) return;
  const container = document.createElement('div');
  container.className = 'persona-options';
  const notice = document.createElement('p');
  notice.className = 'persona-card-note';
  notice.setAttribute('role', 'status');
  if (card.status === 'answered') {
    notice.textContent = '✓ ' + (card.options.find(option => option.value === card.answer)?.label || '');
    notice.setAttribute('aria-label', '골랐어: ' + notice.textContent.slice(2));
  } else if (card.status !== 'open') {
    notice.textContent = card.status === 'expired' ? '시간이 지나서 닫혔어' : '이 질문은 닫혔어';
  } else {
    if (card.step) {
      const progress = document.createElement('p');
      progress.className = 'persona-card-note';
      progress.textContent = `${card.step}/3`;
      container.append(progress);
    }
    const group = document.createElement('div');
    group.className = 'persona-card-group';
    group.setAttribute('role', 'radiogroup');
    group.setAttribute('aria-label', message.text.split('\n').at(-1));
    const buttons = [];
    async function choose(value, button) {
      buttons.forEach(item => { item.disabled = true; });
      group.setAttribute('aria-busy', 'true');
      button.setAttribute('aria-checked', 'true');
      notice.replaceChildren();
      const r = await api(`/cards/${card.id}/answer`, {method: 'POST', body: JSON.stringify({value})}, '/chat/persona/api');
      if (r.status === 200) {
        showCard(li, body, {...message, card: r.body.card});
        if (r.body.effect === 'open_card_screen') {
          location.href = '/chat/persona/?from=draft';
          return;
        }
        if (r.body.effect === 'card_set') {
          ui.notice.textContent = '약속 정했어';
          ui.notice.hidden = false;
        }
        return;
      }
      group.removeAttribute('aria-busy');
      if (r.status === 401) { relogin(r); return; }
      if (r.status === 404) {
        showCard(li, body, {...message, card: null});
        await refreshCards();
        return;
      }
      if (r.status === 409) {
        notice.textContent = '이 카드는 이제 못 골라';
        await refreshCards();
        return;
      }
      if (r.status === 403) {
        const code = r.body?.code;
        notice.textContent = code === 'feature_off' ? '이건 아직 준비 중이야'
          : code === 'cross_site' ? '이 화면에서 다시 해 줘' : '이 계정으로는 열 수 없어';
        return;
      }
      buttons.forEach(item => { item.disabled = false; item.setAttribute('aria-checked', 'false'); });
      if (r.status === 400) { notice.textContent = '뭔가 잘못 보냈나 봐. 다시 해 볼게'; return; }
      const retry = document.createElement('button');
      retry.type = 'button'; retry.className = 'text-button'; retry.textContent = '다시 해 볼게';
      retry.addEventListener('click', () => { void choose(value, button); }, {once: true});
      notice.append(retry);
    }
    for (const option of card.options) {
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('role', 'radio');
      button.setAttribute('aria-checked', 'false');
      button.textContent = option.label;
      button.addEventListener('click', () => { void choose(option.value, button); });
      group.append(button);
      buttons.push(button);
    }
    group.addEventListener('keydown', (event) => {
      const n = buttons.indexOf(event.target);
      const step = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1
        : event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : 0;
      if (step && n >= 0) {
        event.preventDefault();
        buttons[(n + step + buttons.length) % buttons.length].focus();
      }
    });
    container.append(group);
  }
  container.append(notice);
  body.insertBefore(container, body.querySelector('.meta'));
}

async function refreshCards() {
  const r = await api(`/messages?limit=${PAGE}`);
  if (r.status === 200) add(r.body.messages);
}

// A picture topic's picture above Marong's words (SCR-107#picture): an empty box while it loads, gone if it cannot.
function topicPicture(picture) {
  const valid = /^\/chat\/(?:topics\/v[0-9]{1,3}\/[a-z0-9-]{1,40}\.webp|api\/scenes\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/;
  if (typeof picture.src !== 'string' || !valid.test(picture.src)) {
    return null;
  }
  const img = document.createElement('img');
  img.className = 'picture waiting';
  img.alt = typeof picture.alt === 'string' ? picture.alt : '';
  img.width = 240; img.height = 240;
  img.decoding = 'async';
  img.addEventListener('load', () => img.classList.remove('waiting'), {once: true});
  img.addEventListener('error', () => {
    if (!picture.src.startsWith('/chat/api/scenes/')) { img.remove(); return; }
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'picture waiting';
    retry.textContent = '그림 다시 보기';
    retry.addEventListener('click', () => {
      retry.replaceWith(topicPicture(picture));
    });
    img.replaceWith(retry);
  }, {once: true});
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

function lastSeen() {
  try { return Number(localStorage.getItem(app.seenKey)) || 0; } catch { return 0; }
}

function rememberSeen() {
  if (!app.seenKey || !app.ready || document.visibilityState !== 'visible' || !nearBottom()) return;
  if (app.last > lastSeen()) {
    try { localStorage.setItem(app.seenKey, String(app.last)); } catch { /* storage can be blocked */ }
  }
}

function showUnread(messages, friendCode) {
  if (!friendCode) return;
  app.seenKey = `marong.chat.seen.${friendCode}`;
  const lastUser = messages.reduce((id, message) => message.from === 'me' ? Math.max(id, message.id) : id, app.read);
  const seen = Math.max(lastUser, lastSeen());
  const first = messages.find(message =>
    message.from === 'marong' && message.via === 'app' && message.kind !== 'chat' && message.id > seen);
  const row = first && app.shown.get(first.id);
  if (row) {
    const marker = document.createElement('p');
    marker.className = 'unread';
    marker.textContent = '여기부터 안 읽은 말이야';
    const latest = document.createElement('button');
    latest.className = 'text-button';
    latest.type = 'button';
    latest.textContent = '맨 아래로';
    latest.addEventListener('click', () => {
      marker.remove();
      toBottom();
      ui.log.focus({preventScroll: true});
      rememberSeen();
    });
    marker.append(latest);
    row.insertBefore(marker, row.querySelector('.row'));
    marker.scrollIntoView({block: 'start'});
  }
  rememberSeen();
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
    if (app.shown.has(message.id)) {
      const li = app.shown.get(message.id);
      if (message.card || li.dataset.cardVersion) showCard(li, li.querySelector('.body'), message);
      continue;
    }
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
    if (app.ready && message.from === 'marong' && message.kind === 'chat' && Number.isSafeInteger(message.id)) {
      visibleReplies?.observe(li);
    }
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
        if (app.profileActive && (app.dailyBlocked || r.body.messages.some(message => message.kind === 'ring'))) {
          void refreshProfile();
        }
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

async function refreshDailyLimit() {
  if (!app.dailyBlocked) return;
  const result = await api('/usage');
  if (result.status === 200) {
    const {units, limit, tickets} = result.body;
    if (limit === null || units < limit || tickets > 0) {
      app.dailyBlocked = false;
      notice('');
      syncSend();
    }
  }
}
setInterval(refreshDailyLimit, 30000);
window.addEventListener('focus', refreshDailyLimit);

function dailyLimit() {
  app.dailyBlocked = true;
  notice('오늘 쓸 수 있는 양을 다 썼어. 새벽 4시에 다시 채워져');
  const link = document.createElement('a');
  link.href = '/chat/me';
  link.textContent = '내 사용량 보기';
  ui.notice.append(' ', link);
  syncSend();
}

function syncSend() {
  const limited = Date.now() < app.until;
  ui.send.disabled = app.dailyBlocked || !app.ready || Boolean(app.blocked) || limited || !ui.text.value.trim();
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
  if (code === 'daily_limit') {
    app.pending.delete(clientId);
    entry.li.remove();
    if (!ui.text.value.trim()) { ui.text.value = entry.text; grow(); }
    dailyLimit();
    return;
  }
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
ui.log.addEventListener('scroll', () => {
  if (ui.log.scrollTop < 80) loadOlder();
  rememberSeen();
}, {passive: true});

// ── where notifications go (SCR-109) ─────────────────────────

const DELIVERY = {
  app_on: () => (inApp() ? '이 폰으로 받고 있어.' : '마롱이 앱 알림으로 받고 있어.'),
  notifications_off: () => '알림이 꺼져 있어. 먼저 한 말은 여기 남겨 둘게.',
  not_seen: () => '앱을 오래 안 열었어. 먼저 한 말은 여기 남겨 둘게.',
  no_fid: () => '지금은 이 폰으로 알림을 못 보내. 먼저 한 말은 여기 남겨 둘게.',
  no_device: () => (inApp() ? '먼저 한 말은 여기 남겨 둘게.' :
    '알림은 안드로이드 앱에서 받을 수 있어. 여기서는 열었을 때 밀린 말을 보여 줄게.'),
  fcm_off: () => '지금은 알림을 못 보내. 먼저 한 말은 여기 남겨 둘게.',
};

// Marong's own call (docs/app-ring.md SPEC-140): where it rings, and what this phone can fix.
const RING = {
  app: '약속 전화는 이 폰이 울려.',
  appNoFullScreen: '약속 전화는 이 폰이 울려. 잠금 화면에는 전체 화면 대신 위에 뜨는 알림으로 와.',
  off: '전화 알림이 꺼져 있어. 글 대화를 열면 약속 전화를 받을 수 있어.',
  chat: '글 대화를 열면 약속 전화를 받을 수 있어.',
  browser: '약속 전화 벨은 안드로이드 앱에서 울려. 여기서는 글 대화를 열면 받을 수 있어.',
};

const bridgeCan = (name) => Boolean(window.__marongApp && typeof window.__marongApp[name] === 'function');

const updateRow = document.createElement('div');
updateRow.className = 'menu-update';
updateRow.hidden = true;
const updateText = document.createElement('p');
const updateButton = document.createElement('button');
updateButton.type = 'button';
updateButton.className = 'text-button';
updateButton.textContent = '켜기';
updateRow.append(updateText, updateButton);
ui.menu.append(updateRow);

function showMenu() {
  const permission = inApp() ? app.device?.installUpdates : undefined;
  updateRow.hidden = typeof permission !== 'boolean';
  updateText.textContent = permission ? '자동 업데이트: 켜짐' : '자동 업데이트: 꺼짐 · 켜 두면 새 버전이 저절로 깔려';
  updateButton.hidden = permission !== false || !bridgeCan('openInstallSettings');
  const me = app.me;
  if (!me) return;
  const why = me.delivery.reason;
  $('menu-delivery').textContent = (DELIVERY[why] || DELIVERY.fcm_off)();
  if (webNotifications?.apple && !inApp()) {
    $('menu-delivery').textContent = '아이폰에서는 홈 화면에 추가한 뒤 내 마롱이에서 이 기기의 알림을 확인할 수 있어.';
  }
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
    ring.textContent = RING.chat;
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
updateButton.addEventListener('click', () => {
  if (!bridgeCan('openInstallSettings')) return;
  void Promise.resolve(window.__marongApp.openInstallSettings()).catch(() => {});
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
  await updateBannerReady;
  try {
    sessionStorage.removeItem('marong.chat.relogin');
    const draft = sessionStorage.getItem('marong.session.draft');
    if (draft && !ui.text.value) ui.text.value = draft;
    sessionStorage.removeItem('marong.session.draft');
    const character = sessionStorage.getItem('marong.character.applied');
    if (character) {
      sessionStorage.removeItem('marong.character.applied');
      notice(`이제 ${character}로 바뀌었어! 대화랑 기억은 그대로야`);
    }
  } catch { /* sessionStorage can be blocked */ }
  unblock();
  app.hasMore = page.body.hasMore;
  setRead(page.body);
  add(page.body.messages);
  refreshDays();
  toBottom();
  webNotifications?.restoreChatFocus();
  app.ready = true;
  syncSend();
  void showDiary();
  if ($('menu-profile')) {
    void refreshProfile().then(profile => {
      if (profile && app.ready) showUnread(page.body.messages, profile.friendCode);
    });
  }
  waitLoop();
}

async function openNotice(reference) {
  const previousFocus = document.activeElement?.id || 'chat-heading';
  const dialog = document.createElement('section');
  dialog.className = 'state';
  dialog.setAttribute('aria-live', 'polite');
  const title = document.createElement('h1');
  const message = document.createElement('p');
  const retry = document.createElement('button');
  const ordinary = document.createElement('button');
  const chat = document.createElement('button');
  title.className = 'state-title';
  message.className = 'state-text';
  title.tabIndex = -1;
  retry.type = ordinary.type = chat.type = 'button';
  retry.className = ordinary.className = chat.className = 'state-action';
  retry.textContent = '다시 확인';
  ordinary.textContent = '일반 통화';
  chat.textContent = '글 대화로';
  dialog.append(title, message, retry, ordinary, chat);
  ui.log.before(dialog);
  const hidden = [ui.log, ui.form, ui.menuButton];
  for (const element of hidden) element.hidden = true;
  let inactive = false;
  let submitted = false;
  chat.onclick = () => {
    inactive = true;
    webNotifications.clear();
    dialog.remove();
    for (const element of hidden) element.hidden = false;
    void start();
  };
  window.addEventListener('pageshow', event => {
    if (event.persisted && submitted && !inactive) chat.click();
  });
  function show(head, line, allowRetry = false) {
    title.textContent = head;
    message.textContent = line;
    retry.hidden = !allowRetry;
    ordinary.hidden = true;
    chat.hidden = head === '알림을 확인하고 있어';
  }
  async function verify(first = false) {
    show('알림을 확인하고 있어', '지금 로그인과 알림을 열 수 있는지 확인 중이야.');
    if (first) title.focus();
    const response = await webNotifications.request('/target/resolve', 'POST', {targetRef: reference});
    if (inactive) return;
    if (response.status === 200 && response.data.state === 'chat') { chat.click(); return; }
    if (response.status === 401 && webNotifications.preserve('/chat/')) {
      location.replace('/chat/login?expired=1');
      return;
    }
    if (response.status === 200 && response.data?.state === 'ring_ready'
        && document.body.dataset.noticeCallEnabled === 'true') {
      const subscription = await webNotifications.request('/subscription');
      if (inactive) return;
      if (subscription.status === 401 && webNotifications.preserve('/chat/')) {
        location.replace('/chat/login?expired=1');
        return;
      }
      if (subscription.status === 200 && subscription.data?.state === 'active'
          && webNotifications.openCall(reference, previousFocus)) { submitted = true; return; }
    }
    const ringState = {
      ring_ready: ['약속 전화가 와 있어', '화면을 열기만 해서는 수락하지 않아.'],
      ring_expired: ['약속 전화 시간이 지났어', '더 이상 이 약속 전화를 받을 수 없어.'],
      ring_answered: ['이미 받은 전화야', '이 약속 전화는 이미 처리됐어. 글 대화로 돌아갈 수 있어.'],
      ring_unavailable: ['지금은 이 전화를 받을 수 없어', '현재 확인한 상태로는 이 약속 전화를 연결할 수 없어.'],
    }[response.status === 200 ? response.data?.state : ''];
    if (ringState) {
      show(...ringState, response.data.state === 'ring_unavailable');
      if (response.data.state === 'ring_expired' && response.ordinaryChoice
          && document.body.dataset.noticeCallEnabled === 'true') {
        ordinary.hidden = false;
        ordinary.onclick = () => {
          if (submitted) return;
          submitted = webNotifications.openCall(reference, previousFocus, response.ordinaryChoice);
          if (!submitted) void verify();
        };
      }
    } else if ([400, 403, 404].includes(response.status)) {
      webNotifications.clear();
      show('이 알림을 열 수 없어', '글 대화로 돌아가 다시 확인할 수 있어.');
    } else if (response.status === 429) {
      show('잠시 뒤 알림을 확인해 줘', '안내된 대기 시간이 지나면 알림을 다시 확인할 수 있어.', true);
      retry.disabled = true;
      setTimeout(() => { retry.disabled = false; }, Math.max(response.wait, 1) * 1000);
    } else {
      show('아직 알림을 확인할 수 없어', '연결을 확인한 뒤 다시 시도해 줘. 확인 전에는 알림 내용을 열 수 없어.', true);
    }
    if (first) title.focus();
  }
  retry.onclick = () => verify();
  await verify(true);
}

const noticeReference = webNotifications?.restore('/chat/');
if (noticeReference) void openNotice(noticeReference);
else start();
window.addEventListener('hashchange', () => {
  if (webNotifications?.capture() && webNotifications.preserve('/chat/')) location.reload();
});
document.addEventListener('visibilitychange', () => {
  if (app.profileActive && document.visibilityState === 'visible') refreshProfile();
  if (document.visibilityState !== 'visible' && visibleReplies) {
    for (const id of onScreenReplies) reportReply(id, 'hidden');
    onScreenReplies.clear();
  }
});
void discoverPersona();
