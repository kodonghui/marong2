import {action, api, banner, button, CONSENT, dateLabel, el, errorText, Failure, header, link, notice,
  page, picture, show, signIn, text, today} from './pet.js';

import {mediaId, reportControl} from './report.js';
import {decorateDiary, paintDiary} from './diary-decor.js';
import {rechargeSheet} from './orders.js';
import {petLayers} from './closet.js';

const outcomes = {
  skipped: '이날은 이야기가 짧아 일기를 쉬었어요.',
  failed: '이날은 일기를 쓰지 못했어요.',
};

function monthFrom(value) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(value)) return today().slice(0, 7);
  return value;
}

function monthAfter(month, delta) {
  const time = new Date(month + '-01T00:00:00Z');
  time.setUTCMonth(time.getUTCMonth() + delta);
  return time.toISOString().slice(0, 7);
}

async function listing(pet, href, path) {
  header('일기장', {label: pet.name, url: href});
  const now = today().slice(0, 7);
  const month = monthFrom(new URLSearchParams(location.search).get('month') || now);
  const rows = await api(`${path}?month=${encodeURIComponent(month)}`);
  const title = `${month.slice(0, 4)}년 ${Number(month.slice(5))}월`;
  const items = rows.items.filter(row => row.status !== 'skipped')
    .sort((left, right) => Number(right.kind === 'farewell') - Number(left.kind === 'farewell'));
  const diaryRows = items.map(row => {
    const label = row.kind === 'farewell' ? '❀ 마지막 장'
      : row.status === 'pending' ? '쓰는 중' : row.status === 'failed' ? '쓰지 못한 날' : row.title;
    return el('a', {class: row.status === 'failed' ? 'card pet diary-unwritten' : 'card pet', href: `${href}/diary/${row.date}`},
      row.picture ? picture(row.picture, '', 'thumb') : el('span', {class: 'thumb', 'aria-hidden': 'true'}),
      el('div', {class: 'grow'}, el('strong', {}, label), text(dateLabel(row.date), 'muted'),
        row.weather ? text(row.weather, 'muted') : null),
      el('span', {'aria-hidden': 'true'}, '›'));
  });
  show(el('div', {class: 'diary-controls row'},
    link('‹ 지난달', `?month=${monthAfter(month, -1)}`, 'plain'), el('h2', {}, title),
    month < now ? link('다음 달 ›', `?month=${monthAfter(month, 1)}`, 'plain')
      : el('button', {class: 'plain', disabled: true}, '다음 달 ›')),
    diaryRows.length ? el('div', {class: 'stack'}, diaryRows)
      : notice(`이 달에는 일기가 없어요. ${pet.name}와 이야기한 날 밤에 일기를 써요.`));
}

async function share(path, outlet) {
  const response = await fetch(path + '/card.png', {cache: 'no-store'}).catch(() => { throw new Failure(0); });
  if (!response.ok) {
    if (response.status === 401) signIn();
    const problem = await response.json().catch(() => ({}));
    if (response.status === 409 && problem.code === 'wrong_state') problem.detail = '아직 다 쓰지 않은 일기예요';
    throw new Failure(response.status, problem);
  }
  const bytes = await response.blob();
  if (bytes.type !== 'image/png') throw new Failure(500);
  const file = new File([bytes], '마롱이-일기.png', {type: 'image/png'});
  if (navigator.canShare?.({files: [file]})) {
    try { await navigator.share({files: [file]}); return; }
    catch (error) { if (error.name === 'AbortError') return; }
  }
  if (!outlet.isConnected) return;
  const url = URL.createObjectURL(bytes);
  const modal = el('dialog', {class: 'sheet stack'}, picture(url, '공유할 일기 카드', 'diary-art'),
    text('그림을 길게 눌러 저장해요'), button('닫기', () => modal.close()));
  modal.addEventListener('close', () => { URL.revokeObjectURL(url); modal.remove(); }, {once: true});
  outlet.append(modal);
  modal.showModal();
}

