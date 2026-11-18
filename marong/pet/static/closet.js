import {action, api, button, el, header, link, notice, show, showTabs, text} from './pet.js';

const POSITIONS = [['head', '머리'], ['body', '몸'], ['neck', '목']];
const WEAR = '/api/me/inventory?kind=wear';
const part = encodeURIComponent;
const spriteBounds = new Map();
let manifest;

export function itemThumb(id, name, style = '') {
  const image = el('img', {src: `/static/items/${part(id)}/thumb.webp`, alt: name});
  image.addEventListener('error', () => { image.hidden = true; });
  return el('div', {class: `picture ${style}`}, image);
}

export function outfitOf(pet) {
  return Object.fromEntries(POSITIONS.map(([slot]) => [slot, pet.outfit?.[slot] ?? null]));
}

function measures(image) {
  if (spriteBounds.has(image.src)) return spriteBounds.get(image.src);
  const width = image.naturalWidth, height = image.naturalHeight;
  if (!width || !height || width > 2048 || height > 2048) return null;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d', {willReadFrequently: true});
  if (!context) return null;
  context.drawImage(image, 0, 0);
  const {data} = context.getImageData(0, 0, width, height);
  let left = width, top = height, right = 0, bottom = 0;
  for (let pixel = 0; pixel < width * height; pixel++) {
    if (data[pixel * 4 + 3] < 128) continue;
    const x = pixel % width, y = Math.floor(pixel / width);
    left = Math.min(left, x);
    top = Math.min(top, y);
    right = Math.max(right, x + 1);
    bottom = Math.max(bottom, y + 1);
  }
  const box = bottom > top ? {width, height, left, top, right, bottom} : null;
  spriteBounds.set(image.src, box);
  return box;
}

async function positionSprite(stage, image, backdrop, fallback) {
  try {
    manifest ||= fetch('/static/backgrounds/stages.json').then(response => response.ok ? response.json() : null)
      .catch(() => null);
    const canvas = await manifest;
    const position = canvas?.stages[backdrop] || canvas?.stages[fallback];
    if (!position) return;
    const box = measures(image);
    if (!box) return;
    const scale = position.height / (box.bottom - box.top);
    const x = Math.round(position.centerX - (box.left + box.right) * scale / 2);
    const y = Math.round(position.floorY - box.bottom * scale);
    stage.style.setProperty('--sprite-left', x / canvas.width * 100 + '%');
    stage.style.setProperty('--sprite-top', y / canvas.height * 100 + '%');
    stage.style.setProperty('--sprite-width', Math.round(box.width * scale) / canvas.width * 100 + '%');
    stage.style.setProperty('--sprite-height', Math.round(box.height * scale) / canvas.height * 100 + '%');
    stage.dataset.aligned = 'true';
  } catch {
    // If the picture cannot be measured, keep the centered preview.
  }
}

export function petLayers(pet, outfit, errorMessage, {onLayerError, background, expression = 'front'} = {}) {
  const label = el('p', {hidden: true, class: 'muted', role: 'status'}, errorMessage);
  const fallback = pet.mode === 'memorial' ? 'rainbow_meadow' : 'home_livingroom';
  let backdrop = /^[a-z0-9_]{1,40}$/.test(background || '') ? background : fallback;
  const stage = el('div', {class: 'outfit-stage'},
    el('img', {class: 'outfit-background', alt: '',
      src: `/static/backgrounds/${backdrop}.webp`}));
  const backdropImage = stage.firstElementChild;
  const face = pet.sheet?.[expression] || pet.sheet?.front;
  const sprite = face ? el('img', {class: 'outfit-layer', src: face, alt: pet.name}) : null;
  const spriteError = el('div', {class: 'stack', hidden: true}, text('그림을 불러오지 못했어요'),
    button('다시 보기', () => {
      if (!sprite) return;
      spriteError.hidden = true;
      sprite.hidden = false;
      sprite.removeAttribute('src');
      sprite.src = face;
    }, 'plain'));
  const align = () => { if (sprite?.naturalWidth) positionSprite(stage, sprite, backdrop, fallback); };
  if (sprite) {
    sprite.addEventListener('load', align, {once: true});
    sprite.addEventListener('error', () => {
      sprite.hidden = true;
      spriteError.hidden = false;
    });
    stage.append(sprite);
    if (sprite.complete) align();
  }
  backdropImage.addEventListener('error', () => {
    if (backdrop === fallback) { backdropImage.hidden = true; return; }
    backdrop = fallback;
    backdropImage.src = `/static/backgrounds/${backdrop}.webp`;
    align();
  });
  for (const slot of ['body', 'neck', 'head']) {
    if (!outfit[slot] || !pet.template) continue;
    const layer = el('img', {class: 'outfit-layer', alt: '', 'data-slot': slot,
      src: `/api/items/${part(outfit[slot])}/layer?template=${part(pet.template)}`});
    layer.addEventListener('error', () => {
      layer.hidden = true;
      label.hidden = false;
      onLayerError?.(outfit[slot]);
    });
    stage.append(layer);
  }
  return el('div', {class: 'stack'}, stage, spriteError, label);
}

