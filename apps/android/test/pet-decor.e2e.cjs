'use strict';

const assert = require('node:assert/strict');
const {readFile} = require('node:fs/promises');
const path = require('node:path');
const {test} = require('node:test');
const {performance} = require('node:perf_hooks');
const {startCallSite} = require('./support/call-site.cjs');

let chromium;
try { ({chromium} = require('playwright')); } catch {}

const BASE = 'http://127.0.0.1:41798';
const STATIC = path.join(__dirname, '..', '..', '..', 'marong', 'app_chat_static');
const BLANK = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aLhcAAAAASUVORK5CYII=', 'base64');

test('TC-548: call portrait layers draw in order and a missing asset leaves the rest visible', {skip: !chromium}, async () => {
  const site = await startCallSite();
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({viewport: {width: 360, height: 780}, isMobile: true});
    const source = id => '/chat/decor/v1/' + id + '/dog_small.png';
    const body = source('blue-top'), neck = source('lost-scarf'), head = source('berry-beanie');
    await page.route('**/chat/api/profile', route => route.fulfill({json: {
      botName: '콩이', character: {id: 9, outfit: {body: {layerUrl: body}, neck: {layerUrl: neck}, head: {layerUrl: head}}},
    }}));
    await page.route('**/chat/decor/**', route => new URL(route.request().url()).pathname === neck
      ? route.fulfill({status: 404}) : route.fulfill({contentType: 'image/png', body: BLANK}));
    await page.goto(site.url);
    await page.locator(`.outfit-layer[src="${head}"]`).waitFor();
    await page.waitForFunction(() => document.querySelectorAll('.outfit-layer').length === 2);
    const layers = await page.locator('.outfit-layer').evaluateAll(images => images.map(image => image.getAttribute('src')));
    assert.deepEqual(layers, [body, head]);
    assert.equal(await page.locator('#face').isVisible(), true);
  } finally {
    await browser.close();
    await site.close();
  }
});

test('TC-546/548: claim an item, wear it, and display its layer at 360 px', {skip: !chromium}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({viewport: {width: 360, height: 780}, isMobile: true});
    const hat = {id: 'berry-beanie', kind: 'hat', slot: 'head', name: '딸기 털모자',
                 priceKrw: 0, thumbUrl: '/chat/decor/v1/berry-beanie/thumb.webp', owned: false};
    const outfit = {head: null, body: null, neck: null};
    const character = {id: 9, name: '콩이', kind: 'dog', template: 'dog_small', outfit};
    const layer = '/chat/decor/v1/berry-beanie/dog_small.png';
    let picked;
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      assert.equal(url.origin, BASE);
      const address = url.pathname;
      if (address === '/chat/api/profile') return route.fulfill({json: {character}});
      if (address === '/chat/api/shop') return route.fulfill({json: {items: [hat]}});
      if (address === '/chat/api/closet') {
        return route.fulfill({json: {characterId: 9, outfit, items: hat.owned ? [hat] : []}});
      }
      if (address.endsWith('/claim')) {
        hat.owned = true;
        return route.fulfill({status: 201, json: {itemId: hat.id, owned: true}});
      }
      if (address.endsWith('/outfit')) {
        picked = route.request().postDataJSON();
        outfit.head = picked.head ? {id: hat.id, name: hat.name, layerUrl: layer} : null;
        return route.fulfill({json: outfit});
      }
      if (address.includes('/images/') || address.startsWith('/chat/decor/')) {
        return route.fulfill({contentType: 'image/png', body: BLANK});
      }
      const file = ['/chat/shop', '/chat/closet'].includes(address) ? 'decor.html' : path.basename(address);
      if (!['decor.html', 'decor.js', 'chat.css', 'unified.css', 'unified.js'].includes(file)) {
        return route.fulfill({status: 404});
      }
      const type = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : 'text/html';
      return route.fulfill({contentType: type + '; charset=utf-8', body: await readFile(path.join(STATIC, file))});
    });

    await page.clock.setFixedTime(new Date('2026-11-21T03:00:00Z'));
    await page.goto(BASE + '/chat/shop');
    await page.getByText('0원', {exact: true}).waitFor();
    await page.getByRole('link', {name: '아이템 보기'}).click();
    await page.locator(`.decor-layer[src="${layer}"]`).waitFor();
    await page.getByRole('button', {name: '받기', exact: true}).click();
    const received = page.getByRole('button', {name: '받았어'});
    await received.waitFor();
    assert.equal(await received.isDisabled(), true);
    await page.getByRole('link', {name: '보관함'}).click();
    await page.getByLabel('머리').selectOption(hat.id);
    await page.getByRole('button', {name: '이렇게 입을래'}).click();
    await page.locator(`.decor-layer[src="${layer}"]`).waitFor();
    assert.deepEqual(picked, {head: hat.id, body: null, neck: null});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 360);
    await page.clock.setFixedTime(new Date('2026-11-21T13:00:00Z'));
    await page.reload();
    await page.locator(`.decor-layer[src="${layer}"]`).waitFor();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'night');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 360);
  } finally {
    await browser.close();
  }
});

