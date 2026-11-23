'use strict';
// TC-609 / TC-618 use the real page scripts, a local web server and a fake native bridge.
const { describe, it, before, after, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { startCallSite } = require('./support/call-site.cjs');
const { startChatSite } = require('./support/chat-site.cjs');

let chromium;
try { ({ chromium } = require('playwright')); } catch { /* optional browser dependency */ }
const skip = chromium ? false : 'Playwright is not installed';
const shots = process.env.MARONG_BANNER_SCREENSHOTS;
const times = { day: '2026-11-23T03:00:00Z', night: '2026-11-23T13:00:00Z' };

function fakeBridge(options) {
  if (!options) return;
  const fixture = window.updateFixture = {
    update: { state: 'ready', versionName: '0.3.4' }, permitted: true, outcome: 'installing',
    delay: 0, deviceDelay: 0, reads: 0, installs: 0, settings: 0, ...options,
  };
  window.__marongApp = {
    version: fixture.version ?? 3,
    async updateState() {
      fixture.reads++;
      const update = fixture.update;
      if (fixture.delay) await new Promise(resolve => setTimeout(resolve, fixture.delay));
      return update;
    },
    async deviceState() {
      if (fixture.deviceDelay) await new Promise(resolve => setTimeout(resolve, fixture.deviceDelay));
      return fixture.permitted === null ? {} : { installUpdates: fixture.permitted };
    },
    installUpdate: async () => {
      fixture.installs++;
      if (fixture.outcome === 'none') fixture.update = { state: 'none' };
      return { state: fixture.outcome };
    },
    openInstallSettings: () => { fixture.settings++; },
  };
}

function observeFirstContent() {
  const observer = new MutationObserver(() => {
    const start = document.querySelector('#start');
    const log = document.querySelector('#log');
    if ((start && !start.disabled) || (log && !log.hidden && log.querySelector('li[data-id]'))) {
      const banner = document.querySelector('#update-banner');
      window.firstUpdateState = banner.hidden ? 'none' : banner.dataset.updateState;
      observer.disconnect();
    }
  });
  observer.observe(document, { subtree: true, attributes: true, childList: true });
}

describe('app update banners', { skip }, () => {
  let browser, call, chat;
  const contexts = [];
  before(async () => {
    call = await startCallSite();
    chat = await startChatSite();
    for (let i = 1; i <= 30; i++) {
      chat.add(i % 2 ? 'me' : 'marong', i === 30 ? '다음에 또 이야기하자.' : `시험 메시지 ${i}`);
    }
    browser = await chromium.launch({
      args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'],
    });
  });
  afterEach(async () => Promise.all(contexts.splice(0).map(context => context.close())));
  after(async () => {
    await browser?.close();
    await call?.close();
    await chat?.close();
  });

  async function open(surface, { width = 360, theme = 'day', bridge = {}, routes, reducedMotion } = {}) {
    const context = await browser.newContext({
      viewport: { width, height: 800 }, deviceScaleFactor: 1, isMobile: true,
      hasTouch: true, locale: 'ko-KR', reducedMotion,
    });
    contexts.push(context);
    await context.addInitScript(fakeBridge, bridge);
    await context.addInitScript(observeFirstContent);
    if (routes) await routes(context);
    const page = await context.newPage();
    await page.clock.setFixedTime(new Date(times[theme]));
    await page.goto(surface === 'call' ? call.url + '/' : chat.url + '/chat/');
    return page;
  }

  async function state(page, value, visible = true) {
    const banner = page.locator(`#update-banner[data-update-state="${value}"]`);
    await banner.waitFor({ state: visible ? 'visible' : 'attached' });
    if (!visible) assert.equal(await banner.isHidden(), true);
    return banner;
  }

  async function refresh(page, changes, event = 'marongupdate') {
    await page.evaluate(({ changes, event }) => {
      Object.assign(window.updateFixture, changes);
      if (event === 'visibilitychange') document.dispatchEvent(new Event(event));
      else window.dispatchEvent(new Event(event));
    }, { changes, event });
  }

  async function checkLayout(page, banner, width, button) {
    const bounds = await banner.boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
    assert.equal(await banner.locator('p').evaluate(p => p.scrollWidth <= p.clientWidth), true);
    if (button) assert.ok((await banner.getByRole('button').boundingBox()).height >= 44);
  }

  async function screenshot(page, surface, value, width, theme) {
    if (!shots || width !== 360 || (surface === 'chat' && value === 'installing')) return;
    fs.mkdirSync(shots, { recursive: true });
    await page.screenshot({ path: path.join(shots, `${surface}-update-${value}-360-${theme}.png`), animations: 'disabled' });
  }

  for (const [surface, tc] of [['call', 'TC-609'], ['chat', 'TC-618']]) {
    for (const theme of ['day', 'night']) for (const width of [360, 430]) {
      it(`${tc}: ${width}px ${theme}, ready before first content with off and installing states`, async () => {
        const page = await open(surface, { width, theme, bridge: { delay: 80, permitted: false } });
        await page.waitForFunction(() => window.firstUpdateState !== undefined);
        assert.equal(await page.evaluate(() => window.firstUpdateState), 'ready');
        assert.equal(await page.locator('html').getAttribute('data-theme'), theme === 'day' ? 'chestnut' : 'night');
        const ready = await state(page, 'ready');
        assert.equal(await ready.locator('p').textContent(), '새 버전 준비됨 (0.3.4)');
        await checkLayout(page, ready, width, true);
        await screenshot(page, surface, 'ready', width, theme);

        await ready.getByRole('button', { name: '지금 설치' }).click();
        const installing = await state(page, 'installing');
        assert.equal(await installing.locator('p').textContent(), '설치하는 중… 앱이 잠깐 닫혀');
        assert.equal(await installing.locator('.update-progress').isVisible(), true);
        assert.equal(await installing.getByRole('button').count(), 0);
        await checkLayout(page, installing, width, false);
        await screenshot(page, surface, 'installing', width, theme);

        await refresh(page, { update: { state: 'none' } });
        const off = await state(page, 'off');
        assert.equal(await off.locator('p').textContent(), '자동 업데이트 꺼짐 · 켜 두면 새 버전이 저절로 깔려');
        await checkLayout(page, off, width, true);
        await screenshot(page, surface, 'off', width, theme);
        await off.getByRole('button', { name: '켜기' }).click();
        assert.equal(await page.evaluate(() => window.updateFixture.settings), 1);
        await refresh(page, { permitted: true }, 'visibilitychange');
        await state(page, 'none', false);
      });
    }

    it(`${tc}: busy for three seconds, failed for the same release, then none on retry`, async () => {
      const page = await open(surface, { bridge: { outcome: 'busy' } });
      const ready = await state(page, 'ready');
      await ready.evaluate(banner => {
        let busySince;
        const observer = new MutationObserver(() => {
          if (banner.dataset.updateState === 'busy') busySince = performance.now();
          if (busySince && banner.dataset.updateState === 'ready') {
            window.updateFixture.busyFor = performance.now() - busySince;
            observer.disconnect();
          }
        });
        observer.observe(banner, { attributeFilter: ['data-update-state'] });
      });
      await ready.getByRole('button', { name: '지금 설치' }).click();
      const busy = await state(page, 'busy');
      assert.equal(await busy.locator('p').textContent(), '통화 끝나고 깔 수 있어');
      assert.equal(await busy.getByRole('button', { name: '지금 설치' }).isDisabled(), true);
      await refresh(page, { outcome: 'failed' });
      assert.equal(await busy.isVisible(), true, 'an update event does not cut short the three seconds');
      await ready.waitFor();
      assert.ok(await page.evaluate(() => window.updateFixture.busyFor) >= 2950);
      await ready.getByRole('button', { name: '지금 설치' }).click();
      const failed = await state(page, 'failed');
      assert.equal(await failed.locator('p').textContent(), '설치하지 못했어. 나중에 다시 해 볼게');
      await refresh(page, { outcome: 'none' });
      await page.waitForFunction(() => window.updateFixture.reads >= 3);
      assert.equal(await failed.isVisible(), true);
      await failed.getByRole('button', { name: '다시 설치' }).click();
      await state(page, 'none', false);
      assert.equal(await page.evaluate(() => window.updateFixture.installs), 3);
    });

    it(`${tc}: browser, old bridge and Android below 8 never show the banner`, async () => {
      for (const bridge of [null, { version: 2 }, { permitted: null }]) {
        const page = await open(surface, { bridge });
        await page.waitForFunction(() => window.firstUpdateState !== undefined);
        assert.equal(await page.evaluate(() => window.firstUpdateState), 'none');
        assert.equal(await page.locator('#update-banner').isHidden(), true);
      }
    });

    it(`${tc}: both native reads must finish in 500ms, then events can reveal the banner`, async () => {
      const slow = surface === 'call' ? { delay: 1000 } : { deviceDelay: 1000 };
      const page = await open(surface, { bridge: slow });
      await page.waitForFunction(() => window.firstUpdateState !== undefined);
      assert.equal(await page.evaluate(() => window.firstUpdateState), 'none');
      await refresh(page, { delay: 0, deviceDelay: 0 });
      const banner = await state(page, 'ready');
      assert.equal(await banner.evaluate(b => getComputedStyle(b).animationDuration), '0.2s');
    });
  }

  it('TC-609: the banner stays under budget, daily limit and error, and hides during calls', async () => {
    for (const blockedReason of ['budget', 'daily_limit']) {
      const page = await open('call', { routes: context => context.route('**/status', route => route.fulfill({
        json: { ready: true, canCall: false, blockedReason },
      })) });
      assert.equal(await (await state(page, 'ready')).isVisible(), true);
      assert.equal(await page.locator('#start').isDisabled(), true);
    }
    const error = await open('call', { routes: context => context.route('**/status', route => route.fulfill({ status: 503 })) });
    assert.equal(await (await state(error, 'ready')).isVisible(), true);
    const elsewhere = await open('call', { routes: context => context.route('**/status', route => route.fulfill({
      json: { ready: true, active: true },
    })) });
    await elsewhere.locator('body.active-elsewhere').waitFor();
    await state(elsewhere, 'ready', false);
    const page = await open('call');
    await state(page, 'ready');
    await page.locator('#start').click();
    await page.locator('body.in-call').waitFor();
    assert.equal(await page.locator('#update-banner').isHidden(), true);
  });

  it('TC-618: a late banner keeps the last message in view, with menu and limit in their places', async () => {
    const page = await open('chat', { reducedMotion: 'reduce', bridge: { update: { state: 'none' } }, routes: async context => {
      await context.route('**/chat/api/profile', route => route.fulfill({
        json: { botName: '마롱이', features: {}, usageToday: { tickets: 0, units: 1, limit: 1 } },
      }));
      await context.route('**/chat/api/messages', route => route.fulfill({ status: 429, json: { code: 'daily_limit' } }));
    } });
    const composer = page.locator('#composer');
    await page.waitForFunction(() => window.firstUpdateState === 'none');
    const bottom = () => page.locator('#log').evaluate(log => log.scrollHeight - log.scrollTop - log.clientHeight);
    assert.ok(await bottom() < 2);
    await refresh(page, { update: { state: 'ready', versionName: '0.3.4' } });
    const banner = await state(page, 'ready');
    assert.equal(await banner.evaluate(b => getComputedStyle(b).animationName), 'none');
    assert.ok(await bottom() < 2);
    await page.locator('#menu-button').click();
    const menu = page.locator('#menu');
    const bannerBox = await banner.boundingBox();
    const menuBox = await menu.boundingBox();
    assert.ok(bannerBox.y + bannerBox.height <= menuBox.y);
    await page.locator('#menu-button').click();
    await page.locator('#text').fill('한 줄 보낼게.');
    await page.locator('#send').click();
    const notice = page.locator('#notice');
    await notice.waitFor();
    const noticeBox = await notice.boundingBox();
    const composerBox = await composer.boundingBox();
    assert.ok(noticeBox.y + noticeBox.height <= composerBox.y);
    assert.ok(composerBox.y + composerBox.height <= 800);
    assert.ok(await bottom() < 2);
    await refresh(page, { update: { state: 'none' } });
    await state(page, 'none', false);
    assert.ok(await bottom() < 2);
  });
});