export async function closet(id) {
  const url = `/pets/${part(id)}`;
  header('옷 입히기', {label: '대화', url});
  let pet = await api(`/api${url}`);
  if (pet.status === 'archived') {
    show(notice('보관한 아이예요.', link('돌아가기', url)));
    return;
  }
  let [{items}, {items: pets}] = await Promise.all([api(WEAR), api('/api/pets')]);
  const names = new Map(pets.map(child => [child.id, child.name]));
  const stage = el('div', {});
  const grid = el('div', {class: 'grid'});
  const outlet = el('div', {'aria-live': 'polite'});
  const slots = el('div', {class: 'slots', role: 'group', 'aria-label': '옷 입힐 자리'});
  let selected = 'head';
  let saving = false;
  let wear = outfitOf(pet);
  const options = POSITIONS.map(([key, label]) => {
    const option = button(label, () => { if (!saving) { selected = key; render(); } });
    slots.append(option);
    return [key, option];
  });

  function preview(value) {
    stage.replaceChildren(petLayers(pet, value, '미리 보기를 불러오지 못했어요'));
  }

  async function update(item, control) {
    if (saving || !navigator.onLine) return;
    saving = true;
    for (const entry of [...slots.children, ...grid.querySelectorAll('button')]) entry.disabled = entry !== control;
    const next = {...wear, [item.slot]: wear[item.slot] === item.itemId ? null : item.itemId};
    await action(control, outlet, async () => {
      preview(next);
      try {
        pet = await api(`/api${url}/outfit`, {method: 'PUT', body: next});
        wear = outfitOf(pet);
        if (next[item.slot] && item.withdrawableUntil) item.withdrawableUntil = null;
      } catch (error) {
        preview(wear);
        if (error.code === 'archived') {
          show(notice('보관한 아이예요.', link('돌아가기', url)));
          return;
        }
        if (error.code === 'wrong_slot' || error.status === 404) {
          outlet.replaceChildren(text('입힐 수 없어요', 'error'));
          ({items} = await api(WEAR));
        } else {
          throw error;
        }
      }
    });
    saving = false;
    render();
  }

  function render() {
    preview(wear);
    for (const [key, option] of options) {
      option.disabled = false;
      option.setAttribute('aria-pressed', selected === key);
    }
    grid.replaceChildren();
    for (const item of items.filter(entry => entry.slot === selected)) {
      const wearing = wear[item.slot] === item.itemId;
      const card = el('button', {type: 'button', class: 'outfit-item busy', 'aria-pressed': wearing},
        itemThumb(item.itemId, ''), el('span', {}, `${wearing ? '✓ ' : ''}${item.name}`),
        ...(item.wornBy || []).filter(key => key !== id && names.has(key))
          .map(key => el('small', {}, `${names.get(key)}도 입어요`)));
      card.addEventListener('click', () => {
        if (saving) return;
        if (!wearing && item.withdrawableUntil) {
          const sheet = el('dialog', {class: 'sheet stack'}, text('입히면 이 아이템은 청약철회할 수 없어요. 입힐까요?'),
            button('입히기', async () => { sheet.close(); await update(item, card); }, 'primary'),
            button('아니요', () => sheet.close()));
          sheet.addEventListener('close', () => sheet.remove(), {once: true});
          grid.append(sheet);
          sheet.showModal();
          return;
        }
        void update(item, card);
      });
      grid.append(card);
    }
    if (!grid.childElementCount) grid.append(text('이 자리에 입힐 아이템이 없어요.', 'muted outfit-wide'));
  }

  showTabs('/', pets.some(child => child.shopEntry));
  render();
  show(stage, slots, grid, outlet, pet.mode === 'living' && pet.shopEntry ? link('상점에서 더 보기', `/shop?pet=${part(id)}`) : null);
}