test('TC-535/551/553: diary writer and sticker editing at 360 and 430 px', {skip: !chromium}, async t => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({viewport: {width: 360, height: 780}, isMobile: true, hasTouch: true});
    const dates = ['2026-11-18', '2026-11-19', '2026-11-20'];
    const date = dates.at(-1);
    const imageUrl = '/chat/decor/v1/star-sticker/sticker.webp';
    const base = '/chat/diary/api/days/' + date;
    let saved = [];
    let styleMode = 'off';
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      assert.equal(url.origin, BASE);
      const address = url.pathname;
      const dayIndex = dates.findIndex(day => address === '/chat/diary/api/days/' + day);
      if (dayIndex !== -1) {
        const visibleDate = dates[dayIndex];
        return route.fulfill({json: {date: visibleDate, state: 'ready',
          prev: dates[dayIndex - 1] ?? null, next: dates[dayIndex + 1] ?? null, diary: {
          title: visibleDate === date ? '콩이 일기' : '일기 ' + visibleDate,
          body: '누나와 이야기를 나누고 하루를 마무리했다. '.repeat(3), revision: 1,
          weather: 'sunny', drawing: {kind: 'placeholder', id: null}, busy: null, hidden: false,
          stampedAt: null, fix: {left: 5, blocked: null}, redraw: {left: 2, blocked: null, last: null},
          writer: {id: 9, name: '콩이', kind: 'dog', active: false, faceUrl: '/chat/api/characters/9/images/smile'},
        }}});
      }
      if (address === base + '/stickers') {
        if (route.request().method() === 'PUT') saved = route.request().postDataJSON().stickers;
        return route.fulfill({json: {date, stickers: saved.map(sticker => ({...sticker, imageUrl}))}});
      }
      if (dates.some(day => address === '/chat/diary/api/days/' + day + '/stickers')) {
        return route.fulfill({json: {date: address.split('/').at(-2), stickers: []}});
      }
      if (address === '/chat/api/closet') {
        return route.fulfill({json: {items: [{kind: 'sticker', id: 'star-sticker', name: '별', thumbUrl: imageUrl}]}});
      }
      if (address === '/chat/diary/api/decor') {
        if (styleMode === 'off') return route.fulfill({status: 404, json: {code: 'not_found'}});
        if (styleMode === 'starter') return route.fulfill({json: {
          background: {id: 'starter-background', imageUrl: null},
          paper: {id: 'starter-paper', imageUrl: null, style: 'manuscript'},
          font: {id: 'starter-font', fontUrl: null, family: 'Gaegu'},
        }});
        return route.fulfill({json: {background: {imageUrl: '/chat/decor/v1/blue-background/bg.webp'},
          paper: {imageUrl: '/chat/decor/v1/ivory-paper/paper.webp'},
          font: {fontUrl: '/chat/decor/v1/poorstory-font/font.woff2'}}});
      }
      if (address === '/chat/diary/Gaegu-Regular.woff2') {
        return route.fulfill({contentType: 'font/woff2', body: await readFile(path.join(STATIC, 'diary', 'Gaegu-Regular.woff2'))});
      }
      if (address.endsWith('/font.woff2')) {
        const font = path.join(STATIC, '..', 'decor', 'v1', 'poorstory-font', 'font.woff2');
        return route.fulfill({contentType: 'font/woff2', body: await readFile(font)});
      }
      if (address.includes('/images/') || address.startsWith('/chat/decor/') || address.startsWith('/face/')) {
        return route.fulfill({contentType: 'image/png', body: BLANK});
      }
      const file = address === '/chat/diary/' + date ? 'index.html' : path.basename(address);
      if (!['index.html', 'diary.js', 'decor.js', 'tokens.css', 'diary.css', 'sheets.js'].includes(file)) {
        return route.fulfill({status: 404});
      }
      const type = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : 'text/html';
      return route.fulfill({contentType: type + '; charset=utf-8', body: await readFile(path.join(STATIC, 'diary', file))});
    });
    await page.clock.setFixedTime(new Date('2026-11-21T03:00:00Z'));
    const started = performance.now();
    await page.goto(BASE + '/chat/diary/' + date);
    await page.getByRole('heading', {name: '콩이 일기'}).waitFor();
    t.diagnostic('First diary content in routed Chromium: ' + Math.round(performance.now() - started) + ' ms');
    await page.evaluate(() => document.fonts.ready);
    const baseline = await page.locator('.paper').screenshot({animations: 'disabled'});
    styleMode = 'starter';
    await page.reload();
    await page.getByRole('button', {name: '스티커', exact: true}).waitFor();
    await page.evaluate(() => document.fonts.ready);
    const starter = await page.locator('.paper').screenshot({animations: 'disabled'});
    assert.deepEqual(starter, baseline, 'the diary card with starter decor matches the disabled feature');
    styleMode = 'custom';
    await page.reload();
    await page.getByText('오늘은 그림을 못 그렸어요').waitFor();
    assert.equal(await page.getByRole('button', {name: /다시 그리기/}).count(), 0);
    const previousDay = page.locator('#pages button').first();
    const nextDay = page.locator('#pages button').last();
    async function expectSharedStyle(title) {
      await page.getByRole('heading', {name: title, exact: true}).waitFor();
      await page.locator('#day[style*="blue-background/bg.webp"]').waitFor();
      await page.locator('.paper[style*="ivory-paper/paper.webp"][style*="MarongDiary"]').waitFor();
    }
    await expectSharedStyle('콩이 일기');
    for (const previousDate of [dates[1], dates[0]]) {
      await previousDay.click();
      await expectSharedStyle('일기 ' + previousDate);
    }
    await nextDay.click();
    await nextDay.click();
    await expectSharedStyle('콩이 일기');
    await page.getByRole('button', {name: '스티커', exact: true}).click();
    await page.getByRole('button', {name: '별', exact: true}).click();
    await page.getByRole('button', {name: '다 했어', exact: true}).click();
    await page.locator('.paper .diary-sticker').waitFor();
    assert.deepEqual(saved, [{itemId: 'star-sticker', x: 500, y: 500, scale: 100, rotation: 0}]);
    await page.getByRole('button', {name: '스티커', exact: true}).click();
    const sticker = page.locator('.sticker-movable').first();
    const bounds = await sticker.boundingBox();
    const board = await page.locator('.paper').boundingBox();
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
    await page.mouse.down();
    await page.mouse.move(board.x - 20, bounds.y + bounds.height / 2, {steps: 4});
    await page.mouse.up();
    assert.equal(await sticker.evaluate(element => element.style.left), '0%');
    await page.getByRole('button', {name: '별', exact: true}).click();
    page.once('dialog', async dialog => {
      assert.equal(dialog.message(), '안 남기고 나갈까?');
      await dialog.accept();
    });
    await page.getByRole('button', {name: '그만둘래'}).click();
    await page.getByRole('heading', {name: '스티커 붙이기'}).waitFor({state: 'hidden'});
    assert.equal(saved.length, 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 360);

    await page.setViewportSize({width: 430, height: 850});
    await page.getByRole('button', {name: '스티커', exact: true}).click();
    await sticker.scrollIntoViewIfNeeded();
    const touchBounds = await sticker.boundingBox();
    const x = touchBounds.x + touchBounds.width / 2;
    const y = touchBounds.y + touchBounds.height / 2;
    const devtools = await page.context().newCDPSession(page);
    await devtools.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [
      {id: 1, x: x - 5, y},
      {id: 2, x: x + 5, y},
    ]});
    await devtools.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [
      {id: 1, x: x - 7, y: y - 6},
      {id: 2, x: x + 7, y: y + 6},
    ]});
    await devtools.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    await page.getByRole('button', {name: '다 했어', exact: true}).click();
    await page.locator('.paper .diary-sticker').waitFor();
    assert.equal(saved.length, 1);
    assert.ok(saved[0].scale >= 165 && saved[0].scale <= 200, 'the pinch enlarges the sticker');
    assert.ok(saved[0].rotation >= 30 && saved[0].rotation <= 50, 'the pinch rotates the sticker');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 430);
  } finally {
    await browser.close();
  }
});