function observeDraw(pet, href, path, pages, drawing) {
  const deadline = Date.now() + 120_000;
  let timer, stopped = false, fetching = false;
  function stop() {
    stopped = true;
    clearTimeout(timer);
    document.removeEventListener('visibilitychange', visibility);
    window.removeEventListener('pagehide', hide);
    window.removeEventListener('pageshow', restore);
  }
  function schedule() {
    clearTimeout(timer);
    if (!stopped && !document.hidden) timer = setTimeout(poll, 2_000);
  }
  async function poll() {
    if (stopped || document.hidden || fetching) return;
    if (!drawing.isConnected) { stop(); return; }
    if (Date.now() >= deadline) {
      drawing.replaceChildren(text('오래 걸리네요. 조금 뒤에 다시 열어 주세요'),
        button('다시 해 보기', () => location.reload(), 'plain'));
      stop();
      return;
    }
    fetching = true;
    try {
      const entry = await api(path);
      if (stopped) return;
      if (!entry.drawing) {
        stop();
        sheet(pet, href, path, entry, pages, entry.lastRedraw === 'ok' ? '새 그림이에요'
          : entry.lastRedraw === 'failed' ? '그리지 못했어요. 한도는 돌려드렸어요.' : null);
      }
    } catch (error) { if (error.status === 401) stop(); }
    finally { fetching = false; schedule(); }
  }
  function visibility() {
    clearTimeout(timer);
    if (!document.hidden) void poll();
  }
  function hide(event) {
    clearTimeout(timer);
    if (!event.persisted) stop();
  }
  function restore(event) {
    if (event.persisted) visibility();
  }
  document.addEventListener('visibilitychange', visibility);
  window.addEventListener('pagehide', hide);
  window.addEventListener('pageshow', restore);
  schedule();
}

function redrawDialog(pet, path, entry, update, block) {
  const quotaLine = el('div', {class: 'skeleton diary-quota-placeholder', 'aria-label': '한도를 불러오는 중'});
  const note = el('textarea', {maxlength: 100, rows: 3, placeholder: '눈 오는 공원으로'});
  const outcome = el('div', {'aria-live': 'polite'});
  let blocked = false;
  const draw = button(`그리기 · ${entry.redrawsLeft}번 남음`, async () => {
    await action(draw, outcome, async () => {
      try {
        await api(path + '/redraw', {method: 'POST', body: {note: note.value.trim()}});
        modal.close();
        update({...entry, drawing: true});
      } catch (error) {
        if (error.code === 'quota_exhausted' && error.prompt === 'recharge' && pet.mode === 'living') {
          modal.close();
          await rechargeSheet(pet, true);
        } else if (['redraw_limit', 'budget_paused', 'consent_required'].includes(error.code)) {
          blocked = true;
          const message = error.code === 'consent_required' ? CONSENT : error.message;
          outcome.replaceChildren(banner(message, error.code === 'consent_required'
            ? link('설정에서 바꾸기', '/me#consents', 'plain') : null));
          block(message);
        } else if (error.status === 409 && ['busy', 'wrong_state'].includes(error.code)) {
          const latest = await api(path);
          modal.close();
          update(latest);
        } else throw error;
      }
    });
    if (blocked) draw.disabled = true;
  }, 'primary');
  const modal = el('dialog', {class: 'sheet stack', 'aria-label': '새 그림으로 다시 그리기'},
    el('label', {}, '어떤 그림이면 좋을까요?', note), quotaLine, outcome, draw, button('닫기', () => modal.close()));
  modal.addEventListener('close', () => modal.remove(), {once: true});
  document.querySelector('#page').append(modal);
  modal.showModal();
  void api('/api/me/quota').then(quota => {
    quotaLine.replaceWith(text(`새 그림은 오늘 한도를 써요 · 지금 ${quota.percent}%`, 'muted'));
  }, error => {
    quotaLine.removeAttribute('aria-label');
    quotaLine.className = '';
    errorText(error, quotaLine);
  });
}

function dayNavigation(href, entry, pages) {
  const index = pages.indexOf(entry.date);
  const before = index > 0 ? pages[index - 1] : null;
  const after = index >= 0 ? pages[index + 1] : null;
  const direction = (date, arrow, title) => date ?
    el('a', {class: 'button', href: href + '/diary/' + date, 'aria-label': title}, arrow) :
    el('button', {disabled: true, 'aria-label': title}, arrow);
  return el('nav', {class: 'diary-controls row', 'aria-label': '일기 날짜'},
    direction(before, '‹', '앞 날'), direction(after, '›', '뒷 날'));
}

