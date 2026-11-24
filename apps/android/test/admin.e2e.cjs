'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {test} = require('node:test');
const {startChatSite} = require('./support/chat-site.cjs');

let chromium;
try { ({chromium} = require('playwright')); } catch {}
const options = {skip: chromium ? false : 'Playwright is not installed'};
const root = '/chat/admin';
const date = '2026-11-24T05:00:00Z';
const name = '시험친구 가';
const usage = {day: '2026-11-24', units: 320, chatTurns: 12, callSeconds: 300, images: 1};
const defaults = {dailyUnits: 1000, callMonthlyUsd: '3.00'};
const fields = {mode: 'default', dailyUnits: null, callMonthlyUsd: null};
const baseMember = {name, friendId: 7, botName: '시험친구 가', sessions: 2, tickets: 0,
  lastSeenAt: date, limits: fields, effective: defaults, callMonthUsd: '1.23', usageToday: usage};
const members = {members: [
  baseMember, {...baseMember, friendId: 9, callMonthUsd: '0.40', limits: {...fields, mode: 'unlimited'}},
  {...baseMember, friendId: 2, name: '시험친구 나', callMonthUsd: null,
    limits: {...fields, mode: 'custom', dailyUnits: 200}},
], unlinked: [{friendId: 12, name: '시험친구 다'}], defaults};
const latest = {versionName: '0.3.3', versionCode: 11, publishedAt: date};
const device = {friend: name, friendId: 7, phone: 1, appVersion: '0.3.2', behind: true, seenAt: date,
  notifications: 'denied', events: [{kind: 'state', state: 'needs_confirm', at: date},
    {kind: 'state', state: 'downloaded', at: '2026-11-24T04:59:00Z'}]};
const versions = {latest, paused: false, devices: [
  device, {...device, phone: 2, appVersion: '0.3.3', behind: false, events: []},
  {...device, friendId: 9, appVersion: '0.3.1', behind: false, events: [{kind: 'foo', at: date}]},
], releases: [
  {kind: 'published', at: date, versionName: '0.3.3', versionCode: 11, notes: '시험 노트', backfilled: false},
  {kind: 'published', at: '2026-11-21T05:00:00Z', versionName: '0.3.2', versionCode: 10, backfilled: true},
], fetches: [{friend: name, friendId: 7, items: [{versionCode: 11, at: date}]}]};
const removedAt = '2026-11-22T09:14:00Z';
const activePhone = {...device, removedAt: null, notifications: 'granted', events: []};
const removedPhone = {...activePhone, phone: 2, appVersion: '0.2.4', behind: false, removedAt,
  seenAt: '2026-11-21T12:40:00Z', events: [{kind: 'push_failed', versionCode: 11, status: 410, attempt: 1, at: removedAt}]};
const overview = {members: {count: 3, unlinked: 1}, usageToday: usage,
  app: {latest, paused: false, devices: 2, behind: 1},
  callMonth: {month: '2026-11', spentUsd: '121.40', budgetUsd: '150.00', percent: 80, state: 'warn'},
  images: {month: '2026-11', totalUsd: '3.60', budgetPercent: 85}, attention: [
    {kind: 'call_budget', level: 'warn', value: 80, target: root + '/costs'},
    {kind: 'app_behind', level: 'danger', value: 1, target: root + '/app'},
    {kind: 'unlinked_friend', level: 'warn', value: 1, target: root + '/members'},
  ]};
const costs = {month: '2026-11', byKind: {diary: 2, topic: .5, reaction: .1, character: 3},
  budgets: {character: {usedUsd: 3, limitUsd: 20, ratio: .15}, diary: null}};
const invite = {id: 1, kind: 'join', note: '시험 메모', state: 'open', createdAt: date,
  expiresAt: '2026-11-28T05:00:00Z', usedAt: null, revokedAt: null, usedBy: null};
const inviteRows = [invite, {...invite, id: 2, state: 'used', usedAt: date, usedBy: {name, friendId: 7}},
  {...invite, id: 3, state: 'expired'}, {...invite, id: 4, state: 'revoked', revokedAt: date}];
const items = {set: 'fixture', items: [{id: 'fixture-item', name, starter: false, state: 'listed',
  missing: [], owners: 3}]};
const fixture = {'/overview': overview, '/members': members, '/app-versions': versions,
  '/invites': {invites: inviteRows}, '/image-costs': costs, '/items': items};

