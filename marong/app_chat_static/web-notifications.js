'use strict';

(() => {
  const api = '/chat/api/web-notifications';
  const proofKey = 'marong.web-notifications.installation';
  const tokenPattern = /^[A-Za-z0-9_-]{43}$/;
  const apple = /iPhone|iPad|iPod/.test(navigator.userAgent);
  const installed = apple && (navigator.standalone === true || matchMedia('(display-mode: standalone)').matches);
  const supported = installed && 'serviceWorker' in navigator && 'Notification' in window && 'PushManager' in window;
  const handoffKey = 'marong.web-notifications.navigation';
  const callHandoffKey = 'marong.web-notifications.call-navigation';
  const chatFocusKey = 'marong.web-notifications.chat-focus';
  const receiptPrefix = 'marong.web-notifications.receipt.';
  const referencePattern = /^[A-Za-z0-9_-]{48,768}$/;
  const receiptPattern = /^[A-Za-z0-9_-]{102}$/;
  let reference = null;
  let refreshSettings;
  let receiptGeneration = 0;

  function cleanReceipts(all = false) {
    if (all) receiptGeneration++;
    if (!installed) return;
    try {
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const key = localStorage.key(i);
        if (!key?.startsWith(receiptPrefix)) continue;
        if (all || !readReceipt(key)) localStorage.removeItem(key);
      }
    } catch { /* browser storage can be unavailable */ }
  }

  function readReceipt(key) {
    try {
      const entry = JSON.parse(localStorage.getItem(key));
      if (typeof entry?.receipt === 'string' && receiptPattern.test(entry.receipt)
          && entry.until > Date.now()) return entry.receipt;
    } catch { /* corrupted or unavailable browser storage */ }
    return null;
  }

  async function receiptKey(target) {
    if (!installed || !referencePattern.test(target)) return null;
    try {
      const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(target));
      return receiptPrefix + Array.from(new Uint8Array(hash), n => n.toString(16).padStart(2, '0')).join('');
    } catch { return null; }
  }

  cleanReceipts();

  if (supported) {
    navigator.serviceWorker.addEventListener?.('message', event => {
      if (event.data?.type === 'marong-web-push-subscription-changed') void refreshSettings?.(true);
    });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') void refreshSettings?.(false);
    });
  }

  function capture() {
    if (!location.hash.startsWith('#notice=')) return false;
    const captured = location.hash.slice(8, 777);
    history.replaceState(history.state, '', location.pathname + location.search);
    if (!installed) return false;
    reference = captured;
    return true;
  }

  function preserve(destination) {
    return preserveReference(reference, destination);
  }

  function preserveReference(value, destination) {
    if (!value) return false;
    try {
      sessionStorage.setItem(handoffKey, JSON.stringify({reference: value, destination, until: Date.now() + 300000}));
      return true;
    } catch {
      return false;
    }
  }

  function pending(destination) {
    if (!installed) return null;
    try {
      const saved = JSON.parse(sessionStorage.getItem(handoffKey));
      if (saved?.destination === destination && saved.until > Date.now() && typeof saved.reference === 'string') {
        return saved;
      }
    } catch { /* browser storage can be unavailable */ }
    return null;
  }

  function restore(destination) {
    const saved = pending(destination);
    clear();
    if (!reference && saved) reference = saved.reference;
    return reference;
  }

  function clear() {
    try { sessionStorage.removeItem(handoffKey); } catch { /* browser storage can be unavailable */ }
  }

  if (capture() && location.pathname === '/chat/login') preserve('/chat/');

  function proof(create = false) {
    if (!installed || !window.isSecureContext) return null;
    try {
      const saved = localStorage.getItem(proofKey);
      if (saved && tokenPattern.test(saved)) return saved;
      if (!create) return null;
      const bytes = crypto.getRandomValues(new Uint8Array(32));
      const encoded = btoa(String.fromCharCode(...bytes)).replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');
      localStorage.setItem(proofKey, encoded);
      return encoded;
    } catch {
      return null;
    }
  }

  function openCall(reference, focus, ordinaryChoice, redialChoice) {
    const device = proof();
    if (!device || document.body.dataset.noticeCallEnabled !== 'true' || !referencePattern.test(reference)) return false;
    try {
      const navigation = crypto.randomUUID().replaceAll('-', '');
      sessionStorage.setItem(callHandoffKey, JSON.stringify({reference, navigation, redialChoice, until: Date.now() + 60000}));
      if (focus) sessionStorage.setItem(chatFocusKey, focus);
      const form = document.createElement('form');
      form.hidden = true;
      form.action = '/chat/notice-call';
      form.method = 'post';
      const fields = {targetRef: reference, installationProof: device, navigation};
      if (ordinaryChoice) fields.ordinaryChoice = ordinaryChoice;
      if (redialChoice) fields.redialChoice = redialChoice;
      for (const [name, value] of Object.entries(fields)) {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = name;
        input.value = value;
        form.append(input);
      }
      document.body.append(form);
      try { form.submit(); } finally { form.remove(); }
      return true;
    } catch {
      takeCall();
      return false;
    }
  }

  function takeCall(navigation) {
    try {
      const raw = sessionStorage.getItem(callHandoffKey);
      sessionStorage.removeItem(callHandoffKey);
      const saved = JSON.parse(raw);
      if (installed && saved && saved.until > Date.now() && referencePattern.test(saved.reference)
          && (navigation === undefined || saved.navigation === navigation)) return saved;
    } catch { /* storage can be unavailable */ }
    return null;
  }

  function restoreChatFocus() {
    try {
      const target = sessionStorage.getItem(chatFocusKey);
      sessionStorage.removeItem(chatFocusKey);
      if (target) (document.getElementById(target) || document.getElementById('chat-heading'))?.focus();
    } catch { /* storage can be unavailable */ }
  }

  async function request(path, method = 'GET', body, choice, documentClient, redialChoice) {
    const device = proof(true);
    if (!device) return {status: 0};
    const headers = {'X-Marong-Installation': device, Accept: 'application/json'};
    if (choice) headers['X-Marong-Choice'] = choice;
    if (documentClient) headers['X-Marong-Notice-Document'] = documentClient;
    if (redialChoice) headers['X-Marong-Redial-Choice'] = redialChoice;
    const generation = receiptGeneration;
    const targetKey = (path === '/target/resolve' && !documentClient || path === '/call/accept')
      ? await receiptKey(body?.targetRef) : null;
    if (targetKey && path === '/target/resolve') {
      const receipt = readReceipt(targetKey);
      if (receipt) headers['X-Marong-Notice-Receipt'] = receipt;
    }
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    const options = {method, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      headers, signal: controller.signal};
    if (body !== undefined) options.body = JSON.stringify(body);
    try {
      const reply = await fetch(api + path, options);
      const data = await reply.json().catch(() => null);
      if (targetKey && path === '/call/accept' && reply.ok && data?.state === 'accepted'
          && generation === receiptGeneration) {
        const receipt = reply.headers.get('X-Marong-Notice-Receipt');
        const until = Date.parse(reply.headers.get('X-Marong-Notice-Receipt-Expires'));
        if (receipt && receiptPattern.test(receipt) && until > Date.now()) {
          try { localStorage.setItem(targetKey, JSON.stringify({receipt, until})); } catch { /* storage is optional */ }
        }
      }
      if (reply.ok && path === '/subscription' && (method === 'DELETE' || data?.state === 'revoked')) cleanReceipts(true);
      return {status: reply.status, data, wait: Number(reply.headers.get('Retry-After')) || 0,
        ordinaryChoice: reply.headers.get('X-Marong-Ordinary-Choice'), redialChoice: reply.headers.get('X-Marong-Redial-Choice')};
    } catch {
      return {status: 0};
    } finally {
      clearTimeout(timer);
    }
  }

  function applicationKey(value) {
    const binary = atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4));
    return Uint8Array.from(binary, char => char.charCodeAt(0));
  }

  const states = {
    guide: ['홈 화면에 추가', 'Safari에서 공유를 열고 홈 화면에 추가해 줘. ‘웹 앱으로 열기’가 보이면 켜고 추가한 뒤 홈 화면 아이콘을 열어 봐. 지금 창에서도 글 대화와 통화를 쓸 수 있어.'],
    loading: ['알림 설정 확인 중', '이 기기의 알림 권한과 수신 상태를 확인하고 있어.'],
    unsupported: ['이 기기에서는 알림을 켤 수 없어', '이 환경에서는 웹 알림을 이용할 수 없어. 글 대화와 통화는 계속 쓸 수 있어.'],
    off: ['이 기기 알림이 꺼져 있어', '홈 화면에서 알림을 켜면 이 기기에서 새 알림을 확인할 수 있어.'],
    register: ['알림 등록이 필요해', '기기 권한은 허용됐어. 이 기기에서 알림을 켜서 등록을 마쳐 줘.'],
    denied: ['기기에서 알림이 꺼져 있어', '아이폰 설정에서 권한을 바꿀 수 있어. 설정을 바꾼 뒤 여기로 돌아와 상태를 확인해 줘.'],
    active: ['이 기기에서 알림을 받을 수 있어', '이 기기의 알림이 켜져 있어. 다른 기기의 설정은 각 기기에서 관리해 줘.'],
    saving: ['변경한 알림 설정을 확인 중이야', '이 기기의 설정이 바뀌었는지 확인하고 있어.'],
    revoked: ['이 기기에서 알림을 껐어', '이 기기에서 새 알림을 받지 않아. 다시 받으려면 여기서 알림을 직접 켜 줘.'],
    expired: ['알림을 다시 등록해 줘', '기존 등록으로는 새 알림을 받을 수 없어. 이 기기에서 알림을 다시 켤 수 있어.'],
    conflict: ['알림 설정이 바뀌었어', '지금 상태를 다시 확인해 줘. 방금 선택이 반영됐는지는 확인 뒤에 알 수 있어.'],
    bad: ['알림 설정을 확인하지 못했어', '입력된 설정을 다시 확인해 줘. 이 상태에서는 알림 변경을 완료로 표시하지 않아.'],
    blocked: ['여기에서 알림 설정을 열 수 없어', '현재 설치에서 다시 열어 줘. 다른 계정이나 기기의 설정은 여기서 열 수 없어.'],
    limited: ['잠시 뒤 알림 설정을 확인해 줘', '요청이 많아 잠시 기다려야 해. 안내된 시간이 지나면 상태를 다시 확인할 수 있어.'],
    unavailable: ['지금 알림 상태를 확인할 수 없어', '인터넷 연결을 확인한 뒤 다시 확인해 줘. 켜기나 끄기가 완료됐는지 아직 확인되지 않았어.'],
  };

  function settings(relogin) {
    if (!apple) return null;
    const card = Unified.node('section', '', 'card');
    const heading = Unified.node('h2', '이 기기 알림');
    const title = Unified.node('p', '', 'title');
    const detail = Unified.node('p', '', 'caption');
    const action = Unified.button('상태 다시 확인', act, 'btn2');
    const back = Unified.link('글 대화로', '/chat/', 'btnt');
    const status = Unified.node('div');
    status.setAttribute('aria-live', 'polite');
    status.append(title, detail);
    title.tabIndex = -1;
    card.append(heading, status, action, back);
    let current, worker, subscription, state, wait;

    function show(next, focus = false) {
      state = next;
      [title.textContent, detail.textContent] = states[next];
      action.hidden = ['guide', 'loading', 'unsupported', 'blocked'].includes(next);
      action.disabled = next === 'saving' || next === 'limited';
      action.textContent = ({
        active: '알림 끄기', off: '알림 켜기', register: '알림 켜기', revoked: '알림 다시 켜기',
        expired: '알림 다시 켜기', saving: '변경 확인 중',
      })[next] || '상태 다시 확인';
      back.hidden = !['guide', 'unsupported', 'blocked'].includes(next);
      if (focus) title.focus();
    }

    function problem(result) {
      if (result.status === 401) { relogin(); return; }
      const mapped = {400: 'bad', 403: 'blocked', 409: 'conflict', 429: 'limited'};
      show(mapped[result.status] || 'unavailable', true);
      clearTimeout(wait);
      if (result.status === 429) wait = setTimeout(() => { action.disabled = false; }, Math.max(result.wait, 1) * 1000);
    }

    async function change(actionName, method, body) {
      const selected = await request('/subscription/intent', 'POST', {action: actionName, stateToken: current.stateToken});
      if (selected.status !== 200) return selected;
      return request('/subscription', method, body, selected.data.choiceToken);
    }

    async function inspect(first = false, renew = false) {
      if (!installed) { show('guide'); return; }
      if (!supported) { show('unsupported'); return; }
      if (first) show('loading');
      const outcome = await request('/subscription');
      if (!card.isConnected) return;
      if (outcome.status !== 200) { problem(outcome); return; }
      current = outcome.data;
      try {
        worker = await navigator.serviceWorker.register('/chat/web-notification-worker.js', {scope: '/chat/'});
        if (!worker.active) worker = await Promise.race([
          navigator.serviceWorker.ready, new Promise((_, reject) => setTimeout(reject, 5000)),
        ]);
        subscription = await worker.pushManager.getSubscription();
        const allowed = Notification.permission;
        if (allowed !== 'granted' && current.state === 'active') {
          const ended = await change('permission_revoked', 'DELETE');
          if (ended.status !== 200) { problem(ended); return; }
          current = ended.data;
        }
        if (renew && allowed === 'granted' && current.state === 'active' && subscription) {
          const advertised = applicationKey(current.vapid.publicKey);
          const actual = new Uint8Array(subscription.options?.applicationServerKey || []);
          if (actual.length === advertised.length && actual.every((byte, index) => byte === advertised[index])) {
            const {endpoint, expirationTime, keys} = subscription.toJSON();
            const updated = await change('refresh', 'PUT', {vapidKeyId: current.vapid.keyId,
              subscription: {endpoint, expirationTime: expirationTime ?? null, keys}});
            if (updated.status !== 200) { problem(updated); return; }
            current = updated.data;
          }
        }
        if (allowed === 'denied') show('denied');
        else if (current.state === 'active' && subscription && allowed === 'granted') show('active');
        else if (current.state === 'active') show('expired');
        else if (['expired', 'invalid'].includes(current.state)) show('expired');
        else if (current.state === 'revoked') show('revoked');
        else show(allowed === 'granted' ? 'register' : 'off');
      } catch {
        show('unavailable');
      }
    }

    async function act() {
      if (['active', 'register', 'off', 'revoked', 'expired'].includes(state) && worker && current) {
        const previous = state;
        show('saving');
        try {
          if (previous === 'active') {
            const outcome = await change('revoke', 'DELETE');
            if (outcome.status !== 200) { problem(outcome); return; }
            const local = await worker.pushManager.getSubscription();
            if (local) await local.unsubscribe();
            current = outcome.data;
            show('revoked', true);
            return;
          }
          // Ask the OS directly in the click. Auth and choice requests can wait.
          const pushOptions = {userVisibleOnly: true, applicationServerKey: applicationKey(current.vapid.publicKey)};
          let permission = Notification.permission;
          // An already allowed install without an old subscription can subscribe
          // before yielding the activation associated with this click.
          const immediate = permission === 'granted' && !subscription ? worker.pushManager.subscribe(pushOptions) : null;
          if (permission === 'default') permission = await Notification.requestPermission();
          if (permission !== 'granted') { show(permission === 'denied' ? 'denied' : previous, true); return; }
          if (subscription && !await subscription.unsubscribe()) { show('unavailable', true); return; }
          subscription = await (immediate || worker.pushManager.subscribe(pushOptions));
          const {endpoint, expirationTime, keys} = subscription.toJSON();
          const outcome = await change(current.state === 'active' ? 'refresh' : 'enable', 'PUT',
            {vapidKeyId: current.vapid.keyId, subscription: {endpoint, expirationTime: expirationTime ?? null, keys}});
          if (outcome.status !== 200) { problem(outcome); return; }
          current = outcome.data;
          show(current.state === 'active' && Notification.permission === 'granted' ? 'active' : 'unavailable', true);
        } catch {
          show('unavailable', true);
        }
        return;
      }
      await inspect();
    }
    refreshSettings = renew => {
      if (card.isConnected && state !== 'saving' && state !== 'limited') return inspect(false, renew);
      return undefined;
    };
    queueMicrotask(() => inspect(true));
    return card;
  }

  window.MarongWebNotifications = {apple, installed, supported, proof, request, settings, capture,
    preserve, preserveReference, pending, restore, clear, openCall, takeCall, restoreChatFocus, cleanReceipts};
})();
