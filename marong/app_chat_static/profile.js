'use strict';

(() => {
  const {node, button, link, request, signal, shortDate, endLetter} = Unified;
  const area = document.getElementById('profile');
  const face = document.getElementById('face');
  const groups = document.getElementById('profile-groups');
  const actions = document.getElementById('profile-actions');
  const notice = document.getElementById('profile-notice');
  const error = document.getElementById('profile-error');
  let data, editing = false, timer, codeTimer;

  function layers(frame, outfit) {
    for (const slot of ['body', 'neck', 'head']) {
      const url = outfit?.[slot]?.layerUrl;
      if (!url) continue;
      const layer = new Image();
      layer.src = url;
      layer.alt = '';
      layer.className = 'profile-outfit-layer';
      layer.addEventListener('error', () => layer.remove(), {once:true});
      frame.append(layer);
    }
  }

  function relogin() {
    try { sessionStorage.setItem('marong.session.return', location.pathname); } catch {}
    location.replace('/chat/login?expired=1');
  }

  function problem(reply, target = error) {
    if (reply.status === 401) { relogin(); return; }
    signal(target, reply.body?.code === 'cross_site' ? '이 화면에서 다시 해 줘' :
      '잠깐 문제가 생겼어. 다시 해 볼래?', reply);
  }

  function nameGroup() {
    const card = node('div', '', 'card');
    card.append(node('p', data.botName, 'title'));
    const edit = button('이름 바꾸기', () => {
      editing = true;
      const form = node('form', '', 'stack');
      const label = node('label', '마롱이 이름', 'field-label');
      const input = node('input');
      input.value = data.botName;
      input.maxLength = 24;
      label.append(input);
      const counter = node('p', '', 'caption');
      const warning = node('p', '', 'err');
      const save = node('button', '바꾸기', 'btn');
      save.type = 'submit';
      const cancel = button('그만두기', () => { editing = false; render(); }, 'btnt');
      const count = () => {
        const size = Array.from(input.value.trim()).length;
        counter.textContent = size + ' / 12';
        return size;
      };
      input.addEventListener('input', count);
      count();
      form.append(label, counter, warning, save, cancel);
      edit.replaceWith(form);
      input.focus();
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (save.disabled) return;
        const size = count();
        if (size < 1 || size > 12) { signal(warning, '이름은 1~12자로 적어 줘'); return; }
        save.disabled = input.disabled = cancel.disabled = true;
        const reply = await request('/chat/api/profile', {botName: input.value.trim()}, 'PATCH');
        save.disabled = input.disabled = cancel.disabled = false;
        if (reply.status === 200) {
          editing = false;
          data = reply.body;
          render();
          signal(notice, '이제 ' + endLetter(data.botName, '이라고', '라고') + ' 불러 줘!');
          clearTimeout(timer);
          timer = setTimeout(() => signal(notice), 3000);
        } else if (reply.body?.code === 'invalid_input') signal(warning, '이름은 1~12자로 적어 줘');
        else problem(reply, warning);
      });
    }, 'btn2');
    card.append(edit);
    return card;
  }

  function codes() {
    const card = node('div', '', 'card');
    card.append(node('h2', '다른 기기에서도 쓰기'));
    const code = node('p', '', 'code');
    const clock = node('p', '', 'caption');
    const guide = node('p', '', 'caption');
    const make = button('기기 추가 코드 만들기', async () => {
      make.disabled = true;
      signal(error);
      const reply = await request('/chat/api/device-codes', undefined, 'POST');
      make.disabled = false;
      if (reply.status === 201) {
        code.textContent = reply.body.code;
        code.classList.remove('expired');
        guide.textContent = '다른 기기의 로그인 화면에 이 숫자를 넣어 줘. 10분 동안 한 번만 쓸 수 있어';
        make.textContent = '새 코드 만들기';
        clearInterval(codeTimer);
        function tick() {
          const seconds = Math.max(0, Math.ceil((Date.parse(reply.body.expiresAt) - Date.now()) / 1000));
          clock.textContent = Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
          if (seconds === 0) {
            clearInterval(codeTimer);
            clock.textContent = '시간이 지났어. 새 코드를 만들어 줘';
            code.classList.add('expired');
          }
        }
        editing = true;
        tick();
        codeTimer = setInterval(tick, 1000);
      } else if (reply.status === 429) {
        signal(error, '코드를 여러 번 만들었어. 조금 있다가 다시 해 줘');
        make.disabled = true;
        setTimeout(() => { make.disabled = false; }, Math.max(reply.retryAfter, 1) * 1000);
      } else problem(reply);
    }, 'btn2');
    if (/iPhone/.test(navigator.userAgent)) {
      const installed = matchMedia('(display-mode: standalone)').matches || navigator.standalone;
      const instructions = installed ? '' : '아이폰에서는 공유 버튼을 누르고 홈 화면에 추가를 고르면 앱처럼 열 수 있어. ';
      card.append(node('p', instructions + '알림과 전화 벨은 안드로이드 앱에서만 와', 'caption'));
    }
    card.append(code, clock, guide, make);
    return card;
  }

  function usage() {
    const card = node('div', '', 'card');
    card.id = 'usage';
    const current = data.usageToday;
    card.append(node('h2', '내 사용량'));
    if (!current) {
      card.append(node('p', '지금은 못 불러왔어', 'caption'), button('다시 해 볼게', load, 'btnt'));
      return card;
    }
    card.append(node('p',
      '오늘 · 글 답 ' + current.chatTurns + '번 · 통화 ' + Math.floor(current.callSeconds / 60) + '분 · 그림 ' + current.images + '장'));
    if (current.limit !== null) {
      const meter = node('progress', '', 'progress');
      meter.max = current.limit;
      meter.value = Math.min(current.units, meter.max);
      meter.setAttribute('aria-label', '하루 한도');
      card.append(node('p', '하루 한도', 'caption'), meter,
        node('p', '오늘 ' + current.units + ' / ' + current.limit, 'caption'));
      if (current.units >= current.limit) {
        const line = current.tickets ? '오늘 양을 넘어서 티켓으로 이어 가는 중이야(티켓 ' + current.tickets + '장)' :
          '오늘 쓸 수 있는 양을 다 썼어. 새벽 4시에 다시 채워져';
        card.append(node('p', line, 'caption'));
      }
    } else {
      card.append(node('p', '하루 한도 · 무제한', 'caption'));
    }
    if (current.tickets) card.append(node('p', '티켓 ' + current.tickets + '장', 'caption'));
    const month = current.callMonth;
    if (!month?.limited) {
      card.append(node('p', '이번 달 통화 · 무제한', 'caption'));
    } else if (month.percent === null) {
      card.append(node('p', '이번 달 통화 양은 지금 못 불러왔어', 'caption'));
    } else {
      const meter = node('progress', '', 'progress');
      meter.max = 100;
      meter.value = Math.min(month.percent, 100);
      meter.setAttribute('aria-label', '이번 달 통화');
      const reset = shortDate(month.resetsAt, {wholeHour: true}) + '에 다시 채워져';
      const line = month.percent >= 100 ? '이번 달 통화를 다 썼어. ' : month.percent + '% 썼어 · ';
      card.append(node('p', '이번 달 통화', 'caption'), meter, node('p', line + reset, 'caption'));
    }
    return card;
  }

  function wardrobe() {
    const section = node('div', '', 'card');
    section.append(node('h2', '캐릭터'));
    const update = async () => {
      const result = await request('/chat/api/characters');
      if (result.status !== 200) {
        if (result.status === 401) relogin();
        else section.append(node('p', '캐릭터를 못 불러왔어', 'caption'),
          button('다시 해 볼게', () => { section.replaceChildren(node('h2', '캐릭터')); update(); }, 'btnt'));
        return;
      }
      const items = result.body.characters;
      const base = node('div', '', 'card');
      if (data.features.defaultWear && !data.character) {
        const portrait = node('div', '', 'wardrobe-image profile-portrait');
        const image = new Image();
        image.src = '/face/v1/01-neutral.webp';
        image.alt = '';
        portrait.append(image);
        layers(portrait, data.marongOutfit);
        base.append(portrait);
      }
      base.append(node('p', '기본 마롱이' + (data.character ? '' : ' · 쓰는 중')));
      if (data.character) {
        const reset = button('기본 마롱이로 돌아가기', () => {
          const box = node('div', '', 'stack');
          const confirm = button('기본 마롱이로 돌아가기', async () => {
            confirm.disabled = true;
            const response = await request('/chat/api/profile/character', {characterId: null}, 'PATCH');
            confirm.disabled = false;
            if (response.status === 200) {
              data = response.body;
              render();
              signal(notice, '기본 마롱이로 돌아왔어');
            } else problem(response);
          }, 'btn2');
          box.append(node('p', '기본 마롱이로 돌아갈까?'), confirm, button('그만두기', () => box.replaceWith(reset), 'btnt'));
          reset.replaceWith(box);
        }, 'btnt');
        base.append(reset);
      }
      section.append(base);
      if (!items.length) section.append(node('p', '사진으로 강아지나 고양이 캐릭터를 만들 수 있어', 'caption'));
      for (const character of items) {
        const row = node('div', '', 'card');
        const avatar = new Image();
        avatar.src = character.images.front || character.images.preview || '/face/v1/01-neutral.webp';
        avatar.className = 'wardrobe-image';
        avatar.alt = '';
        const worn = data.character?.id === character.id;
        row.append(avatar, node('p', (character.name || '만드는 중이야') + (worn ? ' · 쓰는 중' : '')));
        const path = '/chat/character/' + character.id + '/';
        if (character.status === 'ready') row.append(link('입혀 보기', path + 'try', 'btn2'));
        else row.append(link('이어서 하기', path + (character.stage === 'sheet' ? 'candidates' : character.stage), 'btn2'));
        const remove = button('지우기', () => {
          const box = node('div', '', 'stack');
          const confirm = button('지우기', async () => {
            confirm.disabled = true;
            const reply = await request('/chat/api/characters/' + character.id, undefined, 'DELETE');
            confirm.disabled = false;
            if (reply.status === 204) {
              await load();
              signal(notice, '지웠어');
            } else if (reply.body?.code === 'job_running') {
              signal(error, '지금 그리는 중이라 지울 수 없어. 끝나고 다시 해 줘');
            } else problem(reply);
          }, 'btn2 danger');
          box.append(node('p', '지우면 되돌릴 수 없어. 지울까?'), confirm,
            button('그만두기', () => box.replaceWith(remove), 'btnt'));
          remove.replaceWith(box);
        }, 'btnt danger');
        row.append(remove);
        section.append(row);
      }
      if (items.length < result.body.limit) section.append(link('새 캐릭터 만들기', '/chat/character/new', 'btn2'));
      else {
        const disabled = button('새 캐릭터 만들기', () => {}, 'btn2');
        disabled.disabled = true;
        section.append(disabled, node('p', '캐릭터는 3개까지 둘 수 있어. 하나를 지우면 새로 만들 수 있어', 'caption'));
      }
    };
    update();
    return section;
  }

  function logout() {
    const box = node('div', '', 'card');
    const quit = button('로그아웃', async () => {
      quit.disabled = cancel.disabled = true;
      const reply = await request('/chat/api/logout', undefined, 'POST');
      if (reply.status === 204) { location.replace('/chat/login'); return; }
      quit.disabled = cancel.disabled = false;
      problem(reply);
    }, 'btn2 danger');
    const cancel = button('그만두기', render, 'btnt');
    box.append(node('p', '이 기기에서 나갈까?'), quit, cancel);
    actions.replaceChildren(box);
  }

  function render() {
    signal(error);
    clearInterval(codeTimer);
    const image = new Image();
    image.src = data.character?.faceUrl || '/face/v1/01-neutral.webp';
    image.alt = '';
    face.replaceChildren(image);
    layers(face, data.character?.outfit || data.marongOutfit);
    groups.replaceChildren(nameGroup(), link('통화 목소리 · ' + (data.voiceLabel || data.voice || '기본'),
      '/chat/me/voice', 'btn2'), codes(), usage());
    if (data.features.character) groups.insertBefore(wardrobe(), groups.children[1]);
    if (!data.character && data.features.defaultWear) {
      const worn = [['head', '모자'], ['body', '옷'], ['neck', '목도리']]
        .filter(([slot]) => data.marongOutfit?.[slot]).map(([, label]) => label).join('·') || '아직 안 입음';
      groups.insertBefore(link('꾸미기 · ' + worn, '/chat/closet', 'btn2'), groups.children[1]);
    }
    if (data.character) {
      const introPath = '/chat/character/' + data.character.id + '/intro';
      const intro = node('div', '', 'card');
      intro.append(link('아이 소개', introPath, 'btn2'));
      if (data.character.introMissing) {
        const name = data.character.name;
        intro.append(node('p', name + '에 대해 알려 주면 ' + endLetter(name, '이가', '가') + ' 직접 말할게', 'caption'),
          link('알려 주기', introPath, 'btnt'));
      }
      if (data.features.decor) intro.append(link('꾸미기', '/chat/closet', 'btn2'));
      groups.insertBefore(intro, groups.children[1]);
    }
    if (data.google !== 'off') {
      const connected = data.google === 'connected' ? '연결됨' : '연결 안 됨';
      groups.append(link('구글 캘린더 · ' + connected, '/google/', 'btn2'));
    }
    if (data.features.friends) groups.append(link('친구', '/chat/friends', 'btn2'));
    actions.replaceChildren(button('로그아웃', logout, 'btnt danger'));
  }

  async function load() {
    const reply = await request('/chat/api/profile');
    area.setAttribute('aria-busy', 'false');
    if (reply.status === 200) {
      if (!editing) {
        data = reply.body;
        render();
        try {
          const saved = sessionStorage.getItem('marong.intro.saved');
          if (saved) {
            sessionStorage.removeItem('marong.intro.saved');
            signal(notice, endLetter(saved, '이가', '가') + ' 새로 기억했어');
          }
        } catch {}
        const voices = await request('/chat/api/voices');
        const selected = voices.body?.voices?.find((voice) => voice.name === data.voice)
          || voices.body?.voices?.find((voice) => voice.default);
        if (selected && !editing) {
          data.voiceLabel = selected.label;
          const row = groups.querySelector('a[href="/chat/me/voice"]');
          if (row) row.textContent = '통화 목소리 · ' + selected.label;
        }
      }
    } else {
      problem(reply);
      if (!data && reply.status !== 401) actions.replaceChildren(button('다시 해 볼게', load, 'btn2'));
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') load();
  });
  load();
})();