test('TC-551: preview a new background, then restore and explicitly save defaults', {skip: !chromium}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({viewport: {width: 360, height: 780}, isMobile: true});
    const defaults = ['background', 'paper', 'font'].map(kind => ({
      id: 'starter-' + kind, kind, name: '처음 ' + kind, starter: true,
    }));
    const blue = {id: 'blue-background', kind: 'background', name: '파란 배경',
                  thumbUrl: '/chat/decor/v1/blue-background/thumb.webp'};
    let saved;
    await page.route('**/*', async route => {
      const address = new URL(route.request().url()).pathname;
      if (address === '/chat/api/profile') return route.fulfill({json: {character: null}});
      if (address === '/chat/api/closet') return route.fulfill({json: {items: [...defaults, blue]}});
      if (address === '/chat/diary/api/latest') return route.fulfill({json: {date: null}});
      if (address === '/chat/diary/api/decor') {
        if (route.request().method() === 'PUT') saved = route.request().postDataJSON();
        return route.fulfill({json: Object.fromEntries(defaults.map(item => [item.kind, {id: item.id}]))});
      }
      if (address.startsWith('/chat/decor/')) return route.fulfill({contentType: 'image/png', body: BLANK});
      if (address === '/chat/diary/') return route.fulfill({contentType: 'text/html', body: '<p>Diary</p>'});
      const files = {'/chat/diary/decor': 'decor.html', '/chat/diary/decor.js': 'diary/decor.js',
        '/chat/decor.js': 'decor.js', '/chat/unified.js': 'unified.js', '/chat/chat.css': 'chat.css',
        '/chat/unified.css': 'unified.css'};
      const file = files[address];
      if (!file) return route.fulfill({status: 404});
      const type = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : 'text/html';
      return route.fulfill({contentType: type + '; charset=utf-8', body: await readFile(path.join(STATIC, file))});
    });

    await page.goto(BASE + '/chat/diary/decor');
    await page.getByText('오늘은 산책을 했다…', {exact: true}).waitFor();
    await page.getByLabel('배경', {exact: true}).selectOption(blue.id);
    await page.locator('.decor-book-preview-frame[style*="blue-background/bg.webp"]').waitFor();
    await page.getByRole('button', {name: '처음 모습으로'}).click();
    assert.equal(await page.getByLabel('배경', {exact: true}).inputValue(), 'starter-background');
    assert.equal(saved, undefined);
    await page.getByRole('button', {name: '이걸로 할래'}).click();
    await page.waitForURL(BASE + '/chat/diary/');
    assert.deepEqual(saved, {backgroundId: 'starter-background', paperId: 'starter-paper', fontId: 'starter-font'});
  } finally {
    await browser.close();
  }
});