async function open(t, viewport = {width: 430, height: 820}, launchOptions) {
  const site = await startChatSite();
  t.after(() => site.close());
  const browser = await chromium.launch(launchOptions);
  t.after(() => browser.close());
  const page = await browser.newPage({viewport, locale: 'ko-KR', timezoneId: 'Asia/Seoul'});
  const state = structuredClone(fixture);
  const seen = [], errors = [];
  let active = 0, maxActive = 0;
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/chat/admin/api/**', async route => {
    const req = route.request();
    const address = new URL(req.url()).pathname.slice((root + '/api').length);
    seen.push([req.method(), address]);
    active++;
    maxActive = Math.max(active, maxActive);
    try {
      const data = typeof state[address] === 'function' ? await state[address](req) : state[address];
      if (typeof data === 'number') {
        const code = {400: 'invalid_input', 403: 'not_allowed', 404: 'not_found', 409: 'invite_closed'}[data] || 'internal';
        active--;
        await route.fulfill({status: data, contentType: 'application/problem+json',
          json: {code, traceId: '0123456789abcdef'}});
      } else if (data?.contentType) {
        active--;
        await route.fulfill(data);
      } else {
        active--;
        await route.fulfill(data?.status === 204 ? {status: 204} : {status: data?.status || 200, json: data?.json || data});
      }
    } catch (error) {
      errors.push(error.message);
      await route.abort();
    }
  });
  async function visit(suffix = '/') {
    seen.length = 0;
    const address = site.url + root + suffix;
    if (address !== page.url() && address.split('#')[0] === page.url().split('#')[0]) {
      await page.goto('about:blank');
    }
    await page.goto(address);
    await page.locator('[aria-busy="false"]').first().waitFor();
  }
  return {page, state, site, visit, seen, errors, maxActive: () => maxActive};
}

test('TC-626 overview alerts, cards, partial failure, forbidden and stale reload', options, async t => {
  const {page, state, visit, seen, errors} = await open(t);
  await page.clock.install({time: new Date(date)});
  await visit();
  const content = page.locator('#admin');
  assert.equal(await content.locator('.admin-cards > a').count(), 5);
  assert.deepEqual(await content.locator('.admin-overview > section:first-child a').allTextContents(),
    ['●통화 월 예산 80% 썼어요', '●설치가 멈춘 폰 1대 · 확인 창 기다림이나 실패', '●아직 잇지 않은 기존 친구 1명']);
  assert.equal(await content.getByText('통화 월 예산 80% 썼어요').locator('..').getAttribute('href'), root + '/costs');
  await page.evaluate(() => {
    window.setFixtureVisibility = value => {
      Object.defineProperty(document, 'visibilityState', {configurable: true, value});
      document.dispatchEvent(new Event('visibilitychange'));
    };
    window.setFixtureVisibility('hidden');
  });
  await page.clock.fastForward(30_000);
  await page.evaluate(() => window.setFixtureVisibility('visible'));
  assert.deepEqual(seen, [['GET', '/overview']]);
  await page.evaluate(() => window.setFixtureVisibility('hidden'));
  await page.clock.fastForward(61_000);
  await page.evaluate(() => window.setFixtureVisibility('visible'));
  await page.locator('[aria-busy="false"]').waitFor();
  assert.equal(seen.length, 2);
  state['/overview'] = {...overview, attention: [], callMonth: null, app: {...overview.app, latest: null}};
  await visit();
  await content.getByText('지금 손볼 일 없어요').waitFor();
  assert.equal(await content.getByText('지금 못 불러왔어요').count(), 1);
  await content.getByText('아직 올린 버전이 없어요').waitFor();
  state['/overview'] = 500;
  await visit();
  await content.getByRole('button', {name: '다시 해 볼게요'}).waitFor();
  state['/overview'] = overview;
  await content.getByRole('button', {name: '다시 해 볼게요'}).click();
  await content.getByText('손볼 일').waitFor();
  state['/overview'] = 403;
  await visit();
  assert.equal(await page.locator('.admin-tabs').count(), 0);
  await page.getByText('관리자만 볼 수 있어요').waitFor();
  assert.deepEqual(errors, []);
});

test('TC-627–628 member links, edits, device limits and resize persistence', options, async t => {
  const {page, state, visit, seen, errors} = await open(t, {width: 1280, height: 820});
  await visit('/members');
  assert.equal(await page.locator('.admin-joined li').count(), 3);
  await page.getByText('한도 · 무제한', {exact: true}).waitFor();
  assert.equal(await page.getByRole('link', {name: '잇기 링크 만들기'}).getAttribute('href'), root + '/invites?kind=link&friend=12');
  await page.locator('.admin-joined a[href="/chat/admin/members/7"]').click();
  await page.locator('[aria-busy="false"]').waitFor();
  const current = page.locator('.admin-member-list a[aria-current="page"]');
  assert.equal(await current.getAttribute('href'), root + '/members/7');
  assert.equal(await page.locator('.admin-member-list li').count(), 3);
  assert.deepEqual(seen.slice(-2), [['GET', '/members'], ['GET', '/app-versions']]);
  assert.equal(await page.getByText('마지막 보고', {exact: false}).count(), 2);
  assert.equal(await page.getByRole('link', {name: '앱 버전에서 보기'}).getAttribute('href'), root + '/app#friend=7');

  state['/members/7/limits'] = request => {
    assert.deepEqual(request.postDataJSON(), {mode: 'unlimited'});
    return {limits: {...fields, mode: 'unlimited'}, effective: {dailyUnits: null, callMonthlyUsd: null}};
  };
  await page.getByRole('button', {name: '한도 바꾸기'}).click();
  await page.getByRole('button', {name: '직접 정하기'}).click();
  await page.getByLabel('하루 사용 단위').fill('777');
  const beforeResize = seen.length;
  await page.setViewportSize({width: 1000, height: 820});
  assert.equal(await current.isVisible(), false);
  await page.setViewportSize({width: 1280, height: 820});
  assert.equal(await page.getByLabel('하루 사용 단위').inputValue(), '777');
  assert.equal(seen.length, beforeResize);
  await page.getByRole('button', {name: '무제한', exact: true}).click();
  await page.getByRole('button', {name: '저장'}).click();
  await page.getByText('한도를 바꿨어요').waitFor();
  assert.match(await current.textContent(), /한도 · 무제한/);
  state['/members/7/tickets'] = request => {
    assert.equal(request.postDataJSON().add, 5);
    return {tickets: 5};
  };
  await page.getByRole('button', {name: '티켓 넣기'}).click();
  await page.getByLabel('티켓', {exact: true}).fill('5');
  await page.getByRole('button', {name: '넣기', exact: true}).click();
  await page.getByText('티켓을 넣었어요').waitFor();
  assert.match(await current.textContent(), /티켓 5장/);
  state['/members/7/revoke'] = {status: 204};
  await page.getByRole('button', {name: '로그인 끊기'}).click();
  await page.getByRole('button', {name: '그만두기'}).click();
  assert.equal(seen.filter(([, url]) => url.endsWith('/revoke')).length, 0);
  await page.getByRole('button', {name: '로그인 끊기'}).click();
  await page.getByRole('button', {name: '끊기', exact: true}).evaluate(button => { button.click(); button.click(); });
  await page.getByText('로그인 0개', {exact: false}).waitFor();
  assert.equal(seen.filter(([, url]) => url.endsWith('/revoke')).length, 1);
  await page.locator('.admin-member-list a[href="/chat/admin/members/9"]').click();
  await page.waitForURL('**/members/9');
  await visit('/members/999');
  await page.getByText('그 사람을 찾을 수 없어요').waitFor();
  assert.equal(await page.locator('.admin-member-list [aria-current]').count(), 0);

  state['/app-versions'] = {...versions, devices: Array.from({length: 20}, (_, n) => ({...device, phone: n + 1}))};
  await visit('/members/7');
  await page.getByText('최근 보고한 20대만 보여요').waitFor();
  state['/app-versions'].devices = Array.from({length: 200}, (_, n) => ({...device, friendId: 100 + n}));
  await visit('/members/7');
  await page.getByText('폰이 많아 일부만 보여요').waitFor();
  state['/app-versions'] = 503;
  await visit('/members/7');
  await page.getByText('지금 못 불러왔어요').waitFor();
  await page.getByRole('heading', {name: '한도', exact: true}).waitFor();
  state['/members'] = {...members, members: [], unlinked: []};
  await visit('/members');
  await page.getByText('아직 가입한 사람이 없어요').waitFor();
  state['/members'] = 500;
  await visit('/members');
  await page.getByRole('button', {name: '다시 해 볼게요'}).waitFor();
  assert.deepEqual(errors, []);
});

