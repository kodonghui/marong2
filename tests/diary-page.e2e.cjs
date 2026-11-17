'use strict';

const { after, before, describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');
const { startChatSite, ME } = require('../apps/android/test/support/chat-site.cjs');

const SITE = path.join(__dirname, '..', 'marong', 'app_chat_static', 'diary');
const FACES = path.join(__dirname, '..', 'marong', 'call', 'static', 'face', 'v1');
const API = '/chat/diary/api';
const DATE = '2026-11-17';
const DRAWING = '38a6277f-ab8e-4fc5-ae08-f83ebe169017';
const BODY = '오늘은 군밤을 먹고 이야기했다. 따뜻한 바람이 불었다. 이름도 모르는 작은 열매를 보았다. 다음에는 다른 길을 걸어 보고 싶다.';
const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; " +
  "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'";
const FILETYPES = { 'diary.js': 'text/javascript', 'sheets.js': 'text/javascript', 'diary.css': 'text/css',
  'tokens.css': 'text/css', 'Gaegu-Regular.woff2': 'font/woff2' };

function day(overrides = {}) {
  return { date: DATE, state: 'ready', prev: '2026-11-14', next: null, diary: {
    revision: 1, title: '군밤을 먹은 날', weather: 'cloudy', body: BODY, drawing: { id: DRAWING, kind: 'ai' },
    hidden: false, stampedAt: null, busy: null, fix: { left: 5, blocked: null },
    redraw: { left: 2, blocked: null, last: null }, ...overrides,
  } };
}

function server() {
  const instance = http.createServer((req, res) => {
    const name = new URL(req.url, 'http://127.0.0.1').pathname;
    let file, type;
    if (name === '/chat/diary/' || /^\/chat\/diary\/\d{4}-\d{2}-\d{2}$/.test(name)) {
      file = path.join(SITE, 'index.html');
      type = 'text/html; charset=utf-8';
    } else if (name.startsWith('/chat/diary/') && FILETYPES[path.basename(name)]) {
      const asset = path.basename(name);
      file = path.join(SITE, asset);
      type = FILETYPES[asset];
    } else if (/^\/face\/v1\/\d\d-[\w-]+\.webp$/.test(name) || name === `${API}/drawings/${DRAWING}`) {
      file = path.join(FACES, name.startsWith('/face') ? path.basename(name) : '02-big-laugh.webp');
      type = 'image/webp';
    }
    if (file && fs.existsSync(file)) {
      res.writeHead(200, { 'Content-Type': type, 'Content-Security-Policy': CSP, 'Cache-Control': 'no-store' });
      fs.createReadStream(file).pipe(res);
    } else {
      res.writeHead(404).end();
    }
  });
  return new Promise(resolve => instance.listen(0, '127.0.0.1', () => resolve(instance)));
}

describe('TC-172 diary page in Chromium with local fixtures', { timeout: 20000 }, () => {
  let browser, host, url;
  before(async () => {
    host = await server();
    url = `http://127.0.0.1:${host.address().port}`;
    browser = await chromium.launch();
  });
  after(async () => {
    await browser?.close();
    if (host) await new Promise(resolve => host.close(resolve));
  });

  async function open(t, width = 360, at = '2026-11-17T01:00:00Z', given = {}) {
    const state = { current: day(), visible: { date: DATE, enabled: true }, hidden: [], look: null, ...given };
    const errors = [], outside = [], calls = [];
    const context = await browser.newContext({ viewport: { width, height: 800 }, isMobile: true,
      hasTouch: true, deviceScaleFactor: 1, locale: 'ko-KR' });
    t.after(() => context.close());
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', req => { if (!req.url().startsWith(url)) outside.push(req.url()); });
    const respond = (route, json, status = 200, headers = {}) => route.fulfill({ status, json, headers });
    await page.route(`**${API}/**`, async route => {
      const req = route.request();
      const target = new URL(req.url());
      const dir = target.pathname.slice(API.length);
      const method = req.method();
      if (dir.startsWith('/drawings/')) {
        if (state.pictureBroken) return route.fulfill({ status: 404 });
        return route.continue();
      }
      calls.push([method, dir, req.postDataJSON(), req.headers()['idempotency-key']]);
      if (dir === '/latest') return respond(route, state.visible);
      if (dir === '/days') return respond(route, { days: [{ date: DATE, weather: 'sunny', stamped: true }] });
      if (dir === '/hidden') return respond(route, { items: state.hidden, nextBefore: null });
      if (dir === '/look') {
        if (method === 'PUT') state.look = req.postDataJSON();
        if (method === 'DELETE') {
          state.look = null;
          return route.fulfill({ status: 204 });
        }
        return respond(route, { look: state.look });
      }
      if (method === 'GET') {
        if (state.loadError) return respond(route, state.loadError, state.loadStatus);
        return respond(route, state.current);
      }
      if (dir.endsWith('/fixes')) {
        if (state.fixError) return respond(route, state.fixError, state.fixStatus, state.fixHeaders);
        const diary = state.current.diary;
        diary.revision++;
        diary.fix.left--;
        diary.title = '바꾼 제목';
        return respond(route, { sceneChanged: true, day: state.current });
      }
      if (dir.endsWith('/drawings')) {
        state.current.diary.busy = 'redraw';
        return respond(route, { day: state.current }, 202);
      }
      const change = req.postDataJSON();
      if (dir.endsWith('/weather')) {
        state.current.diary.weather = change.weather;
        state.current.diary.revision++;
      } else if (dir.endsWith('/stamp')) {
        state.current.diary.stampedAt = change.stamped ? '2026-11-17T12:00:00+09:00' : null;
      } else if (dir.endsWith('/hidden')) {
        state.current.diary.hidden = change.hidden;
        if (!change.hidden) state.hidden = [];
      }
      return respond(route, state.current);
    });
    await page.clock.install({ time: new Date(at) });
    await page.goto(`${url}/chat/diary/${state.address ?? DATE}`);
    return { page, state, calls, errors, outside };
  }

  async function screenshot(page, id) {
    const dir = process.env.MARONG_SCREENSHOTS;
    if (!dir) return;
    fs.mkdirSync(dir, { recursive: true });
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(dir, `diary-${id}.png`), fullPage: true });
  }

  for (const [width, at, theme, columns] of [
    [360, '2026-11-17T11:00:00Z', 'night', '10'], [430, '2026-11-16T22:59:58Z', 'night', '12'],
  ]) {
    it(`${width}px columns, theme, signed reads, and accessible content`, async t => {
      const { page, errors, outside } = await open(t, width, at);
      await page.getByRole('heading', { name: '군밤을 먹은 날' }).waitFor();
      assert.equal(await page.locator('html').getAttribute('data-theme'), theme);
      if (width === 430) {
        await page.clock.runFor(2500);
        assert.equal(await page.locator('html').getAttribute('data-theme'), 'chestnut');
      }
      const grid = page.locator('.manuscript');
      assert.equal(await grid.getAttribute('aria-hidden'), 'true');
      assert.equal(await grid.evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length), Number(columns));
      assert.equal(await page.locator('.readable').textContent(), BODY);
      assert.equal(await page.locator('.art').getAttribute('alt'), "마롱이가 그린 '군밤을 먹은 날' 그림");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
      assert.ok(await page.getByRole('button', { name: '달력' }).evaluate(el => el.clientHeight >= 44));
      assert.ok(await page.evaluate(async () => (await document.fonts.load('22px Gaegu')).length));
      assert.deepEqual(errors, []);
      assert.deepEqual(outside, []);
      await screenshot(page, `${width}-ready`);
    });
  }

  it('weather, stamp, hide, calendar, hidden and look sheets', async t => {
    const { page, state } = await open(t);
    await page.getByRole('button', { name: '마음 날씨, 구름' }).click();
    await page.getByRole('radio', { name: '비', exact: true }).click();
    await page.getByRole('button', { name: '마음 날씨, 비' }).waitFor();
    await page.getByRole('button', { name: '도장 찍어 주기' }).click();
    await page.getByRole('button', { name: '도장 빼기' }).waitFor();
    await screenshot(page, 'stamped');
    await page.getByRole('button', { name: '달력' }).click();
    await page.getByRole('button', { name: '11월 17일, 맑음, 도장' }).waitFor();
    assert.equal(await page.getByRole('button', { name: '뒷 달 ›' }).isDisabled(), true);
    assert.equal(await page.locator('.month-grid').evaluate(el => el.scrollWidth <= el.clientWidth), true);
    await screenshot(page, 'calendar');
    await page.goBack();
    assert.equal(await page.locator('dialog').isVisible(), false);
    await page.getByRole('button', { name: '더 보기', exact: true }).click();
    await page.getByRole('button', { name: '이 날 숨기기' }).click();
    await page.getByText('숨긴 일기야. 넘기기와 달력에는 안 보여').waitFor();
    state.hidden = [{ date: DATE, title: '군밤을 먹은 날' }];
    await page.getByRole('button', { name: '더 보기', exact: true }).click();
    await page.getByRole('button', { name: '숨긴 일기', exact: true }).click();
    await page.locator('dialog').getByRole('button', { name: '다시 보이게' }).click();
    await page.getByText('다시 보이게 했어').waitFor();
    await page.locator('dialog').getByRole('button', { name: '닫기' }).click();
    await page.getByRole('button', { name: '더 보기', exact: true }).click();
    await page.getByRole('button', { name: '내 모습 카드', exact: true }).click();
    await page.getByRole('radio', { name: '긴 머리' }).click();
    await page.getByRole('radio', { name: '동그란 안경' }).click();
    await page.getByRole('radio', { name: '남색' }).click();
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await page.getByText('다음 그림부터 이 모습으로 그릴게').waitFor();
    await page.getByRole('button', { name: '카드 비우기' }).click();
    await page.getByText('이제 그림에 너는 안 나와. 마롱이랑 물건·장소만 그릴게').waitFor();
  });

  it('preserves a failed draft, changes the scene and polls redraw', async t => {
    const { page, state, calls } = await open(t);
    await page.getByRole('button', { name: '말로 고치기 · 5번 남음' }).click();
    const text = page.locator('textarea');
    await text.fill('시험에서 나온 일을 고쳐 줘');
    await screenshot(page, 'fix');
    state.fixError = { code: 'fix_failed' };
    state.fixStatus = 503;
    await page.getByRole('button', { name: '고쳐 줘', exact: true }).click();
    await page.getByText('지금은 못 고쳤어. 조금 있다가 다시 해 볼래?').waitFor();
    assert.equal(await text.inputValue(), '시험에서 나온 일을 고쳐 줘');
    state.fixError = null;
    await page.getByRole('button', { name: '다시 보내기', exact: true }).click();
    await page.getByRole('heading', { name: '바꾼 제목' }).waitFor();
    await page.getByText('글이 바뀌어서 그림이랑 조금 다를 수 있어. 다시 그려 볼래?').waitFor();
    const fixes = calls.filter(call => call[1].endsWith('/fixes'));
    assert.equal(fixes.length, 2);
    assert.notEqual(fixes[0][3], fixes[1][3]);
    await page.getByRole('button', { name: '다시 그리기 · 2번 남음' }).click();
    await page.getByRole('button', { name: '다시 그려 줘', exact: true }).click();
    await page.getByText('마롱이가 다시 그리는 중이야').waitFor();
    state.current.diary.busy = null;
    state.current.diary.redraw = { left: 1, blocked: null, last: { result: 'done', at: '2026-11-17T21:00:00+09:00' } };
    await page.clock.runFor(2200);
    await page.getByText('새로 그렸어!', { exact: true }).waitFor();
  });

  it('retries a broken image and reloads after a 503', async t => {
    const { page, state } = await open(t, 360, undefined, { pictureBroken: true,
      loadError: { code: 'db_unavailable' }, loadStatus: 503 });
    await page.getByText('잠깐 문제가 생겼어. 조금 있다가 다시 해 줘').waitFor();
    state.loadError = null;
    await page.clock.runFor(5200);
    await page.getByRole('button', { name: '그림 다시 보기' }).waitFor();
    state.pictureBroken = false;
    await page.getByRole('button', { name: '그림 다시 보기' }).click();
    await page.locator('.art').waitFor();
    await page.getByText('AI가 그린 그림').waitFor();
  });

  it('shows the chat entry for either an enabled setting or a past diary', async t => {
    const site = await startChatSite();
    t.after(() => site.close());
    const context = await browser.newContext({ viewport: { width: 360, height: 800 } });
    t.after(() => context.close());
    const page = await context.newPage();
    site.state.me = { status: 200, body: ME };
    let state = { enabled: false, date: null };
    await page.route(`**${API}/latest`, route => route.fulfill({ status: 200, json: state }));
    const loading = () => page.waitForResponse(response => response.url().endsWith(`${API}/latest`));
    const link = page.getByRole('link', { name: '일기장' });
    await Promise.all([loading(), page.goto(`${site.url}/chat/`)]);
    assert.equal(await link.count(), 0);
    state = { enabled: false, date: DATE };
    await Promise.all([loading(), page.reload()]);
    assert.equal(await link.getAttribute('href'), '/chat/diary/');
    state = { enabled: true, date: null };
    await Promise.all([loading(), page.reload()]);
    await link.waitFor();
  });
});