test('TC-543: show item validation, change listing, and recover after a forbidden read', {skip: !chromium}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({viewport: {width: 360, height: 780}, isMobile: true});
    const items = [
      {id: 'green-cap', kind: 'hat', name: '초록 모자', state: 'listed', owners: 2, missing: []},
      {id: 'blue-cap', kind: 'hat', name: '파란 모자', state: 'unlisted', owners: 1, missing: []},
      {id: 'broken-cap', kind: 'hat', name: '검사 중 모자', state: 'new', owners: 0, missing: ['layer:dog_long']},
    ];
    let permitted = true;
    await page.route('**/*', async route => {
      const address = new URL(route.request().url()).pathname;
      if (address === '/chat/admin/api/items') {
        return permitted ? route.fulfill({json: {items, set: 'v1'}})
          : route.fulfill({status: 403, json: {code: 'not_allowed'}});
      }
      if (address === '/chat/admin/api/items/blue-cap/list') {
        items[1].state = 'listed';
        return route.fulfill({json: items[1]});
      }
      const file = address === '/chat/admin/items' ? 'admin-items.html' : path.basename(address);
      if (!['admin-items.html', 'admin-items.js', 'chat.css', 'unified.css', 'unified.js'].includes(file)) {
        return route.fulfill({status: 404});
      }
      const type = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : 'text/html';
      return route.fulfill({contentType: type + '; charset=utf-8', body: await readFile(path.join(STATIC, file))});
    });
    await page.goto(BASE + '/chat/admin/items');
    const blue = page.getByRole('row').filter({hasText: '파란 모자'});
    assert.equal(await blue.getByText('blue-cap', {exact: true}).count(), 1);
    assert.equal(await blue.getByText('hat', {exact: true}).count(), 1);
    assert.equal(await blue.locator('img').getAttribute('src'), '/chat/decor/v1/blue-cap/thumb.webp');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    for (const label of ['썸네일', 'id', '종류', '이름', '상태', '받은 사람 수', '버튼']) {
      assert.equal(await page.getByRole('columnheader', {name: label, exact: true}).count(), 1);
    }
    const broken = page.getByRole('row').filter({hasText: '검사 중 모자'});
    await broken.getByText('확인할 항목 layer:dog_long').waitFor();
    assert.equal(await broken.getByRole('button', {name: '올리기'}).count(), 0);
    await blue.getByRole('button', {name: '올리기'}).click();
    await blue.getByRole('button', {name: '내리기'}).waitFor();

    permitted = false;
    await page.reload();
    await page.getByText('관리자만 볼 수 있어요').waitFor();
  } finally {
    await browser.close();
  }
});