test('TC-629 and TC-636 invite filtering, prefills, creation and revocation', options, async t => {
  const {page, state, visit, site, seen, errors} = await open(t);
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await visit('/invites');
  const rows = page.locator('.admin-invites li');
  assert.equal(await rows.count(), 1);
  await page.getByRole('button', {name: '전체', exact: true}).click();
  assert.equal(await rows.count(), 4);
  await visit('/invites?kind=relogin&friend=2');
  assert.equal(await page.getByLabel('사람 고르기').inputValue(), '2');
  assert.equal(await page.getByRole('button', {name: '다시 로그인', exact: true}).getAttribute('aria-pressed'), 'true');
  await visit('/invites?kind=join&friend=2');
  await page.getByRole('button', {name: '새 링크 만들기'}).click();
  let createdStatus = 400;
  const address = site.url + '/chat/join/fixture';
  state['/invites'] = req => req.method() === 'GET' ? {invites: inviteRows}
    : createdStatus === 201 ? {status: 201, json: {url: address, expiresAt: invite.expiresAt}} : createdStatus;
  const submit = page.getByRole('button', {name: '만들기', exact: true});
  await submit.click();
  await page.getByText('입력을 확인해 주세요').waitFor();
  createdStatus = 404;
  await submit.click();
  await page.getByText('그 사람을 찾을 수 없어요. 목록을 다시 불러올게요').waitFor();
  createdStatus = 201;
  await submit.click();
  await page.getByText(address, {exact: true}).waitFor();
  assert.equal(await rows.getByText(address).count(), 0);
  await page.getByRole('button', {name: '복사', exact: true}).click();
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), address);

  const revoke = rows.first().getByRole('button', {name: '거두기', exact: true});
  state['/invites/1/revoke'] = {invite: {...invite, state: 'revoked', revokedAt: date}};
  await page.getByRole('button', {name: '전체', exact: true}).click();
  await revoke.click();
  await page.getByRole('button', {name: '그만두기'}).click();
  assert.equal(seen.filter(([, url]) => url.includes('/revoke')).length, 0);
  await revoke.click();
  await revoke.click();
  await page.getByText('링크를 거뒀어요', {exact: true}).waitFor();
  assert.match(await rows.first().innerText(), /거둠/);
  await visit('/invites');
  state['/invites/1/revoke'] = 409;
  await revoke.click();
  await revoke.click();
  await page.getByText('이미 쓰였거나 기간이 지난 링크예요').waitFor();
  state['/invites'] = {invites: []};
  await visit('/invites');
  await page.getByText('열린 초대 링크가 없어요').waitFor();
  await page.getByRole('button', {name: '전체 보기'}).click();
  await page.getByText('만든 초대 링크가 없어요').waitFor();
  assert.deepEqual(errors, []);
});

