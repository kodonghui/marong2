'use strict';

const {test} = require('node:test');
const assert = require('node:assert/strict');
let chromium;
try {
  ({chromium} = require('playwright'));
} catch {
  // Match the rest of the optional browser suite.
}
const options = {skip: chromium ? false : 'Playwright is not installed'};
const {startChatSite} = require('./support/chat-site.cjs');
const PHONE = {viewport: {width: 360, height: 820}, locale: 'ko-KR', isMobile: true, hasTouch: true};
const LAST_DAY = '2026-11-17T10:00:00+09:00';
const item = {id: 3, kind: 'fact', text: '장'.repeat(80), heardAt: LAST_DAY,
  channel: 'discord_dm', quote: '말'.repeat(120), scope: 'group', sensitive: true, validUntil: null};

async function open(t) {
  const site = await startChatSite();
  t.after(() => site.close());
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage(PHONE);
  return {page, site, url: site.url + '/chat/persona/memory'};
}

test('TC-346: mobile memory list, paging, confirmation, lost reply and idempotent retry', options, async t => {
  const {page, url} = await open(t);
  const keys = [];
  let removed = false;
  const requests = [];
  await page.route('**/chat/persona/api/memories**', route => {
    const before = new URL(route.request().url()).searchParams.get('before');
    requests.push(before);
    const body = removed ? {items: [], loops: [], hasMore: false}
      : before ? {items: [{...item, id: 2, kind: 'event', text: '가상 일정'}], loops: [], hasMore: false}
        : {items: [item], loops: [{id: 4, text: '시험 열린 고리', heardAt: LAST_DAY, due: '2026-11-20', channel: 'app'}],
          hasMore: true};
    return route.fulfill({json: body});
  });
  await page.route('**/chat/persona/api/forgets', route => {
    keys.push(route.request().headers()['idempotency-key']);
    assert.deepEqual(route.request().postDataJSON(), {type: 'item', id: 3});
    if (keys.length === 1) return route.abort('connectionreset');
    removed = true;
    return route.fulfill({json: {forgot: 2, messages: 1}});
  });
  await page.goto(url);
  await page.getByText(item.text, {exact: true}).waitFor();
  await page.getByRole('button', {name: '들은 말 보기'}).click();
  assert.equal(await page.getByText(item.quote, {exact: true}).isVisible(), true);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.getByRole('button', {name: '더 보기'}).click();
  await page.getByText('가상 일정').waitFor();
  assert.deepEqual(requests, [null, '3']);

  const rows = page.locator('.memory-row');
  await rows.filter({hasText: '시험 열린 고리'}).getByRole('button', {name: '잊기', exact: true}).click();
  await page.locator('#memory-confirm').getByRole('button', {name: '그만'}).click();
  assert.equal(await page.locator('#memory-confirm').count(), 0);

  await rows.filter({hasText: item.text}).getByRole('button', {name: '잊기', exact: true}).click();
  await page.locator('#memory-confirm').getByRole('button', {name: '잊기', exact: true}).click();
  await page.locator('#memory-confirm').getByRole('button', {name: '다시 해 볼게'}).click();
  await page.getByRole('status').getByText('잊었어 · 기억 2개, 들은 말 1개').waitFor();
  await page.getByText(/아직 따로 적어 둔 건 없어/).waitFor();
  assert.match(keys[0], /^[\da-f-]{36}$/);
  assert.deepEqual(keys, [keys[0], keys[0]]);
  assert.equal(requests.at(-1), null);
});

test('TC-346: loading, feature off, permissions, and recoverable response states', options, async t => {
  const {page, url} = await open(t);
  let release;
  const held = new Promise(resolve => { release = resolve; });
  let outcome = {status: 403, json: {code: 'feature_off'}};
  await page.route('**/chat/persona/api/memories', async route => {
    await held;
    return route.fulfill(outcome);
  });
  await page.goto(url);
  await page.locator('#memory-skeleton').waitFor();
  release();
  await page.getByText('이건 아직 준비 중이야').waitFor();
  assert.equal(await page.getByRole('link', {name: '친구 약속으로'}).getAttribute('href'), '/chat/persona/');

  outcome = {status: 403, json: {code: 'not_allowed'}};
  await page.reload();
  await page.getByText('이 계정으로는 열 수 없어').waitFor();
  assert.equal(await page.getByRole('link', {name: '글 대화로'}).getAttribute('href'), '/chat/');

  outcome = {status: 503, json: {code: 'db_unavailable', traceId: 'trace-fixture'}};
  await page.reload();
  await page.getByText('잠깐 문제가 생겼어. 조금 있다가 다시 해 줘').waitFor();
  assert.equal(await page.getByText('trace-fixture').isVisible(), true);
  outcome = {status: 200, json: {items: [], loops: [], hasMore: false}};
  await page.getByRole('button', {name: '다시 해 볼게'}).click();
  await page.getByText(/아직 따로 적어 둔 건 없어/).waitFor();
});
