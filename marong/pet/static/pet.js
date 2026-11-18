import {home, signup} from './home.js';
import {creation} from './creation.js';
import {account, petScreen} from './member.js';
import {diary} from './diary.js';
import {orders, paymentReturn, plan} from './orders.js';
import {callScreen} from './call.js';
import {settings, farewell} from './settings.js';
import {closet} from './closet.js';
import {shop, shopItem} from './shop.js';

export const page = document.querySelector('#page');
const tabs = document.querySelector('#tabs');
const bar = document.querySelector('#bar');
export const currency = new Intl.NumberFormat('ko-KR');
const koreanClock = new Intl.DateTimeFormat('en-GB', {timeZone: 'Asia/Seoul', hour: '2-digit'});
const koreanDate = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Seoul', dateStyle: 'short'});
const offline = document.querySelector('#offline');

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (name.startsWith('on') && typeof value === 'function') node.addEventListener(name.slice(2), value);
    else if (value !== false && value != null) node.setAttribute(name, value === true ? '' : value);
  }
  node.append(...children.flat().filter(value => value !== null && value !== undefined && value !== false));
  return node;
}

export const link = (label, href, kind = 'button') => el('a', {href, class: kind}, label);
export const button = (label, click, kind = '') => el('button', {type: 'button', class: kind, onclick: click}, label);
export const text = (value, style) => el('p', {class: style}, value);
export const banner = (value, action) => el('aside', {class: 'banner stack'}, text(value), action);
export const AI_NOTICE = 'AI가 만든 캐릭터예요';
export const CONSENT = '사진과 대화를 해외 AI 회사로 보내는 데 동의해야 쓸 수 있어요. 설정에서 바꿀 수 있어요.';
export const RETRY = '잠시 뒤 다시 해 주세요.';

export function header(title, back) {
  document.title = title === '마롱이' ? title : `${title} · 마롱이`;
  bar.replaceChildren(el('h1', {}, title));
  if (back) bar.append(link(`‹ ${back.label}`, back.url, 'back'));
}

export function showTabs(active, shop) {
  tabs.replaceChildren();
  tabs.hidden = !active;
  if (!active) return;
  const entries = [['홈', '/'], ...(shop ? [['상점', '/shop']] : []), ['내 정보', '/me']];
  for (const [name, href] of entries) {
    const node = link(name, href, 'tab');
    if (active === href) node.setAttribute('aria-current', 'page');
    tabs.append(node);
  }
}

export function show(...nodes) {
  page.replaceChildren(...nodes.filter(Boolean));
  page.setAttribute('aria-busy', 'false');
}

export function notice(message, action, tone = '') {
  return el('section', {class: `card stack notice ${tone}`}, text(message), action);
}

export function picture(url, alt, style = '') {
  const box = el('div', {class: `picture ${style}`});
  if (!url) return box;
  const image = el('img', {src: url, alt});
  const fallback = el('div', {class: 'retry-picture stack', hidden: true},
    text('그림을 불러오지 못했어요'), button('다시 보기', () => {
      fallback.hidden = true;
      image.hidden = false;
      image.removeAttribute('src');
      image.src = url;
    }, 'plain'));
  image.addEventListener('error', () => { image.hidden = true; fallback.hidden = false; });
  box.append(image, fallback);
  return box;
}

export class Failure extends Error {
  constructor(status, details = {}) {
    super(details.detail || RETRY);
    this.status = status;
    this.code = details.code || 'server_error';
    this.trace = details.traceId;
    this.photo = details.photo;
    this.prompt = details.prompt;
  }
}

function local(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return null;
  try {
    const url = new URL(value, location.origin);
    if (url.origin === location.origin && !/^\/(api|internal|static)(\/|$)/.test(url.pathname)) return url;
  } catch {}
  return null;
}

export function resumeAfterSignIn() {
  const pending = local(sessionStorage.getItem('pet_next'));
  sessionStorage.removeItem('pet_next');
  if (pending && pending.pathname !== '/') location.replace(pending.href);
}

export function signIn(activePath = location.pathname + location.search + location.hash) {
  if (activePath !== '/' && local(activePath)) sessionStorage.setItem('pet_next', activePath);
  location.replace('/');
}

