'use strict';

const assert = require('node:assert/strict');
const {test} = require('node:test');
const {startCallSite} = require('./support/call-site.cjs');
const {startChatSite} = require('./support/chat-site.cjs');

let chromium;
try { ({chromium} = require('playwright')); } catch {}
const options = {skip: chromium ? false : 'Playwright is not installed'};
const phone = {viewport: {width: 360, height: 820}, isMobile: true, hasTouch: true, locale: 'ko-KR'};
const now = '2026-11-21T14:59:00+09:00';
const month = {limited: true, percent: 40, resetsAt: '2026-12-01T00:00:00Z'};
const baseUsage = {day: '2026-11-21', units: 320, limit: 1000, chatTurns: 12, callSeconds: 480, images: 1, tickets: 0};
const profile = {botName: '시험 친구', features: {}, google: 'off'};

async function open(t, makeSite = startChatSite) {
  const site = await makeSite();
  t.after(() => site.close());
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage(phone);
  await page.clock.setFixedTime(new Date(now));
  return {site, page};
}

test('TC-508: usage limits, reset, and unavailable cost at 360px in both themes', options, async t => {
  const {site, page} = await open(t);
  let usage = {...baseUsage, callMonth: month};
  await page.route('**/chat/api/profile', route => route.fulfill({json: {...profile, usageToday: usage}}));
  await page.goto(site.url + '/chat/me');
  const card = page.locator('#usage');
  await card.getByText('40% 썼어 · 12월 1일 오전 9시에 다시 채워져').waitFor();
  assert.equal(await card.getByRole('progressbar').count(), 2);
  assert.equal(await card.getByText('오늘 320 / 1000').count(), 1);
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'chestnut');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.clock.setFixedTime(new Date('2026-11-21T22:00:00+09:00'));
  usage = {...baseUsage, limit: null, tickets: 3, callMonth: {...month, percent: 120}};
  await page.reload();
  await card.getByText('이번 달 통화를 다 썼어. 12월 1일 오전 9시에 다시 채워져').waitFor();
  assert.equal(await card.getByRole('progressbar').getAttribute('value'), '100');
  assert.equal(await card.getByText('하루 한도 · 무제한').count(), 1);
  assert.equal(await card.getByText('티켓 3장').count(), 1);
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'night');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);

  usage = {...baseUsage, callMonth: {...month, percent: null}};
  await page.reload();
  await card.getByText('이번 달 통화 양은 지금 못 불러왔어').waitFor();
  assert.equal(await card.getByRole('progressbar').count(), 1);
  usage = {...baseUsage, limit: null, callMonth: {limited: false, percent: null, resetsAt: null}};
  await page.reload();
  await card.getByText('이번 달 통화 · 무제한').waitFor();
  assert.equal(await card.getByRole('progressbar').count(), 0);
  assert.doesNotMatch(await card.textContent(), /티켓|\$/);
});

test('TC-508: daily limit call notice links to the profile', options, async t => {
  const {site, page} = await open(t, startCallSite);
  await page.route('**/status', route => route.fulfill({
    json: {ready: true, canCall: false, blockedReason: 'daily_limit'},
  }));
  await page.goto(site.url);
  const view = page.getByRole('link', {name: '내 사용량 보기'});
  await view.waitFor();
  assert.equal(await view.getAttribute('href'), '/chat/me');
});

