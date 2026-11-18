import {action, api, banner, button, currency, dateLabel, el, Failure, header, link, notice, page, show, showTabs, signIn, text} from './pet.js';
import {itemThumb, outfitOf, petLayers} from './closet.js';

const CATEGORIES = [['wear', '착용'], ['sticker_pack', '스티커'], ['theme', '일기장 테마'], ['theme_package', '테마 패키지']];
const POLICY = '산 지 7일 안이고 한 번도 입히거나 적용하거나 붙이지 않았으면 철회할 수 있어요.';
const part = encodeURIComponent;

const alive = pets => pets.filter(pet => pet.mode === 'living' && pet.status === 'active');
const price = item => `${currency.format(item.priceKrw)}원`;

export function business(me) {
  if (!me.business) return null;
  return el('details', {class: 'card'}, el('summary', {}, '사업자 정보'),
    el('dl', {}, ...Object.entries(me.business).flatMap(([key, value]) => [el('dt', {}, key), el('dd', {}, value)])));
}

function shopAccess(pets) {
  showTabs('/shop', pets.length > 0);
  if (pets.length) return true;
  show(notice('함께 사는 아이가 있을 때 열려요.', link('홈으로', '/')));
  return false;
}

export async function shop() {
  header('상점', {label: '홈', url: '/'});
  showTabs(null);
  show(el('div', {class: 'skeleton label-placeholder', 'aria-hidden': 'true'}),
    el('div', {class: 'grid'}, Array.from({length: 6}, () => el('div', {class: 'skeleton', 'aria-hidden': 'true'}))));
  page.setAttribute('aria-busy', 'true');
  const [{items: pets}, me] = await Promise.all([api('/api/pets'), api('/api/me')]);
  if (!shopAccess(alive(pets))) return;
  const query = new URLSearchParams(location.search);
  const pet = query.get('pet');
  let kind = query.get('kind');
  if (!CATEGORIES.some(([category]) => category === kind)) kind = 'wear';
  const controls = el('div', {class: 'row', role: 'group', 'aria-label': '아이템 종류'});
  const results = el('div', {class: 'grid', 'aria-live': 'polite'});
  const message = el('div', {});
  let request = 0;
  const filters = CATEGORIES.map(([category, title]) => {
    const control = button(title, () => void load(category));
    controls.append(control);
    return [category, control];
  });
  async function load(category) {
    const token = ++request;
    for (const [key, control] of filters) control.setAttribute('aria-pressed', key === category);
    results.setAttribute('aria-busy', 'true');
    results.replaceChildren(...Array.from({length: 6}, () => el('div', {class: 'skeleton', 'aria-hidden': 'true'})));
    try {
      const {items} = await api(`/api/shop?kind=${part(category)}`);
      if (token !== request) return;
      message.replaceChildren(...(!me.paymentsEnabled || items.some(item => !item.owned && !item.purchasable)
        ? [banner('결제는 곧 열려요.')] : []));
      results.replaceChildren(...(items.length ? items.map(item => {
        const target = `/shop/${part(item.id)}?kind=${part(category)}${pet ? `&pet=${part(pet)}` : ''}`;
        return el('a', {class: 'card stack shop-item', href: target}, itemThumb(item.id, ''),
          el('h2', {}, item.name), text(price(item)),
          item.limited && item.saleEndsAt ? el('small', {}, `${dateLabel(item.saleEndsAt)}까지`) : null,
          item.owned ? el('small', {}, '가지고 있어요') : null);
      }) : [text('지금은 팔고 있는 것이 없어요.', 'muted outfit-wide')]));
    } catch (error) {
      if (token !== request || error.status === 401) return;
      results.replaceChildren(notice('잠시 뒤 다시 해 주세요.', button('다시 해 보기', () => void load(category)), 'outfit-wide'));
    } finally {
      if (token === request) results.setAttribute('aria-busy', 'false');
    }
  }
  show(text('모두 정가예요. 뽑기는 없어요'), controls, message, results, business(me));
  await load(kind);
}

