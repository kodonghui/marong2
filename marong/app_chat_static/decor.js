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
  let inventory, profile, tab = 'wear', shopTab = 'wear', diaryStyle, diaryExample;
  let wearConfirmed, wearPending = [], wearBusy = false, wearCurrent = null;

  function problem(reply) {
    if (reply.status === 401) { location.replace('/chat/login'); return; }
    const codes = {cross_site: '이 화면에서 다시 해 줘', not_found: '지금은 받을 수 없는 아이템이야', not_owned: diary ? '아직 안 받은 거야' : '보관함에 없는 아이템이야',
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
    const name = !shop && ['background', 'paper', 'font'].includes(item.kind)
      ? link(item.name, '/chat/diary/decor#' + encodeURIComponent(item.id), 'btnt') : node('h2', item.name);
    card.append(thumb, name);
    if (shop) {
      card.append(node('p', '0원', 'caption'));
      if (item.starter) card.append(node('p', '기본', 'caption'));
      if (!detail) card.append(link('아이템 보기', '#' + item.id, 'btnt'));
      if (detail && item.owned) {
        if (item.slot && profile.character) {
          const wear = button('입혀 볼래', async () => {
            wear.disabled = true;
            const picks = Object.fromEntries(['head', 'body', 'neck'].map(slot => [slot,
              slot === item.slot ? item.id : profile.character.outfit?.[slot]?.id || null]));
            const result = await request('/chat/api/characters/' + profile.character.id + '/outfit', picks, 'PUT');
            if (result.status === 200) {
              sessionStorage.setItem('decor-worn', profile.character.name + '가 ' + item.name + ' 입었어!');
              location.href = '/chat/closet';
            } else if (result.status === 409 && result.body?.code === 'not_ready') {
              wear.disabled = false;
              signal(error, '아직 다 만들지 못한 캐릭터야', result);
            } else { wear.disabled = false; problem(result); }
          }, 'btn2');
          card.append(wear);
        } else if (['background', 'paper', 'font'].includes(item.kind)) card.append(link('일기장에 쓰기', '/chat/diary/decor#' + encodeURIComponent(item.id), 'btn2'));
        return card;
      }
      const claim = button(item.owned ? '받았어' : '받기', async () => {
        claim.disabled = true;
        const result = await request('/chat/api/shop/' + item.id + '/claim', undefined, 'POST');
        if ([200, 201].includes(result.status)) {
          item.owned = true;
          render();
        } else if (result.status === 404) {
          inventory.items = inventory.items.filter(current => current.id !== item.id);
          if (detail) history.replaceState(history.state, '', location.pathname);
          render();
          signal(error, '방금 상점에서 내려간 아이템이야');
        } else {
          problem(result);
          claim.disabled = false;
        }
      }, 'btn2');
      claim.disabled = item.owned;
      card.append(claim);
    } else if (inventory.diaryDecor?.[item.kind]?.id === item.id) {
      card.append(node('p', '쓰는 중', 'caption'));
    }
    return card;
  }

  function storefront() {
    const id = location.hash.slice(1);
    const detail = inventory.items.find(item => item.id === id);
    if (detail) {
      target.append(link('상점으로', '/chat/shop', 'btnt'));
      if (detail.slot) {
        if (profile.character) target.append(face(profile.character.outfit, detail));
        else target.append(node('p', '반려동물 캐릭터에 입힐 수 있어', 'caption'));
      } else {
        const frame = node('div', '', 'decor-book-preview-frame');
        const paper = node('article', '오늘은 산책을 했다…', 'decor-paper-preview');
        frame.append(paper);
        target.append(frame);
        if (detail.kind === 'sticker') {
          const picture = node('img', '', 'decor-thumb');
          picture.alt = '';
          picture.src = detail.thumbUrl;
          paper.append(picture);
        } else {
          const files = {background: 'bg.webp', paper: 'paper.webp', font: 'font.woff2'};
          const url = detail.starter ? null : detail.thumbUrl.replace(/thumb\.webp$/, files[detail.kind]);
          const selected = {[detail.kind]: {[detail.kind === 'font' ? 'fontUrl' : 'imageUrl']: url}};
          import('/chat/diary/decor.js').then(({paintDecor}) => paintDecor(paper, frame, selected)).catch(() => {});
        }
      }
      target.append(itemCard(detail, true));
    } else {
      const tabs = node('div', '', 'character-tabs');
      tabs.style.gridTemplateColumns = 'repeat(3, minmax(0, 1fr))';
      for (const [key, name] of [['wear', '입는 것'], ['diary', '일기장'], ['sticker', '스티커']]) {
        const choice = button(name, () => { shopTab = key; render(); }, 'btn2');
        choice.setAttribute('aria-pressed', String(shopTab === key));
        tabs.append(choice);
      }
      target.append(tabs);
      if (!inventory.items.length) target.append(node('p', '아직 상점에 아무것도 없어. 곧 들어올 거야', 'caption'));
      const groups = {wear: ['hat', 'top', 'scarf'], diary: ['background', 'paper', 'font'], sticker: ['sticker']};
      for (const [kind, label] of Object.entries(kinds)) {
        const items = inventory.items.filter(item => groups[shopTab].includes(item.kind) && item.kind === kind);
        if (items.length) {
          const grid = node('div', '', 'decor-shop-grid');
          grid.append(...items.map(item => itemCard(item)));
          target.append(node('h2', label), grid);
        }
      }
    }
  }

  function closet() {
    const notice = sessionStorage.getItem('decor-worn');
    if (notice) { target.append(node('p', notice, 'caption')); sessionStorage.removeItem('decor-worn'); }
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
      target.append(node('p', '반려동물 캐릭터를 만들면 옷을 입힐 수 있어', 'caption'), link('캐릭터 만들기', '/chat/character/new', 'btn2'));
      return;
    }
    const wearable = inventory.items.filter(item => item.slot);
    if (!wearable.length) {
      target.append(node('p', '아직 입힐 게 없어. 상점에서 받아 볼래?', 'caption'), link('상점 가기', '/chat/shop', 'btn2'));
      return;
    }
    for (const [slot, label] of Object.entries(slots)) {
      target.append(node('h2', label));
      for (const item of wearable.filter(candidate => candidate.slot === slot)) {
        const selected = inventory.outfit?.[slot]?.id === item.id;
        const choice = button(item.name, () => {
          const next = {...inventory.outfit};
          next[slot] = selected ? null : {id: item.id, name: item.name,
            layerUrl: item.thumbUrl.replace(/thumb\.webp$/, profile.character.template + '.png')};
          inventory.outfit = next;
          wearPending.push({itemId: item.id, picks: Object.fromEntries(Object.keys(slots).map(key => [key, next[key]?.id || null]))});
          render();
          void flushWear();
        }, 'btn2 decor-wear-item');
        choice.setAttribute('aria-pressed', String(selected));
        if (wearCurrent === item.id || wearPending.some(job => job.itemId === item.id)) {
          const spinner = node('span', '', 'decor-wear-spinner');
          spinner.setAttribute('aria-hidden', 'true');
          choice.append(spinner);
        }
        target.append(choice);
      }
    }
  }

  async function flushWear() {
    if (wearBusy) return;
    wearBusy = true;
    while (wearPending.length) {
      const job = wearPending.shift();
      wearCurrent = job.itemId;
      render();
      const picks = job.picks;
      const result = await request('/chat/api/characters/' + inventory.characterId + '/outfit', picks, 'PUT');
      if (result.status !== 200) {
        wearPending = [];
        wearCurrent = null;
        inventory.outfit = wearConfirmed;
        wearBusy = false;
        render();
        if (result.status === 409 && result.body?.code === 'not_owned') signal(error, '아직 안 받은 거야', result);
        else problem(result);
        return;
      }
      wearConfirmed = result.body;
    }
    inventory.outfit = wearConfirmed;
    wearCurrent = null;
    wearBusy = false;
    render();
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
      const requested = location.hash.slice(1);
      select.value = inventory.items.some(item => item.id === requested && item.kind === kind) ? requested : diaryStyle[kind].id;
      select.addEventListener('change', paint);
      wrap.append(select);
      target.append(wrap);
      return [kind, select];
    });
    async function paint() {
      const previousFont = preview.querySelector('.decor-paper-preview')?.style.getPropertyValue('--font-diary');
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
      if (values.font.fontUrl && previousFont) paper.style.setProperty('--font-diary', previousFont);
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
    const retry = button('다시 해 볼게', () => save.click(), 'btn2');
    retry.hidden = true;
    const save = button('이걸로 할래', async () => {
      retry.hidden = true;
      signal(error);
      if (controls.some(([, control]) => !control.value)) return;
      save.disabled = true;
      const body = Object.fromEntries(controls.map(([key, control]) => [key + 'Id', control.value]));
      const reply = await request('/chat/diary/api/decor', body, 'PUT');
      if (reply.status === 200) {
        sessionStorage.setItem('diary-decor-saved', '1');
        location.replace('/chat/diary/');
      }
      else {
        save.disabled = false;
        if (reply.status === 400) signal(error, '다시 한번 확인해 줄래?', reply);
        else if (reply.status === 403 && reply.body?.code === 'cross_site') signal(error, '이 화면에서 다시 해 줘', reply);
        else {
          problem(reply);
          if (reply.status !== 409 && reply.status !== 401 && reply.status !== 403) retry.hidden = false;
        }
      }
    });
    save.disabled = controls.some(([, control]) => !control.value);
    const reset = button('처음 모습으로', () => {
      for (const [kind, control] of controls) {
        const starter = inventory.items.find(item => item.starter && item.kind === kind);
        if (starter) control.value = starter.id;
      }
      paint();
    }, 'btn2');
    target.append(save, retry, reset, link('일기장으로', '/chat/diary/', 'btnt'));
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

  function loadFailure(reply) {
    target.replaceChildren();
    problem(reply);
    if (reply.status !== 401) {
      const retry = button('다시 해 볼게', () => { retry.disabled = true; void load(); }, 'btn2');
      target.append(retry);
    }
  }

  async function load() {
    if (!inventory && !diary) {
      const holder = node('div');
      holder.setAttribute('aria-hidden', 'true');
      if (!shop) holder.append(node('div', '', 'decor-loading-face'));
      const grid = node('div', '', 'decor-shop-grid');
      for (let i = 0; i < 6; i++) grid.append(node('div', '', 'decor-loading-card'));
      holder.append(grid);
      target.replaceChildren(holder);
    }
    const [list, me, decor] = await Promise.all([request(shop ? '/chat/api/shop' : '/chat/api/closet'),
      request('/chat/api/profile'), diary ? request('/chat/diary/api/decor') : null]);
    screen.setAttribute('aria-busy', 'false');
    if (list.status !== 200 || me.status !== 200) { loadFailure(list.status !== 200 ? list : me); return; }
    inventory = list.body;
    if (!shop && !diary) wearConfirmed = inventory.outfit;
    profile = me.body;
    if (diary) {
      if (decor.status !== 200) { loadFailure(decor); return; }
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
