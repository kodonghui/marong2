'use strict';

(() => {
  const {node, button, link, request, signal} = Unified;
  const area = document.getElementById('profile');
  const face = document.getElementById('face');
  const groups = document.getElementById('profile-groups');
  const actions = document.getElementById('profile-actions');
  const notice = document.getElementById('profile-notice');
  const error = document.getElementById('profile-error');
  let data, editing = false, timer, codeTimer;

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
          signal(notice, '이제 ' + data.botName + '라고 불러 줘!');
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
    const current = data.usageToday;
    card.append(node('h2', '오늘 쓴 양'), node('p',
      '글 답 ' + current.chatTurns + '번 · 통화 ' + Math.floor(current.callSeconds / 60) + '분 · 그림 ' + current.images + '장'));
    if (current.limit !== null) {
      const meter = node('progress', '', 'progress');
      meter.max = current.limit;
      meter.value = Math.min(current.units, meter.max);
      meter.setAttribute('aria-label', '오늘 쓴 양');
      card.append(meter, node('p', '오늘 ' + current.units + ' / ' + current.limit, 'caption'));
      if (current.tickets) card.append(node('p', '티켓 ' + current.tickets + '장', 'caption'));
      if (current.units >= current.limit) {
        const line = current.tickets ? '오늘 양을 넘어서 티켓으로 이어 가는 중이야(티켓 ' + current.tickets + '장)' :
          '오늘 쓸 수 있는 양을 다 썼어. 새벽 4시에 다시 채워져';
        card.append(node('p', line, 'caption'));
      }
    }
    return card;
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
    groups.replaceChildren(nameGroup(), codes(), usage());
    if (data.features.friends) groups.append(link('친구', '/chat/friends', 'btn2'));
    actions.replaceChildren(button('로그아웃', logout, 'btnt danger'));
  }

  async function load() {
    const reply = await request('/chat/api/profile');
    area.setAttribute('aria-busy', 'false');
    if (reply.status === 200) {
      if (!editing) { data = reply.body; render(); }
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
