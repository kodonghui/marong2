import {action, AI_NOTICE, api, banner, button, CONSENT, DELETE_RECEIPT, el, errorText, Failure, header, link, notice,
  page, show, showTabs, text} from './pet.js';

import {outfitOf, petLayers} from './closet.js';
import {mediaId, REPORT_DRAFT, reportControl} from './report.js';
import {rechargeSheet} from './orders.js';
import {pushControl} from './push-control.js';

const HOME = {label: '홈', url: '/'};
const LEGAL = '/static/legal/';
const consentDate = new Intl.DateTimeFormat('ko-KR', {timeZone: 'Asia/Seoul', dateStyle: 'long'});
const callTime = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', hour: 'numeric', hour12: true,
});

function memberBanner(me) {
  return me.overseasTransfer ? null : banner(CONSENT, link('설정에서 바꾸기', '/me#consents', 'plain'));
}

export async function petScreen(id) {
  const path = `/api/pets/${id}`;
  const screen = `/pets/${id}`;
  showTabs(null);
  header('마롱이', HOME);
  show(el('section', {class: 'chat-loading stack', 'aria-hidden': 'true'},
    el('div', {class: 'skeleton chat-loading-notice'}),
    el('div', {class: 'skeleton portrait chat-loading-portrait'}),
    el('div', {class: 'stack'}, ['pet', 'member', 'pet'].map(role => el('div', {class: `skeleton bubble ${role}`}))),
    el('div', {class: 'skeleton chat-loading-composer'})));
  page.setAttribute('aria-busy', 'true');
  const [me, pet, quota, {items, before}] = await Promise.all([
    api('/api/me'), api(path), api('/api/me/quota'), api(path + '/messages'),
  ]);
  const archived = pet.status === 'archived';
  const memorial = pet.mode === 'memorial';
  header(pet.name, HOME, [
    !archived ? link('통화', screen + '/call') : null,
    el('details', {class: 'pet-menu'}, el('summary', {'aria-label': '더 보기'}, '⋯'),
      el('div', {class: 'card stack'}, link('일기장', screen + '/diary', 'plain'),
        !archived ? link('옷 입히기', screen + '/closet', 'plain') : null, link('아이 설정', screen + '/settings', 'plain'),
        pet.shopEntry ? link('상점', '/shop', 'plain') : null)),
  ]);
  const quotaLabel = el('strong', {class: 'grow'}, `오늘 한도 ${quota.percent}%`);
  const quotaLine = archived || memorial ? el('div', {class: 'banner row'}, quotaLabel)
    : el('button', {type: 'button', class: 'banner row quota-trigger', onclick: () => rechargeSheet(pet)},
      quotaLabel, el('span', {}, '충전하기'));
  const chat = el('section', {class: 'stack', 'aria-label': '대화'});
  const portrait = petLayers(pet, outfitOf(pet), '그림을 불러오지 못했어요');
  portrait.classList.add('portrait');
  const pictureId = mediaId(pet.sheet.front);
  const reported = el('div', {role: 'status'});
  show(banner(AI_NOTICE), memberBanner(me), memorial ? el('small', {}, '❀ 추억') : null, portrait,
    el('div', {class: 'row'}, el('small', {class: 'grow'}, 'AI가 그린 그림'), pictureId ? reportControl({
      targetType: 'picture', targetId: pictureId, preview: pet.sheet.front,
    }, '그림 신고', reported, portrait) : null), quotaLine,
    memorial && quota.percent === 0 ? banner('오늘은 여기까지, 새벽 4시 뒤에 또 이야기해요.') : null,
    reported, chat);
  const timeline = el('div', {class: 'chat-log', role: 'log', tabindex: '0', 'aria-label': '메시지'});
  const typing = el('small', {class: 'bubble muted', role: 'status', hidden: true}, '···');
  const reconnecting = banner('다시 연결하는 중이에요');
  reconnecting.hidden = true;
  const outlet = el('div', {'aria-live': 'polite'});
  const bubbles = new Map();
  const pendingSends = new Map();
  const pendingKey = `pet:pending-sends:${id}`;
  const unconfirmed = new Map();
  try {
    const stored = JSON.parse(sessionStorage.getItem(pendingKey));
    if (Array.isArray(stored)) {
      for (const payload of stored) {
        if (typeof payload?.clientId === 'string' && typeof payload.text === 'string') {
          unconfirmed.set(payload.clientId, {clientId: payload.clientId, text: payload.text});
        }
      }
    }
  } catch {}
  let cursor = before;
  let streamAnchor = items[0]?.id;
  function bubble(row) {
    if (row.kind === 'call') return el('details', {class: 'bubble system'},
      el('summary', {}, `통화했어요 · ${callTime.format(new Date(row.createdAt))}`), text(row.text));
    if (row.role === 'system' && row.kind === 'crisis_notice') {
      const number = row.text.match(/\b(?:109|119)\b/)?.[0];
      return el('p', {class: 'bubble system'}, number ? el('a', {href: `tel:${number}`}, row.text) : row.text);
    }
    if (row.role !== 'pet' || !row.id) return el('p', {class: `bubble ${row.role}`}, row.text);
    const message = text(row.text);
    const report = reportControl({targetType: 'message', targetId: row.id, preview: row.text}, '신고', reported, message);
    const snapshot = row.composite;
    const scene = snapshot && ['proactive', 'item_reaction'].includes(row.kind)
      ? petLayers(pet, snapshot.outfit || {}, '그림을 불러오지 못했어요',
        {background: snapshot.backgroundId, expression: snapshot.expression}) : null;
    return el('div', {class: 'bubble'}, scene, message, el('small', {class: 'muted'}, 'AI'), report);
  }
  function persistPending() {
    try {
      if (unconfirmed.size) sessionStorage.setItem(pendingKey, JSON.stringify([...unconfirmed.values()]));
      else sessionStorage.removeItem(pendingKey);
    } catch {}
  }
  function settle(clientId) {
    pendingSends.get(clientId)?.remove();
    pendingSends.delete(clientId);
    if (unconfirmed.delete(clientId)) persistPending();
  }
  function renderBubble(row, {move = false} = {}) {
    if (row.role === 'member' && row.clientId) settle(row.clientId);
    const known = row.id && bubbles.get(row.id);
    if (known) return move ? known : null;
    const item = bubble(row);
    if (row.id) bubbles.set(row.id, item);
    return item;
  }
  function append(rows, {move = false} = {}) {
    const following = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight <= 20;
    for (const row of [...rows].reverse()) {
      const item = renderBubble(row, {move});
      if (item) timeline.append(item);
    }
    if (following) timeline.scrollTop = timeline.scrollHeight;
  }
  append(items);
  const olderStatus = el('div', {'aria-live': 'polite', hidden: true});
  let olderFailed = false;
  function loadOlder() {
    if (!cursor) return;
    void action(more, olderStatus, async () => {
      olderStatus.hidden = true;
      try {
        const prior = await api(`${path}/messages?before=${encodeURIComponent(cursor)}`);
        const {scrollHeight, scrollTop} = timeline;
        timeline.prepend(...[...prior.items].reverse().map(row => renderBubble(row)).filter(Boolean));
        timeline.scrollTop = scrollTop + timeline.scrollHeight - scrollHeight;
        cursor = prior.before;
        more.hidden = !cursor;
        more.textContent = '이전 대화';
        olderFailed = false;
      } catch {
        olderFailed = true;
        olderStatus.hidden = false;
        olderStatus.append(text('불러오지 못했어요', 'error'));
        more.textContent = '다시';
      }
    });
  }
  const more = button('이전 대화', loadOlder, 'plain');
  more.hidden = !cursor;
  timeline.addEventListener('scroll', () => {
    if (!olderFailed && timeline.scrollTop <= 12 && timeline.scrollHeight > timeline.clientHeight) loadOlder();
  });
  const empty = items.length ? null : text('곧 인사하러 와요', 'muted');
  chat.append(reconnecting, olderStatus, more, timeline, empty || document.createComment(''), typing, outlet);
  timeline.scrollTop = timeline.scrollHeight;

  if (archived) {
    const restore = button('꺼내기', () => action(restore, outlet, async () => {
      await api(path + '/unarchive', {method: 'POST', body: {}});
      location.reload();
    }), 'primary');
    chat.append(notice('보관한 아이예요. 꺼내면 다시 이야기할 수 있어요.', restore));
    return;
  }
  const entry = el('textarea', {rows: 2, maxlength: 1000, 'aria-label': `${pet.name}에게 할 말`});
  const submit = el('button', {type: 'submit', class: 'primary'}, '보내기');
  let sendBlocked = !me.overseasTransfer;
  const sleepKey = `pet:sleep:${id}`;
  let wakeAt = Number(sessionStorage.getItem(sleepKey)) || 0;
  let wakeTimer;
  const asleep = banner(`${pet.name}가 잠들었어요. 새벽 4시에 깨요.`);
  function updateComposer() {
    clearTimeout(wakeTimer);
    if (wakeAt && wakeAt <= Date.now()) {
      wakeAt = 0;
      sessionStorage.removeItem(sleepKey);
    }
    asleep.hidden = !wakeAt;
    entry.disabled = submit.disabled = sendBlocked || !navigator.onLine || Boolean(wakeAt);
    for (const retry of timeline.querySelectorAll('[data-retry-send]')) retry.disabled = entry.disabled;
    if (wakeAt && Number.isFinite(wakeAt)) {
      wakeTimer = setTimeout(updateComposer, Math.min(wakeAt - Date.now(), 86_400_000));
    }
  }
  updateComposer();
  const draftKey = `pet:chat:${id}`;
  entry.value = sessionStorage.getItem(draftKey) || '';
  entry.addEventListener('input', () => sessionStorage.setItem(draftKey, entry.value));
  const form = el('form', {class: 'composer'}, entry, submit);

  async function send(payload, feedback) {
    try {
      const message = await api(path + '/messages', {method: 'POST', body: payload});
      settle(payload.clientId);
      append([message]);
    } catch (error) {
      if (!pendingSends.has(payload.clientId)) return;
      if (error.code === 'asleep') {
        const scheduled = Date.parse(error.wakesAt);
        wakeAt = Number.isFinite(scheduled) ? scheduled : Infinity;
        if (Number.isFinite(wakeAt)) sessionStorage.setItem(sleepKey, String(wakeAt));
        asleep.firstElementChild.textContent = error.message;
        if (!entry.value) {
          entry.value = payload.text;
          sessionStorage.setItem(draftKey, entry.value);
          settle(payload.clientId);
        } else offerRetry(payload, feedback);
        updateComposer();
      } else if (['archived', 'consent_required'].includes(error.code) || error.status === 401) {
        if (!entry.value) {
          entry.value = payload.text;
          sessionStorage.setItem(draftKey, entry.value);
          settle(payload.clientId);
        } else offerRetry(payload, feedback);
        sendBlocked = true;
        updateComposer();
        if (error.code === 'archived' || error.code === 'consent_required') location.reload();
        else errorText(error, outlet);
      } else offerRetry(payload, feedback);
    }
  }
  function offerRetry(payload, feedback) {
    const again = button('다시 보내기', () => {
      if (entry.disabled) return;
      feedback.replaceChildren();
      void send(payload, feedback);
    }, 'plain');
    again.dataset.retrySend = '';
    again.disabled = entry.disabled;
    feedback.replaceChildren(text('보내지 못했어요', 'error'), again);
  }
  function addPending(payload) {
    const feedback = el('div');
    const pending = el('div', {class: 'bubble member'}, text(payload.text), feedback);
    pendingSends.set(payload.clientId, pending);
    timeline.append(pending);
    empty?.remove();
    return feedback;
  }
  for (const payload of unconfirmed.values()) offerRetry(payload, addPending(payload));
  timeline.scrollTop = timeline.scrollHeight;
  form.addEventListener('submit', event => {
    event.preventDefault();
    const message = entry.value.trim();
    if (!message || entry.disabled || !navigator.onLine) return;
    const payload = {text: message, clientId: crypto.randomUUID()};
    unconfirmed.set(payload.clientId, payload);
    persistPending();
    const feedback = addPending(payload);
    timeline.scrollTop = timeline.scrollHeight;
    entry.value = '';
    sessionStorage.removeItem(draftKey);
    void send(payload, feedback);
  });
  chat.append(asleep, form);
  if (items.length === 1 && items[0].kind === 'greeting' && !entry.disabled) entry.focus();

  let reconnect;
  let events;
  function retry(source) {
    if (events !== source) return;
    source.close();
    events = null;
    reconnecting.hidden = false;
    typing.hidden = true;
    clearTimeout(reconnect);
    if (navigator.onLine) reconnect = setTimeout(connect, 3_000);
  }

  async function missedMessages(anchor) {
    const missed = [];
    let endpoint = path + '/messages';
    const visited = new Set([endpoint]);
    while (true) {
      const {items, before} = await api(endpoint);
      const index = items.findIndex(row => row.id === anchor);
      if (index !== -1) {
        missed.push(...items.slice(0, index));
        return missed;
      }
      missed.push(...items);
      if (!before) return missed;
      endpoint = `${path}/messages?before=${encodeURIComponent(before)}`;
      if (visited.has(endpoint)) throw new Error('Repeated message cursor');
      visited.add(endpoint);
    }
  }

  function connect() {
    if (!navigator.onLine) return;
    const source = new EventSource(path + '/events');
    events = source;
    let restoring = !reconnecting.hidden;
    const buffered = [];
    source.addEventListener('open', async () => {
      if (!restoring || events !== source) return;
      try {
        const missed = await missedMessages(streamAnchor);
        if (events !== source) return;
        append(missed, {move: true});
        if (missed[0]?.id) streamAnchor = missed[0].id;
        for (const row of buffered) {
          if (!bubbles.has(row.id)) streamAnchor = row.id || streamAnchor;
          append([row]);
        }
        if (missed.length || buffered.length) empty?.remove();
        restoring = false;
        reconnecting.hidden = true;
      } catch { retry(source); }
    });
    source.addEventListener('typing', () => { if (events === source) typing.hidden = false; });
    source.addEventListener('message', event => {
      if (events !== source) return;
      typing.hidden = true;
      try {
        const row = JSON.parse(event.data);
        if (typeof row.text !== 'string') return;
        if (restoring) buffered.push(row);
        else {
          streamAnchor = row.id || streamAnchor;
          empty?.remove();
          append([row]);
        }
      } catch {}
    });
    source.addEventListener('error', () => retry(source));
  }
  connect();
  function suspend() {
    if (events) retry(events);
    clearTimeout(reconnect);
  }
  function resume() {
    updateComposer();
    if (!events) {
      clearTimeout(reconnect);
      connect();
    }
  }
  window.addEventListener('offline', () => {
    updateComposer();
    suspend();
  });
  window.addEventListener('pagehide', () => {
    suspend();
    clearTimeout(wakeTimer);
  });
  window.addEventListener('pageshow', event => { if (event.persisted) resume(); });
  return resume;
}

