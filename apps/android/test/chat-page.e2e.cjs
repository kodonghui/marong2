'use strict';
// TC-132 (with the browser part of TC-123) and TC-157 in a browser: the real chat page (marong/app_chat_static)
// against test/support/chat-site.cjs, a stand-in for the bot's API. Nothing leaves 127.0.0.1.
const { describe, it, before, after, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { startChatSite, seoul, ME } = require('./support/chat-site.cjs');

// The app's own page script (SPEC-123), injected as the app injects it.
const PAGE_SCRIPT = path.join(__dirname, '..', 'android', 'app', 'src', 'main', 'assets', 'marong_page.js');

let chromium = null;
try {
  ({ chromium } = require('playwright'));
} catch {
  // Reported as a skip below.
}

const PHONE = { viewport: { width: 412, height: 915 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true, locale: 'ko-KR' };
const DAY = new Date('2026-11-15T03:00:00Z'); // 12:00 in Seoul: cream theme
const NIGHT = new Date('2026-11-15T13:00:00Z'); // 22:00 in Seoul: night theme
const SHOTS = process.env.MARONG_SCREENSHOTS || '';
const skip = chromium ? false : 'Playwright is not installed here, so the chat page was not checked in a browser';

/** 35 messages over two days: the first page shows the last 30. */
function history(site) {
  const yesterday = new Date(Date.now() - 24 * 3_600_000);
  const today = new Date();
  const list = [];
  for (let i = 1; i <= 35; i++) {
    const at = seoul(new Date((i <= 20 ? yesterday : today).getTime() - (40 - i) * 60_000));
    list.push({ id: i, from: i % 2 ? 'me' : 'marong', text: `이야기 ${i}`, at, via: 'app', kind: 'chat' });
  }
  Object.assign(list[30], { from: 'marong', kind: 'ring', text: '약속한 통화 시간이야! 📞' });
  Object.assign(list[31], { from: 'marong', kind: 'reminder', text: '⏰ 물 마시기' });
  Object.assign(list[32], { from: 'marong', text: '<img src=x onerror="window.__xss=1"> 여기 봐 https://example.test/a.' });
  Object.assign(list[33], { from: 'me', via: 'discord', text: '디스코드에서 한 말' });
  Object.assign(list[34], { from: 'marong', kind: 'proactive', text: '뭐 해?' });
  site.state.messages = list;
  site.state.nextId = 36;
}

describe('chat page', { skip }, () => {
  let site;
  let browser;

  before(async () => {
    site = await startChatSite();
    browser = await chromium.launch();
  });

  const contexts = [];
  afterEach(async () => {
    // Close every screen of the test, also after a failure, so no wait loop runs into the next test.
    await Promise.all(contexts.splice(0).map((c) => c.close().catch(() => {})));
    for (let i = 0; i < 40 && site.state.openWaits > 0; i++) await new Promise((r) => setTimeout(r, 50));
  });

  after(async () => {
    await browser?.close();
    await site?.close();
  });

  async function openChat({ at = null, init = null, device = {} } = {}) {
    const context = await browser.newContext({ ...PHONE, ...device });
    contexts.push(context);
    if (init) await context.addInitScript(init);
    const page = await context.newPage();
    const outside = [];
    page.on('request', (request) => { if (!request.url().startsWith(site.url)) outside.push(request.url()); });
    if (at) await page.clock.setFixedTime(at);
    await page.goto(`${site.url}/chat/`);
    return { context, page, outside };
  }

  async function ready(page) {
    await page.waitForFunction(() => !document.getElementById('log').hidden && document.querySelectorAll('#messages li').length > 0);
  }

  async function shot(page, name) {
    if (!SHOTS) return;
    fs.mkdirSync(SHOTS, { recursive: true });
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
  }

  function reset() {
    Object.assign(site.state, { me: { status: 200, body: ME }, sends: [], typing: false, reply: null, posted: [],
      waits: [], postDelayMs: 0, read: 0, answered: 0, marks: true, pictures: {}, pictureDelayMs: 0 });
    history(site);
  }

  it('TC-132: the last 30 at the bottom, day lines, tags, text only as text, links, older ones on scroll', async () => {
    reset();
    const { context, page, outside } = await openChat();
    await ready(page);
    assert.equal(await page.locator('#messages li').count(), 30);
    const ids = await page.$$eval('#messages li', (items) => items.map((li) => Number(li.dataset.id)));
    assert.deepEqual(ids, Array.from({ length: 30 }, (_, i) => i + 6), 'ids 6..35 in order');
    assert.equal(await page.evaluate(() => {
      const log = document.getElementById('log');
      return log.scrollHeight - log.scrollTop - log.clientHeight < 2;
    }), true, 'starts at the bottom');
    assert.equal(await page.$$eval('.day:not([hidden])', (days) => days.length), 2, 'one day line per day');
    const tags = await page.$$eval('#messages li', (items) => Object.fromEntries(items.map((li) => [li.dataset.id, li.querySelector('.tag')?.textContent || null])));
    assert.deepEqual([tags[31], tags[32], tags[34], tags[35], tags[33]], ['약속 전화', '일정 알림', '디스코드', '먼저 톡', null]);
    assert.equal(await page.$$eval('.bubble img', (imgs) => imgs.length), 0, 'markup is shown as text');
    assert.equal(await page.evaluate(() => window.__xss), undefined);
    assert.match(await page.textContent('li[data-id="33"] .bubble'), /^<img src=x onerror=/);
    const link = page.locator('li[data-id="33"] .bubble a');
    assert.equal(await link.getAttribute('href'), 'https://example.test/a');
    assert.equal(await link.textContent(), 'https://example.test/a', 'the sentence end is not part of the link');
    assert.equal(await link.getAttribute('target'), '_blank');
    assert.equal(await link.getAttribute('rel'), 'noopener noreferrer');
    const marong = await page.locator('li[data-id="35"] .face img').getAttribute('src');
    assert.equal(marong, '/face/v1/01-neutral.webp');
    assert.equal(await page.locator('li[data-id="34"] .face').isVisible(), false, 'my words have no face');

    await page.evaluate(() => { document.getElementById('log').scrollTop = 0; });
    await page.waitForFunction(() => document.querySelectorAll('#messages li').length === 35);
    assert.equal(await page.evaluate(() => document.getElementById('log').scrollTop > 0), true, 'the view stays where it was');
    assert.deepEqual(outside, [], 'no request leaves the site');
    await shot(page, 'chat-history');
    await context.close();
  });

  it('TC-132, TC-123: a sent message shows at once as 보내는 중, then Marong writing and her reply', async () => {
    reset();
    site.state.reply = { afterMs: 1500, text: '응! 나도 반가워' };
    site.state.postDelayMs = 400;
    const { context, page } = await openChat();
    await ready(page);
    await page.fill('#text', '안녕 마롱이');
    await page.click('#send');
    await page.waitForSelector('.message.me.sending');
    assert.equal(await page.textContent('.message.me.sending time'), '보내는 중');
    assert.equal(await page.inputValue('#text'), '', 'the box is emptied');
    await page.waitForFunction(() => !document.getElementById('typing').hidden);
    await shot(page, 'chat-typing');
    await page.waitForFunction(() => [...document.querySelectorAll('.bubble')].some((b) => b.textContent === '응! 나도 반가워'));
    assert.equal(await page.isHidden('#typing'), true, 'writing ends with her reply');
    assert.equal(await page.locator('.message.sending').count(), 0);
    assert.equal(await page.locator('.bubble', { hasText: '안녕 마롱이' }).count(), 1, 'one bubble for the sent words');
    assert.equal(site.state.posted.length, 1);
    assert.match(site.state.posted[0].clientId, /^[0-9a-f-]{36}$/);
    assert.equal(site.state.posted[0].origin, site.url, 'the browser sends this site as Origin (the cross-site check)');
    assert.equal(site.state.waits.every((q) => /^\?after=\d+&typing=[01]&read=\d+$/.test(q)), true);

    // A message saved another way (a reminder) appears within a second.
    const began = Date.now();
    site.add('marong', '⏰ 약 먹기', { kind: 'reminder' });
    await page.waitForFunction(() => [...document.querySelectorAll('.bubble')].some((b) => b.textContent === '⏰ 약 먹기'));
    assert.ok(Date.now() - began < 1000, `new message after ${Date.now() - began} ms`);

    // Enter makes a new line; only the button sends.
    await page.click('#text');
    await page.keyboard.type('첫 줄');
    await page.keyboard.press('Enter');
    await page.keyboard.type('둘째 줄');
    assert.equal(await page.inputValue('#text'), '첫 줄\n둘째 줄');
    assert.equal(site.state.posted.length, 1, 'Enter did not send');
    await context.close();
  });

  const readOf = (page, id) => page.locator(`li[data-id="${id}"] .read`);
  const bubbleShown = (page, words) => page.waitForFunction(
    (w) => [...document.querySelectorAll('.bubble')].some((b) => b.textContent === w), words);

  it('TC-157: 읽음 once Marong takes my message up, gone with her answer; 대답 중 with her face', async () => {
    reset();
    site.state.read = 34;
    site.state.answered = 29;
    site.state.reply = { pickupMs: 900, afterMs: 2800, text: '응, 다 읽었어!' };
    const { context, page } = await openChat({ at: NIGHT });
    await ready(page);
    assert.equal(await readOf(page, 34).textContent(), '읽음', 'on opening: read and not answered yet');
    assert.equal(await page.locator('.read').count(), 1, 'only messages after the last answer');
    assert.deepEqual(await page.$$eval('li[data-id="34"] .meta > *', (els) => els.map((e) => e.className || e.tagName)),
      ['tag', 'read', 'TIME'], 'tag, 읽음, time');
    site.state.answered = 34; // as if her answer came meanwhile

    await page.fill('#text', '마롱아 오늘 뭐 했어?');
    await page.click('#send');
    await page.waitForSelector('li[data-id="36"]');
    assert.equal(await readOf(page, 36).count(), 0, 'sent, not read yet');
    assert.equal(await page.isHidden('#typing'), true);
    const began = Date.now();
    await readOf(page, 36).waitFor();
    assert.ok(Date.now() - began < 1500, `읽음 after ${Date.now() - began} ms`);
    assert.equal(await page.isVisible('#typing'), true, '대답 중 with it');
    assert.equal(await page.locator('#typing .face img').getAttribute('src'), '/face/v1/01-neutral.webp');
    assert.equal(await page.textContent('#typing .meta'), '마롱이가 대답 중…', 'read out as 마롱이가 대답 중');
    const hidden = await page.locator('#typing .meta .sr-only').boundingBox();
    assert.ok(hidden.width <= 1 && hidden.height <= 1, 'seen as 대답 중…: the name is for screen readers');
    assert.equal(await page.locator('#typing .dots i').count(), 3);
    assert.equal(await page.evaluate(() => {
      const log = document.getElementById('log');
      return log.scrollHeight - log.scrollTop - log.clientHeight < 2;
    }), true, 'the end of the log stays in view');
    await shot(page, 'chat-read-typing-night');
    await bubbleShown(page, '응, 다 읽었어!');
    assert.equal(await page.locator('.read').count(), 0, 'answered: no 읽음 left');
    assert.equal(await page.isHidden('#typing'), true, '대답 중 ends with her answer');
    assert.ok(site.state.waits.some((q) => q.endsWith('&read=36')), 'the screen says what it shows');
    await context.close();
  });

  it('TC-157: two quick messages: 읽음 moves to the second, 대답 중 stays after the first answer', async () => {
    reset();
    const { context, page } = await openChat({ at: DAY });
    await ready(page);
    await page.fill('#text', '첫 번째 말');
    await page.click('#send');
    await page.waitForSelector('li[data-id="36"]');
    site.takeUp(36);
    await readOf(page, 36).waitFor();
    await page.fill('#text', '두 번째 말');
    await page.click('#send');
    await page.waitForSelector('li[data-id="37"]');
    assert.equal(await readOf(page, 37).count(), 0, 'waiting behind the answer in progress: not read');
    site.answer(36, '첫 번째 답', { typing: true });
    await bubbleShown(page, '첫 번째 답');
    assert.equal(await readOf(page, 36).count(), 0, 'the first is answered');
    assert.equal(await page.isVisible('#typing'), true, '대답 중 stays: the second is not answered yet');
    site.takeUp(37);
    await readOf(page, 37).waitFor();
    assert.equal(await page.isVisible('#typing'), true);
    await shot(page, 'chat-read-second-day');
    site.answer(37, '두 번째 답');
    await bubbleShown(page, '두 번째 답');
    assert.equal(await page.locator('.read').count(), 0);
    assert.equal(await page.isHidden('#typing'), true);
    await context.close();
  });

  it('TC-157: a server from before 읽음 shows no 읽음, and 대답 중 still works', async () => {
    reset();
    site.state.marks = false;
    site.state.reply = { pickupMs: 300, afterMs: 1500, text: '옛 서버 답' };
    const { context, page } = await openChat();
    await ready(page);
    await page.fill('#text', '안녕');
    await page.click('#send');
    await page.waitForFunction(() => !document.getElementById('typing').hidden);
    assert.equal(await page.locator('.read').count(), 0);
    await bubbleShown(page, '옛 서버 답');
    assert.equal(await page.locator('.read').count(), 0);
    assert.equal(await page.isHidden('#typing'), true);
    await context.close();
  });

  it('TC-132: too fast: the words go back into the box and the button waits for Retry-After', async () => {
    reset();
    site.state.sends = [429];
    const { context, page } = await openChat();
    await ready(page);
    await page.fill('#text', '빠르게 보낸 말');
    await page.click('#send');
    await page.waitForFunction(() => document.getElementById('notice').textContent === '너무 빨라! 3초 뒤에 보내 줘.');
    assert.equal(await page.inputValue('#text'), '빠르게 보낸 말');
    assert.equal(await page.isDisabled('#send'), true);
    assert.equal(await page.locator('.message.me.sending').count(), 0);
    await shot(page, 'chat-too-fast');
    await page.waitForFunction(() => document.getElementById('notice').hidden, null, { timeout: 5000 });
    assert.equal(await page.isDisabled('#send'), false);
    await context.close();
  });

  it('TC-132: a failed send keeps the bubble with 다시 보내기, which resends the same clientId', async () => {
    reset();
    site.state.sends = [500];
    const { context, page } = await openChat();
    await ready(page);
    // The second try loses its connection (the browser would quietly retry a reset keep-alive socket itself).
    let tries = 0;
    await page.route('**/chat/api/messages', (route) => (route.request().method() === 'POST' && ++tries === 2
      ? route.abort('connectionreset') : route.continue()));
    await page.fill('#text', '실패할 말');
    await page.click('#send');
    await page.waitForSelector('.message.failed .retry');
    assert.match(await page.textContent('.message.failed .meta'), /^못 보냄다시 보내기$/);
    assert.equal(await page.textContent('#notice'), '잠깐 문제가 생겼어. 다시 해 볼래? (0123456789abcdef)');
    const box = await page.locator('.message.failed .retry').boundingBox();
    assert.ok(box.height >= 44, `retry is ${box.height}px high`);
    await shot(page, 'chat-failed');
    await page.click('.message.failed .retry');
    await page.waitForFunction(() => document.querySelector('.message.failed .meta')?.textContent === '못 보냄(연결 끊김)다시 보내기');
    await page.click('.message.failed .retry');
    await page.waitForFunction(() => !document.querySelector('.message.failed, .message.sending'));
    const ids = site.state.posted.map((p) => p.clientId);
    assert.equal(tries, 3);
    assert.equal(ids.length, 2, 'the lost try never reached the server');
    assert.equal(new Set(ids).size, 1, 'every try is the same clientId');
    assert.equal(await page.locator('.bubble', { hasText: '실패할 말' }).count(), 1);
    await context.close();
  });

  it('TC-132: sign-in and permission states (SCR-107)', async () => {
    reset();
    for (const [code, title, link] of [['not_allowed', '이 계정으로는 마롱이랑 이야기할 수 없어', '/'],
      ['no_dm', '디스코드 DM에서 마롱이한테 먼저 말 걸어 줘', '/']]) {
      site.state.me = { status: 403, code };
      const { context, page } = await openChat();
      await page.waitForFunction((t) => document.getElementById('state-title').textContent === t, title);
      assert.equal(await page.isHidden('#composer'), true);
      assert.equal(await page.isHidden('#log'), true);
      assert.equal(await page.getAttribute('#state-link', 'href'), link);
      assert.equal(await page.textContent('#state-link'), '통화 화면으로');
      await shot(page, `chat-${code}`);
      await context.close();
    }

    site.state.me = { status: 401, code: 'unauthenticated' };
    let loads = 0;
    const signIn = await openChat();
    signIn.page.on('load', () => { loads++; });
    await signIn.page.waitForFunction(() => document.getElementById('state-title').textContent === '다시 들어와 줘');
    assert.equal(loads, 1, 'one reload to go through Access, then the state');
    assert.equal(await signIn.page.textContent('#state-retry'), '다시 들어가기');
    await signIn.context.close();

    site.state.me = { status: 500, code: 'internal' };
    const broken = await openChat();
    await broken.page.waitForFunction(() => document.getElementById('state-title').textContent === '잠깐 문제가 생겼어');
    assert.equal(await broken.page.textContent('#state-text'), '조금 있다가 다시 해 볼래? (0123456789abcdef)');
    site.state.me = { status: 200, body: ME };
    await broken.page.click('#state-retry');
    await ready(broken.page);
    await broken.context.close();
  });

  // Picture topics (docs/04-functional-spec/call-first.md SPEC-273, SPEC-274; SCR-107#picture, #picture-loading,
  // #picture-missing, #hello). A face WebP stands in for the set's pictures.
  function pictures() {
    reset();
    const stand = path.join(__dirname, '..', '..', '..', 'marong', 'call', 'static', 'face', 'v1', '05-excited.webp');
    site.state.pictures = { '/chat/topics/v1/winter-hat.webp': stand, '/chat/topics/v1/chicken-skewer.webp': stand };
    const list = site.state.messages;
    Object.assign(list[30], { from: 'marong', kind: 'proactive', text: '나 털모자 샀다!\n\n어울려?',
      picture: { src: '/chat/topics/v1/winter-hat.webp', alt: '털모자를 쓴 마롱이' } });
    Object.assign(list[31], { from: 'marong', kind: 'proactive', text: '그림이 없어진 말',
      picture: { src: '/chat/topics/v1/no-such-picture.webp', alt: '없는 그림' } });
    Object.assign(list[32], { from: 'marong', kind: 'proactive', text: '바깥 주소의 그림',
      picture: { src: 'https://example.test/x.webp', alt: '바깥' } });
    Object.assign(list[34], { from: 'marong', kind: 'hello', text: '전화했는데 바빴나 봐!\n\n닭꼬치 먹는 중이야\n\n넌 뭐 먹었어?',
      picture: { src: '/chat/topics/v1/chicken-skewer.webp', alt: '닭꼬치를 든 마롱이' } });
  }

  it('SCR-107#picture, #hello: the picture above her words, its text, the tags; a missing one leaves the words', async () => {
    pictures();
    const { context, page, outside } = await openChat();
    await ready(page);
    await page.waitForFunction(() => document.querySelectorAll('.picture:not(.waiting)').length === 2);
    const hat = page.locator('li[data-id="31"] .picture');
    assert.equal(await hat.getAttribute('alt'), '털모자를 쓴 마롱이');
    const order = await page.$eval('li[data-id="31"] .body', (body) => [...body.children].map((c) => c.className));
    assert.deepEqual(order, ['picture', 'bubble', 'meta'], 'picture, then words, then tag and time');
    const box = await hat.boundingBox();
    assert.ok(Math.abs(box.width - 240) < 1 && Math.abs(box.height - 240) < 1, `picture ${box.width}x${box.height}`);
    assert.equal(await page.textContent('li[data-id="31"] .tag'), '먼저 톡');
    assert.equal(await page.textContent('li[data-id="35"] .tag'), '먼저 건 전화');
    assert.equal(await page.locator('li[data-id="35"] .picture').getAttribute('alt'), '닭꼬치를 든 마롱이');
    assert.equal(await page.locator('li[data-id="32"] .picture').count(), 0, 'a picture that cannot come is gone');
    assert.equal(await page.textContent('li[data-id="32"] .bubble'), '그림이 없어진 말', 'and its words stay');
    assert.equal(await page.locator('li[data-id="33"] .picture').count(), 0, 'an address of another shape is never asked');
    assert.equal(await page.$$eval('.bubble img', (imgs) => imgs.length), 0, 'nothing inside the bubbles');
    assert.deepEqual(outside, [], 'no request leaves the site');
    await context.close();
  });

  it('SCR-107#picture-loading: an empty box of the same size while the picture comes, at 360 and 430 px, day and night', async () => {
    pictures();
    site.state.pictureDelayMs = 1200;
    for (const [width, height] of [[360, 740], [430, 932]]) {
      for (const [at, theme] of [[DAY, 'chestnut'], [NIGHT, 'night']]) {
        const { context, page } = await openChat({ at, device: { viewport: { width, height } } });
        await ready(page);
        const waiting = page.locator('li[data-id="31"] .picture.waiting');
        assert.equal(await waiting.count(), 1, 'waiting while it comes');
        const empty = await waiting.boundingBox();
        assert.ok(Math.abs(empty.width - 240) < 1 && Math.abs(empty.height - 240) < 1, `box ${empty.width}x${empty.height}`);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false, `${width}px`);
        await page.waitForFunction(() => !document.querySelector('li[data-id="31"] .picture').classList.contains('waiting'));
        const shown = await page.locator('li[data-id="31"] .picture').boundingBox();
        assert.ok(shown.x >= 0 && shown.x + shown.width <= width, `picture inside ${width}px`);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false, `${width}px`);
        await page.locator('li[data-id="35"]').scrollIntoViewIfNeeded();
        await shot(page, `chat-picture-${width}-${theme}`);
        await context.close();
      }
    }
  });

  it('TC-132: 52px send button and box, 44px header buttons, cream by day and night colors by night', async () => {
    reset();
    for (const [at, theme] of [[DAY, 'chestnut'], [NIGHT, 'night']]) {
      const { context, page } = await openChat({ at });
      await ready(page);
      assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), theme);
      const send = await page.locator('#send').boundingBox();
      const text = await page.locator('#text').boundingBox();
      assert.ok(send.height >= 52 && text.height >= 52, `send ${send.height}px, box ${text.height}px`);
      for (const selector of ['.actions a', '#menu-button']) {
        const b = await page.locator(selector).boundingBox();
        assert.ok(b.width >= 44 && b.height >= 44, `${selector} ${b.width}x${b.height}`);
      }
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      assert.equal(overflow, false, 'no sideways scroll at phone width');
      await shot(page, `chat-${theme}`);
      await context.close();
    }
  });

  it('TC-123: a hidden screen stops waiting and waits again once shown', async () => {
    reset();
    const { context, page } = await openChat();
    await ready(page);
    for (let i = 0; i < 20 && site.state.openWaits !== 1; i++) await page.waitForTimeout(50);
    assert.equal(site.state.openWaits, 1);
    const hide = (state) => page.evaluate((s) => {
      Object.defineProperty(document, 'visibilityState', { value: s, configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
    }, state);
    await hide('hidden');
    for (let i = 0; i < 20 && site.state.openWaits !== 0; i++) await page.waitForTimeout(50);
    assert.equal(site.state.openWaits, 0, 'the wait was given up');
    const count = site.state.waits.length;
    await page.waitForTimeout(2000);
    assert.equal(site.state.waits.length, count, 'no wait while hidden');
    await hide('visible');
    for (let i = 0; i < 20 && site.state.openWaits !== 1; i++) await page.waitForTimeout(50);
    assert.equal(site.state.openWaits, 1, 'waiting again');
    await context.close();
  });

  it('SCR-109: where notifications go, the settings button only in an app that can open them, the ring line', async () => {
    reset();
    site.state.me = { status: 200, body: { ...ME, delivery: { to: 'discord', reason: 'notifications_off' },
      ring: { to: 'app', reason: 'app_on', fullScreen: false } } };
    const plain = await openChat();
    await ready(plain.page);
    await plain.page.click('#menu-button');
    await plain.page.waitForSelector('#menu:not([hidden])');
    assert.equal(await plain.page.textContent('#menu-delivery'), '알림이 꺼져 있어서 디스코드 DM으로 받고 있어.');
    assert.equal(await plain.page.isHidden('#menu-settings'), true, 'no button without the app');
    // SPEC-140: a browser cannot ring, whatever the friend's phone does.
    assert.equal(await plain.page.textContent('#menu-ring'), '약속 전화 벨은 마롱이 앱에서 울려. 앱이 없으면 디스코드로 알려 줄게.');
    for (const id of ['#menu-ring-settings', '#menu-full-screen', '#menu-samsung']) {
      assert.equal(await plain.page.isHidden(id), true, `${id} only in the app`);
    }
    assert.equal(await plain.page.getAttribute('#menu-button', 'aria-expanded'), 'true');
    await plain.context.close();

    const inApp = await openChat({ init: 'window.__opened = 0; window.__marongApp = { openNotificationSettings() { window.__opened++; } };' });
    await ready(inApp.page);
    await inApp.page.click('#menu-button');
    await inApp.page.waitForSelector('#menu-settings:not([hidden])');
    await inApp.page.click('#menu-settings');
    assert.equal(await inApp.page.evaluate(() => window.__opened), 1);
    await shot(inApp.page, 'chat-menu');
    await inApp.context.close();

    site.state.me = { status: 200, body: ME };
    const off = await openChat();
    await ready(off.page);
    await off.page.click('#menu-button');
    await off.page.waitForSelector('#menu:not([hidden])');
    assert.equal(await off.page.isHidden('#menu-ring'), true, 'no ring line while rings are off on the server');
    assert.equal(await off.page.textContent('#menu-delivery'), '디스코드 DM으로 받고 있어. 알림은 마롱이 앱에서 받을 수 있어.');
    await off.context.close();
  });

  it('SPEC-140: in the app, the ring line with its settings buttons and the Samsung note', async () => {
    reset();
    const bridge = `window.__calls = [];
      window.__marongApp = {
        openNotificationSettings(channel) { window.__calls.push(['notifications', channel === undefined ? null : channel]); return true; },
        openFullScreenSettings() { window.__calls.push(['fullScreen']); return true; },
        deviceState() { return Promise.resolve({ samsung: true, fullScreenSettings: true }); },
      };`;
    site.state.me = { status: 200, body: { ...ME, delivery: { to: 'app', reason: 'app_on' },
      ring: { to: 'app', reason: 'app_on', fullScreen: false } } };
    const ringing = await openChat({ init: bridge, at: NIGHT });
    await ready(ringing.page);
    await ringing.page.click('#menu-button');
    await ringing.page.waitForSelector('#menu-samsung:not([hidden])');
    assert.equal(await ringing.page.textContent('#menu-ring'),
      '약속 전화는 이 폰이 울려. 잠금 화면에는 전체 화면 대신 위에 뜨는 알림으로 와.');
    assert.equal(await ringing.page.textContent('#menu-samsung'), "벨이 늦게 울리면 배터리 설정에서 마롱이를 '절전 예외 앱'에 넣어 줘.");
    assert.equal(await ringing.page.isHidden('#menu-ring-settings'), true);
    await ringing.page.click('#menu-full-screen');
    assert.deepEqual(await ringing.page.evaluate(() => window.__calls), [['fullScreen']]);
    const box = await ringing.page.locator('#menu-full-screen').boundingBox();
    assert.ok(box.height >= 44, `the button is ${box.height}px tall`);
    await shot(ringing.page, 'chat-menu-ring');
    await ringing.context.close();

    site.state.me = { status: 200, body: { ...ME, delivery: { to: 'app', reason: 'app_on' },
      ring: { to: 'discord', reason: 'ring_off', fullScreen: true } } };
    const channelOff = await openChat({ init: bridge });
    await ready(channelOff.page);
    await channelOff.page.click('#menu-button');
    await channelOff.page.waitForSelector('#menu-ring-settings:not([hidden])');
    assert.equal(await channelOff.page.textContent('#menu-ring'), '전화 알림이 꺼져 있어서 약속 전화는 디스코드 DM으로 통화하자고 보내.');
    assert.equal(await channelOff.page.isHidden('#menu-settings'), true, '선톡 still reach the phone');
    assert.equal(await channelOff.page.isHidden('#menu-samsung'), true, 'no ring on the phone, no Samsung note');
    await channelOff.page.click('#menu-ring-settings');
    assert.deepEqual(await channelOff.page.evaluate(() => window.__calls), [['notifications', 'ring']], 'the 마롱이 전화 channel');
    await channelOff.context.close();

    site.state.me = { status: 200, body: { ...ME, delivery: { to: 'discord', reason: 'notifications_off' },
      ring: { to: 'discord', reason: 'notifications_off', fullScreen: true } } };
    const allOff = await openChat({ init: bridge });
    await ready(allOff.page);
    await allOff.page.click('#menu-button');
    await allOff.page.waitForSelector('#menu-settings:not([hidden])');
    assert.equal(await allOff.page.isHidden('#menu-ring-settings'), true, 'one button for one setting');
    await allOff.context.close();

    site.state.me = { status: 200, body: { ...ME, ring: { to: 'discord', reason: 'no_device', fullScreen: null } } };
    const noDevice = await openChat({ init: bridge });
    await ready(noDevice.page);
    await noDevice.page.click('#menu-button');
    await noDevice.page.waitForSelector('#menu:not([hidden])');
    assert.equal(await noDevice.page.textContent('#menu-ring'), '약속 전화는 디스코드 DM으로 통화하자고 보내.');
    for (const id of ['#menu-ring-settings', '#menu-full-screen', '#menu-samsung']) {
      assert.equal(await noDevice.page.isHidden(id), true, `${id} hidden`);
    }
    await noDevice.context.close();
  });

  it("SPEC-123 with the app's page script: the phone report, chat on screen, and the menu after a change", async () => {
    reset();
    site.state.devices = [];
    site.state.deviceStatus = 201;
    site.state.me = { status: 200, body: { ...ME, delivery: { to: 'app', reason: 'app_on' },
      ring: { to: 'app', reason: 'app_on', fullScreen: true } } };
    const INSTALL = '0f8fad5b-d9cb-469f-a165-70867728950e';
    // A stand-in for Capacitor's bridge, then the app's own page script, both at document start as in the app.
    const fake = `window.__native = []; window.__listeners = {};
      window.__state = { installId: '${INSTALL}', fid: 'fid_AAAAAAAAAAAAAAAAAAAA', notifications: 'granted', appVersion: '0.2.0',
        ring: { channel: 'enabled', fullScreen: 'granted' }, fullScreenSettings: true, samsung: false };
      window.Capacitor = {
        nativePromise(plugin, method, options) {
          window.__native.push([plugin, method, JSON.parse(JSON.stringify(options || {}))]);
          return Promise.resolve(plugin === 'MarongPush' && method === 'state' ? JSON.parse(JSON.stringify(window.__state)) : {});
        },
        addListener(plugin, event, callback) { (window.__listeners[plugin + '.' + event] ||= []).push(callback); return { remove() {} }; },
      };`;
    const context = await browser.newContext(PHONE);
    contexts.push(context);
    await context.addInitScript(fake);
    await context.addInitScript({ path: PAGE_SCRIPT });
    const page = await context.newPage();
    await page.goto(`${site.url}/chat/`);
    await ready(page);
    for (let i = 0; i < 40 && site.state.devices.length < 1; i++) await page.waitForTimeout(50);
    assert.equal(site.state.devices.length, 1, 'one report');
    assert.deepEqual(site.state.devices[0], { installId: INSTALL, origin: site.url, type: 'application/json',
      body: { fid: 'fid_AAAAAAAAAAAAAAAAAAAA', notifications: 'granted', appVersion: '0.2.0', ring: { channel: 'enabled', fullScreen: 'granted' } } });
    const visible = await page.evaluate(() => window.__native.filter(([p, m]) => p === 'MarongPush' && m === 'chatVisible').map(([, , o]) => o.visible));
    assert.deepEqual(visible.slice(-1), [true], 'the chat is on screen');

    // The same phone a moment later: nothing to send.
    await page.reload();
    await ready(page);
    await page.waitForTimeout(300);
    assert.equal(site.state.devices.length, 1, 'unchanged, so no second report');

    // The menu is open when Android's settings change the ring: the page reports it and the menu follows.
    await page.click('#menu-button');
    await page.waitForSelector('#menu-ring:not([hidden])');
    assert.equal(await page.textContent('#menu-ring'), '약속 전화는 이 폰이 울려.');
    const asked = site.state.meCount;
    site.state.me = { status: 200, body: { ...ME, delivery: { to: 'app', reason: 'app_on' },
      ring: { to: 'discord', reason: 'ring_off', fullScreen: true } } };
    await page.evaluate(() => {
      window.__state.ring = { channel: 'disabled', fullScreen: 'granted' };
      for (const callback of window.__listeners['MarongPush.resumed'] || []) callback({});
    });
    for (let i = 0; i < 40 && site.state.devices.length < 2; i++) await page.waitForTimeout(50);
    assert.equal(site.state.devices.length, 2);
    assert.deepEqual(site.state.devices[1].body.ring, { channel: 'disabled', fullScreen: 'granted' });
    await page.waitForFunction(() => document.getElementById('menu-ring').textContent.startsWith('전화 알림이 꺼져'));
    assert.ok(site.state.meCount > asked, 'the menu asked the server again');

    // A new id from FCM is reported at once.
    await page.evaluate(() => {
      window.__state.fid = 'fid_BBBBBBBBBBBBBBBBBBBB';
      for (const callback of window.__listeners['MarongPush.registered'] || []) callback({});
    });
    for (let i = 0; i < 40 && site.state.devices.length < 3; i++) await page.waitForTimeout(50);
    assert.equal(site.state.devices[2].body.fid, 'fid_BBBBBBBBBBBBBBBBBBBB');

    // Hidden (screen off, another app): messages come as notifications again.
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    const last = await page.evaluate(() => window.__native.filter(([p, m]) => p === 'MarongPush' && m === 'chatVisible').at(-1)[2]);
    assert.deepEqual(last, { visible: false });
    await context.close();
  });
});
