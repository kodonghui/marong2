import {action, AI_NOTICE, api, banner, button, CONSENT, dateLabel, el, errorText, header, link, notice,
  page, picture, show, showTabs, text} from './pet.js';

import {mediaId, reportControl} from './report.js';
import {rechargeSheet} from './orders.js';
import {pushControl} from './push-control.js';

const HOME = {label: '홈', url: '/'};
const LEGAL = '/static/legal/';

function memberBanner(me) {
  return me.overseasTransfer ? null : banner(CONSENT, link('설정에서 바꾸기', '/me#consents', 'plain'));
}

export async function petScreen(id) {
  const path = `/api/pets/${id}`;
  const screen = `/pets/${id}`;
  const [me, pet, quota] = await Promise.all([api('/api/me'), api(path), api('/api/me/quota')]);
  const archived = pet.status === 'archived';
  const memorial = pet.mode === 'memorial';
  header(pet.name, HOME);
  showTabs(null);
  const title = el('div', {class: 'row'},
    memorial ? el('small', {class: 'grow'}, '❀ 추억') : el('span', {class: 'grow'}),
    !archived ? link('통화', screen + '/call') : null,
    el('details', {}, el('summary', {'aria-label': '더 보기'}, '⋯'),
      el('div', {class: 'stack'}, link('일기장', screen + '/diary', 'plain'),
        !archived ? link('옷 입히기', screen + '/closet', 'plain') : null, link('아이 설정', screen + '/settings', 'plain'),
        pet.shopEntry ? link('상점', '/shop', 'plain') : null)));
  const quotaLine = el('div', {class: 'banner row'}, el('strong', {class: 'grow'}, `오늘 한도 ${quota.percent}%`),
    !archived && !memorial ? button('충전하기', () => rechargeSheet(pet), 'plain') : null);
  const chat = el('section', {class: 'stack', 'aria-label': '대화'});
  const portrait = picture(pet.sheet.front, pet.name, 'portrait');
  const pictureId = mediaId(pet.sheet.front);
  const reported = el('div', {role: 'status'});
  show(banner(AI_NOTICE), memberBanner(me), title, portrait,
    el('div', {class: 'row'}, el('small', {class: 'grow'}, 'AI가 그린 그림'), pictureId ? reportControl({
      targetType: 'picture', targetId: pictureId, preview: pet.sheet.front,
    }, '그림 신고', reported, portrait) : null), quotaLine, reported, chat);
  const {items, before} = await api(path + '/messages');
  const timeline = el('div', {class: 'chat-log', role: 'log', tabindex: '0', 'aria-label': '메시지'});
  const typing = el('small', {class: 'muted', hidden: true}, '···');
  const reconnecting = banner('다시 연결하는 중이에요');
  reconnecting.hidden = true;
  const outlet = el('div', {'aria-live': 'polite'});
  const seen = new Set();
  let cursor = before;
  function bubble(row) {
    if (row.id && seen.has(row.id)) return null;
    if (row.id) seen.add(row.id);
    if (row.kind === 'call') return el('details', {class: 'bubble system'},
      el('summary', {}, `통화했어요 · ${dateLabel(row.createdAt)}`), text(row.text));
    if (row.role === 'system' && row.kind === 'crisis_notice') {
      const number = row.text.match(/\b(?:109|119)\b/)?.[0];
      return el('p', {class: 'bubble system'}, number ? el('a', {href: `tel:${number}`}, row.text) : row.text);
    }
    if (row.role !== 'pet' || !row.id) return el('p', {class: `bubble ${row.role}`}, row.text);
    const message = text(row.text);
    const report = reportControl({targetType: 'message', targetId: row.id, preview: row.text}, '신고', reported, message);
    return el('div', {class: 'bubble'}, message, el('small', {class: 'muted'}, 'AI'), report);
  }
  function append(rows) {
    for (const row of [...rows].reverse()) {
      const item = bubble(row);
      if (item) timeline.append(item);
    }
    timeline.scrollTop = timeline.scrollHeight;
  }
  append(items);
  const more = button('이전 대화', () => action(more, outlet, async () => {
    const height = timeline.scrollHeight;
    const prior = await api(`${path}/messages?before=${encodeURIComponent(cursor)}`);
    timeline.prepend(...[...prior.items].reverse().map(bubble).filter(Boolean));
    timeline.scrollTop += timeline.scrollHeight - height;
    cursor = prior.before;
    more.hidden = !cursor;
  }), 'plain');
  more.hidden = !cursor;
  const empty = items.length ? null : text('곧 인사하러 와요', 'muted');
  chat.append(reconnecting, more, timeline, empty || document.createComment(''), typing, outlet);

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
  entry.disabled = submit.disabled = !me.overseasTransfer;
  const draftKey = `pet:chat:${id}`;
  entry.value = sessionStorage.getItem(draftKey) || '';
  sessionStorage.removeItem(draftKey);
  entry.addEventListener('input', () => sessionStorage.setItem(draftKey, entry.value));
  const form = el('form', {class: 'composer'}, entry, submit);

  async function send(payload, pending) {
    try {
      const message = await api(path + '/messages', {method: 'POST', body: payload});
      pending.remove();
      append([message]);
    } catch (error) {
      if (error.code === 'asleep' || error.code === 'consent_required' || error.status === 401) {
        if (!entry.value) entry.value = payload.text;
        sessionStorage.setItem(draftKey, entry.value);
        if (error.code === 'asleep' || error.code === 'consent_required') entry.disabled = submit.disabled = true;
        pending.remove();
        errorText(error, outlet);
      } else {
        const again = button('다시 보내기', () => {
          if (!navigator.onLine) return;
          again.remove();
          void send(payload, pending);
        }, 'plain');
        pending.append(text('보내지 못했어요', 'error'), again);
      }
    }
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    const message = entry.value.trim();
    if (!message || entry.disabled || !navigator.onLine) return;
    const payload = {text: message, clientId: crypto.randomUUID()};
    const pending = el('div', {class: 'bubble member'}, text(message));
    timeline.append(pending);
    timeline.scrollTop = timeline.scrollHeight;
    entry.value = '';
    sessionStorage.removeItem(draftKey);
    empty?.remove();
    void send(payload, pending);
  });
  chat.append(form);
  if (items.length === 1 && items[0].kind === 'greeting' && !entry.disabled) entry.focus();

  let reconnect;
  let events;
  function connect() {
    events = new EventSource(path + '/events');
    events.addEventListener('open', async () => {
      if (reconnecting.hidden) return;
      try {
        const fresh = await api(path + '/messages');
        append(fresh.items);
        reconnecting.hidden = true;
      } catch (error) { errorText(error, outlet); }
    });
    events.addEventListener('typing', () => { typing.hidden = false; });
    events.addEventListener('message', event => {
      typing.hidden = true;
      empty?.remove();
      try {
        const row = JSON.parse(event.data);
        if (typeof row.text === 'string') append([row]);
      } catch {}
    });
    events.addEventListener('error', () => {
      events.close();
      reconnecting.hidden = false;
      typing.hidden = true;
      reconnect = setTimeout(connect, 3_000);
    });
  }
  connect();
  window.addEventListener('pagehide', () => { events?.close(); clearTimeout(reconnect); }, {once: true});
}

