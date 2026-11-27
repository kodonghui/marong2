'use strict';

const assert = require('node:assert/strict');
const {readFile} = require('node:fs/promises');
const path = require('node:path');
const {test} = require('node:test');
const {performance} = require('node:perf_hooks');
const {createHash} = require('node:crypto');
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
    let missingNeck = true, decorOn = true;
    await page.route('**/chat/api/profile', route => route.fulfill({json: {
      botName: '콩이', character: {id: 9, outfit: decorOn ? {body: {layerUrl: body}, neck: {layerUrl: neck}, head: {layerUrl: head}} : {body:null, neck:null, head:null}},
    }}));
    await page.route('**/chat/decor/**', route => missingNeck && new URL(route.request().url()).pathname === neck
      ? route.fulfill({status: 404}) : route.fulfill({contentType: 'image/png', body: BLANK}));
    await page.goto(site.url);
    await page.locator(`.outfit-layer[src="${head}"]`).waitFor();
    await page.waitForFunction(() => document.querySelectorAll('.outfit-layer').length === 2);
    const layers = await page.locator('.outfit-layer').evaluateAll(images => images.map(image => image.getAttribute('src')));
    assert.deepEqual(layers, [body, head]);
    assert.equal(await page.locator('#face').isVisible(), true);
    missingNeck = false;
    await page.reload();
    await page.waitForFunction(() => document.querySelectorAll('.outfit-layer').length === 3);
    assert.deepEqual(await page.locator('.outfit-layer').evaluateAll(images => images.map(image => image.getAttribute('src'))), [body, neck, head]);
    assert.deepEqual(await page.locator('.outfit-layer').evaluateAll(images => images.map(image => image.alt)), ['', '', '']);
    const sizes = await page.locator('#face, .outfit-layer').evaluateAll(images => images.map(image => {const box=image.getBoundingClientRect(); return [box.width,box.height]}));
    assert.ok(sizes.every(size => Math.abs(size[0]-sizes[0][0])<1 && Math.abs(size[1]-sizes[0][1])<1));
    await page.evaluate(() => { waiting = true; });
    await page.waitForFunction(() => document.getElementById('face').getAttribute('src').includes('/surprised'));
    assert.deepEqual(await page.locator('.outfit-layer').evaluateAll(images => images.map(image => image.getAttribute('src'))), [body, neck, head]);
    decorOn = false;
    const profileLoaded = page.waitForResponse(response => response.url().endsWith('/chat/api/profile'));
    await page.reload(); await profileLoaded;
    await page.waitForFunction(() => document.querySelectorAll('.outfit-layer').length === 0);
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
    const background = {id: 'starter-background', kind: 'background', name: '기본 배경', priceKrw: 0, thumbUrl: '/chat/decor/v1/starter-background/thumb.webp', owned: true, starter: true};
    const stickerItem = {id: 'star-sticker', kind: 'sticker', name: '별 스티커', priceKrw: 0, thumbUrl: '/chat/decor/v1/star-sticker/sticker.webp', owned: false};
    const outfit = {head: null, body: null, neck: null};
    const character = {id: 9, name: '콩이', kind: 'dog', template: 'dog_small', outfit};
    const layer = '/chat/decor/v1/berry-beanie/dog_small.png';
    let picked, rejectWear = null;
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      assert.equal(url.origin, BASE);
      const address = url.pathname;
      if (address === '/chat/api/profile') return route.fulfill({json: {character}});
      if (address === '/chat/api/shop') return route.fulfill({json: {items: [hat, background, stickerItem]}});
      if (address === '/chat/api/closet') {
        return route.fulfill({json: {characterId: 9, outfit, items: hat.owned ? [hat] : []}});
      }
      if (address.endsWith('/claim')) {
        hat.owned = true;
        return route.fulfill({status: 201, json: {itemId: hat.id, owned: true}});
      }
      if (address.endsWith('/outfit')) {
        if (rejectWear) return route.fulfill({status: 409, json: {code: rejectWear}});
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
    assert.doesNotMatch(await page.locator('body').innerText(), /무료|할인|결제/);
    for (const label of ['입는 것', '일기장', '스티커']) {
      assert.equal(await page.getByRole('button', {name: label, exact: true}).count(), 1);
    }
    await page.getByRole('button', {name: '일기장', exact: true}).click();
    assert.equal(await page.getByText('기본 배경', {exact: true}).count(), 1);
    assert.equal(await page.getByText('기본', {exact: true}).count(), 1);
    assert.equal(await page.getByText('딸기 털모자', {exact: true}).count(), 0);
    await page.getByRole('button', {name: '스티커', exact: true}).click();
    assert.equal(await page.getByText('별 스티커', {exact: true}).count(), 1);
    assert.equal(await page.getByText('기본 배경', {exact: true}).count(), 0);
    await page.getByRole('button', {name: '입는 것', exact: true}).click();
    await page.getByRole('link', {name: '아이템 보기'}).click();
    await page.locator(`.decor-layer[src="${layer}"]`).waitFor();
    await page.getByRole('button', {name: '받기', exact: true}).click();
    rejectWear = 'not_ready';
    await page.getByRole('button', {name: '입혀 볼래'}).click({timeout: 1500});
    await page.getByText('아직 다 만들지 못한 캐릭터야').waitFor();
    rejectWear = null;
    await page.getByRole('button', {name: '입혀 볼래'}).click({timeout: 1500});
    await page.waitForURL(BASE + '/chat/closet');
    await page.getByText('콩이가 딸기 털모자 입었어!', {exact: true}).waitFor();
    assert.deepEqual(picked, {head: hat.id, body: null, neck: null});
    const ownedHat = page.getByRole('button', {name: '딸기 털모자', exact: true});
    assert.equal(await ownedHat.count(), 1);
    await ownedHat.click();
    await page.waitForFunction(() => !document.querySelector('.decor-layer'));
    assert.deepEqual(picked, {head: null, body: null, neck: null});
    await page.getByRole('button', {name: '딸기 털모자', exact: true}).click();
    await page.locator(`.decor-layer[src="${layer}"]`).waitFor();
    await page.waitForFunction(() => document.querySelector('[aria-pressed="true"]') !== null);
    assert.deepEqual(picked, {head: hat.id, body: null, neck: null});
    rejectWear = 'not_owned';
    await page.getByRole('button', {name: '딸기 털모자', exact: true}).click();
    await page.getByText('아직 안 받은 거야').waitFor();
    assert.equal(await page.getByRole('button', {name: '딸기 털모자', exact: true}).getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator(`.decor-layer[src="${layer}"]`).count(), 1);
    rejectWear = null;
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
        return route.fulfill({json: {items: [{kind: 'sticker', id: 'star-sticker', name: '별', thumbUrl: imageUrl},
          ...['background','paper','font'].map(kind=>({kind,id:'starter-'+kind,name:'처음 '+kind,starter:true})),
          ...[['background','blue-background'],['paper','ivory-paper'],['font','poorstory-font']].map(([kind,id])=>({kind,id,name:id,thumbUrl:'/chat/decor/v1/'+id+'/thumb.webp'}))]}});
      }
      if (address === '/chat/api/profile') return route.fulfill({json:{character:null}});
      if (address === '/chat/diary/api/latest') return route.fulfill({json:{date,enabled:true}});
      if (address === '/chat/diary/api/decor') {
        if (route.request().method() === 'PUT') {
          const body=route.request().postDataJSON();
          styleMode=body.backgroundId==='starter-background' && body.paperId==='starter-paper' && body.fontId==='starter-font'?'starter':'custom';
        }
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
      if (address === '/chat/diary/decor' || ['/chat/decor.js','/chat/unified.js','/chat/unified.css','/chat/chat.css'].includes(address)) {
        const file=address==='/chat/diary/decor'?'decor.html':path.basename(address);
        const type=file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':'text/html';
        return route.fulfill({contentType:type+'; charset=utf-8',body:await readFile(path.join(STATIC,file))});
      }
      const file = [ '/chat/diary/' + date, '/chat/diary/' ].includes(address) ? 'index.html' : path.basename(address);
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
    const digest = data => createHash('sha256').update(data).digest('hex');
    assert.equal(digest(starter), digest(baseline), 'the diary card with starter decor matches the disabled feature');
    await page.goto(BASE + '/chat/diary/decor');
    await page.getByRole('button',{name:'처음 모습으로'}).click();
    await page.getByRole('button',{name:'이걸로 할래'}).click();
    await page.waitForURL(BASE + '/chat/diary/' + date);
    await page.getByRole('button',{name:'스티커',exact:true}).waitFor();
    await page.evaluate(() => document.fonts.ready);
    await page.locator('#banner').evaluate(el => { el.hidden = true; });
    const savedDefaults = await page.locator('.paper').screenshot({animations:'disabled'});
    assert.equal(digest(savedDefaults), digest(baseline), 'saving starter decor preserves the original diary card');
    await page.goto(BASE + '/chat/diary/decor');
    await page.getByLabel('배경',{exact:true}).selectOption('blue-background');
    await page.getByLabel('속지',{exact:true}).selectOption('ivory-paper');
    await page.getByLabel('글꼴',{exact:true}).selectOption('poorstory-font');
    await page.getByRole('button',{name:'이걸로 할래'}).click();
    await page.waitForURL(BASE + '/chat/diary/' + date);
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
    const handle = sticker.locator('.sticker-handle');
    const handleBox = await handle.boundingBox();
    await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(handleBox.x + handleBox.width / 2 + 18, handleBox.y + handleBox.height / 2 + 18, {steps: 4});
    await page.mouse.up();
    assert.ok(Number(await sticker.evaluate(el => el.style.getPropertyValue('--sticker-size'))) > 1);
    const angle = page.getByLabel('스티커 1 기울기');
    await angle.fill('45');
    assert.equal(await sticker.evaluate(el => el.style.getPropertyValue('--sticker-angle')), '45deg');
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
    await page.emulateMedia({reducedMotion: 'reduce'});
    await page.getByRole('button', {name: '스티커', exact: true}).click();
    for (let i = 0; i < 9; i++) await page.getByRole('button', {name: '별', exact: true}).click();
    assert.equal(await page.getByText('10/10', {exact: true}).count(), 1);
    assert.equal(await page.getByText('한 장에 10개까지야').count(), 1);
    assert.equal(await page.getByRole('button', {name: '별', exact: true}).isDisabled(), true);
    for (let i = 0; i < 9; i++) await page.getByRole('button', {name: '떼기', exact: true}).last().click();
    assert.equal(await page.getByText('1/10', {exact: true}).count(), 1);
    assert.equal(await sticker.evaluate(element => getComputedStyle(element).animationName), 'none');
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
    assert.equal(await blue.locator('img').getAttribute('src'), '/chat/admin/api/items/blue-cap/thumbnail');
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

async function itemAdminFixture(page, denied = false, csp = false) {
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
    return route.fulfill({contentType: type + '; charset=utf-8', body: content,
      headers: csp && file === 'admin-items.html' ? {'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'"} : {}});
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


test('TC-543: loading shows a grey placeholder until the items arrive', {skip: !chromium}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    let release;
    const pending = new Promise(resolve => { release = resolve; });
    await page.route('**/*', async route => {
      const address = new URL(route.request().url()).pathname;
      if (address === '/chat/admin/api/items') { await pending; return route.fulfill({json: {set: 'v1', items: []}}); }
      const file = address === '/chat/admin/items' ? 'admin-items.html' : path.basename(address);
      if (!['admin-items.html', 'admin-items.js', 'chat.css', 'unified.css', 'unified.js'].includes(file)) return route.fulfill({status: 404});
      const type = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : 'text/html';
      return route.fulfill({contentType: type + '; charset=utf-8', body: await readFile(path.join(STATIC, file))});
    });
    await page.goto(BASE + '/chat/admin/items');
    assert.equal(await page.locator('#item-admin').getAttribute('aria-busy'), 'true');
    assert.equal(await page.locator('#item-list .loading-placeholder').isVisible(), true);
    assert.notEqual(await page.locator('.loading-placeholder').evaluate(el => getComputedStyle(el).backgroundColor), 'rgba(0, 0, 0, 0)');
    release();
    await page.locator('#item-admin[aria-busy="false"]').waitFor();
    assert.equal(await page.locator('.loading-placeholder').count(), 0);
  } finally { await browser.close(); }
});

test('TC-551: slow or missing font keeps the current preview font', {skip: !chromium}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({viewport: {width: 360, height: 780}});
    const initial = ['background', 'paper'].map(kind => ({id: 'starter-' + kind, kind, name: '처음 ' + kind, starter: true}));
    const fonts = ['current-font', 'slow-font'].map(id => ({id, kind: 'font', name: id, starter: false, thumbUrl: `/chat/decor/v1/${id}/thumb.webp`}));
    let release, requested;
    const waiting = new Promise(resolve => { release = resolve; });
    const started = new Promise(resolve => { requested = resolve; });
    await page.route('**/*', async route => {
      const address = new URL(route.request().url()).pathname;
      if (address === '/chat/api/profile') return route.fulfill({json: {character: null}});
      if (address === '/chat/api/closet') return route.fulfill({json: {items: [...initial, ...fonts]}});
      if (address === '/chat/diary/api/latest') return route.fulfill({json: {date: null}});
      if (address === '/chat/diary/api/decor') return route.fulfill({json: {background: {id:'starter-background'}, paper: {id:'starter-paper'}, font: {id:'current-font'}}});
      if (address === '/chat/decor/v1/current-font/font.woff2') return route.fulfill({contentType:'font/woff2', body: await readFile(path.join(STATIC, 'diary/Gaegu-Regular.woff2'))});
      if (address === '/chat/decor/v1/slow-font/font.woff2') { requested(); await waiting; return route.fulfill({status:404}); }
      const files = {'/chat/diary/decor':'decor.html', '/chat/diary/decor.js':'diary/decor.js', '/chat/decor.js':'decor.js', '/chat/unified.js':'unified.js', '/chat/chat.css':'chat.css', '/chat/unified.css':'unified.css'};
      const file = files[address];
      if (!file) return route.fulfill({status:404});
      const type = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : 'text/html';
      return route.fulfill({contentType:type+'; charset=utf-8', body:await readFile(path.join(STATIC,file))});
    });
    await page.goto(BASE+'/chat/diary/decor');
    const paper = page.locator('.decor-paper-preview');
    await page.waitForFunction(() => !!document.querySelector('.decor-paper-preview')?.style.getPropertyValue('--font-diary'));
    const current = await paper.evaluate(el => el.style.getPropertyValue('--font-diary'));
    await page.getByLabel('글꼴', {exact:true}).selectOption('slow-font');
    await started;
    assert.equal(await page.getByText('글꼴 받는 중…').isVisible(), true);
    assert.equal(await paper.evaluate(el => el.style.getPropertyValue('--font-diary')), current);
    release();
    await page.getByText('글꼴 받는 중…').waitFor({state:'hidden'});
    assert.equal(await paper.evaluate(el => el.style.getPropertyValue('--font-diary')), current);
  } finally { await browser.close(); }
});

async function decorStateFixture(page, {many = false, character = false} = {}) {
  const hat = {id:'blue-hat', kind:'hat', slot:'head', name:'파란 모자', priceKrw:0, owned:false, thumbUrl:'/chat/decor/v1/blue-hat/thumb.webp'};
  const bg = {id:'starter-background', kind:'background', name:'기본 배경', priceKrw:0, owned:true, starter:true, thumbUrl:'/chat/decor/v1/starter-background/thumb.webp'};
  const newBg = {id:'green-background',kind:'background',name:'초록 배경',owned:true,starter:false,thumbUrl:'/chat/decor/v1/green-background/thumb.webp'};
  let claimStatus = 201, saveStatus = 200, shopStatus = 200, closetStatus = 200, wearStatus = 200, emptyShop = false, validationErrors = [];
  await page.route('**/*', async route => {
    const address = new URL(route.request().url()).pathname;
    if (address === '/chat/api/profile') return route.fulfill({json:{character:character ? {id:9,template:'dog_small',outfit:{head:null,body:null,neck:null}} : null}});
    if (address === '/chat/api/shop') return shopStatus === 200 ? route.fulfill({json:{items:emptyShop ? [] : many ? [hat, {...hat,id:'red-hat',name:'빨간 모자'}, {...hat,id:'green-hat',name:'초록 모자'}, bg,newBg] : [hat,bg,newBg]}}) : route.fulfill({status:shopStatus,json:{code:'internal'}});
    if (address === '/chat/api/closet') return closetStatus!==200 ? route.fulfill({status:closetStatus,json:{code:'internal'}}) : route.fulfill({json:{characterId:character ? 9 : null, outfit:character ? {head:null,body:null,neck:null} : null, items:[bg,newBg,{id:'starter-paper',kind:'paper',name:'처음 속지',starter:true},{id:'starter-font',kind:'font',name:'처음 글꼴',starter:true}], diaryDecor:{background:{id:bg.id},paper:{id:'starter-paper'},font:{id:'starter-font'}}}});
    if (address.endsWith('/claim')) return route.fulfill({status:claimStatus, json:claimStatus===404 ? {code:'not_found'} : claimStatus===403 ? {code:'cross_site'} : claimStatus>=500 ? {code:'internal'} : {itemId:hat.id,owned:true}});
    if (address.endsWith('/outfit')) return route.fulfill({status:wearStatus,json:wearStatus===200?{head:{id:hat.id},body:null,neck:null}:{code:wearStatus===400?'invalid_input':'internal',errors:wearStatus===400?[{field:'head',reason:'wrong_kind'}]:[]}});
    if (address === '/chat/diary/api/decor') { if (route.request().method()==='PUT') return route.fulfill({status:saveStatus,json:{code:saveStatus===409?'not_owned':saveStatus===400?'invalid_input':'internal',errors:validationErrors}}); return route.fulfill({json:{background:{id:bg.id},paper:{id:'starter-paper'},font:{id:'starter-font'}}}); }
    if (address === '/chat/diary/api/latest') return route.fulfill({json:{date:null}});
    if (address === '/chat/diary/decor.js') return route.fulfill({contentType:'application/javascript',body:await readFile(path.join(STATIC,'diary/decor.js'))});

    if (address.startsWith('/chat/decor/') || address.startsWith('/face/')) return route.fulfill({contentType:'image/png',body:BLANK});
    const file = ['/chat/shop','/chat/closet','/chat/diary/decor'].includes(address) ? 'decor.html' : path.basename(address);
    if (!['decor.html','decor.js','chat.css','unified.css','unified.js'].includes(file)) return route.fulfill({status:404});
    const type = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : 'text/html';
    return route.fulfill({contentType:type+'; charset=utf-8',body:await readFile(path.join(STATIC,file))});
  });
  return {setClaimStatus: status => {claimStatus=status;}, setSaveStatus: status => {saveStatus=status;}, setShopStatus: status => {shopStatus=status;}, setClosetStatus: status => {closetStatus=status;}, setWearStatus: status => {wearStatus=status;}, setEmptyShop: value => {emptyShop=value;}, setValidationErrors: value => {validationErrors=value;}};
}

test('D189 TC-551: validation rules appear under each affected field', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage(); const fixture=await decorStateFixture(page);
    fixture.setSaveStatus(400);
    fixture.setValidationErrors([{field:'backgroundId',reason:'wrong_kind'},{field:'fontId',reason:'required'}]);
    await page.goto(BASE+'/chat/diary/decor');
    await page.getByLabel('배경',{exact:true}).selectOption('green-background');
    await page.getByRole('button',{name:'이걸로 할래'}).click();
    await page.locator('label').filter({has:page.getByLabel('배경',{exact:true})}).getByText('배경 아이템을 골라 줘').waitFor({timeout:1500});
    assert.equal(await page.locator('label').filter({has:page.getByLabel('배경',{exact:true})}).getByText('다시 한번 확인해 줄래?',{exact:true}).count(),1);
    assert.equal(await page.locator('label').filter({has:page.getByLabel('글꼴',{exact:true})}).getByText('글꼴 아이템을 골라 줘').count(),1);
    assert.equal(await page.getByLabel('배경',{exact:true}).inputValue(),'green-background');
    fixture.setValidationErrors([{field:'paperId',reason:'bad_format'}]);
    await page.getByRole('button',{name:'이걸로 할래'}).click();
    await page.locator('label').filter({has:page.getByLabel('속지',{exact:true})}).getByText('속지 아이템 ID 형식을 확인해 줘').waitFor({timeout:1500});
    assert.equal(await page.getByLabel('속지',{exact:true}).getAttribute('aria-invalid'),'true');
  } finally { await browser.close(); }
});