test('TC-630 and TC-634 app API only, record matching, caps, empty and literal text', options, async t => {
  const {page, state, visit, seen, errors} = await open(t);
  const plain = '<b>시험친구 가</b>';
  const note = '<img alt="시험">' + '가'.repeat(285);
  state['/app-versions'].devices.forEach(row => { row.friend = plain; });
  state['/app-versions'].releases[0].notes = note;
  await visit('/app#friend=7');
  assert.match(await page.locator('details[open]').innerText(), /확인 창 기다림.*지금 설치/s);
  assert.match(await page.locator('details[open]').innerText(), /받아 감 0\.3\.3\(11\)/);
  await page.getByText(note, {exact: true}).waitFor();
  assert.equal(await page.locator('.admin-note img').count(), 0);
  await page.getByText('기록에서 채움').waitFor();
  assert.equal(await page.locator('details').nth(2).locator('summary').innerText().then(line => line.includes(plain + '(9)')), true);
  await page.locator('details').nth(2).locator('summary').click();
  assert.match(await page.locator('details').nth(2).innerText(), /foo/);
  assert.doesNotMatch(await page.locator('details').nth(2).innerText(), /받아 감/);
  assert.deepEqual(seen, [['GET', '/app-versions']]);
  assert.equal(await page.getByRole('button').count(), 0);
  await visit('/app#friend=abc');
  assert.equal(await page.locator('details[open]').count(), 0);
  state['/app-versions'] = {...versions, paused: true, devices: [
    ...Array.from({length: 20}, (_, n) => ({...device, phone: n + 1})),
    ...Array.from({length: 180}, (_, n) => ({...device, friendId: 100 + n})),
  ], fetches: Array.from({length: 100}, (_, n) => ({friendId: 100 + n, items: []}))};
  await visit('/app');
  for (const text of ['업데이트 멈춤 중 · 폰이 새로 받지 않아요', '폰이 많아 200대까지만 보여요',
    '이 사람은 최근 보고한 20대만 보여요', '받아 간 사람이 많아 100명까지만 보여요']) await page.getByText(text).waitFor();
  state['/app-versions'] = {latest: null, paused: false, devices: [], releases: [], fetches: []};
  await visit('/app');
  await page.getByText('아직 올린 버전이 없어요').waitFor();
  await page.getByText('90일 안에 보고한 폰이 없어요').waitFor();
  state['/app-versions'] = 503;
  await visit('/app');
  await page.getByText('잠깐 문제가 생겼어요. 다시 해 볼까요?').waitFor();
  state['/invites'] = {invites: [{...invite, note: '<span>시험 메모</span>'}]};
  await visit('/invites');
  await page.getByText(/<span>시험 메모<\/span>/).waitFor();
  assert.equal(await page.locator('.admin-invites li p span').count(), 0);
  state['/members'].members[0].name = plain;
  await visit('/members');
  await page.getByText(new RegExp(plain)).first().waitFor();
  assert.deepEqual(errors, []);
});