async function itemAdminFixture(page, denied = false) {
  const items = [
    {id: 'green-cap', kind: 'hat', name: '초록 모자', state: 'listed', owners: 2, missing: [], starter: false},
    {id: 'blue-cap', kind: 'hat', name: '파란 모자', state: 'unlisted', owners: 1, missing: [], starter: false},
    {id: 'broken-cap', kind: 'hat', name: '검사 중 모자', state: 'new', owners: 0, missing: ['layer:dog_long'], starter: false},
  ];
  let writes = 0;
  await page.route('**/*', async route => {
    const address = new URL(route.request().url()).pathname;
    if (address === '/chat/admin/api/items') return denied
      ? route.fulfill({status: 403, json: {code: 'not_allowed'}})
      : route.fulfill({json: {items, set: 'v1'}});
    if (address === '/chat/admin/api/items/blue-cap/list') return route.fulfill({status: 409, json: {code: 'item_invalid', missing: ['license']}});
    if (address === '/chat/admin/api/items/green-cap/unlist') {
      writes++; items[0].state = 'unlisted'; return route.fulfill({json: items[0]});
    }
    const file = address === '/chat/admin/items' ? 'admin-items.html' : path.basename(address);
    if (!['admin-items.html', 'admin-items.js', 'chat.css', 'unified.css', 'unified.js'].includes(file)) return route.fulfill({status: 404});
    const type = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : 'text/html';
    let content = await readFile(path.join(STATIC, file), 'utf8');
    if (file === 'admin-items.html') content = content.replace('<!-- admin-tabs -->', '<nav class="admin-tabs"><a href="/chat/admin/items">아이템</a></nav>');
    return route.fulfill({contentType: type + '; charset=utf-8', body: content});
  });
  await page.goto(BASE + '/chat/admin/items');
  if (denied) await page.getByText('관리자만 볼 수 있어요').waitFor({timeout: 1500});
  else await page.locator('#item-admin[aria-busy="false"]').waitFor();
  return () => writes;
}