test('TC-546: removed shop item disappears and explains why', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage({viewport:{width:430,height:800}});
    const fixture=await decorStateFixture(page); fixture.setClaimStatus(404);
    await page.goto(BASE+'/chat/shop');
    await page.getByText('파란 모자',{exact:true}).waitFor();
    await page.getByRole('button',{name:'받기',exact:true}).click();
    await page.getByText('방금 상점에서 내려간 아이템이야',{exact:true}).waitFor();
    assert.equal(await page.getByText('방금 상점에서 내려간 아이템이야',{exact:true}).count(),1);
    assert.equal(await page.getByText('파란 모자',{exact:true}).count(),0);
  } finally { await browser.close(); }
});

test('TC-546: default Marong sees approved detail and closet states', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage({viewport:{width:430,height:800}});
    await decorStateFixture(page);
    await page.goto(BASE+'/chat/shop');
    await page.getByRole('link',{name:'아이템 보기'}).click();
    await page.getByText('반려동물 캐릭터에 입힐 수 있어',{exact:true}).waitFor();
    assert.equal(await page.getByText('반려동물 캐릭터에 입힐 수 있어',{exact:true}).count(),1);
    await page.goto(BASE+'/chat/closet');
    await page.getByText('반려동물 캐릭터를 만들면 옷을 입힐 수 있어',{exact:true}).waitFor({timeout:1500});
    assert.equal(await page.getByRole('link',{name:'캐릭터 만들기'}).count(),1);
    await page.getByRole('button',{name:'일기장',exact:true}).click();
    assert.equal(await page.getByText('기본 배경',{exact:true}).count(),1);
    assert.equal(await page.getByText('쓰는 중',{exact:true}).count(),3);
  } finally { await browser.close(); }
});