test('TC-633 cost groups read sequentially and fail independently', options, async t => {
  const {page, state, visit, seen, errors, maxActive} = await open(t);
  const order = [['GET', '/overview'], ['GET', '/members'], ['GET', '/image-costs']];
  await visit('/costs');
  assert.deepEqual(seen, order);
  await page.getByText('80% 넘음').waitFor();
  const labels = await page.locator('.admin-costs section:nth-child(2) a').allTextContents();
  assert.deepEqual(labels, ['시험친구 가 · $1.23', '시험친구 가 · $0.40', '시험친구 나 · —']);
  state['/overview'].callMonth.percent = 101;
  state['/overview'].callMonth.state = 'exhausted';
  await visit('/costs');
  await page.getByText('다 씀', {exact: true}).waitFor();
  assert.equal(await page.getByRole('progressbar').getAttribute('value'), '100');
  state['/overview'].callMonth = null;
  state['/image-costs'] = 500;
  await visit('/costs');
  assert.deepEqual(seen, order);
  await page.locator('.admin-costs section').nth(0).getByText('지금 못 불러왔어요').waitFor();
  await page.locator('.admin-costs section').nth(2).getByRole('button', {name: '다시 해 볼게요'}).waitFor();
  await page.locator('.admin-costs section').nth(1).getByRole('link').first().click();
  await page.waitForURL('**/members/7');
  assert.equal(maxActive(), 1);
  assert.deepEqual(errors, []);
});

const sizes = [360, 430, 768, 1023, 1024, 1280, 1440];
const paths = ['/', '/members', '/members/7', '/invites', '/app#friend=7', '/costs', '/items'];

async function inspectLayout(page, width, suffix) {
  const capture = await page.evaluate(() => {
    const root = document.documentElement;
    const rect = element => element.getBoundingClientRect();
    const grids = [...document.querySelectorAll('#admin .admin-grid')];
    const cols = grids.map(grid => getComputedStyle(grid).gridTemplateColumns.split(' ').length);
    const overflow = grids.some(grid => [...grid.children].some(child => child.scrollWidth > child.clientWidth + 1));
    const tabs = document.querySelector('.admin-tabs');
    return {viewport: root.clientWidth, page: root.scrollWidth, main: rect(document.querySelector('main')).width,
      tabs: tabs.clientWidth, tabScroll: tabs.scrollWidth, cols, overflow,
      hitboxes: [...document.querySelectorAll('a, button, summary')]
        .filter(el => rect(el).height > 0).every(el => rect(el).height >= 44)};
  });
  assert.ok(capture.page <= width, JSON.stringify({suffix, width, ...capture}));
  assert.equal(capture.main, Math.min(width < 1024 ? 720 : 1200, capture.viewport - (width < 1024 ? 32 : 64)));
  assert.deepEqual(capture.cols, width < 1024 ? (suffix === '/items' ? [] : suffix === '/members/7' ? [1, 1] : [1])
    : ({'/': [2], '/members': [2], '/members/7': [2, 2], '/invites': [2], '/app': [2],
      '/app#friend=7': [2], '/costs': [3], '/items': []})[suffix]);
  assert.equal(capture.overflow, false, JSON.stringify({suffix, width, ...capture}));
  assert.equal(capture.hitboxes, true, JSON.stringify({suffix, width, ...capture}));
  if (width >= 1024) assert.equal(capture.tabs, capture.tabScroll);
}