export async function account() {
  header('내 정보', HOME);
  const [me, {items: pets}, {items: consents}] = await Promise.all([
    api('/api/me'), api('/api/pets'), api('/api/me/consents'),
  ]);
  showTabs('/me', pets.some(pet => pet.shopEntry === true));
  const names = {terms: '이용약관', privacy: '개인정보 처리방침', ai_notice: 'AI 고지', overseas_transfer: '국외 이전'};
  const outcome = el('div', {'aria-live': 'polite'});
  const consent = button(me.overseasTransfer ? '국외 이전 동의 끄기' : '국외 이전 동의 켜기', () => dialog.showModal());
  const confirm = button(me.overseasTransfer ? '끄기' : '동의하기', () => action(confirm, outcome, async () => {
    await api('/api/me/consents/overseas_transfer', {method: 'PUT', body: {value: !me.overseasTransfer}});
    location.replace('/me#consents');
    location.reload();
  }), 'primary');
  const dialog = el('dialog', {class: 'sheet stack'},
    me.overseasTransfer ? text('끄면 새 대화·새 그림·통화가 멈춰요. 지금까지 만든 것은 볼 수 있어요')
      : link('받는 곳 보기', LEGAL + 'overseas.html', 'plain'),
    outcome, confirm, button('닫기', () => dialog.close()));
  const panel = el('details', {id: 'consents', class: 'card stack', open: location.hash === '#consents'},
    el('summary', {}, '동의'), ...consents.map(row => text(`${names[row.kind]} · ${row.value ? '동의함' : '동의 안 함'}`)),
    text('필수 동의는 계정을 지워 거둘 수 있어요.', 'muted'), consent, dialog);
  const logout = button('로그아웃', async () => {
    try { await api('/api/auth/logout', {method: 'POST', body: {}}); }
    finally { location.replace('/'); }
  });
  const confirmText = el('input', {'aria-label': '확인 문구'});
  const deleteOutlet = el('div', {'aria-live': 'polite'});
  const deleteButton = button('지우기', () => action(deleteButton, deleteOutlet, async () => {
    await api('/api/me', {method: 'DELETE', body: {confirm: confirmText.value}});
    location.replace('/');
  }), 'danger');
  deleteButton.disabled = true;
  confirmText.addEventListener('input', () => { deleteButton.disabled = confirmText.value !== '계정 지우기'; });
  const deletion = el('dialog', {class: 'sheet stack'}, el('h2', {}, '계정 지우기'),
    text('아이, 사진, 대화, 기억, 그림이 모두 지워지고 구독은 해지돼요. 주문 기록만 이름 없이 5년 남아요'),
    el('label', {}, '계정 지우기', confirmText), deleteOutlet, deleteButton, button('닫기', () => deletion.close()));
  show(me.status === 'minor_locked' ? banner('이 서비스는 만 19세 이상만 쓸 수 있어요.') : null,
    el('section', {class: 'card stack'}, el('h2', {}, '회원 번호'),
      button(me.memberNo, () => navigator.clipboard?.writeText(me.memberNo).catch(() => {}), 'plain'),
      text('문의할 때 알려 주세요', 'muted'),
      me.freeTickets ? text(`무료 만들기권 ${me.freeTickets}장`) : null,
      text(`본인인증 · ${me.identityVerified ? '했어요' : '안 했어요'}`)),
    link('한도와 구독', '/me/plan'), link('주문 내역', '/me/orders'), pushControl(me), panel,
    el('div', {class: 'row'}, link('이용약관', LEGAL + 'terms.html', 'plain'),
      link('개인정보 처리방침', LEGAL + 'privacy.html', 'plain')), logout,
    button('계정 지우기', () => deletion.showModal(), 'plain danger'), deletion);
}
