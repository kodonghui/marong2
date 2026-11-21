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
        return route.fulfill({json: {paper: {imageUrl: '/chat/decor/v1/ivory-paper/paper.webp'},
          font: {fontUrl: '/chat/decor/v1/poorstory-font/font.woff2'}}});
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
    await page.getByText('오늘은 그림을 못 그렸어요').waitFor();
    assert.equal(await page.getByRole('button', {name: /다시 그리기/}).count(), 0);
    await page.getByRole('button', {name: '스티커', exact: true}).click();
    await page.getByRole('button', {name: '별', exact: true}).click();
    await page.getByRole('button', {name: '저장', exact: true}).click();
    await page.locator('.paper .diary-sticker').waitFor();
    assert.deepEqual(saved, [{itemId: 'star-sticker', x: 500, y: 500, scale: 100, rotation: 0}]);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 360);
  } finally {
    await browser.close();
  }
});
