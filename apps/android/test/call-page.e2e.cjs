'use strict';
// TC-101 to TC-107 in a browser: the real call page (tools/vertex_live/static) with the app's page
// script injected at document start, as the Android app does, and a stand-in for Capacitor's bridge.
// The call server is replaced by test/support/call-site.cjs; nothing leaves 127.0.0.1.
const { describe, it, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { startCallSite, REPO } = require('./support/call-site.cjs');

let chromium = null;
try {
  ({ chromium } = require('playwright'));
} catch {
  // Reported as a skip below.
}

const PAGE_SCRIPT = fs.readFileSync(path.join(REPO, 'apps', 'android', 'android', 'app', 'src', 'main', 'assets', 'marong_page.js'), 'utf8');
// Capacitor adds its bridge after the app's script, so the stand-in runs second here too.
const BRIDGE_STUB = `window.__nativeCalls = [];
window.Capacitor = { nativePromise(plugin, method, options) {
  window.__nativeCalls.push({ plugin, method, options: options || {} });
  return Promise.resolve({});
} };`;
const INIT_SCRIPT = `${PAGE_SCRIPT}\n;${BRIDGE_STUB}`;
const CALL_SITE = 'https://marong.corthex-hq.com/';
const PHONE = { viewport: { width: 412, height: 915 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true, locale: 'ko-KR' };
const DAY = new Date('2026-11-15T03:00:00Z'); // 12:00 in Seoul: cream theme
const NIGHT = new Date('2026-11-15T13:00:00Z'); // 22:00 in Seoul: night theme
const SHOTS = process.env.MARONG_SCREENSHOTS || '';
const skip = chromium ? false : 'Playwright is not installed here, so the call page was not checked in a browser';

describe('call page inside the app', { skip }, () => {
  let site;
  let browser;
  let deniedBrowser;

  before(async () => {
    site = await startCallSite();
    browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'] });
    deniedBrowser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream=deny'] });
  });

  after(async () => {
    await browser?.close();
    await deniedBrowser?.close();
    await site?.close();
  });

  async function openCallPage(target, at = NIGHT) {
    const context = await target.newContext(PHONE);
    await context.addInitScript(INIT_SCRIPT);
    const page = await context.newPage();
    await page.clock.setFixedTime(at);
    await page.goto(`${site.url}/`);
    await page.waitForFunction(() => !document.getElementById('start').disabled);
    const calls = async (plugin) => (await page.evaluate(() => window.__nativeCalls)).filter((c) => c.plugin === plugin);
    return { context, page, calls };
  }

  async function shot(page, name) {
    if (!SHOTS) return;
    fs.mkdirSync(SHOTS, { recursive: true });
    await page.waitForTimeout(600); // let the page's own theme transitions (0.45 s) finish
    await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
  }

  it('TC-107: status bar icons follow the page theme (cream day, night)', async () => {
    const day = await openCallPage(browser, DAY);
    assert.equal(await day.page.evaluate(() => document.documentElement.dataset.theme), 'chestnut');
    assert.deepEqual((await day.calls('SystemBars')).map((c) => c.options), [{ style: 'LIGHT' }]);
    await shot(day.page, 'call-day');
    await day.context.close();

    const night = await openCallPage(browser, NIGHT);
    assert.equal(await night.page.evaluate(() => document.documentElement.dataset.theme), 'night');
    assert.deepEqual((await night.calls('SystemBars')).map((c) => c.options), [{ style: 'DARK' }]);
    await shot(night.page, 'call-night');
    await night.context.close();
  });

  it('TC-101, TC-104: a call tells the app it started, and the notification hang-up ends it through the page', async () => {
    const { context, page, calls } = await openCallPage(browser);
    assert.equal(await page.evaluate(() => window.__marongApp.endCall()), false, 'no call yet, nothing to end');

    await page.click('#start');
    await page.waitForFunction(() => document.body.classList.contains('in-call') && document.getElementById('status').textContent === '듣고 있어. 편하게 말해 줘.');
    assert.deepEqual((await calls('MarongCall')).map((c) => c.method), ['callStarted']);
    assert.equal(await page.evaluate(() => window.__marongApp.isCallActive()), true);
    await shot(page, 'call-active');

    assert.equal(await page.evaluate(() => window.__marongApp.endCall()), true);
    await page.waitForFunction(() => !document.body.classList.contains('in-call'));
    assert.deepEqual((await calls('MarongCall')).map((c) => c.method), ['callStarted', 'callEnded']);
    assert.equal(await page.evaluate(() => window.__marongApp.isCallActive()), false);
    // The page ended the call its own way: it told the server to stop.
    await page.waitForFunction(() => document.getElementById('status').textContent === '또 이야기하자. 여기 있을게.');
    for (let i = 0; i < 20 && !site.received.some((m) => m.type === 'stop'); i++) await new Promise((r) => setTimeout(r, 100));
    assert.ok(site.received.some((m) => m.type === 'stop'), 'the page sent its stop message');
    await context.close();
  });

  it('TC-105: a refused microphone tells the app, and the page keeps its own explanation', async () => {
    const { context, page, calls } = await openCallPage(deniedBrowser);
    await page.click('#start');
    await page.waitForFunction(() => document.getElementById('status').textContent === '마이크 사용을 허용해 줘. 준비되면 다시 전화해.');
    assert.deepEqual((await calls('MarongCall')).map((c) => c.method), ['microphoneDenied']);
    await context.close();
  });

  it('TC-106: the offline page explains and goes back to the call site', async () => {
    const context = await browser.newContext(PHONE);
    // The call site is answered here, so the retry never reaches the real server.
    await context.route(`${CALL_SITE}**`, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<title>call site</title>' }));
    const page = await context.newPage();

    await page.goto(`${site.url}/__app/error.html`);
    assert.equal(await page.textContent('h1'), '마롱이한테 연결하지 못했어');
    assert.equal(await page.textContent('#reason'), '마롱이 쪽이 잠깐 쉬고 있는 것 같아. 조금 있다가 다시 시도해 줘.');
    const box = await page.locator('#retry').boundingBox();
    assert.ok(box.height >= 48 && box.width >= 48, `retry button is ${box.width}x${box.height}`);
    await shot(page, 'offline-server');
    await page.click('#retry');
    await page.waitForURL(CALL_SITE);

    const offline = await context.newPage();
    await offline.addInitScript(() => Object.defineProperty(Navigator.prototype, 'onLine', { get: () => false }));
    await offline.goto(`${site.url}/__app/error.html`);
    assert.equal(await offline.textContent('#reason'), '인터넷 연결을 확인하고 다시 시도해 줘.');
    await shot(offline, 'offline-network');
    await offline.evaluate(() => window.dispatchEvent(new Event('online')));
    await offline.waitForURL(CALL_SITE);
    await context.close();
  });
});