test('TC-546: shop cards fit three columns at 360 and 430 pixels', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage(); await decorStateFixture(page,{many:true});
    for (const width of [360,430]) for (const [time,theme] of [['2026-11-21T03:00:00Z','chestnut'],['2026-11-21T13:00:00Z','night']]) {
      await page.setViewportSize({width,height:800});
      await page.clock.setFixedTime(new Date(time));
      await page.goto(BASE+'/chat/shop');
      await page.getByText('파란 모자',{exact:true}).waitFor();
      assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
      const cards=page.locator('#decor-content .card');
      assert.equal(await cards.count(),3);
      const boxes=await cards.evaluateAll(nodes=>nodes.map(n=>{const b=n.getBoundingClientRect();return {x:b.x,y:b.y,right:b.right,overflow:n.scrollWidth>n.clientWidth}}));
      assert.ok(boxes.every(box=>Math.abs(box.y-boxes[0].y)<1 && !box.overflow));
      assert.ok(boxes[0].x < boxes[1].x && boxes[1].x < boxes[2].x);
      assert.ok(boxes[2].right <= width);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
    }
  } finally { await browser.close(); }
});


test('TC-546: choosing a diary background in the closet preselects it', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage(); await decorStateFixture(page);
    await page.goto(BASE+'/chat/closet');
    await page.getByRole('button',{name:'일기장',exact:true}).click();
    await page.getByRole('link',{name:'초록 배경'}).click({timeout:1500});
    await page.waitForURL(/\/chat\/diary\/decor/);
    assert.equal(await page.getByLabel('배경',{exact:true}).inputValue(), 'green-background');
  } finally { await browser.close(); }
});

