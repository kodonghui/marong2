'use strict';
// TC-619 / BUG-113. Only run with the local Android 16 debug fixtures described in docs/12-qa/app-update.md.
// node app-update-chat-emulator.cjs <emulator-serial> <code-12.apk> <code-13.apk> [second-module-delay-ms]
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { readFileSync, writeFileSync } = require('node:fs');
const http = require('node:http');
const { setTimeout: sleep } = require('node:timers/promises');
const { startEmulatorSite } = require('./emulator-site.cjs');
const [serial, seedApk, nextApk, delay = '1200'] = process.argv.slice(2);
const delayMs = Number(delay);
assert.ok(seedApk && nextApk, 'Supply code-12 and code-13 debug APKs');
assert.ok(Number.isInteger(delayMs) && delayMs >= 0);
const pkg = 'com.corthexhq.marong';
const updateLog = 'FixtureFcm';
let attempt = 0;
assert.match(serial, /^emulator-\d+$/);
function adb(...args) {
  return execFileSync(process.env.ADB, ['-s', serial, ...args], {
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
    timeout: args[0] === 'install' ? 120_000 : 30_000,
  }).replace(/\r/g, '').trim();
}
function version() {
  return Number(adb('shell', 'dumpsys', 'package', pkg).match(/versionCode=(\d+)/)?.[1]);
}
function foreground() {
  return adb('shell', 'dumpsys', 'activity', 'activities').match(/topResumedActivity=([^\n]+)/)?.[1] ?? '';
}
function notices() {
  return adb('shell', 'cmd', 'notification', 'list').split('\n').filter(line => line.includes('|' + pkg + '|'));
}
const callActive = () => notices().some(line => line.includes('|' + pkg + '|101|'));
const callControl = mode => adb('shell', 'am', 'broadcast', '-n', pkg + '/.UpdateFixtureReceiver', '--es', 'mode', mode);
async function waitFor(check, label, budget = 45_000) {
  const end = Date.now() + budget;
  for (; Date.now() < end; await sleep(250)) {
    const state = await check();
    if (state) return state;
  }
  assert.fail(label);
}
function install(apk, expected) {
  assert.match(adb('install', apk), /Success/);
  assert.equal(version(), expected);
}
function grant() {
  adb('shell', 'pm', 'grant', pkg, 'android.permission.POST_NOTIFICATIONS');
  adb('shell', 'pm', 'grant', pkg, 'android.permission.RECORD_AUDIO');
  adb('shell', 'appops', 'set', pkg, 'REQUEST_INSTALL_PACKAGES', 'allow');
}
const launch = () => adb('shell', 'am', 'start', '-W', '-n', pkg + '/.MainActivity');
async function minimize() {
  await waitFor(() => foreground().includes(pkg), 'The app did not become visible before pressing Home');
  adb('shell', 'input', 'keyevent', 'KEYCODE_HOME');
  // Use the emulator's launcher intent if a cold WebView delayed input dispatch.
  await sleep(700);
  if (!/Launcher/.test(foreground())) {
    adb('shell', 'am', 'start', '-W', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.HOME');
  }
  await waitFor(() => /Launcher/.test(foreground()), 'Android home never appeared');
}
function checkPending() {
  try {
    adb('shell', 'cmd', 'jobscheduler', 'get-job-state', pkg, '2210');
    return true;
  } catch (error) {
    if (error.status === 23 && error.stderr.includes('Could not find job')) return false;
    throw error;
  }
}
async function warm(site) {
  launch();
  await waitFor(() => site.updateRequests.length > 0, 'No warm-up release request', 90_000);
  await waitFor(() => !checkPending(), 'Warm-up job stayed scheduled');
}
async function fakeFcm() {
  const inbox = new Map();
  const delivered = [];
  const server = http.createServer((req, res) => {
    const code = Number(new URL(req.url, 'http://localhost').pathname.match(/^\/inbox\/(\d+)$/)?.[1]);
    const pending = inbox.get(code) ?? [];
    const message = pending.shift();
    if (!message) return res.writeHead(204).end();
    delivered.push({ code, kind: message.data.kind });
    res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify(message));
  });
  await new Promise(resolve => server.listen(18788, '127.0.0.1', resolve));
  return {
    send(code, message) {
      inbox.set(code, [...(inbox.get(code) ?? []), message]);
    },
    delivered,
    async close() {
      server.closeAllConnections();
      await new Promise(resolve => server.close(resolve));
    },
  };
}
async function deliver(fcm, code, message) {
  const marker = 'fixture_fcm_' + Date.now() + '_' + ++attempt;
  adb('shell', 'log', '-t', updateLog, marker);
  const before = fcm.delivered.length;
  fcm.send(code, message);
  await waitFor(() => fcm.delivered.length > before, 'Fake FCM envelope was not received over HTTP');
  const expected = 'callback kind=' + message.data.kind + ' notification=' + Boolean(message.notification);
  await waitFor(() => adb('logcat', '-d', '-s', updateLog).split(marker).at(-1).includes(expected),
    'The Firebase callback did not return with the expected payload type');
}
async function evaluate(target, expression) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    const timer = setTimeout(() => { ws.close(); reject(new Error('WebView evaluation timed out')); }, 4500);
    ws.addEventListener('open', () => ws.send(JSON.stringify({
      id: 1, method: 'Runtime.evaluate', params: { expression, returnByValue: true, awaitPromise: true, userGesture: true },
    })));
    ws.addEventListener('message', event => {
      const reply = JSON.parse(event.data);
      if (reply.id !== 1) return;
      clearTimeout(timer);
      ws.close();
      if (reply.error || reply.result?.exceptionDetails) reject(new Error('WebView evaluation returned an exception'));
      else resolve(reply.result?.result?.value);
    });
    ws.addEventListener('error', () => {
      clearTimeout(timer);
      reject(new Error('WebView debugger socket did not open'));
    });
  });
}
const snapshot = `(() => {
  const banner = document.querySelector('#update-banner');
  const module = performance.getEntriesByType('resource').find(entry =>
    new URL(entry.name).pathname === '/chat/update-banner.js');
  return {
    visible: document.visibilityState === 'visible', bridge: window.__marongApp?.version,
    banner: banner && (banner.hidden ? 'none' : banner.dataset.updateState),
    origin: performance.timeOrigin, moduleMs: module?.duration ?? null,
    firstContent: document.querySelector('#messages li[data-id]') !== null
  };
})()`;
let chatTarget;
async function findVisibleChat(previous) {
  const pid = adb('shell', 'pidof', pkg).split(/\s+/)[0];
  if (!pid) return null;
  adb('forward', 'tcp:19225', 'localabstract:webview_devtools_remote_' + pid);
  const response = await fetch('http://127.0.0.1:19225/json/list', { signal: AbortSignal.timeout(3000) })
    .catch(() => null);
  if (!response?.ok) return null;
  const pages = (await response.json()).filter(page => new URL(page.url).pathname === '/chat/');
  const visible = [];
  for (const page of pages) {
    const state = await evaluate(page, snapshot);
    if (state.visible && state.bridge === 3 && state.banner
        && (!previous || page.id !== previous.id || state.origin !== previous.state.origin)) {
      visible.push({ page, state });
    }
  }
  visible.sort((a, b) => b.state.origin - a.state.origin);
  return visible[0];
}
const evaluateChat = expression => evaluate(chatTarget.page, expression);
const bannerState = () => evaluateChat(snapshot).then(state => state.banner);
async function tapNotification(title) {
  const previous = chatTarget && { id: chatTarget.page.id, state: chatTarget.state };
  await waitFor(() => notices().some(line => line.includes('|marong_talk|')), 'Proactive notification was never posted');
  console.log('fixture_notification_posted title=' + title);
  adb('shell', 'cmd', 'statusbar', 'expand-notifications');
  await sleep(700);
  const shade = process.env.MARONG_TC619_SHADE_PNG;
  if (shade) {
    writeFileSync(shade, execFileSync(process.env.ADB, ['-s', serial, 'exec-out', 'screencap', '-p'], { timeout: 10_000 }));
    console.log('TC-619 tap the posted notification: ' + shade);
  } else {
    assert.match(adb('shell', 'wm', 'size'), /Physical size: 320x640/);
    adb('shell', 'input', 'tap', '120', '279');
  }
  await waitFor(() => foreground().includes(pkg + '/.ChatActivity'), 'Notification tap did not open chat', 90_000);
  chatTarget = await waitFor(() => findVisibleChat(previous), 'The visible chat WebView or its v3 bridge did not load');
  console.log('TC-619 foreground_chat=' + (previous ? 2 : 1));
}
async function current(site, fcm, update, apk, updateBanner) {
  try {
    install(seedApk, 12);
    grant();
    await warm(site);
    callControl('call-on');
    await waitFor(callActive, 'Foreground call service did not start');
    await minimize();
    const proactive = title => ({ data: { kind: 'proactive', open: '/chat/' }, notification: { title, body: 'Synthetic QA message' } });
    await deliver(fcm, 12, proactive('QA fixture one'));
    await tapNotification('QA fixture one');
    assert.equal(await bannerState(), 'none');
    const beforeNotices = notices().length;
    const beforeRequests = site.updateRequests.length;
    update.release = {
      versionCode: 13, versionName: '0.3.5', size: apk.length,
      sha256: createHash('sha256').update(apk).digest('hex'), url: '/chat/app/marong-0.3.5-13.apk',
    };
    await deliver(fcm, 12, { data: { kind: 'app_update', v: '13' } });
    await waitFor(async () => await bannerState() === 'ready', 'Staged download did not render the late chat banner', 95_000);
    const requests = site.updateRequests.slice(beforeRequests);
    assert.equal(requests.filter(r => r.path.endsWith('/release')).length, 1);
    assert.equal(requests.filter(r => r.path === update.release.url).length, 1);
    assert.equal(notices().length, beforeNotices);
    console.log('TC-601 code=12 callback=1 release_requests=1 apk_requests=1 added_notifications=0');
    const busy = await evaluateChat("new Promise(resolve=>{const b=document.querySelector('#update-banner');const observer=new MutationObserver(()=>{if(b.dataset.updateState==='busy'){observer.disconnect();resolve(b.querySelector('button').disabled);}});observer.observe(b,{attributeFilter:['data-update-state']});setTimeout(()=>{observer.disconnect();resolve(false)},3000);b.querySelector('button').click();})");
    assert.equal(busy, true);
    assert.equal(version(), 12);
    await waitFor(async () => await bannerState() === 'ready', 'The busy banner did not return to ready');
    await minimize();
    updateBanner.delayMs = delayMs;
    await deliver(fcm, 12, proactive('QA fixture two'));
    await tapNotification('QA fixture two');
    const loaded = await waitFor(async () => {
      const result = await evaluateChat(snapshot);
      return result.firstContent && result.moduleMs !== null && result;
    }, 'The reopened chat did not load its messages and update module');
    const elapsedModule = Math.round(loaded.moduleMs);
    console.log('TC-619 second_chat_module_ms=' + elapsedModule + ' banner_on_load=' + loaded.banner);
    if (delayMs >= 500) assert.ok(elapsedModule >= 500, 'The test did not delay the module past the deadline');
    try {
      await waitFor(async () => await bannerState() === 'ready', 'The staged banner stayed hidden in the visible reopened chat', 6000);
    } catch (error) {
      const native = await evaluateChat("window.__marongApp.updateState().then(update => update.state)");
      console.log('TC-619 second_chat_banner=' + await bannerState() + ' native=' + native);
      throw error;
    }
    assert.equal(await evaluateChat("document.querySelector('.update-version').textContent.trim()"), '(0.3.5)');
    callControl('call-off');
    await waitFor(() => !callActive(), 'Foreground call service did not stop');
    const started = performance.now();
    await evaluateChat("document.querySelector('#update-banner button').click(); true");
    await waitFor(() => version() === 13, 'The manual install did not replace the APK', 90_000);
    const elapsed = ((performance.now()-started)/1000).toFixed(3);
    launch();
    await waitFor(() => foreground().includes(pkg), 'The installed app would not open');
    console.log('TC-619 notifications_tapped=2 late_banner=ready busy_block=1 before=12 after=13 reopened=1 install_seconds=' + elapsed);
  } finally {
    try { if (adb('forward', '--list').includes('tcp:19225')) adb('forward', '--remove', 'tcp:19225'); } finally { adb('uninstall',pkg); }
  }
}
async function main() {
  assert.equal(adb('shell', 'getprop', 'ro.kernel.qemu'), '1');
  assert.equal(adb('shell', 'getprop', 'ro.build.version.sdk'), '36');
  assert.equal(adb('shell', 'pm', 'list', 'packages', pkg), '');
  adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP');
  adb('shell', 'wm', 'dismiss-keyguard');
  adb('reverse', 'tcp:18787', 'tcp:18787');
  adb('reverse', 'tcp:18788', 'tcp:18788');
  const next = readFileSync(nextApk);
  const update = { release: null, apk: next, mode: 'normal' };
  const updateBanner = { delayMs: 0 };
  const site = await startEmulatorSite({ port: 18787, update, updateBanner });
  site.chat.add('marong', 'Synthetic QA message');
  const fcm = await fakeFcm();
  try {
    await current(site, fcm, update, next, updateBanner);
  } finally {
    await Promise.all([site.close(), fcm.close()]);
  }
}
main().catch(error => { console.error(error); process.exitCode=1; });
