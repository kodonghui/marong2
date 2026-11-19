'use strict';

(() => {
  const {node, button, link, request, signal} = Unified;
  const screen = document.getElementById('character');
  const root = document.getElementById('character-body');
  const title = document.getElementById('character-title');
  const error = document.getElementById('character-error');
  const retry = document.getElementById('character-retry');
  const parts = location.pathname.split('/');
  const fresh = parts[3] === 'new';
  const path = '/chat/character/' + parts[3] + '/';
  const base = '/chat/api/characters';
  const detail = base + '/' + parts[3];
  const wanted = fresh ? 'new' : parts[4];
  const editingEarlier = new URLSearchParams(location.search).has('edit');
  const names = {photos: '캐릭터 만들기', traits: '특징표 고치기', preview: '미리 보기', candidates: '후보 고르기',
                 name: '이름 짓기', try: '입혀 보기', new: '캐릭터 만들기'};
  const templateNames = {dog_small: '작은 강아지', dog_large: '큰 강아지', dog_long: '몸이 긴 강아지',
                         cat: '고양이', cat_round: '동그란 고양이'};
  const expressions = {
    smile: '웃음', excited: '신남', sleepy: '졸림', surprised: '놀람', sad: '슬픔', pout: '삐침',
  };
  let saving = false, workTimer, workStarted = 0, selectedPhotoURLs = [];
  title.textContent = names[wanted] || '캐릭터';

  function go(stage, id) {
    location.replace(id ? '/chat/character/' + id + '/' + stage : path + stage);
  }

  function failure(reply, again) {
    const code = reply.body?.code;
    if (reply.status === 401) {
      try { sessionStorage.setItem('marong.session.return', location.pathname); } catch {}
      location.replace('/chat/login?expired=1');
      return;
    }
    const texts = {
      invalid_input: '다시 한번 확인해 줄래?',
      wrong_stage: '지금 단계에서 다시 해 줘',
      not_ready: '아직 다 만들지 못한 캐릭터야. 이어서 만들어 줄래?',
      not_found: '찾지 못했어',
      photo_invalid: '사진 형식이나 크기를 확인해 줘',
      check_unavailable: '지금은 사진을 확인할 수 없어. 조금 있다가 다시 해 줘',
      too_many_characters: '캐릭터는 3개까지 둘 수 있어. 하나를 지우면 새로 만들 수 있어',
      image_budget: '이번 달에는 그림을 더 만들 수 없어',
      job_running: '지금 그리는 중이야',
      no_regen_left: '다시 만들기를 다 썼어',
      cross_site: '이 화면에서 다시 해 줘',
    };
    signal(error, texts[code] || '잠깐 문제가 생겼어. 다시 해 볼래?', reply);
    retry.replaceChildren();
    if (code === 'not_ready') retry.append(link('이어서 만들기', path + 'photos', 'btn2'));
    else if (reply.status === 404) retry.append(link('내 마롱이로', '/chat/me', 'btn2'));
    else if (again) retry.append(button('다시 해 볼게', again, 'btnt'));
  }

  async function save(control, action, done) {
    if (saving) return;
    signal(error);
    retry.replaceChildren();
    saving = control.disabled = true;
    try {
      const response = await action();
      if (response.status >= 200 && response.status < 300) done(response.body);
      else failure(response);
    } catch {
      failure({status: 0, body: null});
    } finally {
      saving = control.disabled = false;
    }
  }

  function picture(url, style = 'character-picture') {
    const image = new Image();
    image.className = style;
    image.alt = '';
    image.src = url;
    image.onerror = () => {
      if (image.nextElementSibling?.classList.contains('picture-retry')) return;
      image.after(button('그림 다시 보기', () => { image.nextElementSibling.remove(); image.src = url; },
        'btnt picture-retry'));
    };
    return image;
  }

  function pickNew() {
    root.append(node('p', '강아지나 고양이 캐릭터를 만들 수 있어', 'title'));
    for (const [kind, label] of [['dog', '강아지'], ['cat', '고양이']]) {
      const control = button(label, () => save(control, () => request(base, {kind}), data =>
        go('photos', data.character.id)), 'btn2');
      root.append(control);
    }
  }

  async function resize(file) {
    const original = await createImageBitmap(file);
    try {
      const ratio = Math.min(1, 1600 / Math.max(original.width, original.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(original.width * ratio));
      canvas.height = Math.max(1, Math.round(original.height * ratio));
      const context = canvas.getContext('2d');
      context.fillStyle = '#fff';
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(original, 0, 0, canvas.width, canvas.height);
      return await new Promise((resolve, reject) => canvas.toBlob(data => data ? resolve(data) : reject(),
        'image/jpeg', .9));
    } finally {
      original.close();
    }
  }

  async function upload(files) {
    const data = new FormData();
    let index = 0;
    for (const photo of files) {
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(photo.type) || photo.size > 8 * 1024 * 1024)
        return {status: 400, body: {code: 'photo_invalid'}};
      data.append('photos', await resize(photo), 'photo-' + (++index) + '.jpg');
    }
    const response = await fetch(detail + '/photos', {method: 'PUT', body: data, credentials: 'same-origin',
      redirect: 'manual', signal: AbortSignal.timeout(10_000)});
    return {status: response.status, body: await response.json().catch(() => null)};
  }

  function photos() {
    const input = node('input');
    input.type = 'file';
    input.accept = 'image/jpeg,image/png,image/webp';
    input.multiple = true;
    input.setAttribute('aria-label', '사진 고르기');
    const gallery = node('div', '', 'character-pictures');
    const action = button('사진 살펴보기', () => save(action, () => upload(Array.from(input.files)), load));
    action.disabled = true;
    input.addEventListener('change', () => {
      selectedPhotoURLs.forEach(url => URL.revokeObjectURL(url));
      selectedPhotoURLs = [];
      gallery.replaceChildren();
      const files = Array.from(input.files);
      action.disabled = files.length < 1 || files.length > 3;
      if (files.length > 3) signal(error, '사진은 1~3장 골라 줘');
      else {
        signal(error);
        selectedPhotoURLs = files.map(file => URL.createObjectURL(file));
        gallery.append(...selectedPhotoURLs.map(url => picture(url)));
      }
    });
    root.append(node('p', '사진을 1~3장 골라 줘', 'title'), input, gallery, action);
  }

  function field(label, value, limit) {
    const wrap = node('label', label, 'field-label');
    const entry = node('input');
    entry.maxLength = limit;
    entry.value = value || '';
    wrap.append(entry);
    root.append(wrap);
    return entry;
  }

  function selectField(label, options, value) {
    const wrap = node('label', label, 'field-label');
    const input = node('select');
    for (const [key, name] of Object.entries(options)) {
      const option = node('option', name);
      option.value = key;
      input.append(option);
    }
    input.value = value;
    wrap.append(input);
    root.append(wrap);
    return input;
  }

  function traits(card) {
    root.append(node('p', '사진에서 본 특징이 맞는지 확인해 줘', 'title'));
    const details = card.traits;
    const name = field('품종 짐작', details.breedGuess, 30);
    const patternNotes = field('무늬 설명', details.patternNotes, 60);
    const distinctive = field('눈에 띄는 점', details.distinctive, 60);
    const describe = (values) => Object.fromEntries(values.map(value => [value, value]));
    const edited = Object.fromEntries(Object.entries({
      pattern: ['무늬', '단색', '얼룩', '줄무늬', '턱시도', '포인트', '삼색', '브린들'],
      earShape: ['귀', '선 귀', '접힌 귀', '늘어진 귀', '반쯤 선 귀'],
      eyeColor: ['눈 색', '갈색', '검은색', '파란색', '초록색', '노란색', '짝눈'],
      build: ['체형', '작음', '중간', '큼', '긴 몸', '통통함'],
      furLength: ['털 길이', '짧음', '중간', '긺', '곱슬'],
    }).map(([key, [label, ...options]]) => [key, selectField(label, describe(options), details[key])]));
    const colors = node('fieldset', '', 'card');
    colors.append(node('legend', '털 색 1~3개'));
    const choices = ['흰색', '검은색', '갈색', '크림', '회색', '황토', '주황', '은색'].map(color => {
      const label = node('label', '', 'row');
      const input = node('input');
      input.type = 'checkbox';
      input.value = color;
      input.checked = details.coatColors.includes(color);
      label.append(input, node('span', color));
      colors.append(label);
      return input;
    });
    root.append(colors);
    const tone = field('말투', card.tone, 60);
    const types = Object.fromEntries(Object.entries(templateNames).filter(([key]) => key.startsWith(card.kind)));
    const template = selectField('몸 템플릿', types, card.template);
    const next = button('이 특징으로 할게', () => {
      const coatColors = choices.filter(input => input.checked).map(input => input.value);
      if (coatColors.length < 1 || coatColors.length > 3) {
        signal(error, '털 색은 1~3개 골라 줘');
        return;
      }
      const updated = {...details, ...Object.fromEntries(Object.entries(edited).map(([key, input]) =>
        [key, input.value])), breedGuess: name.value, patternNotes: patternNotes.value,
        distinctive: distinctive.value, coatColors};
      save(next, () => request(detail + '/traits', {traits: updated, template: template.value, tone: tone.value}, 'PATCH'),
        () => go('preview'));
    });
    root.append(next, link('사진 다시 고르기', path + 'photos?edit=1', 'btnt'));
  }

  function preview(card) {
    if (card.images.preview) {
      root.append(picture(card.images.preview));
      const next = button('후보 4장 그리기', () => save(next,
        () => request(detail + '/candidates', undefined, 'POST'), load));
      root.append(next);
    } else {
      const draw = button('미리 보기 그리기', () => save(draw,
        () => request(detail + '/preview', undefined, 'POST'), load));
      root.append(draw);
    }
    root.append(link('특징표 다시 고치기', path + 'traits?edit=1', 'btnt'));
  }

  function candidates(card) {
    const group = node('div', '', 'character-pictures');
    let selected;
    const next = button('이 그림으로 할게', () => save(next,
      () => request(detail + '/pick', {slot: selected}), load));
    next.disabled = true;
    for (const slot of ['candidate_1', 'candidate_2', 'candidate_3', 'candidate_4']) {
      if (!card.images[slot]) continue;
      const choose = button('', () => {
        selected = slot;
        for (const other of group.children) other.setAttribute('aria-pressed', String(other === choose));
        next.disabled = false;
      }, 'picture-choice');
      choose.setAttribute('aria-label', '후보 ' + slot.slice(-1));
      choose.setAttribute('aria-pressed', 'false');
      choose.append(picture(card.images[slot]));
      group.append(choose);
    }
    root.append(group, next);
    if (card.stage !== 'sheet') {
      const regenerate = button('다시 만들기', () => save(regenerate,
        () => request(detail + '/candidates', undefined, 'POST'), load), 'btn2');
      regenerate.disabled = card.regenLeft === 0;
      root.append(regenerate, node('p', '남은 다시 만들기 ' + card.regenLeft + '번', 'caption'));
    }
  }

  function expressionRow(faces, choose) {
    const row = node('div', '', 'character-expressions');
    for (const [slot, label] of Object.entries(expressions)) {
      if (!faces[slot]) continue;
      const photo = picture(faces[slot]);
      if (choose) {
        const option = button('', () => {
          row.querySelector('[aria-pressed="true"]')?.setAttribute('aria-pressed', 'false');
          option.setAttribute('aria-pressed', 'true');
          choose(slot);
        }, 'picture-choice');
        option.setAttribute('aria-label', label);
        option.setAttribute('aria-pressed', String(slot === 'smile'));
        option.append(photo);
        row.append(option);
      } else {
        photo.alt = label;
        row.append(photo);
      }
    }
    return row;
  }

  function naming(card) {
    root.append(picture(card.images.front), expressionRow(card.images), node('p', '이름을 지어 줘', 'title'));
    const input = field('이름', card.name, 24);
    const count = node('p', '', 'caption');
    const submit = button('다 됐어', async () => {
      submit.textContent = '마무리하는 중이야…';
      await save(submit, () => request(detail, {name: input.value.trim()}, 'PATCH'), () => go('try'));
      submit.textContent = '다 됐어';
      update();
    });
    function update() {
      const length = Array.from(input.value.trim()).length;
      count.textContent = length + ' / 12';
      submit.disabled = saving || length < 1 || length > 12;
      if (length > 12) signal(error, '이름은 1~12자로 적어 줘');
      else if (error.textContent === '이름은 1~12자로 적어 줘') signal(error);
    }
    input.addEventListener('input', update);
    update();
    root.append(count, node('p', '적용하면 이 이름이 마롱이 이름이 돼', 'caption'), submit);
  }

  function tryOn(data, profile) {
    const tabs = node('div', '', 'character-tabs');
    tabs.setAttribute('role', 'tablist');
    const chat = node('div', '', 'card');
    const header = node('div', '', 'character-preview-header');
    header.append(picture(data.faces.front, 'wardrobe-image'), node('p', data.botName, 'title'));
    chat.append(header);
    for (const line of data.chatSample) {
      chat.append(node('p', line.text, 'bubble ' + (line.from === 'me' ? 'character-preview-me' : '')));
    }
    const call = node('div', '', 'card centered');
    const face = node('div', '', 'account-face');
    function showFace(slot) { face.replaceChildren(picture(data.faces[slot] || data.faces.front)); }
    showFace('smile');
    call.append(face, node('p', data.callLine),
      expressionRow(data.faces, showFace), node('p', '목소리는 통화 목소리에서 골라', 'caption'));
    const panels = [chat, call];
    const controls = ['대화', '통화'].map((label, index) => {
      const tab = button(label, () => select(index), 'btn2');
      tab.id = 'character-tab-' + index;
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-controls', 'character-panel-' + index);
      tab.addEventListener('keydown', event => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        select(1 - index);
        controls[1 - index].focus();
      });
      panels[index].id = 'character-panel-' + index;
      panels[index].setAttribute('role', 'tabpanel');
      panels[index].setAttribute('aria-labelledby', tab.id);
      return tab;
    });
    function select(index) {
      controls.forEach((tab, current) => {
        tab.setAttribute('aria-selected', String(current === index));
        tab.tabIndex = current === index ? 0 : -1;
        panels[current].hidden = current !== index;
      });
    }
    select(0);
    tabs.append(...controls);
    root.append(node('p', '미리 보기야. 아직 바뀐 건 없어', 'caption'), tabs, ...panels);
    if (profile.character?.id === Number(parts[3])) {
      root.append(node('p', '지금 쓰는 중이야', 'caption'), link('내 마롱이로', '/chat/me', 'btn2'));
    } else {
      const apply = button('이 모습으로 할래', async () => {
        apply.textContent = '바꾸는 중이야…';
        await save(apply, () => request('/chat/api/profile/character', {characterId: Number(parts[3])}, 'PATCH'),
          updated => {
            try { sessionStorage.setItem('marong.character.applied', updated.botName); } catch {}
            location.replace('/chat/');
          });
        apply.textContent = '이 모습으로 할래';
      });
      root.append(apply, link('나중에 할래', '/chat/me', 'btn2'),
        node('p', '바꿔도 대화랑 기억은 그대로야. 먼저 보내는 그림 얘기는 글로만 와', 'caption'));
    }
  }

  function render(card) {
    const running = card.job && ['queued', 'running'].includes(card.job.state);
    if (running) {
      root.append(node('p', card.job.step === 'traits' ? '사진을 살펴보고 있어' : '그리는 중이야', 'title'));
      if (!workStarted) workStarted = Date.now();
      if (document.visibilityState === 'visible')
        workTimer = setTimeout(load, Date.now() - workStarted < 30_000 ? 2000 : 5000);
      return;
    }
    workStarted = 0;
    if (card.job?.state === 'failed') {
      const hint = card.job.error === 'model_refused' ? '사진을 다시 골라 줘' :
        card.job.error === 'budget' ? '지금은 그림을 만들 수 없어' : '잠깐 문제가 생겼어. 다시 해 볼래?';
      signal(error, hint);
    }
    const stage = card.stage === 'done' ? 'try' : card.stage === 'sheet' ? 'candidates' : card.stage;
    const canEditEarlier = editingEarlier && ((wanted === 'photos' && stage === 'traits')
      || (wanted === 'traits' && stage === 'preview'));
    if ((stage !== wanted && !canEditEarlier) || stage === 'try') {
      go(stage);
      return;
    }
    ({photos, traits, preview, candidates, name: naming})[wanted](card);
  }

  async function load() {
    clearTimeout(workTimer);
    if (fresh) {
      screen.setAttribute('aria-busy', 'false');
      pickNew();
      return;
    }
    const response = await request(detail + (wanted === 'try' ? '/try' : ''));
    screen.setAttribute('aria-busy', 'false');
    if (response.status !== 200) { failure(response, load); return; }
    selectedPhotoURLs.forEach(url => URL.revokeObjectURL(url));
    selectedPhotoURLs = [];
    signal(error);
    retry.replaceChildren();
    root.replaceChildren();
    if (wanted === 'try') {
      const profile = await request('/chat/api/profile');
      if (profile.status !== 200) { failure(profile, load); return; }
      tryOn(response.body, profile.body);
    } else render(response.body.character);
  }

  document.addEventListener('visibilitychange', () => {
    if (workStarted && document.visibilityState === 'visible') load();
    else clearTimeout(workTimer);
  });
  load();
})();
