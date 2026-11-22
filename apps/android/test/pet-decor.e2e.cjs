'use strict';

const assert = require('node:assert/strict');
const {readFile} = require('node:fs/promises');
const path = require('node:path');
const {test} = require('node:test');
const {performance} = require('node:perf_hooks');

let chromium;
try { ({chromium} = require('playwright')); } catch {}

const BASE = 'http://127.0.0.1:41798';
const STATIC = path.join(__dirname, '..', '..', '..', 'marong', 'app_chat_static');
const BLANK = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aLhcAAAAASUVORK5CYII=', 'base64');

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

test('TC-535/551/553: diary writer and sticker editing at 360 px', {skip: !chromium}, async t => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({viewport: {width: 360, height: 780}, isMobile: true});
    const date = '2026-11-20';
    const imageUrl = '/chat/decor/v1/star-sticker/sticker.webp';
    const base = '/chat/diary/api/days/' + date;
    let saved = [];
    let styleMode = 'off';
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      assert.equal(url.origin, BASE);
      const address = url.pathname;
      if (address === base) {
        return route.fulfill({json: {date, state: 'ready', prev: null, next: null, diary: {
          title: '콩이 일기', body: '누나와 이야기를 나누고 하루를 마무리했다. '.repeat(3), revision: 1,
          weather: 'sunny', drawing: {kind: 'placeholder', id: null}, busy: null, hidden: false,
          stampedAt: null, fix: {left: 5, blocked: null}, redraw: {left: 2, blocked: null, last: null},
          writer: {id: 9, name: '콩이', kind: 'dog', active: false, faceUrl: '/chat/api/characters/9/images/smile'},
        }}});
      }
      if (address === base + '/stickers') {
        if (route.request().method() === 'PUT') saved = route.request().postDataJSON().stickers;
        return route.fulfill({json: {date, stickers: saved.map(sticker => ({...sticker, imageUrl}))}});
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
        return route.fulfill({json: {paper: {imageUrl: '/chat/decor/v1/ivory-paper/paper.webp'},
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
    await page.getByRole('button', {name: '스티커', exact: true}).click();
    await page.getByRole('button', {name: '별', exact: true}).click();
    await page.getByRole('button', {name: '다 했어', exact: true}).click();
    await page.locator('.paper .diary-sticker').waitFor();
    assert.deepEqual(saved, [{itemId: 'star-sticker', x: 500, y: 500, scale: 100, rotation: 0}]);
    await page.getByRole('button', {name: '스티커', exact: true}).click();
    await page.getByRole('button', {name: '별', exact: true}).click();
    page.once('dialog', async dialog => {
      assert.equal(dialog.message(), '안 남기고 나갈까?');
      await dialog.accept();
    });
    await page.getByRole('button', {name: '그만둘래'}).click();
    await page.getByRole('heading', {name: '스티커 붙이기'}).waitFor({state: 'hidden'});
    assert.equal(saved.length, 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 360);
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
      {id: 'green-cap', name: '초록 모자', state: 'listed', owners: 2, missing: []},
      {id: 'blue-cap', name: '파란 모자', state: 'unlisted', owners: 1, missing: []},
      {id: 'broken-cap', name: '검사 중 모자', state: 'new', owners: 0, missing: ['layer:dog_long']},
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
    const blue = page.locator('li').filter({hasText: '파란 모자'});
    const broken = page.locator('li').filter({hasText: '검사 중 모자'});
    await broken.getByText('확인할 항목 layer:dog_long').waitFor();
    assert.equal(await broken.getByRole('button', {name: '올리기'}).isDisabled(), true);
    await blue.getByRole('button', {name: '올리기'}).click();
    await blue.getByRole('button', {name: '내리기'}).waitFor();

    permitted = false;
    await page.reload();
    await page.getByText('아이템을 불러오지 못했어요').waitFor();
    permitted = true;
    await page.getByRole('button', {name: '다시 보기'}).click();
    await blue.getByRole('button', {name: '내리기'}).waitFor();
  } finally {
    await browser.close();
  }
});
