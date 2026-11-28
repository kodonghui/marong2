'use strict';

(() => {
  const {node, button, link, request, signal, endLetter} = Unified;
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

  function stickerLink(item) {
    const parts = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(new Date());
    const get = type => parts.find(part => part.type === type).value;
    return '/chat/diary/' + [get('year'), get('month'), get('day')].join('-') + '#sticker=' + encodeURIComponent(item.id);
  }

  function problem(reply) {
    if (reply.status === 401) { location.replace('/chat/login'); return; }
    if (reply.status === 400) { signal(error, '다시 한번 확인해 줄래?', reply); return; }
    if (reply.status === 404) {
      signal(error);
      target.replaceChildren(node('p', '찾지 못했어'), link('내 마롱이로', '/chat/me', 'btn2'));
      return;
    }
    const codes = {cross_site: '이 화면에서 다시 해 줘', not_found: '지금은 받을 수 없는 아이템이야', not_owned: diary ? '아직 안 받은 거야' : '보관함에 없는 아이템이야',
                   not_ready: '캐릭터를 먼저 완성해 줘'};
    signal(error, codes[reply.body?.code] || '잠깐 문제가 생겼어. 다시 해 볼래?', reply);
  }

  function wearFieldErrors(reply, detailControl = null, detailSlot = null) {
    if (reply.status !== 400 || !Array.isArray(reply.body?.errors)) return;
    for (const entry of reply.body.errors.slice(0, 10)) {
      if (!entry || typeof entry !== 'object') continue;
      if (!Object.prototype.hasOwnProperty.call(slots, entry.field) || !['required', 'bad_format', 'wrong_kind'].includes(entry.reason)) continue;
      const group = detailControl && detailSlot === entry.field ? detailControl.parentElement
        : [...target.querySelectorAll('.decor-wear-group')].find(element => element.dataset.slot === entry.field);
      if (!group) continue;
      const id = 'outfit-error-' + entry.field;
      let note = group.querySelector('#' + id);
      if (!note) { note = node('span', '', 'caption'); note.id = id; group.append(note); }
      const rule = entry.reason === 'bad_format' ? slots[entry.field] + ' 아이템을 다시 골라 줘'
        : entry.reason === 'required' ? slots[entry.field] + ' 자리는 고르거나 비워 둬야 해'
        : slots[entry.field] + ' 자리에 맞는 아이템을 골라 줘';
      note.replaceChildren(node('span', '다시 한번 확인해 줄래?'), node('br'), node('span', rule));
      const controls = detailControl ? [detailControl] : group.querySelectorAll('.decor-wear-item');
      for (const control of controls) { control.setAttribute('aria-invalid', 'true'); control.setAttribute('aria-describedby', id); }
    }
  }

  function face(outfit, item) {
    const pet = profile.character;
    const frame = node('div', '', 'decor-face');
    const base = node('img');
    base.alt = '';
    base.src = pet ? '/chat/api/characters/' + pet.id + '/images/smile' : '/face/v1/01-neutral.webp';
    frame.append(base);
    if (!pet && !profile.features?.defaultWear) return frame;
    for (const slot of ['body', 'neck', 'head']) {
      const layer = node('img', '', 'decor-layer');
      layer.alt = '';
      const source = item?.slot === slot ? item.thumbUrl.replace(/thumb\.webp$/, (pet?.template || 'marong') + '.png') : outfit?.[slot]?.layerUrl;
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
    const name = !shop && item.kind === 'sticker' ? link(item.name, stickerLink(item), 'btnt')
      : !shop && ['background', 'paper', 'font'].includes(item.kind)
      ? link(item.name, '/chat/diary/decor#' + encodeURIComponent(item.id), 'btnt') : node('h2', item.name);
    card.append(thumb, name);
    if (shop) {
      card.append(node('p', '0원', 'caption'));
      if (item.starter) card.append(node('p', '기본', 'caption'));
      if (!detail) card.append(link('아이템 보기', '#' + item.id, 'btnt'));
      if (detail && item.owned) {
        if (item.slot && (profile.character || profile.features?.defaultWear)) {
          const wear = button('입혀 볼래', async () => {
            for (const note of wear.parentElement.querySelectorAll('[id^="outfit-error-"]')) note.remove();
            wear.removeAttribute('aria-invalid');
            wear.removeAttribute('aria-describedby');
            signal(error);
            wear.disabled = true;
            const picks = Object.fromEntries(['head', 'body', 'neck'].map(slot => [slot,
              slot === item.slot ? item.id : (profile.character?.outfit || profile.marongOutfit)?.[slot]?.id || null]));
            const result = await request(profile.character ? '/chat/api/characters/' + profile.character.id + '/outfit' : '/chat/api/marong/outfit', picks, 'PUT');
            if (result.status === 200) {
              sessionStorage.setItem('decor-worn', endLetter(profile.character?.name || profile.botName || '마롱이', '이가', '가') + ' ' + item.name + ' 입었어!');
              location.href = '/chat/closet';
            } else if (result.status === 409 && result.body?.code === 'not_ready') {
              wear.disabled = false;
              signal(error, '아직 다 만들지 못한 캐릭터야', result);
            } else if (result.status === 409 && result.body?.code === 'not_owned') {
              wear.disabled = false;
              signal(error, '아직 안 받은 거야', result);
            } else {
              wear.disabled = false;
              problem(result);
              wearFieldErrors(result, wear, item.slot);
              if (result.status === 0 || result.status >= 500) error.append(' ', button('다시 해 볼게', () => wear.click(), 'btnt'));
            }
          }, 'btn2');
          card.append(wear);
        } else if (['background', 'paper', 'font'].includes(item.kind)) card.append(link('일기장에 쓰기', '/chat/diary/decor#' + encodeURIComponent(item.id), 'btn2'));
        else if (item.kind === 'sticker') card.append(link('일기장에 쓰기', stickerLink(item), 'btn2'));
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
          if (result.status === 0 || result.status >= 500) error.append(' ', button('다시 해 볼게', () => claim.click(), 'btnt'));
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
        if (profile.character || profile.features?.defaultWear) {
          target.append(face(profile.character?.outfit || profile.marongOutfit, detail));
          if (!profile.character) target.append(node('p', endLetter(profile.botName, '이가', '가') + ' 입으면 이렇게 돼', 'caption'));
        }
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
    if (!inventory.characterId && !profile.features?.defaultWear) {
      target.append(node('p', '반려동물 캐릭터를 만들면 옷을 입힐 수 있어', 'caption'));
      if (profile.features?.character) target.append(link('캐릭터 만들기', '/chat/character/new', 'btn2'));
      return;
    }
    const wearable = inventory.items.filter(item => item.slot);
    if (!wearable.length) {
      target.append(node('p', '아직 입힐 게 없어. 상점에서 받아 볼래?', 'caption'), link('상점 가기', '/chat/shop', 'btn2'));
      return;
    }
    for (const [slot, label] of Object.entries(slots)) {
      const group = node('div', '', 'decor-wear-group stack');
      group.dataset.slot = slot;
      group.append(node('h2', label));
      target.append(group);
      for (const item of wearable.filter(candidate => candidate.slot === slot)) {
        const selected = inventory.outfit?.[slot]?.id === item.id;
        const choice = button(item.name, () => {
          const next = {...inventory.outfit};
          next[slot] = selected ? null : {id: item.id, name: item.name,
            layerUrl: item.thumbUrl.replace(/thumb\.webp$/, (profile.character?.template || 'marong') + '.png')};
          inventory.outfit = next;
          wearPending.push({itemId: item.id, picks: Object.fromEntries(Object.keys(slots).map(key => [key, next[key]?.id || null]))});
          render();
          void flushWear();
        }, 'btn2 decor-wear-item');
        choice.dataset.itemId = item.id;
        choice.setAttribute('aria-pressed', String(selected));
        if (wearCurrent === item.id || wearPending.some(job => job.itemId === item.id)) {
          const spinner = node('span', '', 'decor-wear-spinner');
          spinner.setAttribute('aria-hidden', 'true');
          choice.append(spinner);
        }
        group.append(choice);
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
      const result = await request(inventory.characterId ? '/chat/api/characters/' + inventory.characterId + '/outfit' : '/chat/api/marong/outfit', picks, 'PUT');
      if (result.status !== 200) {
        wearPending = [];
        wearCurrent = null;
        inventory.outfit = wearConfirmed;
        wearBusy = false;
        render();
        if (result.status === 409 && result.body?.code === 'not_owned') signal(error, '아직 안 받은 거야', result);
        else {
          problem(result);
          wearFieldErrors(result);
          if (result.status === 0 || result.status >= 500) {
            error.append(' ', button('다시 해 볼게', () => {
              const choice = [...target.querySelectorAll('.decor-wear-item')].find(item => item.dataset.itemId === job.itemId);
              choice?.click();
            }, 'btnt'));
          }
        }
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
      const validation = node('span', '', 'caption');
      validation.id = 'diary-decor-error-' + kind;
      select.setAttribute('aria-describedby', validation.id);
      validation.hidden = true;
      select.addEventListener('change', () => { validation.hidden = true; select.removeAttribute('aria-invalid'); paint(); });
      wrap.append(select);
      wrap.append(validation);
      target.append(wrap);
      return [kind, select, validation];
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
      for (const [, control, validation] of controls) { validation.hidden = true; control.removeAttribute('aria-invalid'); }
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
        if (reply.status === 400) {
          signal(error, '다시 한번 확인해 줄래?', reply);
          for (const entry of reply.body?.errors || []) {
            const found = controls.find(([kind]) => entry.field === kind + 'Id');
            if (!found || !['required', 'bad_format', 'wrong_kind'].includes(entry.reason)) continue;
            const [kind, control, validation] = found;
            const rule = entry.reason === 'bad_format' ? kinds[kind] + ' 아이템 ID 형식을 확인해 줘' : kinds[kind] + ' 아이템을 골라 줘';
            validation.replaceChildren(node('span', '다시 한번 확인해 줄래?'), node('br'), node('span', rule));
            validation.hidden = false;
            control.setAttribute('aria-invalid', 'true');
          }
        }
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
    if (reply.status !== 401 && reply.status !== 404) {
      const retry = button('다시 해 볼게', () => { retry.disabled = true; void load(); }, 'btn2');
      target.append(retry);
    }
  }

  async function load() {
    if (!inventory) {
      const holder = node('div');
      holder.setAttribute('aria-hidden', 'true');
      if (diary) {
        holder.append(node('div', '', 'decor-loading-card decor-loading-preview'), node('div', '', 'decor-loading-card'));
      } else {
        if (!shop) holder.append(node('div', '', 'decor-loading-face'));
        const grid = node('div', '', 'decor-shop-grid');
        for (let i = 0; i < 6; i++) grid.append(node('div', '', 'decor-loading-card'));
        holder.append(grid);
      }
      target.replaceChildren(holder);
    }
    const [list, me, decor] = await Promise.all([request(shop ? '/chat/api/shop' : '/chat/api/closet'),
      request('/chat/api/profile'), diary ? request('/chat/diary/api/decor') : null]);
    if (list.status !== 200 || me.status !== 200) { screen.setAttribute('aria-busy', 'false'); loadFailure(list.status !== 200 ? list : me); return; }
    inventory = list.body;
    if (!shop && !diary) wearConfirmed = inventory.outfit;
    profile = me.body;
    if (diary) {
      if (decor.status !== 200) { screen.setAttribute('aria-busy', 'false'); loadFailure(decor); return; }
      diaryStyle = decor.body;
      diaryExample = null;
      const recent = await request('/chat/diary/api/latest');
      if (recent.status === 200 && recent.body.date) {
        const day = await request('/chat/diary/api/days/' + recent.body.date);
        if (day.status === 200) diaryExample = day.body.diary;
      }
    }
    screen.setAttribute('aria-busy', 'false');
    render();
  }
  window.addEventListener('hashchange', () => { if (inventory) render(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  load();
})();
