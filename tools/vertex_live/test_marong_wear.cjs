'use strict';
// TC-766: run with the same Playwright dependency used by apps/android.
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {chromium} = require('../../apps/android/node_modules/playwright');
const {startCallSite} = require('../../apps/android/test/support/call-site.cjs');
const blank = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aLhcAAAAASUVORK5CYII=', 'base64');

test('TC-766 default face layers survive changes and missing files', async () => {
  const site = await startCallSite();
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({viewport:{width:360,height:780},reducedMotion:'reduce'});
    const paths = ['body-item','neck-item','head-item'].map(id => `/chat/decor/v1/${id}/marong.png`);
    let missing = false, enabled = true;
    await page.route('**/chat/api/profile', r => r.fulfill({json:{botName:'마롱이',character:null,
      ...(enabled ? {marongOutfit:{body:{layerUrl:paths[0]},neck:{layerUrl:paths[1]},head:{layerUrl:paths[2]}}} : {})}}));
    await page.route('**/chat/decor/**', r => missing && r.request().url().includes('neck-item')
      ? r.fulfill({status:404}) : r.fulfill({contentType:'image/png',body:blank}));
    await page.goto(site.url);
    await page.waitForFunction(() => document.querySelectorAll('.outfit-layer').length === 3);
    const positions = await page.locator('#face, .outfit-layer').evaluateAll(images => images.map(i => {
      const box=i.getBoundingClientRect(); return [box.x,box.y,box.width,box.height];
    }));
    assert.ok(positions.every(p => p.every((v,i) => Math.abs(v-positions[0][i]) < 1)));
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.evaluate(() => { intended=true; speaking=true; });
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.face-disc')).transform !== 'none', null, {timeout:2000});
    const moving = await page.locator('#face, .outfit-layer').evaluateAll(images => images.map(i=>{const b=i.getBoundingClientRect();return [b.x,b.y,b.width,b.height]}));
    assert.ok(moving.every(p => p.every((v,i) => Math.abs(v-moving[0][i]) < 1)));
    await page.waitForFunction(() => document.querySelector('.face-disc').classList.contains('talk-bounce-4'), null, {timeout:2000});
    await page.waitForFunction(() => document.querySelector('.face-disc').classList.contains('talk-bounce-2'), null, {timeout:2000});
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.face-disc')).transform === 'none');
    for (const id of ['01-neutral','02-big-laugh','03-listening','04-thinking','05-excited','06-sad','07-crying',
      '08-surprised','09-pouting','10-shy','11-drowsy','12-asleep','13-concerned','15-mouth-slightly-open',
      '16-mouth-wide-open','18-eyes-half-closed','19-eyes-closed','20-mouth-slightly-open-eyes-half-closed',
      '21-mouth-slightly-open-eyes-closed','22-mouth-wide-open-eyes-half-closed','23-mouth-wide-open-eyes-closed']) {
      await page.locator('#face').evaluate((img,name) => img.src='/face/v1/'+name+'.webp',id);
      assert.deepEqual(await page.locator('.outfit-layer').evaluateAll(a=>a.map(i=>i.getAttribute('src'))),paths);
    }
    missing = true;
    await page.reload();
    await page.waitForFunction(() => document.querySelectorAll('.outfit-layer').length === 2);
    assert.equal(await page.locator('#face').isVisible(),true);
    enabled=false;
    await page.emulateMedia({reducedMotion:'no-preference'});
    const loaded=page.waitForResponse(r=>r.url().endsWith('/chat/api/profile'));
    await page.reload();
    await loaded;
    await page.evaluate(() => { intended=true; speaking=true; });
    await page.waitForTimeout(500);
    assert.equal(await page.locator('.face-disc').evaluate(el=>getComputedStyle(el).transform),'none');
  } finally { await browser.close(); await site.close(); }
});
