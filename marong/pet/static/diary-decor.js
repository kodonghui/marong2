import {action, api, button, el, text} from './pet.js';

const UUID = /^[a-f0-9-]{36}$/;
const STICKER = /^[a-z0-9_-]{1,40}$/;
const TABS = {theme: '테마', font: '글꼴', sticker_pack: '스티커'};
const fonts = new Map();
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

function asset(id, name) {
  return UUID.test(id || '') ? '/static/items/' + id + '/' + name : null;
}

function applyFont(element, id) {
  element.style.fontFamily = '';
  const url = asset(id, 'font.woff2');
  if (!url || !window.FontFace) return;
  if (!fonts.has(id)) {
    const face = new FontFace('diary-' + id, 'url("' + url + '")');
    fonts.set(id, face.load().then(loaded => {
      document.fonts.add(loaded);
      return loaded.family;
    }).catch(() => {
      fonts.delete(id);
      return '';
    }));
  }
  const request = fonts.get(id);
  element.dataset.diaryFont = id;
  request.then(family => {
    if (element.dataset.diaryFont === id) element.style.fontFamily = family;
  });
}

function paintSticker(node, sticker) {
  node.style.left = sticker.x * 100 + '%';
  node.style.top = sticker.y * 100 + '%';
  node.style.transform = 'translate(-50%, -50%) rotate(' + sticker.rotate + 'deg) scale(' + sticker.scale + ')';
}

function points(pointerMap) {
  const [first, second] = pointerMap.values();
  if (!second) return null;
  const x = second[0] - first[0], y = second[1] - first[1];
  return {distance: Math.hypot(x, y), angle: Math.atan2(y, x), x: (first[0] + second[0]) / 2,
    y: (first[1] + second[1]) / 2};
}

function moveSticker(node, container, sticker, select) {
  const pointers = new Map();
  let gesture;
  const place = (x, y) => {
    const rect = container.getBoundingClientRect();
    sticker.x = clamp((x - rect.left) / rect.width, 0, 1);
    sticker.y = clamp((y - rect.top) / rect.height, 0, 1);
  };
  node.addEventListener('pointerdown', event => {
    select();
    pointers.set(event.pointerId, [event.clientX, event.clientY]);
    const pair = points(pointers);
    if (pair) gesture = {...pair, scale: sticker.scale, rotate: sticker.rotate};
    node.setPointerCapture(event.pointerId);
  });
  node.addEventListener('pointermove', event => {
    if (!pointers.has(event.pointerId)) return;
    pointers.set(event.pointerId, [event.clientX, event.clientY]);
    const pair = points(pointers);
    if (pair && gesture && gesture.distance > 0) {
      sticker.scale = clamp(gesture.scale * pair.distance / gesture.distance, .5, 2);
      const delta = Math.atan2(Math.sin(pair.angle - gesture.angle), Math.cos(pair.angle - gesture.angle));
      sticker.rotate = clamp(gesture.rotate + delta * 180 / Math.PI, -45, 45);
      place(pair.x, pair.y);
    } else if (!pair) {
      place(event.clientX, event.clientY);
    }
    paintSticker(node, sticker);
  });
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    node.addEventListener(type, event => {
      pointers.delete(event.pointerId);
      gesture = null;
    });
  }
}

export function paintDiary(paper, artwork, style, stickers, choose) {
  const background = asset(style.themeId, 'background.webp');
  paper.style.backgroundImage = background ? 'url("' + background + '")' : '';
  const body = paper.querySelector('.diary-body');
  body.dataset.diaryFont = '';
  applyFont(body, style.fontId);
  const overlay = artwork.querySelector('.diary-stickers');
  overlay.replaceChildren();
  for (const [index, sticker] of stickers.entries()) {
    const url = STICKER.test(sticker.sticker || '') ? asset(sticker.packId, 'stickers/' + sticker.sticker + '.webp') : null;
    if (!url) continue;
    const image = el('img', {src: url, alt: '', draggable: 'false'});
    const marker = choose ? button('', () => choose(index), 'diary-sticker') :
      el('span', {class: 'diary-sticker'});
    if (choose) {
      marker.setAttribute('aria-pressed', 'false');
      marker.setAttribute('aria-label', '스티커 ' + (index + 1));
    }
    marker.classList.toggle('moveable', Boolean(choose));
    if (choose) {
      marker.addEventListener('keydown', event => {
        const movement = {ArrowLeft: [-.02, 0], ArrowRight: [.02, 0], ArrowUp: [0, -.02], ArrowDown: [0, .02]}[event.key];
        if (!movement) return;
        event.preventDefault();
        sticker.x = clamp(sticker.x + movement[0], 0, 1);
        sticker.y = clamp(sticker.y + movement[1], 0, 1);
        paintSticker(marker, sticker);
        choose(index);
      });
      moveSticker(marker, artwork, sticker, () => choose(index));
    }
    marker.append(image);
    paintSticker(marker, sticker);
    overlay.append(marker);
  }
  return overlay;
}

