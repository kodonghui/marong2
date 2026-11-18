import {action, api, button, el, header, link, notice, show, showTabs, text} from './pet.js';

const POSITIONS = [['head', '머리'], ['body', '몸'], ['neck', '목']];
const WEAR = '/api/me/inventory?kind=wear';
const part = encodeURIComponent;

export function itemThumb(id, name, style = '') {
  const image = el('img', {src: `/static/items/${part(id)}/thumb.webp`, alt: name});
  image.addEventListener('error', () => { image.hidden = true; });
  return el('div', {class: `picture ${style}`}, image);
}

export function outfitOf(pet) {
  return Object.fromEntries(POSITIONS.map(([slot]) => [slot, pet.outfit?.[slot] ?? null]));
}

export function petLayers(pet, outfit, errorMessage, {onLayerError} = {}) {
  const label = el('p', {hidden: true, class: 'muted', role: 'status'}, errorMessage);
  const stage = el('div', {class: 'outfit-stage'},
    el('img', {class: 'outfit-background', alt: '',
      src: `/static/backgrounds/${pet.mode === 'memorial' ? 'memorial_meadow' : 'home_livingroom'}.webp`}));
  stage.firstElementChild.addEventListener('error', event => { event.target.hidden = true; });
  if (pet.sheet?.front) stage.append(el('img', {class: 'outfit-layer', src: pet.sheet.front, alt: pet.name}));
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
  return el('div', {class: 'stack'}, stage, label);
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
