'use strict';

const Unified = (() => {
  function theme() {
    if (document.querySelector('.admin-layout')) return;
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

  function endLetter(name, withBatchim, withoutBatchim) {
    const last = name.charCodeAt(name.length - 1);
    return name + (last >= 0xac00 && last <= 0xd7a3 && (last - 0xac00) % 28 ? withBatchim : withoutBatchim);
  }

  const date = (iso) => iso ? new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', dateStyle: 'short', timeStyle: 'short',
  }).format(new Date(iso)) : '—';

  const koreanDateTime = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: 'numeric', day: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  });

  function shortDate(iso, {wholeHour = false} = {}) {
    if (!iso) return '—';
    const parts = value => Object.fromEntries(
      koreanDateTime.formatToParts(value).filter(part => part.type !== 'literal').map(part => [part.type, part.value]),
    );
    const {year, month, day, dayPeriod, hour, minute} = parts(new Date(iso));
    const prefix = year === parts(new Date()).year ? '' : year + '년 ';
    const time = wholeHour && Number(minute) === 0 ? hour + '시' : hour + ':' + minute;
    return prefix + month + '월 ' + day + '일 ' + dayPeriod + ' ' + time;
  }

  function fitAdminTabs(tabs) {
    if (!tabs) return;
    const current = tabs.querySelector('[aria-current="page"]');
    if (current) {
      const row = tabs.getBoundingClientRect();
      const active = current.getBoundingClientRect();
      if (active.right > row.right) tabs.scrollLeft += active.right - row.right;
      else if (active.left < row.left) tabs.scrollLeft += active.left - row.left;
    }
    const markOverflow = () => {
      tabs.parentElement.dataset.overflow = String(tabs.scrollLeft + tabs.clientWidth < tabs.scrollWidth - 1);
    };
    markOverflow();
    new ResizeObserver(markOverflow).observe(tabs);
    tabs.addEventListener('scroll', markOverflow, {passive: true});
  }

  return {node, button, link, request, signal, date, shortDate, endLetter, fitAdminTabs};
})();
