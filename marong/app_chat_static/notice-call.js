'use strict';

(() => {
  const page = document.querySelector('.notice-phone');
  if (!page) return;
  const web = window.MarongWebNotifications;
  const title = document.getElementById('notice-title');
  const back = document.getElementById('notice-back');
  const loginUrl = '/chat/login?expired=1';

  if (page.dataset.failure) {
    const hour = (new Date(Date.now() + 9 * 3600000)).getUTCHours();
    document.documentElement.dataset.theme = hour >= 8 && hour < 20 ? 'chestnut' : 'night';
    title.focus();
    const reference = web?.takeCall();
    const login = document.getElementById('notice-login');
    if (login && reference) login.addEventListener('click', () => web.preserveReference(reference, '/chat/'));
    const retry = document.getElementById('notice-retry');
    if (retry) {
      const seconds = Number(page.dataset.wait);
      if (seconds > 0) {
        retry.disabled = true;
        setTimeout(() => { retry.disabled = false; }, seconds * 1000);
      }
      retry.onclick = () => {
        if (reference) web.preserveReference(reference, '/chat/');
        location.replace('/chat/');
      };
    }
    return;
  }

  const detail = document.getElementById('notice-detail');
  const action = document.getElementById('notice-action');
  const controls = document.getElementById('notice-controls');
  const mute = document.getElementById('mute');
  const status = document.getElementById('status');
  const reference = web?.takeCall(page.dataset.navigation);
  delete page.dataset.navigation;
  const client = page.dataset.clientId;
  delete page.dataset.clientId;
  const ordinary = page.dataset.purpose === 'ordinary';
  const installation = web?.proof();
  const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
  const token = /^[A-Za-z0-9_-]{48,768}$/;
  const screens = {
    ring_ready: ['약속 전화가 와 있어', '받기를 누르면 이 전화를 연결해 볼게. 화면을 열기만 해서는 수락하지 않아.', '받기'],
    accepting: ['전화 받는 중', '전화가 아직 유효한지 확인하고 있어.', '받는 중'],
    ordinary: ['일반 통화', '일반 통화를 선택했어. 통화 시작을 누르면 마이크를 준비할게.', '통화 시작'],
    ring_answered: ['이미 받은 전화야', '이 약속 전화는 이미 처리됐어. 글 대화로 돌아갈 수 있어.'],
    ring_unavailable: ['지금은 이 전화를 받을 수 없어', '현재 확인한 상태로는 이 약속 전화를 연결할 수 없어.', '상태 다시 확인'],
    result: ['전화 받기 결과를 확인해 줘', '수락이 끝났는지 아직 확인되지 않았어. 확인하면 이미 수락한 경우 같은 통화로 돌아갈 수 있어.', '결과 확인'],
    resultLoading: ['받기 결과 확인 중', '처음 요청한 전화의 결과를 확인하고 있어.', '결과 확인 중'],
    denied: ['이 알림을 열 수 없어', '글 대화로 돌아가 다시 확인할 수 있어.'],
    offline: ['지금 전화 상태를 확인할 수 없어', '연결을 확인한 뒤 이 전화의 상태를 다시 확인해 줘.', '상태 다시 확인'],
    limited: ['잠시 뒤 다시 확인해 줘', '안내된 시간이 지나면 전화 상태를 다시 확인할 수 있어.', '상태 다시 확인'],
    ended: ['통화가 끝났어', '기존 통화에 다시 연결할 수 없어. 원하면 새로 전화를 걸 수 있어.', '다시 걸기'],
    connecting: ['통화 연결을 준비하고 있어', '아직 통화가 연결되지 않았어. 잠시 기다려 줘.', '닫기'],
    reconnecting: ['같은 통화에 다시 연결 중이야', '잠금 해제나 연결 전환 뒤 기존 통화를 확인하고 있어.'],
    checking: ['지금 통화 연결을 확인할 수 없어', '연결을 다시 확인해 줘. 확인 전에는 새 통화를 시작하지 않아.', '연결 확인'],
    talking: ['통화 중이야', '기존 통화에 연결됐어.'],
    mic: ['마이크를 허용해야 통화할 수 있어', '마이크를 허용한 뒤 다시 해 봐. 지금은 약속 전화에 응답하지 않았어.', '다시 해 볼게'],
    micResume: ['마이크를 허용해야 통화할 수 있어', '마이크를 허용한 뒤 다시 해 봐.', '다시 해 볼게'],
    call_busy: ['다른 기기에서 통화 중이야', '그 통화를 끝내고 다시 걸어 줘.', '상태 다시 확인'],
    calls_full: ['지금은 전화가 꽉 찼어', '조금 있다가 다시 걸어 줘.', '상태 다시 확인'],
    budget_exhausted: ['이번 달 통화는 여기까지야', '다음 달에 또 걸어 줘. 글로는 계속 얘기할 수 있어.'],
    daily_limit: ['오늘 쓸 수 있는 양을 다 썼어', '새벽 4시에 다시 채워져.'],
    login: ['로그인한 뒤 알림을 확인할게', '기존 기기 코드로 로그인해 줘. 여기에서는 알림 내용을 먼저 보여 주지 않아.', '들어가기'],
  };
  let state, engine, frame, expected, connected = false, issuedAt = 0, retryTimer;
  let micMode, pending, version = 0;

  function show(next, focus = true) {
    clearTimeout(retryTimer);
    state = next;
    const [heading, copy, label] = screens[next];
    title.textContent = heading;
    detail.textContent = copy;
    action.textContent = label || '';
    action.hidden = !label;
    action.setAttribute('aria-disabled', String(['accepting', 'resultLoading', 'limited'].includes(next)));
    const active = next === 'talking' || next === 'reconnecting';
    controls.hidden = !active;
    status.hidden = next !== 'talking';
    back.hidden = active || ['accepting', 'resultLoading', 'connecting'].includes(next);
    if (focus) title.focus();
  }

  function failed(result, otherwise) {
    if (result.status === 401) { pending = null; show('login'); }
    else if ([400, 403, 404].includes(result.status)) { pending = null; show('denied'); }
    else if (['call_busy', 'calls_full', 'budget_exhausted', 'daily_limit'].includes(result.data?.code)) {
      pending = null;
      show(result.data.code);
    } else if (result.status === 429) {
      pending = null;
      show('limited');
      retryTimer = setTimeout(() => action.setAttribute('aria-disabled', 'false'), Math.max(result.wait, 1) * 1000);
    } else show(otherwise);
  }

  function current() {
    return Boolean(reference && uuid.test(client) && installation && web.proof() === installation);
  }

  function resolve() {
    return web.request('/target/resolve', 'POST', {targetRef: reference}, undefined, client);
  }

  function returnToLookup() {
    version++;
    frame = expected = pending = null;
    connected = false;
    if (reference) web?.preserveReference(reference, '/chat/');
    location.replace('/chat/');
  }

  function lookupRejected(result, otherwise) {
    if (result.status === 403 && result.data?.code === 'not_allowed') returnToLookup();
    else failed(result, otherwise);
  }

  async function inspect() {
    const run = ++version;
    if (!current()) { show('denied'); return; }
    if (!ordinary) {
      const subscribed = await web.request('/subscription');
      if (run !== version) return;
      if (subscribed.status !== 200) { failed(subscribed, 'offline'); return; }
      if (subscribed.data?.state !== 'active') { returnToLookup(); return; }
    }
    const result = await resolve();
    if (run !== version) return;
    if (result.status === 200 && ['ring_ready', 'ring_expired', 'ring_answered', 'ring_unavailable'].includes(result.data?.state)) {
      if (ordinary && result.data.state === 'ring_expired') show('ordinary');
      else if (ordinary || result.data.state === 'ring_expired') returnToLookup();
      else show(result.data.state);
    } else lookupRejected(result.status === 200 ? {status: 404} : result, 'offline');
  }

  function accept(clientId) {
    return web.request('/call/accept', 'POST', {targetRef: reference, clientId});
  }

  function accepted(result, clientId) {
    if (result.status !== 200 || result.data?.state !== 'accepted'
        || !uuid.test(result.data.callId) || !token.test(result.data.connectToken)) return false;
    if (expected && expected !== result.data.callId) return false;
    expected = result.data.callId;
    issuedAt = Date.now();
    frame = {type: 'start_notified', clientId, installationProof: installation, connectToken: result.data.connectToken};
    return true;
  }

  async function authorize(mode, clientId) {
    const run = version;
    if (!current() || clientId !== client) { returnToLookup(); return false; }
    const verified = await resolve();
    if (run !== version) return false;
    if (verified.status !== 200) { lookupRejected(verified, 'offline'); return false; }
    if (mode === 'ordinary') {
      if (!ordinary || verified.data?.state !== 'ring_expired') { returnToLookup(); return false; }
      frame = {type: 'start_ordinary', clientId, installationProof: installation, targetRef: reference};
    } else {
      if (ordinary || verified.data?.state === 'ring_expired') { returnToLookup(); return false; }
      pending = mode;
      const result = await accept(clientId);
      if (run !== version) return false;
      if (!accepted(result, clientId)) {
        if (result.status === 200 && ['ring_answered', 'ring_expired', 'ring_unavailable'].includes(result.data?.state)) {
          pending = null;
          if (result.data.state === 'ring_expired') returnToLookup();
          else show(result.data.state);
        } else lookupRejected(result, 'result');
        return false;
      }
      pending = null;
    }
    show('connecting');
    return true;
  }

  async function resume() {
    if (!current() || !frame) { show('checking'); return false; }
    if (frame.type === 'start_ordinary' || Date.now() - issuedAt < 110000) return true;
    const run = version;
    const result = await resolve();
    if (run !== version) return false;
    if (result.status !== 200) { lookupRejected(result, 'checking'); return false; }
    if (result.data?.state !== 'ring_answered') { show('ended'); return false; }
    // Replay only the exact request for a known, already-answered call.
    const previous = await accept(frame.clientId);
    if (run !== version) return false;
    if (accepted(previous, frame.clientId)) return true;
    if (previous.status === 200) show('ended');
    else lookupRejected(previous, 'checking');
    return false;
  }

  function start(mode) {
    if (!engine) { show('offline'); return; }
    micMode = mode;
    version++;
    if (mode !== 'resume') {
      expected = frame = null;
      connected = false;
    }
    show(mode === 'result' ? 'resultLoading' : mode === 'accept' ? 'accepting' : 'connecting', mode !== 'result' && mode !== 'accept');
    if (mode === 'accept' || mode === 'result') action.focus({preventScroll: true});
    void engine.begin(mode);
  }

  async function checkConnection() {
    const run = ++version;
    if (!current()) { show('denied'); return; }
    const result = await resolve();
    if (run !== version) return;
    if (result.status !== 200) { lookupRejected(result, 'checking'); return; }
    if (frame && ((frame.type === 'start_notified' && result.data?.state === 'ring_answered')
        || (frame.type === 'start_ordinary' && expected && result.data?.state === 'ring_expired'))) {
      start('resume');
    } else show('ended');
  }

  action.onclick = () => {
    if (action.getAttribute('aria-disabled') === 'true') return;
    if (state === 'ring_ready') start('accept');
    else if (state === 'ordinary') start('ordinary');
    else if (state === 'result' && pending) start('result');
    else if (state === 'mic' || state === 'micResume') start(micMode);
    else if (state === 'connecting') { version++; void engine?.end(); show('checking'); }
    else if (state === 'checking') void checkConnection();
    else if (state === 'ended') location.replace('/');
    else if (state === 'login') {
      if (current()) web.preserveReference(reference, '/chat/');
      location.replace(loginUrl);
    } else void inspect();
  };
  back.onclick = event => {
    event.preventDefault();
    version++;
    web?.clear();
    void engine?.end();
    location.replace('/chat/');
  };
  window.addEventListener('pagehide', () => { version++; pending = null; });
  window.addEventListener('pageshow', event => { if (event.persisted) void inspect(); });

  window.MarongNoticeCall = {
    clientId: client,
    attach(value) { engine = value; },
    authorize, resume,
    handshake() { return {frame, expected, ring: frame?.type === 'start_notified'}; },
    ready(message, stopping) {
      if (!uuid.test(message.callId) || (expected && message.callId !== expected)
          || message.ring !== (frame?.type === 'start_notified') || message.memoryConnected !== true) {
        show('checking');
        return false;
      }
      expected = message.callId;
      if (!stopping) show('talking', !connected);
      connected = true;
      return true;
    },
    reconnecting() { if (connected) show('reconnecting', false); },
    microphoneFailed() { show(micMode === 'accept' ? 'mic' : 'micResume'); },
    ended() { frame = pending = expected = null; show('ended'); },
    failure(type) {
      if (type === 'not_allowed' && frame?.type === 'start_ordinary') {
        returnToLookup();
        return true;
      }
      if (type === 'ring_expired') {
        returnToLookup();
        return true;
      }
      const mapped = {
        login_required: 'login', not_allowed: 'denied', invalid_input: 'denied',
        ring_answered: expected ? 'ended' : 'ring_answered', ring_unavailable: connected ? 'ended' : 'ring_unavailable',
        call_busy: 'call_busy', calls_full: 'calls_full', daily_limit: 'daily_limit', budget_exhausted: 'budget_exhausted',
        db_unavailable: 'checking', transport: 'checking',
      }[type];
      if (!mapped) return false;
      if (mapped !== 'checking') { frame = pending = expected = null; }
      show(mapped);
      return true;
    },
    setMuted(value) { mute.textContent = value ? '음소거 해제' : '음소거'; },
  };
  title.focus();
  void inspect();
})();