function sheet(pet, href, path, entry, pages, status) {
  header('일기 한 장', {label: '일기장', url: href + '/diary'});
  const navigation = dayNavigation(href, entry, pages);
  if (entry.status !== 'ready') {
    show(notice(entry.status === 'pending' ? `${pet.name}가 아직 쓰는 중이에요. 조금 뒤에 다시 와 주세요.`
      : outcomes[entry.status]), navigation);
    return;
  }
  const editable = entry.kind !== 'farewell' && pet.status !== 'archived';
  const outcome = el('div', {'aria-live': 'polite'});
  const redraw = button(`새 그림으로 다시 그리기 · ${entry.redrawsLeft}번 남음`, () => {
    if (redraw.disabled || !navigator.onLine) return;
    redrawDialog(pet, path, entry, next => sheet(pet, href, path, next, pages), message => {
      redraw.disabled = true;
      outcome.replaceChildren(banner(message));
    });
  });
  redraw.disabled = entry.drawing || !entry.redrawsLeft;
  const send = button('카드로 공유', () => action(send, outcome, () => share(path, outcome)), 'plain');
  const drawing = entry.drawing ? banner('새 그림을 그리는 중이에요') : null;
  const composition = entry.picture ? null : entry.composite;
  const artwork = entry.picture || pet.sheet?.[composition?.expression] || pet.sheet?.front;
  const artworkView = composition ? petLayers(pet, composition.outfit || {}, '그림을 불러오지 못했어요', {
    background: composition.backgroundId, expression: composition.expression,
  }) : artwork ? picture(artwork, 'AI가 그린 그림', 'diary-art') : null;
  const pictureId = mediaId(artwork);
  const reported = el('div', {role: 'status'});
  const report = pictureId && pet.status !== 'archived' ? reportControl({targetType: 'picture', targetId: pictureId, preview: artwork},
    '그림 신고', reported, artworkView) : null;
  const frame = el('div', {class: 'diary-art-frame' + (composition ? ' composite' : '')
    + (entry.drawing ? ' drawing' : '')},
    artworkView, el('div', {class: 'diary-stickers'}));
  const paper = el('article', {class: 'diary-paper stack'},
    el('small', {}, entry.kind === 'farewell' ? '❀ 마지막 장' : dateLabel(entry.date)),
    el('h2', {}, entry.title), entry.weather ? el('small', {}, entry.weather) : null, frame,
    artworkView ? el('small', {}, 'AI가 그린 그림') : null, text(entry.body || '', 'diary-body'));
  const editor = el('div');
  const decorate = button('꾸미기', () => action(decorate, outcome, async () => {
    await decorateDiary(pet, path, entry, paper, frame, editor,
      (savedPet, savedEntry) => sheet(savedPet, href, path, savedEntry, pages));
    actions.hidden = true;
  }));
  decorate.disabled = entry.drawing;
  const actions = el('div', {class: 'row diary-actions'}, editable ? [decorate, redraw] : null, send, report);
  if (entry.kind !== 'farewell') paintDiary(paper, frame, pet.diaryStyle || {}, entry.stickers || []);
  show(drawing, status ? banner(status) : null, paper, navigation, actions, editor, outcome, reported);
  if (drawing) observeDraw(pet, href, path, pages, drawing);
  if (editable && location.hash === '#redraw') {
    history.replaceState(null, '', location.pathname + location.search);
    if (!redraw.disabled) redraw.click();
  }
}

export async function diary(route) {
  const [, , id, , day] = route.split('/');
  const href = `/pets/${id}`;
  const apiRoot = `/api${href}`;
  header(day ? '일기 한 장' : '일기장', {label: day ? '일기장' : '돌아가기', url: day ? href + '/diary' : href});
  const skeleton = kind => el('div', {class: `skeleton ${kind}`, 'aria-hidden': 'true'});
  if (day) show(el('article', {class: 'diary-paper stack'}, skeleton('diary-line-placeholder'),
    skeleton('diary-picture-placeholder'), ...Array.from({length: 6}, () => skeleton('diary-line-placeholder'))));
  else show(skeleton('diary-heading-placeholder'), ...Array.from({length: 3}, () => skeleton('diary-card-placeholder')));
  page.setAttribute('aria-busy', 'true');
  await api('/api/me');
  const pet = await api(apiRoot);
  if (!day) { await listing(pet, href, apiRoot + '/diary'); return; }
  const path = `${apiRoot}/diary/${day}`;
  try {
    const [entry, {items}] = await Promise.all([api(path), api(apiRoot + '/diary?month=' + monthFrom(day.slice(0, 7)))]);
    const pages = [...new Set(items.filter(row => row.status !== 'skipped').map(row => row.date))].sort();
    sheet(pet, href, path, entry, pages);
  } catch (error) {
    if (error.status !== 404) throw error;
    header('일기 한 장', {label: '일기장', url: href + '/diary'});
    show(notice('찾을 수 없어요.', link('일기장으로', href + '/diary')));
  }
}
