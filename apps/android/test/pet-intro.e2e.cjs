'use strict';

const assert = require('node:assert/strict');
const {readFile} = require('node:fs/promises');
const path = require('node:path');
const {test} = require('node:test');

let chromium;
try { ({chromium} = require('playwright')); } catch {}

const FIXTURE = 'http://127.0.0.1:41799';
const STATIC = path.join(__dirname, '..', '..', '..', 'marong', 'app_chat_static');
const ROUTE = '/chat/character/7/';
const ASSETS = {
  '/chat/character.js': 'character.js', '/chat/unified.js': 'unified.js',
  '/chat/unified.css': 'unified.css', '/chat/chat.css': 'chat.css',
  '/chat/profile.js': 'profile.js', '/chat/voice.js': 'voice.js',
};

test('TC-517: name, intro, voice sample and skip fit 360 px in both themes', {skip: !chromium}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({viewport: {width: 360, height: 780}, isMobile: true});
    const endpoint = '/chat/api/characters/7';
    const character = {id: 7, name: '콩이', stage: 'name', images: {front: '/face/v1/01-neutral.webp'}};
    let current = null;
    let written;
    let failSave = false;
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      assert.equal(url.origin, FIXTURE);
      const address = url.pathname;
      const method = route.request().method();
      if (address === endpoint + '/intro') {
        if (method === 'PUT') {
          written = route.request().postDataJSON();
          if (failSave) return route.fulfill({status: 400, json: {code: 'invalid_input'}});
          current = written;
        }
        return route.fulfill({json: {intro: current, voice: current ? 'Puck' : null,
                                     voiceSource: current ? 'recommended' : 'none'}});
      }
      if (address === endpoint) return route.fulfill({json: {character}});
      if (address === endpoint + '/try') {
        return route.fulfill({json: {botName: '콩이', faces: character.images, chatSample: [], callLine: '안녕!'}});
      }
      if (address === '/chat/api/profile') {
        return route.fulfill({json: {botName: '콩이', character: {...character, introMissing: !current},
                                     features: {}, google: 'off', usageToday: {limit: null}}});
      }
      if (address === '/chat/api/voices') {
        return route.fulfill({json: {voices: [{name: 'Puck', label: '견본 목소리', sampleUrl: '/chat/voices/Puck'}]}});
      }
      const file = ASSETS[address] || (address === '/chat/me' ? 'profile.html' :
        address === '/chat/me/voice' ? 'voice.html' : address.startsWith(ROUTE) ? 'character.html' : null);
      if (!file) return route.fulfill({status: 404});
      const type = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : 'text/html';
      return route.fulfill({contentType: type + '; charset=utf-8', body: await readFile(path.join(STATIC, file))});
    });

    await page.clock.setFixedTime(new Date('2026-11-21T03:00:00Z'));
    await page.goto(FIXTURE + ROUTE + 'name');
    await page.getByLabel('이름', {exact: true}).fill('콩이');
    await page.getByRole('button', {name: '다 됐어'}).click();
    await page.waitForURL('**/intro?from=create');
    await page.getByRole('heading', {name: '아이 소개'}).waitFor();
    const save = page.getByRole('button', {name: '저장할래'});
    await save.waitFor();
    assert.equal(await save.evaluate(button => button.disabled), true);
    for (const name of ['먹보', '얌전함', '호기심 많음']) await page.getByRole('button', {name, exact: true}).click();
    assert.equal(await page.getByRole('button', {name: '활발함'}).evaluate(button => button.disabled), true);
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'chestnut');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 360);
    await page.getByLabel('좋아하는 것').fill('고구마');
    await page.getByLabel('부르는 말').fill('누나');
    failSave = true;
    await save.click();
    await page.getByText('입력한 내용을 한 번 확인해 줘').waitFor();
    assert.equal(await page.getByLabel('좋아하는 것').inputValue(), '고구마');
    failSave = false;
    await save.click();
    await page.getByRole('button', {name: '견본 듣기'}).waitFor();
    assert.deepEqual(written, {personality: ['먹보', '얌전함', '호기심 많음'], likes: '고구마',
                               dislikes: '', ownerCall: '누나'});
    await page.getByRole('link', {name: '좋아', exact: true}).click();
    await page.waitForURL('**/try');

    await page.clock.setFixedTime(new Date('2026-11-21T13:00:00Z'));
    await page.goto(FIXTURE + '/chat/me');
    await page.getByRole('link', {name: '아이 소개'}).click();
    assert.equal(await page.getByLabel('부르는 말').inputValue(), '누나');
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'night');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 360);
    await page.getByLabel('부르는 말').fill('언니');
    await save.click();
    await page.getByText('콩이가 새로 기억했어').waitFor();

    current = null;
    await page.goto(FIXTURE + ROUTE + 'intro?from=create');
    await page.getByRole('link', {name: '나중에 할래'}).click();
    await page.waitForURL('**/try');
    assert.equal(current, null);
  } finally {
    await browser.close();
  }
});