export async function account() {
  header('내 정보', HOME);
  showTabs(null);
  show(...Array.from({length: 8}, () => el('div', {class: 'skeleton', 'aria-hidden': 'true'})));
  page.setAttribute('aria-busy', 'true');
  const [me, {items: pets}, {items: consents}] = await Promise.all([
    api('/api/me'), api('/api/pets'), api('/api/me/consents'),
  ]);
  const locked = me.status === 'minor_locked';
  showTabs('/me', !locked && pets.some(pet => pet.shopEntry === true));
  const names = {terms: '이용약관', privacy: '개인정보 처리방침', ai_notice: 'AI 고지', overseas_transfer: '국외 이전'};
  const outcome = el('div', {'aria-live': 'polite'});
  const consent = button(me.overseasTransfer ? '국외 이전 동의 끄기' : '국외 이전 동의 켜기', () => dialog.showModal());
  consent.disabled = locked;
  const confirm = button(me.overseasTransfer ? '끄기' : '동의하기', () => action(confirm, outcome, async () => {
    await api('/api/me/consents/overseas_transfer', {method: 'PUT', body: {value: !me.overseasTransfer}});
    history.replaceState(null, '', '/me#consents');
    location.reload();
  }), 'primary');
  const dialog = el('dialog', {class: 'sheet stack', 'aria-label': '국외 이전 동의'},
    me.overseasTransfer ? text('끄면 새 대화·새 그림·통화가 멈춰요. 지금까지 만든 것은 볼 수 있어요')
      : el('a', {class: 'plain', href: LEGAL + 'overseas.html', target: '_blank', rel: 'noopener'}, '받는 곳 보기'),
    outcome, confirm, button('닫기', () => dialog.close()));
  const rows = Object.entries(names).map(([kind, name]) => {
    const row = consents.find(item => item.kind === kind);
    if (!row) return null;
    const date = new Date(row.at);
    const when = row.at && !Number.isNaN(date.getTime()) ? ` · ${consentDate.format(date)}` : '';
    return text(`${name} · ${row.value ? '동의함' : '동의 안 함'}${when}`);
  });
  const panel = el('details', {id: 'consents', class: 'card stack', open: location.hash === '#consents'},
    el('summary', {}, '동의'), rows, text('필수 동의는 계정을 지워 거둘 수 있어요.', 'muted'), consent, dialog);
  const logout = button('로그아웃', async () => {
    try { await api('/api/auth/logout', {method: 'POST', body: {}}); }
    finally { location.replace('/'); }
  });
  const confirmPhrase = '계정 지우기';
  const confirmText = el('input', {'aria-label': '확인 문구', maxlength: 10});
  const deleteOutlet = el('div', {'aria-live': 'polite'});
  const closeDeletion = button('닫기', () => deletion.close());
  const deleteButton = button('지우기', async () => {
    if (confirmText.value !== confirmPhrase) return;
    await action(deleteButton, deleteOutlet, async () => {
      confirmText.disabled = closeDeletion.disabled = true;
      try {
        const receipt = await api('/api/me', {method: 'DELETE', body: {confirm: confirmPhrase}});
        if (receipt?.ok !== true) throw new Failure(500);
        for (const pet of pets) {
          for (const key of ['chat', 'sleep', 'export', 'settings-refresh']) sessionStorage.removeItem(`pet:${key}:${pet.id}`);
        }
        sessionStorage.removeItem('pet_next');
        sessionStorage.removeItem('pet_pay_return');
        sessionStorage.removeItem(REPORT_DRAFT);
        localStorage.removeItem(`pet:push:${me.memberNo}`);
        sessionStorage.setItem(DELETE_RECEIPT, '1');
        location.replace('/');
      } catch (error) {
        if (error.code !== 'confirm_required') throw error;
        deleteOutlet.replaceChildren(text('글이 맞지 않아요', 'error'));
      } finally { confirmText.disabled = closeDeletion.disabled = false; }
    });
    updateDelete();
  }, 'danger');
  function updateDelete() {
    deleteButton.disabled = confirmText.value !== confirmPhrase || deleteButton.hasAttribute('aria-busy');
  }
  updateDelete();
  confirmText.addEventListener('input', updateDelete);
  const deletion = el('dialog', {class: 'sheet stack', 'aria-labelledby': 'delete-account-heading'},
    el('h2', {id: 'delete-account-heading'}, confirmPhrase),
    text('아이, 사진, 대화, 기억, 그림이 모두 지워지고 구독은 해지돼요. 주문 기록만 이름 없이 5년 남아요'),
    el('label', {}, confirmPhrase, confirmText), deleteOutlet, deleteButton, closeDeletion);
  deletion.addEventListener('cancel', event => {
    if (deleteButton.hasAttribute('aria-busy')) event.preventDefault();
  });
  const startDeletion = button(confirmPhrase, () => {
    confirmText.value = '';
    deleteOutlet.replaceChildren();
    updateDelete();
    deletion.showModal();
  }, 'plain danger');
  show(locked ? banner('이 서비스는 만 19세 이상만 쓸 수 있어요.') : null,
    el('section', {class: 'card stack'}, el('h2', {}, '회원 번호'),
      button(me.memberNo, () => navigator.clipboard?.writeText(me.memberNo).catch(() => {}), 'plain'),
      text('문의할 때 알려 주세요', 'muted'),
      me.freeTickets ? text(`무료 만들기권 ${me.freeTickets}장`) : null,
      text(`본인인증 · ${me.identityVerified ? '했어요' : '안 했어요'}`)),
    locked ? el('button', {disabled: true}, '한도와 구독') : link('한도와 구독', '/me/plan'),
    link('주문 내역', '/me/orders'), pushControl(me), panel,
    el('div', {class: 'row'}, link('이용약관', LEGAL + 'terms.html', 'plain'),
      link('개인정보 처리방침', LEGAL + 'privacy.html', 'plain')), logout,
    startDeletion, deletion);
}