test('TC-655 removed phones appear in app versions and member details', options, async t => {
  const {page, state, visit, errors} = await open(t);
  const rows = page.locator('details.admin-device');
  const memberPhones = page.locator('section').filter({has: page.getByRole('heading', {name: '이 사람의 폰', exact: true})});
  for (const [theme, time] of [['chestnut', date], ['night', '2026-11-24T13:30:00Z']]) {
    await page.clock.setFixedTime(new Date(time));
    for (const width of [360, 430, 1280]) {
      await page.setViewportSize({width, height: 820});
      state['/app-versions'] = {...versions, fetches: [], devices: [activePhone, removedPhone]};
      await visit('/app');
      assert.deepEqual(await rows.locator('summary > span:first-child').allTextContents(),
        [name + ' · 폰 1', name + ' · 폰 2']);
      const summary = rows.nth(1).locator('summary');
      assert.equal(await summary.getByText('0.2.4 · 앱 지워짐', {exact: true}).count(), 1);
      assert.equal(await summary.getByText('뒤처짐').count(), 0);
      const colorOf = element => getComputedStyle(element).color;
      assert.equal(await summary.getByText('0.2.4 · 앱 지워짐', {exact: true}).evaluate(colorOf),
        await summary.getByText(/^마지막 보고 /).evaluate(colorOf));
      await summary.click();
      const records = await rows.nth(1).locator('li').allTextContents();
      assert.equal(records[0], '앱 지워짐 · 11월 22일 오후 6:14');
      assert.equal(records[1], '보내기 실패(410) · 1번째 · 11월 22일 오후 6:14');
      assert.equal(await page.locator('html').getAttribute('data-theme'), theme);
      await inspectLayout(page, width, '/app');
      if (theme === 'chestnut' && width === 1280 && process.env.MARONG_ADMIN_SCREENSHOTS) {
        await page.screenshot({path: path.join(process.env.MARONG_ADMIN_SCREENSHOTS, 'app-removed.png')});
      }

      await visit('/members/7');
      await memberPhones.getByText('폰 2 · 0.2.4 · 앱 지워짐 · 마지막 보고 11월 21일 오후 9:40', {exact: true}).waitFor();
      await inspectLayout(page, width, '/members/7');

      state['/app-versions'] = versions;
      await visit('/app');
      assert.equal(await rows.getByText('앱 지워짐').count(), 0);
      assert.equal(await rows.getByText('뒤처짐').count(), 1);

      state['/app-versions'] = {...versions, devices: Array.from({length: 20}, (_, index) =>
        index === 1 ? removedPhone : {...activePhone, phone: index + 1})};
      await visit('/members/7');
      await memberPhones.getByText('최근 보고한 20대만 보여요', {exact: true}).waitFor();
      const phones = await memberPhones.getByText(/^폰 \d+ · /).allTextContents();
      assert.equal(phones.length, 20);
      assert.match(phones[1], /^폰 2 · 0\.2\.4 · 앱 지워짐 · /);
      await inspectLayout(page, width, '/members/7');
    }
  }
  assert.deepEqual(errors, []);
});

test('TC-659 overview, app versions and member details agree on phones behind', options, async t => {
  const {page, state, visit, errors} = await open(t);
  await page.clock.setFixedTime(new Date('2026-11-24T19:10:00Z'));
  const published = {...latest, publishedAt: '2026-11-23T13:10:00Z'};
  state['/members'].members.push({...baseMember, friendId: 8});
  state['/app-versions'] = {...versions, latest: published, devices: [
    activePhone, removedPhone, {...activePhone, phone: 3, appVersion: '0.3.3', behind: false},
    {...activePhone, friendId: 8, appVersion: '0.3.1'},
  ]};
  state['/overview'] = {...overview, app: {latest: published, paused: false, devices: 3, behind: 2},
    attention: [{kind: 'app_behind', level: 'warn', value: 2, target: root + '/app'}]};
  await visit();
  assert.equal(await page.getByText('최신 0.3.3 · 폰 3대 중 2대 뒤처짐', {exact: true}).count(), 1);
  assert.equal(await page.getByRole('link', {name: '새 버전을 아직 받지 못한 폰 2대', exact: true}).count(), 1);

  await visit('/app');
  const rows = page.locator('details.admin-device');
  assert.deepEqual(await rows.evaluateAll(elements => elements.map(element => element.dataset.phone)),
    ['7:1', '8:1', '7:3', '7:2']);
  assert.equal(await rows.getByText('뒤처짐').count(), 2);
  const memberPhones = page.locator('section').filter({has: page.getByRole('heading', {name: '이 사람의 폰', exact: true})});
  let behind = 0;
  for (const id of [7, 8]) {
    await visit('/members/' + id);
    await memberPhones.getByText(/^폰 1 · .* · 뒤처짐 · /).waitFor();
    behind += await memberPhones.getByText('뒤처짐').count();
  }
  assert.equal(behind, 2);
  assert.deepEqual(errors, []);
});

