'use strict';
// TC-145 (docs/app-ring.md) and the call page's '글 대화' link (docs/app-chat.md SPEC-124) in a browser: the real
// call page (tools/vertex_live/static) against test/support/call-site.cjs. Nothing leaves 127.0.0.1.
// In-app cases run the app's own page script (0.2.0, autoAnswer) with a stand-in for Capacitor's bridge.
const { describe, it, before, after, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { startCallSite } = require('./support/call-site.cjs');

let chromium = null;
try {
  ({ chromium } = require('playwright'));
} catch {
  // Reported as a skip below.
}

const PHONE = { viewport: { width: 412, height: 915 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true, locale: 'ko-KR' };
const RING = '6f1c1d2e-3b4a-4c5d-8e9f-0a1b2c3d4e5f';
const PAGE_SCRIPT = path.join(__dirname, '..', 'android', 'app', 'src', 'main', 'assets', 'marong_page.js');
// Capacitor's bridge as the page script sees it: it records the app calls and has no phone to report.
const BRIDGE = `window.__native = [];
window.Capacitor = {
  nativePromise(plugin, method) { window.__native.push(plugin + '.' + method); return Promise.resolve(null); },
  addListener() { return { remove() {} }; },
};`;
const SHOTS = process.env.MARONG_SCREENSHOTS || '';
const STATUSES = `window.__statuses = [];
new MutationObserver(() => {}).observe(document, { childList: true });
document.addEventListener('DOMContentLoaded', () => {
  const status = document.getElementById('status');
  new MutationObserver(() => window.__statuses.push(status.textContent)).observe(status, { childList: true, characterData: true, subtree: true });
});`;
const skip = chromium ? false : 'Playwright is not installed here, so the call page was not checked in a browser';

describe('call page: Marong\'s own call and the chat link', { skip }, () => {
  let browser;
  const sites = [];
  const contexts = [];

  before(async () => {
    browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'] });
  });

  afterEach(async () => {
    await Promise.all(contexts.splice(0).map((c) => c.close().catch(() => {})));
    await Promise.all(sites.splice(0).map((s) => s.close()));
  });

  after(async () => {
    await browser?.close();
  });

  async function open(options, address = '/', init = '', { idle = false, app = false } = {}) {
    const site = await startCallSite(options);
    sites.push(site);
    const context = await browser.newContext(PHONE);
    contexts.push(context);
    await context.addInitScript(STATUSES + init);
    if (app) {
      await context.addInitScript(BRIDGE);
      await context.addInitScript({ path: PAGE_SCRIPT });
    }
    const page = await context.newPage();
    await page.goto(`${site.url}${address}`);
    if (idle) await page.waitForTimeout(1500);  // another screen's call keeps the button off
    else await page.waitForFunction(() => !document.getElementById('start').disabled);
    return { site, page };
  }

  /** The call's WebSocket address once the page has opened it. */
  async function socketURL(site) {
    for (let i = 0; i < 60 && !site.upgrades.length; i++) await new Promise((r) => setTimeout(r, 50));
    assert.ok(site.upgrades.length, 'the call opened its WebSocket');
    return site.upgrades.at(-1);
  }

  async function shot(page, name) {
    if (!SHOTS) return;
    fs.mkdirSync(SHOTS, { recursive: true });
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
  }

  const inCall = (page) => page.waitForFunction(() => document.body.classList.contains('in-call'));

  it('SPEC-124: the header shows 글 대화 only when the chat answers 200 for this sign-in', async () => {
    const yes = await open({ chat: 200 });
    await yes.page.waitForSelector('#chat-link:not([hidden])');
    assert.equal(await yes.page.getAttribute('#chat-link', 'href'), '/chat/');
    const box = await yes.page.locator('#chat-link').boundingBox();
    assert.ok(box.height >= 44 && box.width >= 44, `link ${box.width}x${box.height}`);
    assert.equal(await yes.page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    await shot(yes.page, 'call-chat-link');

    const no = await open({ chat: 401 });
    await no.page.waitForTimeout(500);
    assert.ok(no.site.requests.includes('GET /chat/api/me'), 'the page asked');
    assert.equal(await no.page.isHidden('#chat-link'), true);
  });

  it('TC-145: in a browser the ring leaves the address, 받기 answers it and the call carries the ring', async () => {
    const { site, page } = await open({ ready: { ring: true } }, `/?ring=${RING}&from=dm`);
    assert.equal(await page.evaluate(() => location.search), '?from=dm', 'only the ring is taken out');
    assert.equal(await page.textContent('#headline'), '마롱이가 건 전화예요');
    assert.equal(await page.getAttribute('#start', 'aria-label'), '마롱이 전화 받기');
    assert.equal(await page.textContent('#start .button-label'), '받기');
    assert.equal(await page.textContent('#status'), '마롱이가 약속한 전화를 걸었어. 받기를 누르면 바로 이어져.');
    assert.equal(site.upgrades.length, 0, 'nothing starts by itself in a browser');
    await shot(page, 'call-ring-offer');
    await page.click('#start');
    await inCall(page);
    const url = await socketURL(site);
    assert.ok(url.includes(`&ring=${RING}`), url);
    assert.ok(!(await page.evaluate(() => window.__statuses)).includes('약속 시간이 지나서 보통 전화로 이어졌어.'));
  });

  it('TC-145: inside the app (the page script\'s autoAnswer) the ring answers itself', async () => {
    const { site, page } = await open({ ready: { ring: true } }, `/?ring=${RING}`, '', { app: true });
    await inCall(page);
    assert.ok((await socketURL(site)).includes(`&ring=${RING}`));
    assert.equal(site.upgrades.length, 1);
    assert.equal(await page.evaluate(() => location.search), '');
    assert.equal(await page.evaluate(() => window.__marongApp.version), 2);
    // The page took the microphone: the app keeps the call alive and stops the ring (SPEC-132).
    await page.waitForFunction(() => window.__native.includes('MarongCall.callStarted'));
  });

  it('TC-145: no auto answer while another screen is in a call', async () => {
    const { site, page } = await open({ status: { active: true } }, `/?ring=${RING}`, '', { idle: true, app: true });
    assert.equal(site.upgrades.length, 0);
    assert.equal(await page.textContent('#headline'), '마롱이한테 전화할래?');
  });

  it('TC-145: a ring past its time becomes an ordinary call and says so', async () => {
    const { site, page } = await open({}, `/?ring=${RING}`);
    await page.click('#start');
    await inCall(page);
    await page.waitForFunction(() => window.__statuses.includes('약속 시간이 지나서 보통 전화로 이어졌어.'));
    assert.ok((await socketURL(site)).includes(`&ring=${RING}`));
  });

  it('TC-145: a ring value that is not a UUID is dropped', async () => {
    const { site, page } = await open({}, '/?ring=../../x%20y');
    assert.equal(await page.evaluate(() => location.search), '');
    assert.equal(await page.textContent('#headline'), '마롱이한테 전화할래?');
    await page.click('#start');
    await inCall(page);
    const url = await socketURL(site);
    assert.ok(!url.includes('ring='), url);
  });
});