export async function shopItem(id) {
  const query = new URLSearchParams(location.search);
  const kind = query.get('kind');
  const suffix = CATEGORIES.some(([category]) => category === kind) ? `?kind=${part(kind)}` : '';
  const url = '/shop' + suffix;
  header('아이템 보기', {label: '상점', url});
  showTabs(null);
  show(el('div', {class: 'skeleton shop-preview-placeholder', 'aria-hidden': 'true'}),
    ...Array.from({length: 3}, () => el('div', {class: 'skeleton label-placeholder', 'aria-hidden': 'true'})));
  page.setAttribute('aria-busy', 'true');
  const [{items: pets}, me] = await Promise.all([api('/api/pets'), api('/api/me')]);
  const living = alive(pets);
  if (!shopAccess(living)) return;
  const {items} = await api('/api/shop' + suffix);
  const item = items.find(value => value.id === id);
  let previewRequest = 0, previewFetch, previewUrl;
  function releasePreview() {
    previewFetch?.abort();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  }
  function soldOut() {
    previewRequest += 1;
    releasePreview();
    show(notice('판매가 끝났어요.', link('상점으로', url)));
  }
  if (!item) return soldOut();
  window.addEventListener('pagehide', event => { if (!event.persisted) releasePreview(); });
  header(item.name, {label: '상점', url});
  let picked = living.find(pet => pet.id === query.get('pet')) || living[0];
  const stage = el('div', {class: 'stack'});
  const controls = el('div', {class: 'row', role: 'group', 'aria-label': '입혀 볼 아이'});
  const purchase = el('div', {class: 'stack'});
  const choices = living.map(child => {
    const control = button(child.name, () => { picked = child; drawPurchase(); void preview(); });
    controls.append(control);
    return [child.id, control];
  });
  async function preview() {
    const token = ++previewRequest;
    releasePreview();
    for (const [key, control] of choices) control.setAttribute('aria-pressed', key === picked.id);
    if (item.kind !== 'wear') {
      stage.replaceChildren(itemThumb(item.id, item.name));
      return;
    }
    const controller = new AbortController();
    previewFetch = controller;
    const unavailable = () => {
      releasePreview();
      stage.replaceChildren(itemThumb(item.id, item.name), text('입혀 보기를 불러오지 못했어요', 'muted'));
    };
    stage.replaceChildren(el('div', {class: 'skeleton shop-preview-placeholder', 'aria-hidden': 'true'}));
    try {
      const pet = await api(`/api/pets/${part(picked.id)}`);
      if (token !== previewRequest) return;
      const response = await fetch(`/api/items/${part(item.id)}/layer?template=${part(pet.template)}`,
        {signal: controller.signal, cache: 'no-store'});
      if (token !== previewRequest) return;
      if (response.status === 404) { soldOut(); return; }
      if (response.status === 401) { signIn(); return; }
      if (!response.ok) { unavailable(); return; }
      const raster = await response.blob();
      if (token !== previewRequest) return;
      if (raster.type !== 'image/png') { unavailable(); return; }
      previewUrl = URL.createObjectURL(raster);
      stage.replaceChildren(petLayers(pet, {...outfitOf(pet), [item.slot]: item.id}, '입혀 보기를 불러오지 못했어요', {
        layerUrls: {[item.id]: previewUrl},
        onLayerError: failed => {
          if (failed === item.id && token === previewRequest) unavailable();
        },
      }));
    } catch (error) {
      if (token === previewRequest && error.status !== 401 && error.name !== 'AbortError') unavailable();
    }
  }
  function drawPurchase() {
    const petPath = `/pets/${part(picked.id)}`;
    if (item.owned) {
      purchase.replaceChildren(notice('가지고 있어요', item.kind === 'wear' ? link('입히러 가기', petPath + '/closet')
        : link('일기장에서 쓰기', petPath + '/diary')));
      return;
    }
    const buy = button('사기', () => sheet.showModal(), 'primary');
    if (me.status === 'minor_locked') {
      buy.disabled = true;
      purchase.replaceChildren(banner('이 서비스는 만 19세 이상만 쓸 수 있어요.'), buy);
      return;
    }
    if (!me.paymentsEnabled || !item.purchasable) {
      buy.disabled = true;
      purchase.replaceChildren(banner('결제는 곧 열려요.'), buy);
      return;
    }
    const outlet = el('div', {'aria-live': 'polite'});
    const confirm = button('결제하기', () => action(confirm, outlet, async () => {
      const key = `pet:item-order:${item.id}`;
      const idempotencyKey = sessionStorage.getItem(key) || crypto.randomUUID();
      sessionStorage.setItem(key, idempotencyKey);
      sessionStorage.setItem('pet_pay_return', location.pathname + location.search);
      let result;
      try {
        result = await api('/api/orders', {method: 'POST', body: {product: 'item', itemId: item.id, idempotencyKey}});
      } catch (error) {
        if (error.code === 'already_owned') {
          item.owned = true;
          sheet.close();
          drawPurchase();
          return;
        }
        if (error.status === 404) return soldOut();
        if (error.code === 'payments_off') {
          item.purchasable = false;
          sheet.close();
          drawPurchase();
          return;
        }
        if (error.code === 'identity_required') {
          outlet.replaceChildren(notice('첫 결제 전에 본인인증을 한 번 해 주세요.', link('내 정보', '/me')));
          return;
        }
        throw error;
      }
      if (result.order?.status === 'fulfilled') {
        item.owned = true;
        sessionStorage.removeItem(key);
        sheet.close();
        drawPurchase();
        return;
      }
      // The provider-specific checkout window is connected when its SDK is selected.
      throw new Failure(503);
    }), 'primary');
    const sheet = el('dialog', {class: 'sheet stack'}, el('h2', {}, item.name), text(`${price(item)}, 부가세 포함`),
      text(POLICY), business(me), outlet, confirm, button('닫기', () => sheet.close()));
    purchase.replaceChildren(buy, sheet);
  }
  show(stage, item.kind === 'wear' && living.length > 1 ? controls : null,
    el('section', {class: 'card stack'}, el('h2', {}, item.name), text(`${price(item)}(부가세 포함)`),
      item.limited && item.saleEndsAt ? text(`${dateLabel(item.saleEndsAt)}까지`) : null,
      item.kind === 'theme_package' && item.contents.length ? el('ul', {}, ...item.contents.map(value => el('li', {}, value))) : null,
      text(POLICY, 'muted'), purchase), business(me));
  drawPurchase();
  await preview();
}
