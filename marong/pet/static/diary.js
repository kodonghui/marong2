import {action, api, banner, button, dateLabel, el, Failure, header, link, notice,
  picture, show, text, today} from './pet.js';

import {mediaId, reportControl} from './report.js';
import {decorateDiary, paintDiary} from './diary-decor.js';

const outcomes = {
  pending: '아직 쓰는 중이에요. 조금 뒤에 다시 와 주세요.',
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
  const items = rows.items.filter(row => row.status !== 'skipped');
  const diaryRows = items.map(row => {
    const label = row.kind === 'farewell' ? '❀ 마지막 장'
      : row.status === 'pending' ? '쓰는 중' : row.status === 'failed' ? '쓰지 못한 날' : row.title;
    return el('a', {class: 'card pet', href: `${href}/diary/${row.date}`},
      row.picture ? picture(row.picture, '', 'thumb') : el('span', {class: 'thumb', 'aria-hidden': 'true'}),
      el('div', {class: 'grow'}, el('strong', {}, label), text(dateLabel(row.date), 'muted')),
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
  const response = await fetch(path + '/card.png', {cache: 'no-store'});
  if (!response.ok) throw new Failure(response.status, await response.json().catch(() => ({})));
  const bytes = await response.blob();
  if (bytes.type !== 'image/png') throw new Failure(500);
  const file = new File([bytes], '마롱이-일기.png', {type: 'image/png'});
  if (navigator.canShare?.({files: [file]})) {
    try { await navigator.share({files: [file]}); return; }
    catch (error) { if (error.name === 'AbortError') return; }
  }
  const url = URL.createObjectURL(bytes);
  const modal = el('dialog', {class: 'sheet stack'}, picture(url, '공유할 일기 카드', 'diary-art'),
    text('그림을 길게 눌러 저장해요'), button('닫기', () => modal.close()));
  modal.addEventListener('close', () => { URL.revokeObjectURL(url); modal.remove(); }, {once: true});
  outlet.append(modal);
  modal.showModal();
}

function observeDraw(pet, href, path) {
  const deadline = Date.now() + 120_000;
  window.setTimeout(async function poll() {
    if (Date.now() >= deadline) {
      show(notice('오래 걸리네요. 조금 뒤에 다시 열어 주세요', button('다시 해 보기', () => location.reload())));
      return;
    }
    if (!document.hidden) {
      try {
        const entry = await api(path);
        if (!entry.drawing) {
          sheet(pet, href, path, entry, entry.lastRedraw === 'ok' ? '새 그림이에요'
            : entry.lastRedraw === 'failed' ? '그리지 못했어요. 한도는 돌려드렸어요.' : null);
          return;
        }
      } catch (error) { if (error.status === 401) return; }
    }
    window.setTimeout(poll, 2_000);
  }, 2_000);
}

async function redrawDialog(path, entry, onSuccess) {
  const quota = await api('/api/me/quota');
  const note = el('textarea', {maxlength: 100, rows: 3, placeholder: '눈 오는 공원으로'});
  const outcome = el('div', {'aria-live': 'polite'});
  const draw = button(`그리기 · ${entry.redrawsLeft}번 남음`, () => action(draw, outcome, async () => {
    await api(path + '/redraw', {method: 'POST', body: {note: note.value.trim()}});
    modal.close();
    onSuccess();
  }), 'primary');
  const modal = el('dialog', {class: 'sheet stack'}, el('label', {}, '어떤 그림이면 좋을까요?', note),
    text(`새 그림은 오늘 한도를 써요 · 지금 ${quota.percent}%`, 'muted'),
    outcome, draw, button('닫기', () => modal.close()));
  modal.addEventListener('close', () => modal.remove(), {once: true});
  document.querySelector('#page').append(modal);
  modal.showModal();
}

function sheet(pet, href, path, entry, status) {
  header('일기 한 장', {label: '일기장', url: href + '/diary'});
  if (entry.status !== 'ready') { show(notice(outcomes[entry.status])); return; }
  const editable = entry.kind !== 'farewell' && pet.status !== 'archived';
  const outcome = el('div', {'aria-live': 'polite'});
  const redraw = button(`새 그림으로 다시 그리기 · ${entry.redrawsLeft}번 남음`,
    () => action(redraw, outcome, () => redrawDialog(path, entry,
      () => sheet(pet, href, path, {...entry, drawing: true}))));
  redraw.disabled = entry.drawing || !entry.redrawsLeft;
  const send = button('카드로 공유', () => action(send, outcome, () => share(path, outcome)), 'plain');
  const drawing = entry.drawing ? banner('새 그림을 그리는 중이에요') : null;
  const artwork = entry.picture || pet.sheet?.front;
  const artworkView = artwork ? picture(artwork, 'AI가 그린 그림', 'diary-art') : null;
  const pictureId = mediaId(artwork);
  const reported = el('div', {role: 'status'});
  const report = pictureId ? reportControl({targetType: 'picture', targetId: pictureId, preview: artwork},
    '그림 신고', reported, artworkView) : null;
  const frame = el('div', {class: 'diary-art-frame'}, artworkView, el('div', {class: 'diary-stickers'}));
  const paper = el('article', {class: 'diary-paper stack'},
    el('small', {}, entry.kind === 'farewell' ? '❀ 마지막 장' : dateLabel(entry.date)),
    el('h2', {}, entry.title), entry.weather ? el('small', {}, entry.weather) : null, frame,
    entry.picture ? el('small', {}, 'AI가 그린 그림') : null, text(entry.body || '', 'diary-body'));
  const editor = el('div');
  const decorate = button('꾸미기', () => action(decorate, outcome, async () => {
    await decorateDiary(pet, path, entry, paper, frame, editor,
      (savedPet, savedEntry) => sheet(savedPet, href, path, savedEntry));
    actions.hidden = true;
  }));
  decorate.disabled = entry.drawing;
  const actions = el('div', {class: 'row diary-actions'}, editable ? [decorate, redraw] : null, send, report);
  if (entry.kind !== 'farewell') paintDiary(paper, frame, pet.diaryStyle || {}, entry.stickers || []);
  show(drawing, status ? banner(status) : null, paper, actions, editor, outcome, reported);
  if (entry.drawing) observeDraw(pet, href, path);
  if (editable && location.hash === '#redraw') {
    history.replaceState(null, '', location.pathname + location.search);
    if (!redraw.disabled) redraw.click();
  }
}

export async function diary(route) {
  const [, , id, , day] = route.split('/');
  const href = `/pets/${id}`;
  const apiRoot = `/api${href}`;
  await api('/api/me');
  const pet = await api(apiRoot);
  if (!day) { await listing(pet, href, apiRoot + '/diary'); return; }
  const path = `${apiRoot}/diary/${day}`;
  const entry = await api(path);
  sheet(pet, href, path, entry);
}
