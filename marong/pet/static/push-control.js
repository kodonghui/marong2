import {action, api, button, el, Failure, text} from './pet.js';

export function pushControl(member, {waiting = false} = {}) {
  if (member.status !== 'active') return null;
  const appleMobile = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  if (appleMobile && !navigator.standalone && !matchMedia('(display-mode: standalone)').matches) {
    return el('section', {class: 'card stack'},
      text('홈 화면에 추가하면 알림을 받을 수 있어요'), text('공유 → 홈 화면에 추가', 'muted'));
  }
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return null;

  const key = `pet:push:${member.memberNo}`;
  let subscriptionId = localStorage.getItem(key);
  let registration, subscription, applicationServerKey;
  const outcome = el('div', {'aria-live': 'polite'});
  const toggle = button('', () => action(toggle, outcome, async () => {
    if (subscriptionId) {
      try { await api(`/api/me/push/${subscriptionId}`, {method: 'DELETE'}); }
      catch (error) { if (error.status !== 404) throw error; }
      localStorage.removeItem(key);
      subscriptionId = null;
      await subscription?.unsubscribe().catch(() => {});
      subscription = null;
    } else {
      try {
        subscription ||= await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey});
      } catch (error) {
        if (error.name !== 'NotAllowedError' && Notification.permission !== 'denied') throw new Failure(0);
        denied();
        return;
      }
      const {endpoint, keys} = subscription.toJSON();
      const {jobId} = await api('/api/me/push', {method: 'POST', body: {endpoint, keys}});
      localStorage.setItem(key, jobId);
      subscriptionId = jobId;
      if (waiting) outcome.replaceChildren(text('알려 드릴게요'));
    }
    render();
  }));
  const pane = el('section', {class: 'card stack', 'aria-label': '알림', hidden: true}, toggle, outcome);
  toggle.disabled = true;

  function render() {
    toggle.textContent = subscriptionId ? '알림 끄기' : waiting ? '다 그리면 알려 드릴까요?' : '알림 켜기';
  }

  function denied() {
    outcome.replaceChildren(text(waiting ? '알림을 끄셨어요. 이 화면을 다시 열면 볼 수 있어요'
      : '브라우저 설정에서 알림을 허용해 주세요'));
  }

  void Promise.all([api('/static/push-key.json', {auth: false}), navigator.serviceWorker.ready])
    .then(async ([config, ready]) => {
      if (!config.publicKey) return;
      applicationServerKey = Uint8Array.from(atob(config.publicKey.replace(/-/g, '+').replace(/_/g, '/')),
        character => character.charCodeAt(0));
      if (applicationServerKey.length !== 65 || applicationServerKey[0] !== 4) return;
      registration = ready;
      subscription = await ready.pushManager.getSubscription();
      if (subscriptionId && !subscription) {
        try { await api(`/api/me/push/${subscriptionId}`, {method: 'DELETE'}); }
        catch (error) { if (error.status !== 404) throw error; }
        localStorage.removeItem(key);
        subscriptionId = null;
      }
      if (Notification.permission === 'denied') denied();
      render();
      toggle.disabled = false;
      pane.hidden = false;
    }).catch(() => {});
  return pane;
}