test('BUG-115 TC-543: state filter shows only matching items', {skip: !chromium}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage(); await itemAdminFixture(page);
    for (const [label, expected] of [['새것', ['검사 중 모자']], ['올림', ['초록 모자']], ['내림', ['파란 모자']], ['전체', ['초록 모자', '파란 모자', '검사 중 모자']]]) {
      await page.getByRole('button', {name: label, exact: true}).click({timeout: 1500});
      assert.deepEqual(await page.locator('tbody tr td:nth-child(4)').allTextContents(), expected);
    }
  } finally { await browser.close(); }
});

test('BUG-115 TC-543: unlisting requires confirmation', {skip: !chromium}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage(); const writes = await itemAdminFixture(page);
    const row = page.getByRole('row').filter({hasText: '초록 모자'});
    await row.getByRole('button', {name: '내리기'}).click();
    assert.equal(writes(), 0);
    assert.equal(await row.getByText('상점에서 내릴까요? 받은 사람은 계속 써요').count(), 1);
    await row.getByRole('button', {name: '취소'}).click();
    assert.equal(writes(), 0);
    await row.getByRole('button', {name: '내리기'}).click();
    await row.getByRole('button', {name: '확인'}).click();
    await row.getByRole('button', {name: '올리기'}).waitFor();
    assert.equal(writes(), 1);
  } finally { await browser.close(); }
});

test('BUG-115 TC-543: invalid item has no listing button', {skip: !chromium}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage(); await itemAdminFixture(page);
    const row = page.getByRole('row').filter({hasText: '검사 중 모자'});
    assert.equal(await row.getByText(/layer:dog_long/).count(), 1);
    assert.equal(await row.getByRole('button', {name: '올리기'}).count(), 0);
  } finally { await browser.close(); }
});

test('BUG-115 TC-543: forbidden hides tabs and shows admin-only state', {skip: !chromium}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage(); await itemAdminFixture(page, true);
    assert.equal(await page.getByText('관리자만 볼 수 있어요').count(), 1);
    assert.equal(await page.locator('.admin-tabs:visible').count(), 0);
    assert.equal(await page.getByRole('button', {name: '다시 보기'}).count(), 0);
  } finally { await browser.close(); }
});


test('BUG-115 TC-543: validation failure shows missing items on the row', {skip: !chromium}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage(); await itemAdminFixture(page);
    const row = page.getByRole('row').filter({hasText: '파란 모자'});
    await row.getByRole('button', {name: '올리기'}).click();
    await row.getByText(/license/).waitFor();
    assert.equal(await row.getByRole('button', {name: '올리기'}).count(), 0);
  } finally { await browser.close(); }
});
