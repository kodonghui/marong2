'use strict';

const Unified = (() => {
  function theme() {
    const hour = Math.floor((Date.now() / 3_600_000 + 9) % 24);
    const cream = hour >= 8 && hour < 20;
    document.documentElement.dataset.theme = cream ? 'chestnut' : 'night';
    document.querySelector('meta[name="theme-color"]').content = cream ? '#fbf6ee' : '#121729';
  }
  theme();
  setInterval(theme, 60_000);
  addEventListener('pageshow', theme);
  document.addEventListener('visibilitychange', theme);

  function node(tag, text = '', className = '') {
    const element = document.createElement(tag);
    element.className = className;
    element.textContent = text;
    return element;
  }

  function button(text, action, className = 'btn') {
    const element = node('button', text, className);
    element.type = 'button';
    element.addEventListener('click', action);
    return element;
  }

  function link(text, href, className = 'btn') {
    const element = node('a', text, className);
    element.href = href;
    return element;
  }

  async function request(path, payload, method = payload === undefined ? 'GET' : 'POST') {
    const controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), 10_000);
    try {
      const options = {method, credentials: 'same-origin', cache: 'no-store', redirect: 'manual',
                       headers: {Accept: 'application/json'}, signal: controller.signal};
      if (payload !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(payload);
      }
      const response = await fetch(path, options);
      const body = await response.json().catch(() => null);
      return {status: response.status, body, retryAfter: Number(response.headers.get('Retry-After')) || 0};
    } catch {
      return {status: 0, body: null, retryAfter: 0};
    } finally {
      clearTimeout(deadline);
    }
  }

  function signal(target, message = '', reply) {
    const trace = reply?.body?.traceId;
    target.textContent = trace ? message + ' · ' + trace : message;
    target.hidden = !message;
  }

  const date = (iso) => iso ? new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', dateStyle: 'short', timeStyle: 'short',
  }).format(new Date(iso)) : '—';

  return {node, button, link, request, signal, date};
})();
