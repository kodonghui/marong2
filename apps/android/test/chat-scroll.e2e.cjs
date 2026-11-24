'use strict';
// TC-650 (BUG-123, SCR-107, SPEC-124/148/149): real chat assets and a local scripted API.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { startChatSite, ME } = require('./support/chat-site.cjs');

let playwright;
try { playwright = require('playwright'); } catch {}
const skip = playwright ? false : 'Install Playwright and its WebKit browser to run TC-650';

async function measure(page, step) {
  return page.evaluate(async (step) => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const root = document.scrollingElement;
    const log = document.getElementById('log');
    const { width, height, offsetTop } = window.visualViewport;
    const composer = document.getElementById('composer').getBoundingClientRect();
    return {
      step,
      rootY: window.scrollY,
      documentHeight: root.scrollHeight,
      layoutHeight: root.clientHeight,
      visualViewport: { width, height, offsetTop },
      composerTop: composer.top,
      composerBottom: composer.bottom,
      logY: log.scrollTop,
      logHeight: log.scrollHeight,
      logBottomGap: log.scrollHeight - log.scrollTop - log.clientHeight,
      scrollEvents: window.scrollEvents,
    };
  }, step);
}

for (const resizeForKeyboard of [false, true]) {
  const name = resizeForKeyboard ? 'emulated keyboard opens and closes' : 'viewport stays the same';
  test(`TC-650: iPhone WebKit keeps chat scrolling inside the list (${name})`, { skip, timeout: 30_000 }, async (t) => {
    const site = await startChatSite({ waitMs: 1100 });
    t.after(() => site.close());
    site.state.me.body = { ...ME, name: '시험친구 가' };
    for (let i = 0; i < 36; i++) site.add(i % 2 ? 'me' : 'marong', `합성 메시지 ${i}`);
    const sentId = site.state.nextId;

    const browser = await playwright.webkit.launch();
    t.after(() => browser.close());
    const phone = playwright.devices['iPhone 13'];
    const context = await browser.newContext(phone);
    const page = await context.newPage();
    await page.goto(`${site.url}/chat/`);
    await page.locator(`#messages li[data-id="${sentId - 1}"]`).waitFor();
    await page.evaluate(() => {
      const log = document.getElementById('log');
      window.scrollEvents = { root: 0, viewport: 0, log: 0 };
      window.addEventListener('scroll', () => window.scrollEvents.root++);
      window.visualViewport.addEventListener('scroll', () => window.scrollEvents.viewport++);
      log.addEventListener('scroll', () => window.scrollEvents.log++);
    });
    const ready = await measure(page, 'ready');

    const text = page.locator('#text');
    await text.tap();
    await text.fill('합성 전송');
    // Desktop WebKit has no iOS software keyboard. Resize its viewport, keeping native scroll metrics.
    if (resizeForKeyboard) await page.setViewportSize({ ...phone.viewport, height: 430 });
    const opening = await measure(page, 'focused');
    await page.locator('#send').tap();
    const sent = page.locator(`#messages li[data-id="${sentId}"]`);
    await sent.waitFor();
    const posted = await measure(page, 'sent');

    site.takeUp(sentId);
    await sent.locator('.read').waitFor();
    const typing = page.locator('#typing');
    await typing.waitFor();
    const waiting = await measure(page, 'typing');
    await page.waitForResponse(response => {
      const url = new URL(response.url());
      return url.pathname === '/chat/api/messages/wait' && url.searchParams.get('typing') === '1';
    });
    const stillWaiting = await measure(page, 'typing after another poll');

    if (resizeForKeyboard) {
      await text.blur();
      await page.setViewportSize(phone.viewport);
    }
    const closing = await measure(page, 'before root scroll');
    await page.evaluate(() => window.scrollBy(0, 250));
    const rootScroll = await measure(page, 'after attempted root scroll');

    site.answer(sentId, '합성 답변');
    await page.getByText('합성 답변', { exact: true }).waitFor();
    await typing.waitFor({ state: 'hidden' });
    assert.equal(await sent.locator('.read').count(), 0);
    const reply = await measure(page, 'reply');

    const samples = [ready, opening, posted, waiting, stillWaiting, closing, rootScroll, reply];
    t.diagnostic(JSON.stringify(samples));
    assert.equal(opening.visualViewport.height, resizeForKeyboard ? 430 : ready.visualViewport.height);
    assert.equal(closing.visualViewport.height, ready.visualViewport.height);
    assert.equal(stillWaiting.logY, waiting.logY, 'an unchanged poll must not move the list');
    assert.deepEqual(stillWaiting.scrollEvents, waiting.scrollEvents, 'the viewport and list must stay still while waiting');
    for (const sample of samples) {
      assert.equal(sample.documentHeight, sample.layoutHeight, `document gained scrollable height at ${sample.step}`);
      assert.equal(sample.rootY, 0, `document scroll changed at ${sample.step}`);
      assert.ok(sample.composerTop >= sample.visualViewport.offsetTop &&
        sample.composerBottom <= sample.visualViewport.offsetTop + sample.visualViewport.height,
      `composer must fit in the visible viewport at ${sample.step}`);
    }
    for (const sample of [posted, waiting, stillWaiting, closing, rootScroll, reply]) {
      assert.ok(Math.abs(sample.logBottomGap) <= 1, `latest message must stay in view at ${sample.step}`);
    }
  });
}