function approveUse(item, outlet) {
  if (!item.withdrawableUntil) return Promise.resolve(true);
  const label = {theme: '테마를', font: '글꼴을', sticker_pack: '스티커를'}[item.kind];
  return new Promise(resolve => {
    const confirm = el('dialog', {class: 'sheet stack'},
      text('이 ' + label + ' 쓰면 청약철회할 수 없어요. 쓸까요?'),
      button('아니요', () => confirm.close()), button('쓸게요', () => confirm.close('use'), 'primary'));
    confirm.addEventListener('close', () => {
      confirm.remove();
      resolve(confirm.returnValue === 'use');
    }, {once: true});
    outlet.append(confirm);
    confirm.showModal();
  });
}

export async function decorateDiary(pet, path, entry, paper, artwork, outlet, done) {
  const {items} = await api('/api/me/inventory');
  const inventory = items.filter(item => Object.hasOwn(TABS, item.kind));
  const originalStyle = pet.diaryStyle || {themeId: null, fontId: null};
  const originalStickers = entry.stickers || [];
  const style = {...originalStyle};
  const stickers = originalStickers.map(sticker => ({...sticker}));
  const approved = new Set();
  const notice = el('div', {'aria-live': 'polite'});
  const choices = el('div', {class: 'diary-choices'});
  let tab = 'theme', selected = -1, overlay;
  const edit = el('div', {class: 'stack diary-editor'});

  function preview() {
    overlay = paintDiary(paper, artwork, style, stickers, choose);
    choose(selected, false);
  }

  function choose(index, update = true) {
    selected = index;
    overlay.querySelectorAll('button').forEach((node, current) => node.setAttribute('aria-pressed', current === index));
    if (update && tab === 'sticker_pack') showChoices();
  }

  async function approve(item) {
    if (approved.has(item.itemId)) return true;
    if (!await approveUse(item, edit)) return false;
    approved.add(item.itemId);
    return true;
  }

  function showChoices() {
    choices.replaceChildren();
    if (tab !== 'sticker_pack') {
      const field = tab + 'Id';
      choices.append(button('기본', () => { style[field] = null; preview(); showChoices(); }));
      for (const item of inventory.filter(row => row.kind === tab)) {
        const pick = button(item.name, () => action(pick, notice, async () => {
          if (!await approve(item)) return;
          style[field] = item.itemId;
          preview();
          showChoices();
        }));
        pick.setAttribute('aria-pressed', style[field] === item.itemId);
        choices.append(pick);
      }
      return;
    }
    for (const item of inventory.filter(row => row.kind === 'sticker_pack')) {
      for (const name of item.contents.filter(value => STICKER.test(value))) {
        const pick = button(item.name, () => action(pick, notice, async () => {
          if (stickers.length >= 10) { notice.replaceChildren(text('스티커는 10개까지예요')); return; }
          if (!await approve(item)) return;
          stickers.push({packId: item.itemId, sticker: name, x: .5, y: .5, scale: 1, rotate: 0});
          selected = stickers.length - 1;
          preview();
          showChoices();
        }));
        pick.replaceChildren(el('img', {src: asset(item.itemId, 'stickers/' + name + '.webp'), alt: item.name}));
        choices.append(pick);
      }
    }
    if (selected >= 0) choices.append(button('떼기', () => {
      stickers.splice(selected, 1);
      selected = -1;
      preview();
      showChoices();
    }));
  }

  const menu = el('div', {class: 'row'}, Object.entries(TABS).map(([key, label]) => {
    const control = button(label, () => {
      for (const sibling of menu.children) sibling.setAttribute('aria-pressed', String(sibling === control));
      tab = key;
      showChoices();
    });
    control.setAttribute('aria-pressed', key === tab);
    return control;
  }));
  const cancel = button('취소', () => done(pet, entry));
  const save = button('저장', () => action(save, notice, async () => {
    const changedStyle = style.themeId !== originalStyle.themeId || style.fontId !== originalStyle.fontId;
    const changedStickers = JSON.stringify(stickers) !== JSON.stringify(originalStickers);
    let savedPet = pet;
    let savedEntry = entry;
    cancel.disabled = true;
    choices.inert = menu.inert = artwork.inert = true;
    try {
      if (changedStyle) savedPet = await api('/api/pets/' + pet.id + '/diary-style', {method: 'PUT', body: style});
      if (changedStickers) savedEntry = await api(path + '/stickers', {method: 'PUT', body: stickers});
    } catch (error) {
      if (error.status === 409 || error.status === 404 || savedPet !== pet) {
        const [freshPet, freshEntry] = await Promise.all([api('/api/pets/' + pet.id), api(path)]);
        done(freshPet, freshEntry);
        return;
      }
      throw error;
    } finally {
      cancel.disabled = false;
      choices.inert = menu.inert = artwork.inert = false;
    }
    done(savedPet, savedEntry);
  }), 'primary');
  edit.append(el('div', {class: 'row'}, cancel, save), menu, choices, notice);
  preview();
  showChoices();
  outlet.replaceChildren(edit);
}