test('TC-507: admin date labels and limit validation, edit, and persistence', options, async t => {
  const {site, page} = await open(t);
  const expires = '2026-11-28T14:59:00+09:00';
  const defaults = {dailyUnits: 1000, callMonthlyUsd: '3.00'};
  let member = {friendId: 17, name: '시험 회원', botName: '시험 친구', lastSeenAt: now, sessions: 1,
    tickets: 0, usageToday: baseUsage, limits: {mode: 'default', dailyUnits: null, callMonthlyUsd: null},
    effective: defaults, callMonthUsd: '1.23'};
  const common = {kind: 'join', note: '', createdAt: now, expiresAt: expires, usedAt: null, revokedAt: null, usedBy: null};
  await page.route('**/chat/admin/api/invites', route => route.request().method() === 'POST'
    ? route.fulfill({status: 201, json: {url: site.url + '/chat/join/fixture', expiresAt: expires}})
    : route.fulfill({json: {invites: [
      {id: 1, state: 'open', ...common},
      {id: 2, state: 'used', ...common, usedAt: '2026-11-21T15:01:00+09:00', usedBy: {name: '시험 회원'}},
      {id: 3, state: 'expired', ...common, createdAt: '2025-11-12T19:16:00+09:00', expiresAt: '2025-11-19T19:16:00+09:00'},
      {id: 4, state: 'revoked', ...common, revokedAt: '2026-11-21T15:03:00+09:00'},
    ]}}));
  await page.route('**/chat/admin/api/members', route => route.fulfill({
    json: {members: [member], defaults, unlinked: []},
  }));
  await page.route('**/chat/admin/api/members/17/limits', route => {
    assert.equal(route.request().method(), 'PUT');
    const payload = route.request().postDataJSON();
    if (payload.callMonthlyUsd === '1.234') return route.fulfill({status: 400, json: {code: 'invalid_input'}});
    assert.deepEqual(payload, {mode: 'custom', dailyUnits: 200, callMonthlyUsd: '5'});
    const limits = {...payload, callMonthlyUsd: '5.00'};
    const effective = {dailyUnits: limits.dailyUnits, callMonthlyUsd: limits.callMonthlyUsd};
    member = {...member, limits, effective};
    return route.fulfill({json: {limits, effective}});
  });
  await page.goto(site.url + '/chat/admin/invites');
  await page.getByRole('button', {name: '전체', exact: true}).click();
  await page.getByText('만든 때 11월 21일 오후 2:59 · 만료 11월 28일 오후 2:59(7일 남음)').waitFor();
  await page.getByText('만든 때 11월 21일 오후 2:59 · 쓴 때 11월 21일 오후 3:01').waitFor();
  await page.getByText('만든 때 2025년 11월 12일 오후 7:16 · 만료됨 2025년 11월 19일 오후 7:16').waitFor();
  await page.getByText('만든 때 11월 21일 오후 2:59 · 거둔 때 11월 21일 오후 3:03').waitFor();
  await page.getByRole('button', {name: '새 링크 만들기'}).click();
  await page.getByRole('button', {name: '만들기', exact: true}).click();
  await page.getByText('만료 11월 28일 오후 2:59(7일 뒤)', {exact: true}).waitFor();
  await page.goto(site.url + '/chat/admin/members');
  await page.getByText('기본 한도 · 하루 1000 · 통화 월 $3.00').waitFor();
  await page.locator('a[href="/chat/admin/members/17"]').click();
  await page.getByText('이번 달 통화 $1.23').waitFor();
  await page.getByRole('button', {name: '한도 바꾸기'}).click();
  assert.equal(await page.getByRole('button', {name: '기본 한도', exact: true}).getAttribute('aria-pressed'), 'true');
  await page.getByRole('button', {name: '직접 정하기'}).click();
  assert.equal(await page.getByRole('button', {name: '저장'}).isEnabled(), false);
  await page.getByLabel('하루 사용 단위').fill('200');
  await page.getByLabel('통화 월 달러').fill('1.234');
  await page.getByRole('button', {name: '저장'}).click();
  await page.getByText('숫자를 확인해 주세요(하루 1~100000, 통화 월 0.01~1000)').waitFor();
  assert.equal(await page.getByLabel('통화 월 달러').inputValue(), '1.234');
  await page.getByLabel('통화 월 달러').fill('5');
  await page.getByRole('button', {name: '저장'}).click();
  await page.getByText('한도를 바꿨어요').waitFor();
  await page.locator('.admin-member-content').getByText('한도 · 직접(하루 200 · 통화 월 $5.00)').waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
});