export async function api(path, {method = 'GET', body, auth = true, timeout = 10_000} = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const json = body !== undefined && !(body instanceof FormData);
  try {
    const response = await fetch(path, {
      method, signal: controller.signal, credentials: 'same-origin', cache: 'no-store',
      headers: {'Accept': 'application/json', ...(json ? {'Content-Type': 'application/json'} : {})},
      body: json ? JSON.stringify(body) : body,
    });
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 && auth) signIn();
      throw new Failure(response.status, data);
    }
    return data;
  } catch (error) {
    if (error instanceof Failure) throw error;
    throw new Failure(0);
  } finally {
    clearTimeout(timer);
  }
}

export function errorText(error, outlet) {
  const message = error.code === 'cross_site' ? '요청을 처리할 수 없어요. 이 화면에서 다시 해 주세요.'
    : error.code === 'invalid_input' ? '입력을 확인해 주세요.' : error.message;
  outlet.replaceChildren(text(message, 'error'), ...(error.trace ? [el('small', {}, error.trace)] : []));
}

export function failurePage(error) {
  if (error.status === 401 && location.pathname !== '/') return;
  page.setAttribute('aria-busy', 'false');
  show(error.status === 404
    ? notice('찾을 수 없어요.', link('홈으로', '/'))
    : notice(RETRY, button('다시 해 보기', () => location.reload(), 'primary')));
  if (error.trace) page.append(el('small', {}, error.trace));
}

export async function action(control, outlet, task) {
  if (control.disabled || !navigator.onLine) return;
  control.disabled = true;
  control.setAttribute('aria-busy', 'true');
  control.classList.add('busy');
  outlet.replaceChildren();
  try { await task(); }
  catch (error) { errorText(error, outlet); }
  finally {
    control.disabled = false;
    control.removeAttribute('aria-busy');
  }
}

export function dateLabel(value) {
  return new Intl.DateTimeFormat('ko-KR', {timeZone: 'Asia/Seoul', month: 'long', day: 'numeric'}).format(new Date(value));
}

export function today() {
  const fields = Object.fromEntries(koreanDate.formatToParts(new Date()).map(({type, value}) => [type, value]));
  return `${fields.year}-${fields.month}-${fields.day}`;
}

function applyTheme() {
  const hour = Number(koreanClock.format(new Date()));
  const day = hour >= 8 && hour < 20;
  document.documentElement.dataset.theme = day ? 'chestnut' : 'night';
  document.querySelector('meta[name=theme-color]').content = day ? '#fbf6ee' : '#121729';
}

async function start() {
  applyTheme();
  setInterval(applyTheme, 30_000);
  document.addEventListener('visibilitychange', applyTheme);
  navigator.serviceWorker?.register('/pet-worker.js').catch(() => {});
  offline.hidden = navigator.onLine;
  window.addEventListener('offline', () => { offline.hidden = false; });
  window.addEventListener('online', () => { location.reload(); });
  const path = location.pathname;
  try {
    if (path === '/') await home();
    else if (path === '/signup') await signup();
    else if (path === '/create' || path.startsWith('/create/')) await creation(path);
    else if (/^\/pets\/[^/]+$/.test(path)) await petScreen(path.split('/')[2]);
    else if (/^\/pets\/[^/]+\/diary(?:\/[^/]+)?$/.test(path)) await diary(path);
    else if (/^\/pets\/[^/]+\/call$/.test(path)) await callScreen(path.split('/')[2]);
    else if (/^\/pets\/[^/]+\/closet$/.test(path)) await closet(path.split('/')[2]);
    else if (/^\/pets\/[^/]+\/settings$/.test(path)) await settings(path.split('/')[2]);
    else if (/^\/pets\/[^/]+\/farewell$/.test(path)) await farewell(path.split('/')[2]);
    else if (path === '/me') await account();
    else if (path === '/me/plan') await plan();
    else if (path === '/me/orders') await orders();
    else if (path === '/shop') await shop();
    else if (/^\/shop\/[^/]+$/.test(path)) await shopItem(path.split('/')[2]);
    else if (path === '/pay/return') await paymentReturn();
    else failurePage(new Failure(404));
    if (sessionStorage.getItem('pet:creation-refresh') === path) {
      sessionStorage.removeItem('pet:creation-refresh');
      page.prepend(banner('화면을 새로 고쳤어요.'));
    }
  } catch (error) {
    failurePage(error);
  }
}

queueMicrotask(start);