test('TC-546: decor switch hides shop and closet menu links', {skip:!chromium}, async () => {
  const {startChatSite} = require('./support/chat-site.cjs');
  const site=await startChatSite(); const browser=await chromium.launch();
  try {
    const page=await browser.newPage({viewport:{width:360,height:780}});
    let enabled=false;
    await page.route('**/chat/api/profile', route => route.fulfill({json:{botName:'시험 마롱이',character:null,features:{decor:enabled,friends:false}}}));
    await page.goto(site.url+'/chat/');
    await page.waitForFunction(()=>!document.getElementById('menu-profile').hidden);
    assert.equal(await page.locator('#menu-shop').evaluate(el=>el.hidden),true);
    assert.equal(await page.locator('#menu-closet').evaluate(el=>el.hidden),true);
    enabled=true;
    await page.reload();
    await page.waitForFunction(()=>!document.getElementById('menu-profile').hidden);
    assert.equal(await page.locator('#menu-shop').evaluate(el=>el.hidden),false);
    assert.equal(await page.locator('#menu-closet').evaluate(el=>el.hidden),false);
  } finally { await browser.close(); await site.close(); }
});

test('TC-548: chat header and message faces keep ordered decorative layers', {skip:!chromium}, async () => {
  const {startChatSite}=require('./support/chat-site.cjs'); const site=await startChatSite();
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage({viewport:{width:360,height:780}});
    const paths=['blue-top','soft-scarf','blue-hat'].map(id=>'/chat/decor/v1/'+id+'/dog_small.png');
    let enabled=true;
    site.state.messages=[{id:1,from:'marong',text:'합성 대화',at:'2026-11-26T09:00:00+09:00',via:'app',kind:'chat'}];
    await page.route('**/chat/api/profile',route=>route.fulfill({json:{botName:'시험 아이',features:{decor:enabled,friends:false},character:{id:9,faceUrl:'/face/v1/01-neutral.webp',outfit:enabled?{body:{layerUrl:paths[0]},neck:{layerUrl:paths[1]},head:{layerUrl:paths[2]}}:{body:null,neck:null,head:null}}}}));
    await page.route('**/chat/decor/**',route=>route.fulfill({contentType:'image/png',body:BLANK}));
    await page.goto(site.url+'/chat/');
    await page.locator('#header-pet-face .face-layer').first().waitFor();
    await page.locator('.message.marong .face .face-layer').first().waitFor();
    for (const face of [page.locator('#header-pet-face'), page.locator('.message.marong .face').first()]) {
      assert.deepEqual(await face.locator('.face-layer').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('src'))),paths);
      assert.deepEqual(await face.locator('.face-layer').evaluateAll(nodes=>nodes.map(n=>n.alt)),['','','']);
      const sizes=await face.locator('img').evaluateAll(nodes=>nodes.map(n=>{const b=n.getBoundingClientRect();return [b.width,b.height]}));
      assert.ok(sizes.every(size=>size[0]===sizes[0][0] && size[1]===sizes[0][1]));
    }
    enabled=false; await page.reload();
    await page.waitForFunction(()=>!document.getElementById('menu-profile').hidden);
    assert.equal(await page.locator('.face-layer').count(),0);
    assert.equal(await page.locator('#header-pet-face img').count(),1);
  } finally { await browser.close(); await site.close(); }
});


