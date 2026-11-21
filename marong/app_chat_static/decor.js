'use strict';

(() => {
  const {node, button, link, request, signal} = Unified;
  const title = document.getElementById('decor-title');
  const target = document.getElementById('decor-content');
  const screen = document.getElementById('decor-screen');
  const error = document.getElementById('decor-error');
  const shop = location.pathname === '/chat/shop';
  const diary = location.pathname === '/chat/diary/decor';
  const kinds = {hat: '모자', top: '옷', scarf: '목도리', background: '배경', paper: '속지', font: '글꼴', sticker: '스티커'};
  const slots = {head: '머리', body: '몸', neck: '목'};
  let inventory, profile, tab = 'wear', diaryStyle, diaryExample;

  function problem(reply) {
    if (reply.status === 401) { location.replace('/chat/login'); return; }
    const codes = {not_found: '지금은 받을 수 없는 아이템이야', not_owned: diary ? '아직 안 받은 거야' : '보관함에 없는 아이템이야',
                   not_ready: '캐릭터를 먼저 완성해 줘'};
    signal(error, codes[reply.body?.code] || '잠깐 문제가 생겼어. 다시 해 볼래?', reply);
  }

  function face(outfit, item) {
    const pet = profile.character;
    const frame = node('div', '', 'decor-face');
    const base = node('img');
    base.alt = '';
    base.src = pet ? '/chat/api/characters/' + pet.id + '/images/smile' : '/face/v1/01-neutral.webp';
    frame.append(base);
    if (!pet) return frame;
    for (const slot of ['body', 'neck', 'head']) {
      const layer = node('img', '', 'decor-layer');
      layer.alt = '';
      const source = item?.slot === slot ? item.thumbUrl.replace(/thumb\.webp$/, pet.template + '.png') : outfit?.[slot]?.layerUrl;
      if (!source) continue;
      layer.src = source;
      layer.addEventListener('error', () => layer.remove(), {once: true});
      frame.append(layer);
    }
    return frame;
  }

  function itemCard(item, detail = false) {
    const card = node('div', '', 'card');
    const thumb = node('img', '', 'decor-thumb');
    thumb.alt = '';
    thumb.src = item.thumbUrl;
    card.append(thumb, node('h2', item.name));
    if (shop) {
      card.append(node('p', '0원', 'caption'));
      if (!detail) card.append(link('아이템 보기', '#' + item.id, 'btnt'));
      const claim = button(item.owned ? '받았어' : '받기', async () => {
        claim.disabled = true;
        const result = await request('/chat/api/shop/' + item.id + '/claim', undefined, 'POST');
        if ([200, 201].includes(result.status)) {
          item.owned = true;
          render();
        } else {
          problem(result);
          claim.disabled = false;
        }
      }, 'btn2');
      claim.disabled = item.owned;
      card.append(claim);
    }
    return card;
  }

  function storefront() {
    const id = location.hash.slice(1);
    const detail = inventory.items.find(item => item.id === id);
    if (detail) {
      target.append(link('상점으로', '/chat/shop', 'btnt'));
      if (detail.slot) {
        target.append(face(profile.character?.outfit, detail));
        if (!profile.character) target.append(node('p', '반려동물 캐릭터를 적용하면 입혀 볼 수 있어', 'caption'));
      }
      target.append(itemCard(detail, true));
    } else {
      if (!inventory.items.length) target.append(node('p', '상점에 올라온 아이템이 없어', 'caption'));
      for (const [kind, label] of Object.entries(kinds)) {
        const items = inventory.items.filter(item => item.kind === kind);
        if (items.length) target.append(node('h2', label), ...items.map(item => itemCard(item)));
      }
    }
  }

  function closet() {
    const tabs = node('div', '', 'character-tabs');
    for (const [key, name] of [['wear', '입는 것'], ['diary', '일기장']]) {
      const choice = button(name, () => { tab = key; render(); }, 'btn2');
      choice.setAttribute('aria-pressed', String(tab === key));
      tabs.append(choice);
    }
    target.append(tabs);
    if (tab === 'diary') {
      target.append(link('일기장 꾸미기', '/chat/diary/decor', 'btn2'),
                    ...inventory.items.filter(item => !item.slot).map(item => itemCard(item)));
      return;
    }
    target.append(face(inventory.outfit));
    if (!inventory.characterId) {
      target.append(node('p', '반려동물 캐릭터를 적용하면 입혀 볼 수 있어', 'caption'), link('내 마롱이', '/chat/me', 'btn2'));
      return;
    }
    const controls = Object.entries(slots).map(([slot, label]) => {
      const wrap = node('label', label, 'field-label');
      const select = node('select');
      const empty = node('option', '벗기');
      empty.value = '';
      select.append(empty);
      for (const item of inventory.items.filter(item => item.slot === slot)) {
        const option = node('option', item.name);
        option.value = item.id;
        select.append(option);
      }
      select.value = inventory.outfit?.[slot]?.id || '';
      wrap.append(select);
      target.append(wrap);
      return [slot, select];
    });
    const save = button('이렇게 입을래', async () => {
      save.disabled = true;
      const selected = Object.fromEntries(controls.map(([slot, control]) => [slot, control.value || null]));
      const result = await request('/chat/api/characters/' + inventory.characterId + '/outfit', selected, 'PUT');
      save.disabled = false;
      if (result.status === 200) {
        inventory.outfit = result.body;
        render();
      } else problem(result);
    });
    target.append(save);
  }

  function diaryEditor() {
    const preview = node('div', '', 'decor-book-preview');
    target.append(preview);
    const controls = ['background', 'paper', 'font'].map(kind => {
      const wrap = node('label', kinds[kind], 'field-label');
      const select = node('select');
      select.setAttribute('aria-label', kinds[kind]);
      for (const item of inventory.items.filter(item => item.kind === kind)) {
        const option = node('option', item.name);
        option.value = item.id;
        select.append(option);
      }
      select.value = diaryStyle[kind].id;
      select.addEventListener('change', paint);
      wrap.append(select);
      target.append(wrap);
      return [kind, select];
    });
    async function paint() {
      const paper = node('article', diaryExample?.body || '오늘은 산책을 했다…', 'decor-paper-preview');
      if (diaryExample?.drawing?.kind === 'ai') {
        const picture = node('img');
        picture.alt = '';
        picture.src = '/chat/diary/api/drawings/' + diaryExample.drawing.id;
        paper.prepend(picture);
      }
      const fontStatus = node('p', '글꼴 받는 중…', 'caption');
      const frame = node('div', '', 'decor-book-preview-frame');
      frame.append(paper);
      preview.replaceChildren(frame, fontStatus);
      const files = {background: 'bg.webp', paper: 'paper.webp', font: 'font.woff2'};
      const values = Object.fromEntries(controls.map(([kind, control]) => {
        const item = inventory.items.find(row => row.id === control.value);
        const url = item && !item.starter ? item.thumbUrl.replace(/thumb\.webp$/, files[kind]) : null;
        return [kind, {[kind === 'font' ? 'fontUrl' : 'imageUrl']: url}];
      }));
      fontStatus.hidden = !values.font.fontUrl;
      try {
        const {paintDecor} = await import('/chat/diary/decor.js');
        await paintDecor(paper, frame, values);
      } catch {
        // The preview still works with the default style.
      } finally {
        fontStatus.hidden = true;
      }
    }
    const save = button('이걸로 할래', async () => {
      if (controls.some(([, control]) => !control.value)) return;
      save.disabled = true;
      const body = Object.fromEntries(controls.map(([key, control]) => [key + 'Id', control.value]));
      const reply = await request('/chat/diary/api/decor', body, 'PUT');
      if (reply.status === 200) {
        sessionStorage.setItem('diary-decor-saved', '1');
        location.replace('/chat/diary/');
      }
      else { save.disabled = false; problem(reply); }
    });
    save.disabled = controls.some(([, control]) => !control.value);
    const reset = button('처음 모습으로', () => {
      for (const [kind, control] of controls) {
        const starter = inventory.items.find(item => item.starter && item.kind === kind);
        if (starter) control.value = starter.id;
      }
      paint();
    }, 'btn2');
    target.append(save, reset, link('일기장으로', '/chat/diary/', 'btnt'));
    paint();
  }

  function render() {
    signal(error);
    target.replaceChildren();
    title.textContent = diary ? '일기장 꾸미기' : shop ? '상점' : '보관함';
    if (diary) diaryEditor();
    else if (shop) storefront();
    else closet();
  }

  async function load() {
    const [list, me, decor] = await Promise.all([request(shop ? '/chat/api/shop' : '/chat/api/closet'),
      request('/chat/api/profile'), diary ? request('/chat/diary/api/decor') : null]);
    screen.setAttribute('aria-busy', 'false');
    if (list.status !== 200 || me.status !== 200) { problem(list.status !== 200 ? list : me); return; }
    inventory = list.body;
    profile = me.body;
    if (diary) {
      if (decor.status !== 200) { problem(decor); return; }
      diaryStyle = decor.body;
      diaryExample = null;
      const recent = await request('/chat/diary/api/latest');
      if (recent.status === 200 && recent.body.date) {
        const day = await request('/chat/diary/api/days/' + recent.body.date);
        if (day.status === 200) diaryExample = day.body.diary;
      }
    }
    render();
  }
  window.addEventListener('hashchange', () => { if (inventory) render(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  load();
})();
