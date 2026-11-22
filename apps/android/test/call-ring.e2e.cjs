'use strict';
// TC-145 (docs/app-ring.md) and the call page's '글 대화' link (docs/app-chat.md SPEC-124) in a browser: the real
// call page (tools/vertex_live/static) against test/support/call-site.cjs. Nothing leaves 127.0.0.1.
// In-app cases run the app's own page script (0.2.0, autoAnswer) with a stand-in for Capacitor's bridge.
const { describe, it, before, after, afterEach } = require('node:test');
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

const PHONE = { viewport: { width: 412, height: 915 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true, locale: 'ko-KR' };
const RING = '6f1c1d2e-3b4a-4c5d-8e9f-0a1b2c3d4e5f';
// A hello call's first 'ready' (docs/04-functional-spec/call-first.md SPEC-268) and a WebP to stand in for its picture.
const HELLO = { ring: true, topic: { picture: '/chat/topics/v1/winter-hat.webp', title: '털모자' } };
const PICTURE = { '/chat/topics/v1/winter-hat.webp': path.join(REPO, 'marong', 'call', 'static', 'face', 'v1', '05-excited.webp') };
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

  async function open(options, address = '/', init = '', { idle = false, app = false, device = {} } = {}) {
    const site = await startCallSite(options);
    sites.push(site);
    const context = await browser.newContext({ ...PHONE, ...device });
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

  it('TC-575, TC-579: slow LiveKit does not block the page; profile and status overlap', async () => {
    const site = await startCallSite();
    sites.push(site);
    const context = await browser.newContext(PHONE);
    contexts.push(context);
    const page = await context.newPage();
    const starts = {};
    let releaseKit;
    const kit = new Promise(resolve => { releaseKit = resolve; });
    await page.route('**/livekit-client.js', async route => {
      await kit;
      await route.continue();
    });
    for (const [url, reply] of [['/status', {ready: true}], ['/chat/api/profile', {botName: '시험'}]]) {
      await page.route('**' + url, async route => {
        starts[url] = Date.now();
        await new Promise(resolve => setTimeout(resolve, 500));
        await route.fulfill({json: reply});
      });
    }
    try {
      await page.goto(site.url, {waitUntil: 'domcontentloaded'});
      await page.locator('#start:enabled').waitFor({timeout: 1500});
      assert.ok(Math.abs(starts['/status'] - starts['/chat/api/profile']) < 125);
    } finally {
      releaseKit();
    }
  });

  it('TC-576, TC-589, TC-596: warm app ring opens the socket while the microphone is pending', async () => {
    const site = await startCallSite({ready: {ring: true}});
    sites.push(site);
    const context = await browser.newContext(PHONE);
    contexts.push(context);
    const page = await context.newPage();
    await page.addInitScript(() => {
      const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = async constraints => {
        await new Promise(resolve => { window.__releaseFixtureMic = resolve; });
        return original(constraints);
      };
    });
    await page.goto(site.url);
    await page.locator('#start:enabled').waitFor();
    assert.deepEqual(await page.evaluate(() => {
      const call = window.__marongCall;
      return [call.version, Object.isFrozen(call), call.prepareCall(), call.prepareCall(),
        call.answerRing('bad-id', Date.now())];
    }), [1, true, true, false, false]);
    const accepted = await page.evaluate(ring => window.__marongCall.answerRing(ring, Date.now()), RING);
    assert.equal(accepted, true);
    const socket = new URL(await socketURL(site), site.url);
    assert.equal(socket.searchParams.get('ring'), RING);
    assert.equal(socket.searchParams.get('hold'), '1');
    assert.equal(site.audio.bytes, 0);
    await page.evaluate(() => window.__releaseFixtureMic());
    await page.waitForFunction(() => typeof worklet !== 'undefined' && worklet !== null);
    await page.locator('#stop').click();
    const timing = site.received.find(entry => entry.type === 'timing').client;
    assert.equal(timing.base, 'answer');
    assert.equal(timing.reloaded, false);
    assert.ok(timing.liveOpen < timing.micReady);
    assert.equal(site.received.filter(entry => entry.type === 'audio_ready').length, 1);
  });

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
    assert.equal(await page.textContent('#status'), '마롱이가 전화를 걸었어. 받기를 누르면 바로 이어져.');
    assert.equal(site.upgrades.length, 0, 'nothing starts by itself in a browser');
    await shot(page, 'call-ring-offer');
    await page.click('#start');
    await inCall(page);
    const url = await socketURL(site);
    assert.ok(url.includes(`&ring=${RING}`), url);
    assert.ok(!(await page.evaluate(() => window.__statuses)).includes('벨이 울린 지 오래돼서 보통 전화로 이어졌어.'));
    assert.equal(await page.evaluate(() => document.body.classList.contains('topic-on')), false, 'no picture without a topic');
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
    await page.waitForFunction(() => window.__statuses.includes('벨이 울린 지 오래돼서 보통 전화로 이어졌어.'));
    assert.ok((await socketURL(site)).includes(`&ring=${RING}`));
  });

  const topicOn = (page) => page.waitForFunction(() => document.body.classList.contains('topic-on'));
  const topicOff = (page) => page.evaluate(() => !document.body.classList.contains('topic-on'));

  /** Nothing of the call is covered: the center of each button hits the button itself. */
  async function controlsFree(page) {
    for (const id of ['mute', 'stop']) {
      const free = await page.evaluate((name) => {
        const button = document.getElementById(name), box = button.getBoundingClientRect();
        const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
        return !button.hidden && button.contains(hit);
      }, id);
      assert.ok(free, `${id} is not covered`);
    }
  }

  it('SPEC-269: a hello call shows its picture in the face circle for 15 seconds, then her face', async () => {
    const { page } = await open({ ready: HELLO, topics: PICTURE }, `/?ring=${RING}`);
    await page.click('#start');
    await inCall(page);
    await topicOn(page);
    const shownAt = Date.now();
    assert.equal(await page.getAttribute('#topic-picture', 'src'), HELLO.topic.picture);
    assert.equal(await page.getAttribute('#topic-picture', 'alt'), '털모자', 'the title is the picture\'s text');
    assert.equal(await page.isHidden('#face'), true);
    assert.equal(await page.textContent('#topic-title'), '털모자');
    assert.equal(await page.getAttribute('#topic-close', 'aria-label'), '그림 닫기');
    const close = await page.locator('#topic-close').boundingBox();
    assert.ok(close.width >= 48 && close.height >= 48, `close ${close.width}x${close.height}`);
    // Measured together: the circle grows into its call size with a transition.
    const fills = await page.evaluate(() => {
      const circle = document.querySelector('.face-disc').getBoundingClientRect();
      const picture = document.getElementById('topic-picture').getBoundingClientRect();
      return Math.abs(picture.width - circle.width) < 1 && Math.abs(picture.height - circle.height) < 1;
    });
    assert.ok(fills, 'the picture fills the circle');
    await controlsFree(page);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    await shot(page, 'call-topic-card');
    await page.waitForFunction(() => !document.body.classList.contains('topic-on'), null, { timeout: 20000 });
    const shownFor = Date.now() - shownAt;
    assert.ok(shownFor >= 14000 && shownFor < 17000, `the picture stayed ${shownFor} ms`);
    assert.equal(await page.isVisible('#face'), true, 'her face is back');
    assert.equal(await page.isHidden('#topic-close'), true);
    assert.ok(await page.evaluate(() => document.body.classList.contains('in-call')), 'the call goes on');
  });

  it('SPEC-269: 그림 닫기 or a tap on the picture brings her face back at once', async () => {
    for (const target of ['#topic-close', '#topic-picture', '#topic-title']) {
      const { page } = await open({ ready: HELLO, topics: PICTURE }, `/?ring=${RING}`);
      await page.click('#start');
      await inCall(page);
      await topicOn(page);
      await page.click(target);
      assert.ok(await topicOff(page), `${target} closes the picture`);
      assert.equal(await page.isVisible('#face'), true);
      assert.ok(await page.evaluate(() => document.body.classList.contains('in-call')), 'and the call goes on');
    }
  });

  it('SPEC-269: a picture that does not load, or a picture address of another shape, shows nothing', async () => {
    const shapes = [{ picture: '/chat/topics/v1/no-such-picture.webp', title: '없는 그림' },
      { picture: 'https://example.com/x.webp', title: '바깥' }, { picture: '/chat/topics/v1/winter-hat.webp', title: '' }];
    for (const topic of shapes) {
      const { site, page } = await open({ ready: { ring: true, topic }, topics: PICTURE }, `/?ring=${RING}`);
      await page.click('#start');
      await inCall(page);
      await page.waitForTimeout(800);
      assert.ok(await topicOff(page), JSON.stringify(topic));
      assert.equal(await page.isVisible('#face'), true);
      assert.ok(!site.requests.some((line) => line.includes('example.com')), 'nothing outside the site was asked');
    }
  });

  it('SPEC-269: at 360 and 430 px the card fits, covers no button, and shows without movement under reduced motion', async () => {
    for (const [width, height] of [[360, 740], [430, 932]]) {
      for (const motion of ['no-preference', 'reduce']) {
        const { page } = await open({ ready: HELLO, topics: PICTURE }, `/?ring=${RING}`, '',
          { device: { viewport: { width, height }, reducedMotion: motion } });
        await page.click('#start');
        await inCall(page);
        await topicOn(page);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false, `${width}px`);
        for (const id of ['#topic-close', '#topic-title']) {
          const box = await page.locator(id).boundingBox();
          assert.ok(box.x >= 0 && box.x + box.width <= width, `${id} inside ${width}px`);
        }
        await controlsFree(page);
        const animation = await page.evaluate(() => getComputedStyle(document.getElementById('topic-picture')).animationName);
        assert.equal(animation === 'none', motion === 'reduce', `${motion}: ${animation}`);
        if (motion === 'no-preference') await shot(page, `call-topic-card-${width}`);
      }
    }
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
