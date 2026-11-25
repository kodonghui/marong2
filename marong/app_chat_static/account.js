'use strict';

(() => {
  const {node, button, link, request, signal, endLetter} = Unified;
  const area = document.getElementById('account');
  const face = document.getElementById('face');
  const headline = document.getElementById('headline');
  const hint = document.getElementById('hint');
  const actions = document.getElementById('actions');
  const error = document.getElementById('error');
  const api = '/chat/api';
  const join = location.pathname.startsWith('/chat/join/');
  const token = join ? location.pathname.split('/').pop() : null;
  let stateTimer;

  function installationHeaders() {
    const proof = window.MarongWebNotifications?.proof();
    return proof ? {'X-Marong-Installation': proof} : undefined;
  }

  function setPage(title, worried = false) {
    clearInterval(stateTimer);
    headline.textContent = title;
    signal(hint);
    signal(error);
    actions.replaceChildren();
    area.setAttribute('aria-busy', 'false');
    const image = new Image();
    image.src = worried ? '/face/v1/13-concerned.webp' : '/face/v1/01-neutral.webp';
    image.alt = '';
    face.replaceChildren(image);
  }

  function failure(reply, retry) {
    signal(error, reply.body?.code === 'cross_site' ? '이 화면에서 다시 해 줘' :
      '잠깐 문제가 생겼어. 다시 해 볼래?', reply);
    const again = button('다시 해 볼게', () => { again.remove(); retry(); }, 'btnt');
    actions.append(again);
  }

  function continueToChat() {
    let target = '/chat/';
    try {
      const saved = sessionStorage.getItem('marong.session.return');
      if (saved && !window.MarongWebNotifications?.pending('/chat/')) {
        const url = new URL(saved, location.origin);
        if (url.origin === location.origin && (url.pathname === '/' || url.pathname.startsWith('/chat/')) &&
            !/^\/chat\/(login|join|admin)(?:\/|$)/.test(url.pathname)) target = url.pathname + url.search + url.hash;
      }
      sessionStorage.removeItem('marong.session.return');
    } catch { /* sessionStorage can be blocked */ }
    location.replace(target);
  }

  function inviteError(reply, retry) {
    const messages = {
      invite_not_found: '이 링크는 찾지 못했어. 주소를 다시 확인해 줄래?',
      invite_used: '이 링크는 이미 썼어. 링크를 보내 준 사람한테 새 링크를 부탁해 줘',
      invite_expired: '이 링크는 기간(7일)이 지났어. 링크를 보내 준 사람한테 새 링크를 부탁해 줘',
    };
    const code = reply.body?.code;
    if (messages[code]) {
      setPage(messages[code], true);
      if (code === 'invite_used') actions.append(link('로그인하러 가기', '/chat/login'));
    } else {
      area.setAttribute('aria-busy', 'false');
      failure(reply, retry);
    }
  }

  function showInvite(kind) {
    const titles = {
      join: '안녕! 나는 마롱이야. 뭐라고 부르면 돼?',
      link: '다시 만나서 반가워! 이 기기에서도 이어서 얘기하자',
      relogin: '다시 들어오는 거구나. 바로 이어 줄게',
    };
    setPage(titles[kind]);
    const form = node('form', '', 'stack');
    const name = node('input');
    const buttonText = kind === 'join' ? '시작하기' : '이어 가기';
    const submit = node('button', buttonText, 'btn');
    const count = node('span', '0 / 12', 'caption');
    submit.type = 'submit';
    submit.disabled = kind === 'join';
    if (kind === 'join') {
      const label = node('label', '이름', 'field-label');
      name.maxLength = 24;
      name.autocomplete = 'nickname';
      label.append(name);
      form.append(label, count);
      name.addEventListener('input', () => {
        const size = Array.from(name.value.trim()).length;
        count.textContent = size + ' / 12';
        submit.disabled = size < 1 || size > 12;
      });
    }
    form.append(submit);
    actions.append(form);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (submit.disabled) return;
      signal(error);
      submit.disabled = name.disabled = true;
      submit.textContent = '준비하는 중이야…';
      const reply = await request(api + '/join', kind === 'join' ? {token, name: name.value.trim()} : {token},
        'POST', installationHeaders());
      submit.textContent = buttonText;
      submit.disabled = name.disabled = false;
      if (reply.status === 201) showDone(reply.body);
      else if (reply.body?.code === 'invalid_input') signal(error, '이름은 1~12자로 적어 줘');
      else inviteError(reply, () => form.requestSubmit());
    });
  }

  function showDone(body) {
    setPage(body.friendName + ', 반가워! 이제 ' + endLetter(body.botName, '이랑', '랑') + ' 얘기할 수 있어');
    actions.append(link('글 대화로 가기', '/chat/'));
    const card = node('section', '', 'card');
    card.append(node('h2', '앱에서도 쓰기'));
    const code = node('p', '', 'code');
    const status = node('p', '', 'caption');
    const guide = node('p', '', 'caption');
    const make = button('기기 추가 코드 만들기', async () => {
      make.disabled = true;
      signal(error);
      const reply = await request(api + '/device-codes', undefined, 'POST');
      make.disabled = false;
      if (reply.status === 201) {
        code.textContent = reply.body.code;
        code.classList.remove('expired');
        guide.textContent = '앱 첫 화면에 이 숫자를 넣어 줘. 10분 동안 한 번만 쓸 수 있어';
        make.textContent = '새 코드 만들기';
        clearInterval(stateTimer);
        const tick = () => {
          const left = Math.max(0, Math.ceil((Date.parse(reply.body.expiresAt) - Date.now()) / 1000));
          status.textContent = Math.floor(left / 60) + ':' + String(left % 60).padStart(2, '0');
          if (!left) {
            clearInterval(stateTimer);
            code.classList.add('expired');
            status.textContent = '시간이 지났어. 새 코드를 만들어 줘';
          }
        };
        tick();
        stateTimer = setInterval(tick, 1000);
      } else if (reply.status === 429) {
        signal(error, '코드를 여러 번 만들었어. 조금 있다가 다시 해 줘');
        make.disabled = true;
        setTimeout(() => { make.disabled = false; }, Math.max(reply.retryAfter, 1) * 1000);
      } else {
        failure(reply, () => make.click());
      }
    }, 'btn2');
    if (/Android/.test(navigator.userAgent) && !/MarongApp\//.test(navigator.userAgent)) {
      const download = node('div');
      const loadRelease = async () => {
        const release = await request(api + '/app/release');
        if (release.status === 200 && /^\/chat\/app\//.test(release.body?.url || '')) {
          download.replaceChildren(link('앱 받기', release.body.url, 'btn2'));
        } else if (release.status === 204) download.replaceChildren(node('p', '앱은 곧 준비돼', 'caption'));
        else failure(release, loadRelease);
      };
      card.append(download);
      loadRelease();
    }
    if (/iPhone/.test(navigator.userAgent) && !window.MarongWebNotifications) {
      const installed = matchMedia('(display-mode: standalone)').matches || navigator.standalone;
      const instructions = installed ? '' : '아이폰에서는 공유 버튼을 누르고 홈 화면에 추가를 고르면 앱처럼 열 수 있어. ';
      card.append(node('p', instructions + '알림과 전화 벨은 안드로이드 앱에서만 와', 'caption'));
    }
    card.append(code, guide, status, make);
    actions.append(card);
  }

  function showLogin(fromExpired) {
    setPage('다시 만나서 반가워! 기기 추가 코드를 넣어 줘');
    if (fromExpired) signal(hint, '로그인이 풀렸어. 다시 들어와 줘');
    const form = node('form', '', 'stack');
    const label = node('label', '', 'code-field');
    const input = node('input');
    input.inputMode = 'numeric';
    input.autocomplete = 'one-time-code';
    input.maxLength = 6;
    input.setAttribute('aria-label', '기기 추가 코드');
    const digits = node('span', '', 'digits');
    digits.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 6; i++) digits.append(node('span'));
    label.append(digits, input);
    const submit = node('button', '들어가기', 'btn');
    submit.type = 'submit';
    submit.disabled = true;
    function draw() {
      input.value = input.value.replace(/[^0-9]/g, '').slice(0, 6);
      Array.from(digits.children).forEach((cell, i) => { cell.textContent = input.value[i] || ' '; });
      submit.disabled = input.value.length !== 6;
    }
    input.addEventListener('input', draw);
    form.append(label, submit);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (submit.disabled) return;
      signal(error);
      submit.disabled = input.disabled = true;
      submit.textContent = '확인하는 중이야…';
      const reply = await request(api + '/login/code', {code: input.value}, 'POST', installationHeaders());
      if (reply.status === 200) { continueToChat(); return; }
      submit.textContent = '들어가기';
      input.disabled = false;
      if (reply.body?.code === 'code_wrong') {
        input.value = '';
        signal(error, '코드가 맞지 않거나 시간이 지났어. 다시 확인해 줄래?');
        input.focus();
      } else if (reply.body?.code === 'invalid_input') signal(error, '숫자 6자리를 넣어 줘');
      else if (reply.body?.code === 'too_many_tries') {
        input.disabled = true;
        face.querySelector('img').src = '/face/v1/13-concerned.webp';
        const end = Date.now() + Math.max(reply.retryAfter, 1) * 1000;
        function tick() {
          const left = Math.ceil((end - Date.now()) / 60_000);
          if (left <= 0) showLogin(fromExpired);
          else signal(error, '여러 번 틀려서 잠깐 쉬어 갈게. ' + left + '분 뒤에 다시 해 줘');
        }
        tick();
        stateTimer = setInterval(tick, 1000);
        return;
      } else failure(reply, () => form.requestSubmit());
      draw();
    });
    const help = node('details', '', 'card');
    help.append(node('summary', '코드가 없어?'),
      node('p', '이미 쓰고 있는 기기의 내 마롱이에서 코드를 만들 수 있어', 'caption'),
      node('p', '쓰는 기기가 없으면 초대 링크를 보내 준 사람한테 다시 로그인 링크를 부탁해 줘', 'caption'));
    actions.append(form, help);
  }

  async function load() {
    signal(error);
    actions.replaceChildren();
    const state = join ? await request(api + '/invites/' + token) : null;
    if (state && state.status !== 200) { inviteError(state, load); return; }
    let me = null;
    if (document.body.dataset.sessionCookie) {
      me = await request(api + '/profile');
      if (me.status !== 200 && me.status !== 401) { failure(me, load); return; }
    }
    if (join && me?.status === 200) {
      setPage('이 기기는 이미 ' + endLetter(me.body.friendName, '으로', '로') + ' 들어와 있어');
      actions.append(link('글 대화로 가기', '/chat/'),
        button('이 링크로 다시 들어가기', () => showInvite(state.body.kind), 'btn2'));
    } else if (join) showInvite(state.body.kind);
    else if (me?.status === 200) continueToChat();
    else showLogin(new URLSearchParams(location.search).has('expired'));
  }
  load();
})();