test('TC-551: save errors preserve selection and offer approved recovery', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage(); const fixture=await decorStateFixture(page);
    for (const [status,message] of [[400,'다시 한번 확인해 줄래?'],[409,'아직 안 받은 거야'],[500,'잠깐 문제가 생겼어. 다시 해 볼래?']]) {
      fixture.setSaveStatus(status);
      await page.goto(BASE+'/chat/diary/decor');
      await page.getByLabel('배경',{exact:true}).selectOption('green-background');
      await page.getByRole('button',{name:'이걸로 할래'}).click();
      await page.getByText(message,{exact:true}).waitFor({timeout:1500});
      assert.equal(await page.getByLabel('배경',{exact:true}).inputValue(),'green-background');
      if (status===500) assert.equal(await page.getByRole('button',{name:'다시 해 볼게',exact:true}).count(),1);
    }
  } finally { await browser.close(); }
});


test('TC-546: shop read error offers retry and recovers', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage(); const fixture=await decorStateFixture(page); fixture.setShopStatus(500);
    await page.goto(BASE+'/chat/shop');
    await page.getByText('잠깐 문제가 생겼어. 다시 해 볼래?',{exact:true}).waitFor();
    const retry=page.getByRole('button',{name:'다시 해 볼게',exact:true});
    assert.equal(await retry.count(),1);
    fixture.setShopStatus(200); await retry.click();
    await page.getByText('파란 모자',{exact:true}).waitFor();
  } finally { await browser.close(); }
});


test('TC-546: diary decor detail previews the chosen background', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage(); await decorStateFixture(page);
    await page.goto(BASE+'/chat/shop');
    await page.getByRole('button',{name:'일기장',exact:true}).click();
    const item=page.locator('.card').filter({hasText:'초록 배경'});
    await item.getByRole('link',{name:'아이템 보기'}).click();
    await page.locator('.decor-book-preview-frame[style*="green-background/bg.webp"]').waitFor({timeout:1500});
  } finally { await browser.close(); }
});

test('TC-546: shop and closet show loading placeholders until their lists arrive', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    for (const pageName of ['shop','closet']) {
      const page=await browser.newPage({viewport:{width:360,height:780}});
      let release; const gate=new Promise(resolve=>{release=resolve});
      await page.route('**/*',async route=>{
        const address=new URL(route.request().url()).pathname;
        if (address==='/chat/api/profile') return route.fulfill({json:{character:null}});
        if (address==='/chat/api/'+pageName) {await gate; return route.fulfill({json:{items:[],characterId:null,outfit:null}});}
        const file=address==='/chat/'+pageName?'decor.html':path.basename(address);
        if (!['decor.html','decor.js','unified.js','unified.css','chat.css'].includes(file)) return route.fulfill({status:404});
        const type=file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':'text/html';
        return route.fulfill({contentType:type+'; charset=utf-8',body:await readFile(path.join(STATIC,file))});
      });
      await page.goto(BASE+'/chat/'+pageName);
      assert.equal(await page.locator('#decor-screen').getAttribute('aria-busy'),'true');
      assert.equal(await page.locator('.decor-loading-card').count(),6);
      if (pageName==='closet') assert.equal(await page.locator('.decor-loading-face').count(),1);
      release(); await page.locator('#decor-screen[aria-busy="false"]').waitFor();
      assert.equal(await page.locator('.decor-loading-card').count(),0);
      await page.close();
    }
  } finally { await browser.close(); }
});


test('TC-546: empty shop and empty wear closet show approved guidance', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage(); const fixture=await decorStateFixture(page,{character:true});
    fixture.setEmptyShop(true);
    await page.goto(BASE+'/chat/shop');
    await page.getByText('아직 상점에 아무것도 없어. 곧 들어올 거야',{exact:true}).waitFor();
    await page.goto(BASE+'/chat/closet');
    await page.getByText('아직 입힐 게 없어. 상점에서 받아 볼래?',{exact:true}).waitFor();
    assert.equal(await page.getByRole('link',{name:'상점 가기'}).count(),1);
  } finally { await browser.close(); }
});

test('TC-546: wear saves queue one by one while other items remain usable', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage(); let release, started;
    const gate=new Promise(resolve=>{release=resolve}); const firstStarted=new Promise(resolve=>{started=resolve});
    const items=[{id:'blue-hat',kind:'hat',slot:'head',name:'파란 모자',thumbUrl:'/chat/decor/v1/blue-hat/thumb.webp'},
      {id:'red-top',kind:'top',slot:'body',name:'빨간 옷',thumbUrl:'/chat/decor/v1/red-top/thumb.webp'},
      {id:'green-hat',kind:'hat',slot:'head',name:'초록 모자',thumbUrl:'/chat/decor/v1/green-hat/thumb.webp'}];
    const sent=[]; let active=0,maxActive=0;
    await page.route('**/*',async route=>{
      const address=new URL(route.request().url()).pathname;
      if (address==='/chat/api/profile') return route.fulfill({json:{character:{id:9,template:'dog_small'}}});
      if (address==='/chat/api/closet') return route.fulfill({json:{items,characterId:9,outfit:{head:null,body:null,neck:null}}});
      if (address.endsWith('/outfit')) {
        active++; maxActive=Math.max(maxActive,active); const data=route.request().postDataJSON(); sent.push(data);
        if (sent.length===1) {started(); await gate;}
        active--; return route.fulfill({json:Object.fromEntries(Object.entries(data).map(([slot,id])=>[slot,id?{id,layerUrl:'/chat/decor/v1/'+id+'/dog_small.png'}:null]))});
      }
      if (address.startsWith('/chat/decor/') || address.includes('/images/')) return route.fulfill({contentType:'image/png',body:BLANK});
      const file=address==='/chat/closet'?'decor.html':path.basename(address);
      if (!['decor.html','decor.js','unified.js','unified.css','chat.css'].includes(file)) return route.fulfill({status:404});
      const type=file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':'text/html';
      return route.fulfill({contentType:type+'; charset=utf-8',body:await readFile(path.join(STATIC,file))});
    });
    await page.goto(BASE+'/chat/closet');
    await page.getByRole('button',{name:'파란 모자',exact:true}).click(); await firstStarted;
    assert.equal(await page.getByRole('button',{name:'파란 모자',exact:true}).locator('.decor-wear-spinner').isVisible(),true);
    await page.getByRole('button',{name:'빨간 옷',exact:true}).click();
    assert.equal(sent.length,1);
    release(); await page.waitForFunction(()=>!document.querySelector('.decor-wear-spinner'));
    assert.deepEqual(sent,[{head:'blue-hat',body:null,neck:null},{head:'blue-hat',body:'red-top',neck:null}]);
    assert.equal(maxActive,1);
    await page.getByRole('button',{name:'초록 모자',exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('.decor-wear-spinner'));
    assert.equal((sent.at(-1)).head,'green-hat');
    assert.equal(await page.getByRole('button',{name:'파란 모자',exact:true}).getAttribute('aria-pressed'),'false');
    assert.equal(await page.getByRole('button',{name:'초록 모자',exact:true}).getAttribute('aria-pressed'),'true');
  } finally { await browser.close(); }
});