test('TC-656 items show the decor-off notice only for 404', options, async t => {
  const {page, state, visit, seen, errors} = await open(t);
  const screen = page.locator('#item-admin');
  for (const [theme, time] of [['chestnut', date], ['night', '2026-11-24T13:30:00Z']]) {
    await page.clock.setFixedTime(new Date(time));
    for (const width of [360, 430, 1280]) {
      await page.setViewportSize({width, height: 820});
      state['/items'] = 404;
      await visit('/items');
      assert.deepEqual(await screen.locator('#item-list > *').allTextContents(), ['꾸미기가 꺼져 있어요']);
      assert.equal(await screen.locator('#item-error').isVisible(), false);
      assert.equal(await screen.getByRole('button').count(), 0);
      assert.deepEqual(seen, [['GET', '/items']]);
      assert.equal(await page.locator('.admin-tabs [aria-current="page"]').innerText(), '아이템');
      assert.equal(await page.locator('html').getAttribute('data-theme'), theme);
      await inspectLayout(page, width, '/items');
      if (theme === 'chestnut' && width === 1280 && process.env.MARONG_ADMIN_SCREENSHOTS) {
        await page.screenshot({path: path.join(process.env.MARONG_ADMIN_SCREENSHOTS, 'decor-off.png')});
      }

      for (const status of [403, 500, 503]) {
        state['/items'] = status;
        await visit('/items');
        assert.match(await screen.locator('#item-error').innerText(), /아이템을 불러오지 못했어요.*0123456789abcdef/s);
        assert.equal(await screen.getByRole('button', {name: '다시 보기'}).count(), 1);
      }
      state['/items'] = {...items, items: []};
      await screen.getByRole('button', {name: '다시 보기'}).click();
      await screen.getByText('등록할 아이템이 없어요').waitFor();
      assert.equal(await screen.locator('#item-error').isVisible(), false);
      state['/items'] = items;
      await visit('/items');
      assert.equal(await screen.getByRole('heading', {name}).count(), 1);
    }
  }
  assert.deepEqual(errors, []);
});

test('TC-658 a non-Problem 404 also shows the decor-off notice', options, async t => {
  const {page, state, visit, seen, errors} = await open(t, {width: 360, height: 820});
  await page.clock.setFixedTime(new Date(date));
  state['/items'] = {status: 404, contentType: 'text/plain', body: 'Not Found'};
  await visit('/items');
  assert.deepEqual(await page.locator('#item-list > *').allTextContents(), ['꾸미기가 꺼져 있어요']);
  assert.equal(await page.locator('#item-error').isVisible(), false);
  assert.deepEqual(seen, [['GET', '/items']]);
  assert.deepEqual(errors, []);
});

test('TC-656 items keep retry for a failed request and for a request over 10 seconds', options, async t => {
  const {page, visit, errors} = await open(t, {width: 360, height: 820});
  const screen = page.locator('#item-admin');
  const retry = screen.getByRole('button', {name: '다시 보기'});
  const endpoint = '**/chat/admin/api/items';
  await page.clock.install({time: new Date(date)});
  await page.route(endpoint, route => route.abort(), {times: 1});
  await visit('/items');
  assert.equal(await screen.locator('#item-error').innerText(), '아이템을 불러오지 못했어요');

  let stalled;
  const requestStarted = new Promise(resolve => { stalled = resolve; });
  await page.route(endpoint, stalled, {times: 1});
  await retry.click();
  const route = await requestStarted;
  try {
    const failed = page.waitForEvent('requestfailed', request => request === route.request());
    await page.clock.fastForward(10_000);
    await failed;
  } finally {
    await route.abort();
  }
  assert.equal(await screen.locator('#item-error').innerText(), '아이템을 불러오지 못했어요');
  await retry.click();
  await screen.getByRole('heading', {name}).waitFor();
  assert.equal(await screen.locator('#item-error').isVisible(), false);
  assert.deepEqual(errors, []);
});