test('TC-546: cross-site claim refusal shows approved guidance', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage(); const fixture=await decorStateFixture(page); fixture.setClaimStatus(403);
    await page.goto(BASE+'/chat/shop');
    await page.getByRole('button',{name:'받기',exact:true}).click();
    await page.getByText('이 화면에서 다시 해 줘',{exact:true}).waitFor({timeout:1500});
  } finally { await browser.close(); }
});


test('TC-543: item table stays within viewport under production style CSP', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage({viewport:{width:360,height:780}}); await itemAdminFixture(page,false,true);
    assert.equal(await page.locator('#item-list').evaluate(el=>getComputedStyle(el).overflowX),'auto');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),360);
  } finally { await browser.close(); }
});

test('D189 TC-546/553: sticker selection opens today and handles no diary or a full page', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage({viewport:{width:430,height:850}});
    const date='2026-11-21', item={id:'star-sticker',kind:'sticker',name:'별 스티커',owned:true,priceKrw:0,thumbUrl:'/chat/decor/v1/star-sticker/sticker.webp'};
    let ready=true, full=false, noItems=false, saveStatus=200, saveCode='too_many_stickers', saveErrors=[{field:'scale',index:0,reason:'out_of_range'},{field:'rotation',index:1,reason:'out_of_range'}], loadStatus=200, delayCloset=false, delaySave=false, releaseCloset, reachedCloset, releaseSave, reachedSave;
    const closetGate=new Promise(resolve=>{releaseCloset=resolve;});
    const closetStarted=new Promise(resolve=>{reachedCloset=resolve;});
    const saveGate=new Promise(resolve=>{releaseSave=resolve;});
    const saveStarted=new Promise(resolve=>{reachedSave=resolve;});
    await page.clock.setFixedTime(new Date('2026-11-20T16:00:00Z'));
    await page.route('**/*',async route=>{
      const address=new URL(route.request().url()).pathname;
      if (address==='/chat/api/profile') return route.fulfill({json:{character:null}});
      if (address==='/chat/api/shop') return route.fulfill({json:{items:[item]}});
      if (address==='/chat/api/closet') {
        if (delayCloset) { reachedCloset(); await closetGate; }
        return route.fulfill({json:{characterId:null,outfit:null,items:noItems?[]:[item]}});
      }
      if (address==='/chat/diary/api/decor') return route.fulfill({json:{background:{id:'starter-background',imageUrl:null},paper:{id:'starter-paper',imageUrl:null},font:{id:'starter-font',fontUrl:null}}});
      if (address===`/chat/diary/api/days/${date}`) return route.fulfill({json:ready?{date,state:'ready',prev:null,next:null,diary:{title:'오늘 일기',body:'시험 일기',revision:1,weather:'sunny',drawing:{kind:'placeholder',id:null},busy:null,hidden:false,stampedAt:null,fix:{left:5,blocked:null},redraw:{left:2,blocked:null,last:null}}}:{date,state:'none',prev:null,next:null,diary:null}});
      if (address===`/chat/diary/api/days/${date}/stickers`) {
        if (route.request().method()==='PUT' && saveStatus!==200) return route.fulfill({status:saveStatus,json:{code:saveStatus===409?saveCode:saveStatus===403?'cross_site':saveStatus===404?'not_found':saveStatus===400?'invalid_input':'internal',errors:saveStatus===400?saveErrors:[]}});
        if (route.request().method()==='PUT' && delaySave) { reachedSave(); await saveGate; }
        if (route.request().method()==='GET' && loadStatus!==200) return route.fulfill({status:loadStatus,json:{code:'internal'}});
        const stickers=route.request().method()==='PUT'?route.request().postDataJSON().stickers.map(row=>({...row,imageUrl:item.thumbUrl})):
          full?Array.from({length:10},()=>({itemId:item.id,imageUrl:item.thumbUrl,x:500,y:500,scale:100,rotation:0})):[];
        return route.fulfill({json:{date,stickers}});
      }
      if (address.startsWith('/chat/decor/') || address.startsWith('/face/')) return route.fulfill({contentType:'image/png',body:BLANK});
      let file;
      if (['/chat/shop','/chat/closet'].includes(address)) file='decor.html';
      else if (address===`/chat/diary/${date}` || address==='/chat/diary/') file='diary/index.html';
      else if (address.startsWith('/chat/diary/')) file='diary/'+path.basename(address);
      else file=path.basename(address);
      const allowed=['decor.html','decor.js','chat.css','unified.css','unified.js','diary/index.html','diary/diary.js','diary/decor.js','diary/diary.css','diary/tokens.css','diary/sheets.js','diary/Gaegu-Regular.woff2'];
      if (!allowed.includes(file)) return route.fulfill({status:404});
      const type=file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':file.endsWith('.woff2')?'font/woff2':'text/html';
      return route.fulfill({contentType:type,body:await readFile(path.join(STATIC,file))});
    });
    await page.goto(BASE+'/chat/closet');
    await page.getByRole('button',{name:'일기장',exact:true}).click();
    await page.getByRole('link',{name:item.name,exact:true}).click({timeout:1500});
    await page.waitForURL(BASE+'/chat/diary/'+date+'#sticker=star-sticker');
    await page.getByRole('heading',{name:'스티커 붙이기'}).waitFor();
    assert.equal(await page.getByText('1/10',{exact:true}).count(),1);
    assert.equal(await page.locator('.sticker-movable').count(),1);
    saveStatus=409;
    await page.getByRole('button',{name:'다 했어'}).click();
    await page.getByText('한 장에 10개까지야',{exact:true}).waitFor({timeout:1500});
    assert.equal(await page.getByText('1/10',{exact:true}).count(),1);
    saveCode='not_owned';
    await page.getByRole('button',{name:'다시 해 볼게'}).click();
    await page.getByText('아직 안 받은 거야',{exact:true}).waitFor({timeout:1500});
    saveStatus=403;
    await page.getByRole('button',{name:'다시 해 볼게'}).click();
    await page.getByText('이 화면에서 다시 해 줘',{exact:true}).waitFor({timeout:1500});
    await page.getByRole('button',{name:'별 스티커',exact:true}).click();
    saveStatus=400;
    await page.getByRole('button',{name:'다 했어'}).click();
    await page.locator('#banner').getByText('다시 한번 확인해 줄래?',{exact:true}).waitFor({timeout:1500});
    await page.getByText('크기는 50~200%로 골라 줘',{exact:true}).waitFor({timeout:1500});
    assert.equal(await page.getByText('기울기는 -180~180도로 골라 줘',{exact:true}).count(),1);
    assert.ok(await page.getByLabel('스티커 1 크기').getAttribute('aria-describedby'));
    assert.ok(await page.getByLabel('스티커 2 기울기').getAttribute('aria-describedby'));
    assert.equal(await page.getByLabel('스티커 1 기울기').getAttribute('aria-describedby'),null);
    assert.equal(await page.getByText('2/10',{exact:true}).count(),1);
    for (const width of [360,430]) {
      await page.setViewportSize({width,height:850});
      await page.waitForFunction(()=>document.documentElement.scrollWidth===innerWidth, null, {timeout:1500});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
    }
    saveErrors=[{field:'x',index:1,reason:'out_of_range'},{field:'itemId',index:1,reason:'wrong_kind'}];
    await page.getByRole('button',{name:'다시 해 볼게'}).click();
    await page.getByText('가로 위치는 0~1000으로 골라 줘',{exact:true}).waitFor({timeout:1500});
    assert.equal(await page.getByText('스티커 아이템을 골라 줘',{exact:true}).count(),1);
    assert.ok((await page.getByLabel('스티커 2 움직이기').getAttribute('aria-describedby')).includes('sticker-error-1-x'));
    assert.equal(await page.getByLabel('스티커 1 크기').getAttribute('aria-describedby'),null);
    saveStatus=404;
    await page.getByRole('button',{name:'다시 해 볼게'}).click();
    await page.getByText('찾지 못했어',{exact:true}).waitFor({timeout:1500});
    assert.equal(await page.getByRole('link',{name:'내 마롱이로'}).getAttribute('href'),'/chat/me');
    assert.equal(await page.getByText('2/10',{exact:true}).count(),1);
    saveStatus=500;
    await page.getByRole('button',{name:'다시 해 볼게'}).click();
    await page.getByText('잠깐 문제가 생겼어. 다시 해 볼래?').waitFor({timeout:1500});
    assert.equal(await page.getByText('2/10',{exact:true}).count(),1);
    saveStatus=200; delaySave=true;
    await page.getByRole('button',{name:'다시 해 볼게'}).click();
    await saveStarted;
    assert.equal(await page.getByRole('button',{name:'붙이는 중이야…'}).isDisabled(),true);
    assert.equal(await page.getByRole('button',{name:'그만둘래'}).isDisabled(),true);
    releaseSave(); delaySave=false;
    await page.getByRole('heading',{name:'스티커 붙이기'}).waitFor({state:'hidden'});
    ready=false;
    await page.goto(BASE+'/chat/shop#star-sticker');
    for (const width of [360,430]) for (const [instant,theme] of [['2026-11-21T03:00:00Z','chestnut'],['2026-11-20T16:00:00Z','night']]) {
      await page.setViewportSize({width,height:850});
      await page.clock.setFixedTime(new Date(instant));
      await page.reload();
      await page.locator('.decor-paper-preview img.decor-thumb').waitFor();
      assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
    }
    await page.getByRole('link',{name:'일기장에 쓰기'}).click({timeout:1500});
    await page.getByText('오늘 일기가 생기면 붙일 수 있어요',{exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'일기장으로 가기'}).count(),1);
    await page.getByRole('button',{name:'일기장으로 가기'}).click();
    await page.waitForURL(BASE+'/chat/diary/');
    await page.goto(BASE+'/chat/diary/'+date+'#stickers');
    await page.getByText('아직 일기가 없는 날이야',{exact:true}).waitFor({timeout:1500});
    assert.equal(await page.getByRole('button',{name:'일기장으로',exact:true}).count(),1);
    ready=true; full=true;
    await page.goto(BASE+'/chat/shop#star-sticker');
    await page.getByRole('link',{name:'일기장에 쓰기'}).click();
    await page.getByText('10/10',{exact:true}).waitFor();
    assert.equal(await page.getByText('한 장에 10개까지야').count(),1);
    assert.equal(await page.locator('.sticker-movable').count(),10);
    noItems=true; full=false;
    await page.goto(BASE+'/chat/diary/'+date+'#stickers');
    await page.reload();
    await page.getByText('스티커는 상점에서 받을 수 있어').waitFor({timeout:5000});
    assert.equal(await page.getByRole('link',{name:'상점 가기'}).count(),1);
    await page.goto(BASE+'/chat/shop');
    noItems=false; delayCloset=true;
    await page.goto(BASE+'/chat/diary/'+date+'#stickers');
    await closetStarted;
    assert.equal(await page.locator('#day').getAttribute('aria-busy'),'true');
    assert.equal(await page.locator('#day .loading').count(),1);
    releaseCloset();
    await page.getByRole('heading',{name:'스티커 붙이기'}).waitFor();
    await page.goto(BASE+'/chat/shop');
    delayCloset=false; loadStatus=500;
    await page.goto(BASE+'/chat/diary/'+date+'#stickers');
    await page.getByText('잠깐 문제가 생겼어. 다시 해 볼래?').waitFor({timeout:1500});
    loadStatus=200;
    await page.getByRole('button',{name:'다시 해 볼게'}).click();
    await page.getByRole('heading',{name:'스티커 붙이기'}).waitFor();
  } finally { await browser.close(); }
});

test('TC-546: closet wear errors roll back and expose approved recovery', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage({viewport:{width:430,height:850}});
    const item={id:'blue-hat',kind:'hat',slot:'head',name:'파란 모자',thumbUrl:'/chat/decor/v1/blue-hat/thumb.webp'};
    let code='cross_site', status=403, validationErrors=[{field:'head',reason:'wrong_kind'}];
    await page.route('**/*',async route=>{
      const address=new URL(route.request().url()).pathname;
      if(address==='/chat/api/profile') return route.fulfill({json:{character:{id:9,template:'dog_small',outfit:{head:null,body:null,neck:null}}}});
      if(address==='/chat/api/closet') return route.fulfill({json:{characterId:9,outfit:{head:null,body:null,neck:null},items:[item]}});
      if(address.endsWith('/outfit')) return route.fulfill({status,json:status===200?{head:{id:item.id,layerUrl:'/chat/decor/v1/blue-hat/dog_small.png'},body:null,neck:null}:{code,errors:status===400?validationErrors:[]}});
      if(address.startsWith('/chat/decor/') || address.includes('/images/')) return route.fulfill({contentType:'image/png',body:BLANK});
      const file=address==='/chat/closet'?'decor.html':path.basename(address);
      if(!['decor.html','decor.js','chat.css','unified.css','unified.js'].includes(file)) return route.fulfill({status:404});
      return route.fulfill({contentType:file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':'text/html',body:await readFile(path.join(STATIC,file))});
    });
    await page.goto(BASE+'/chat/closet');
    const choice=page.getByRole('button',{name:item.name,exact:true});
    await choice.click();
    await page.getByText('이 화면에서 다시 해 줘').waitFor({timeout:1500});
    assert.equal(await choice.getAttribute('aria-pressed'),'false');
    status=400; code='invalid_input';
    await choice.click();
    await page.getByText('머리 자리에 맞는 아이템을 골라 줘',{exact:true}).waitFor({timeout:1500});
    assert.ok(await choice.getAttribute('aria-describedby'));
    assert.equal(await choice.getAttribute('aria-pressed'),'false');
    validationErrors=[{field:'head',reason:'bad_format'},{field:'body',reason:'wrong_kind'}];
    await choice.click();
    await page.getByText('머리 아이템을 다시 골라 줘',{exact:true}).waitFor({timeout:1500});
    assert.equal(await page.getByText('몸 자리에 맞는 아이템을 골라 줘',{exact:true}).count(),1);
    for (const width of [360,430]) {
      await page.setViewportSize({width,height:850});
      await page.waitForFunction(()=>document.documentElement.scrollWidth===innerWidth, null, {timeout:1500});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
    }
    status=404; code='not_found';
    await choice.click();
    await page.getByText('찾지 못했어',{exact:true}).waitFor({timeout:1500});
    assert.equal(await page.getByRole('link',{name:'내 마롱이로'}).getAttribute('href'),'/chat/me');
    status=500; code='internal';
    await page.reload();
    await page.getByRole('button',{name:item.name,exact:true}).click();
    await page.getByText('잠깐 문제가 생겼어. 다시 해 볼래?').waitFor({timeout:1500});
    assert.equal(await page.getByRole('button',{name:'다시 해 볼게'}).count(),1);
    assert.equal(await page.getByRole('button',{name:item.name,exact:true}).getAttribute('aria-pressed'),'false');
    status=200;
    await page.getByRole('button',{name:'다시 해 볼게'}).click();
    await page.waitForFunction(()=>!document.querySelector('.decor-wear-spinner'));
    assert.equal(await page.getByRole('button',{name:item.name,exact:true}).getAttribute('aria-pressed'),'true');
  } finally { await browser.close(); }
});