test('TC-637, TC-638, TC-640 and TC-641 layouts from 360px through 1440px', options, async t => {
  const {page, state, visit, errors} = await open(t);
  const screenshots = process.env.MARONG_ADMIN_SCREENSHOTS || fs.mkdtempSync(path.join(os.tmpdir(), 'marong-admin-'));
  fs.mkdirSync(screenshots, {recursive: true});
  state['/members'].members[0].name = '시험친구 가'.repeat(2);
  state['/app-versions'].devices = Array.from({length: 20}, (_, n) => ({...device, phone: n + 1}));
  state['/app-versions'].releases[0].notes = '가'.repeat(300);
  state['/invites'].invites[0].note = '가'.repeat(40);
  let checked = 0, images = 0;
  for (const [theme, time] of [['chestnut', date], ['night', '2026-11-24T13:30:00Z']]) {
    await page.clock.setFixedTime(new Date(time));
    for (const width of sizes) {
      await page.setViewportSize({width, height: 820});
      for (const [index, suffix] of paths.entries()) {
        await visit(suffix);
        if (suffix === '/invites') await page.getByRole('button', {name: '전체', exact: true}).click();
        await inspectLayout(page, width, suffix);
        assert.equal(await page.locator('html').getAttribute('data-theme'), theme);
        assert.equal(await page.locator('.admin-tabs [aria-current="page"]').count(), 1);
        if (suffix === '/items') assert.equal(await page.locator('.admin-tabs [aria-current]').innerText(), '아이템');
        if ([360, 430, 1280, 1440].includes(width)) {
          await page.evaluate(() => window.scrollTo(0, 0));
          await page.screenshot({path: path.join(screenshots, theme + '-' + width + '-' + index + '.png'), fullPage: true});
          images++;
        }
        checked++;
      }
    }
  }
  assert.deepEqual(errors, []);
  t.diagnostic(checked + ' layouts and ' + images + ' synthetic screenshots at ' + screenshots);
});

test('TC-640 keeps columns inside the viewport with visible scrollbars', options, async t => {
  const {page, visit} = await open(t, {width: 1024, height: 320}, {ignoreDefaultArgs: ['--hide-scrollbars']});
  for (const width of [1024, 1280]) {
    await page.setViewportSize({width, height: 320});
    for (const suffix of paths) {
      await visit(suffix);
      await inspectLayout(page, width, suffix);
    }
  }
  t.diagnostic('14 layouts with visible scrollbars');
});

test('TC-641 places loading and error states in the approved columns and keeps tab order', options, async t => {
  const {page, site, state, visit} = await open(t, {width: 1280, height: 820});
  const wait = Promise.withResolvers();
  state['/app-versions'] = async () => {
    await wait.promise;
    return versions;
  };
  await page.goto(site.url + root + '/app');
  await page.locator('.admin-app .admin-placeholder').first().waitFor();
  const columns = page.locator('.admin-app > section');
  assert.deepEqual(await Promise.all((await columns.all()).map(el => el.locator('.admin-placeholder').count())), [1, 2, 3]);
  const horizontal = async locator => (await locator.boundingBox()).x;
  const loadingX = await Promise.all((await columns.all()).map(horizontal));
  wait.resolve();
  await page.locator('[aria-busy="false"]').waitFor();
  assert.deepEqual(await Promise.all((await columns.all()).map(horizontal)), loadingX);
  state['/app-versions'] = 503;
  await visit('/members/7');
  const detail = page.locator('.admin-member-content > section');
  assert.deepEqual((await detail.locator('h2').allTextContents()).slice(1), ['한도', '오늘', '로그인', '이 사람의 폰']);
  await detail.last().getByText('지금 못 불러왔어요').waitFor();
  assert.ok(await horizontal(detail.nth(1)) < await horizontal(detail.nth(2)));
  assert.ok(await horizontal(detail.nth(3)) < await horizontal(detail.nth(4)));

  const order = async () => {
    const sequence = [];
    for (let i = 0; i < 24; i++) {
      await page.keyboard.press('Tab');
      const item = await page.evaluate(() => {
        const active = document.activeElement;
        return active === document.body ? null : {
          name: active.getAttribute('href') || active.textContent.trim(),
          sidebar: Boolean(active.closest('.admin-member-list')),
        };
      });
      if (!item) break;
      sequence.push(item);
    }
    return sequence;
  };
  const wide = await order();
  assert.equal(wide.filter(item => item.sidebar).length, 3);
  assert.ok(wide.slice(6, 9).every(item => item.sidebar));
  await page.setViewportSize({width: 360, height: 820});
  await visit('/members/7');
  const narrow = await order();
  assert.deepEqual(narrow, wide.filter(item => !item.sidebar));

  await page.setViewportSize({width: 1280, height: 820});
  await visit('/invites?kind=relogin&friend=2');
  const left = page.locator('.admin-invites > section').first();
  const right = page.locator('.admin-invites > section').last();
  assert.ok(await horizontal(left) < await horizontal(right));
  await left.getByLabel('사람 고르기').waitFor();
  await right.getByRole('button', {name: '거두기', exact: true}).click();
  await right.locator('li').first().getByText('이 링크를 거둬요. 받은 사람이 열어도 쓸 수 없어요').waitFor();
  assert.equal(await left.getByText('이 링크를 거둬요. 받은 사람이 열어도 쓸 수 없어요').count(), 0);
  t.diagnostic('loading columns, partial failure, narrow/wide focus order and confirmation placement checked');
});