test('TC-546: shop write and closet read errors can be retried', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage({viewport:{width:430,height:850}});
    const fixture=await decorStateFixture(page,{character:true});
    fixture.setClaimStatus(500);
    await page.goto(BASE+'/chat/shop');
    await page.getByRole('button',{name:'받기',exact:true}).click();
    await page.getByText('잠깐 문제가 생겼어. 다시 해 볼래?').waitFor({timeout:1500});
    fixture.setClaimStatus(201);
    await page.getByRole('button',{name:'다시 해 볼게',exact:true}).click({timeout:1500});
    await page.getByRole('button',{name:'받았어',exact:true}).waitFor();
    fixture.setWearStatus(400);
    await page.getByRole('link',{name:'아이템 보기'}).click();
    await page.getByRole('button',{name:'입혀 볼래'}).click();
    await page.getByText('머리 자리에 맞는 아이템을 골라 줘',{exact:true}).waitFor({timeout:1500});
    assert.ok(await page.getByRole('button',{name:'입혀 볼래'}).getAttribute('aria-describedby'));
    fixture.setWearStatus(500);
    await page.getByRole('button',{name:'입혀 볼래'}).click();
    await page.getByText('잠깐 문제가 생겼어. 다시 해 볼래?').waitFor({timeout:1500});
    assert.equal(await page.getByRole('button',{name:'다시 해 볼게',exact:true}).count(),1);
    fixture.setWearStatus(200);
    await page.getByRole('button',{name:'다시 해 볼게',exact:true}).click();
    await page.waitForURL(BASE+'/chat/closet');
    fixture.setClosetStatus(500);
    await page.reload();
    await page.getByText('잠깐 문제가 생겼어. 다시 해 볼래?').waitFor({timeout:1500});
    fixture.setClosetStatus(200);
    await page.getByRole('button',{name:'다시 해 볼게',exact:true}).click();
    await page.getByText('아직 입힐 게 없어. 상점에서 받아 볼래?').waitFor();
  } finally { await browser.close(); }
});

test('TC-551: diary decor shows loading preview and fields while inventory is delayed', {skip:!chromium}, async () => {
  const browser=await chromium.launch(); let release;
  try {
    const page=await browser.newPage(); await decorStateFixture(page);
    let reached; const started=new Promise(resolve=>{reached=resolve}); const gate=new Promise(resolve=>{release=resolve});
    await page.route('**/chat/api/closet',async route=>{reached(); await gate; return route.fulfill({json:{items:[]}});});
    await page.goto(BASE+'/chat/diary/decor'); await started;
    assert.equal(await page.locator('#decor-screen').getAttribute('aria-busy'),'true');
    assert.ok(await page.locator('#decor-content .decor-loading-card').count() >= 2);
    release();
    await page.getByRole('button',{name:'처음 모습으로'}).waitFor();
  } finally { if (release) release(); await browser.close(); }
});

test('TC-546: shop detail and closets fit both themes at 360 and 430 pixels', {skip:!chromium}, async () => {
  const browser=await chromium.launch();
  try {
    for (const character of [false,true]) {
      const page=await browser.newPage(); await decorStateFixture(page,{character});
      for (const width of [360,430]) for (const instant of ['2026-11-21T03:00:00Z','2026-11-20T16:00:00Z']) {
        await page.setViewportSize({width,height:850}); await page.clock.setFixedTime(new Date(instant));
        await page.goto(BASE+'/chat/shop');
        await page.getByRole('link',{name:'아이템 보기'}).click();
        await page.getByRole('link',{name:'상점으로'}).waitFor();
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
        await page.goto(BASE+'/chat/closet');
        await page.getByText(character?'아직 입힐 게 없어. 상점에서 받아 볼래?':'반려동물 캐릭터를 만들면 옷을 입힐 수 있어').waitFor();
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
        await page.getByRole('button',{name:'일기장',exact:true}).click();
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
      }
      await page.close();
    }
  } finally { await browser.close(); }
});

test('TC-551: empty diary uses the example and save stays disabled while pending', {skip:!chromium}, async () => {
  const browser=await chromium.launch(); let release;
  try {
    const page=await browser.newPage(); await decorStateFixture(page);
    let reached; const started=new Promise(resolve=>{reached=resolve}); const gate=new Promise(resolve=>{release=resolve});
    await page.route('**/chat/diary/api/decor',async route=>{
      if(route.request().method()!=='PUT') return route.fallback();
      reached(); await gate; return route.fulfill({status:409,json:{code:'not_owned'}});
    });
    await page.goto(BASE+'/chat/diary/decor');
    await page.getByText('오늘은 산책을 했다…').waitFor();
    const save=page.getByRole('button',{name:'이걸로 할래'});
    await save.click(); await started;
    assert.equal(await save.isDisabled(),true);
    release();
    await page.getByText('아직 안 받은 거야').waitFor();
    assert.equal(await save.isDisabled(),false);
  } finally { if(release) release(); await browser.close(); }
});
