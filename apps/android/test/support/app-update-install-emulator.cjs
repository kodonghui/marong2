'use strict';

// TC-610 and the native part of TC-619. Use the TC-222 debug APKs with UpdateFixtureReceiver.
// Set MARONG_UPDATE_PORT if the fixture APKs point to a different loopback test port.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const { readFileSync } = require('node:fs');
const { performance } = require('node:perf_hooks');
const { setTimeout: delay } = require('node:timers/promises');
const { startEmulatorSite } = require('./emulator-site.cjs');

const PACKAGE = 'com.corthexhq.marong';
const PORT = Number(process.env.MARONG_UPDATE_PORT || 18787);
const ORIGIN = process.env.MARONG_UPDATE_ORIGIN || 'http://10.0.2.2:' + PORT;
const [serial, oldApk, newApk, mode = 'install'] = process.argv.slice(2);
assert.match(serial ?? '', /^emulator-\d+$/);
assert.match(mode, /^(install|confirm)$/);

function adb(...args) {
  return execFileSync(process.env.ADB || 'adb', ['-s', serial, ...args], {
    encoding: 'utf8', timeout: 120_000, stdio: ['ignore', 'pipe', 'pipe']
  }).trim();
}

function fixture(mode, ...args) {
  adb('shell', 'am', 'broadcast', '-n', PACKAGE + '/.UpdateFixtureReceiver', '--es', 'mode', mode, ...args);
}

async function waitFor(probe, timeout, description) {
  const until = performance.now() + timeout;
  do {
    const result = await probe();
    if (result) return result;
    await delay(400);
  } while (performance.now() < until);
  assert.fail(description);
}

async function evaluate(page, expression) {
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  try {
    const result = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('WebView did not answer')), 12_000);
      ws.addEventListener('open', () => ws.send(JSON.stringify({
        id: 1, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true },
      })), { once: true });
      ws.addEventListener('message', (event) => {
        clearTimeout(timer);
        const message = JSON.parse(event.data);
        if (message.error || message.result?.exceptionDetails) reject(new Error('WebView evaluation failed'));
        else resolve(message.result.result.value);
      }, { once: true });
      ws.addEventListener('error', () => { clearTimeout(timer); reject(new Error('WebView socket failed')); }, { once: true });
    });
    return result;
  } finally {
    ws.close();
  }
}

async function main() {
  assert.equal(adb('shell', 'getprop', 'ro.build.version.sdk'), '36');
  assert.equal(adb('shell', 'getprop', 'ro.kernel.qemu'), '1');
  assert.equal(adb('shell', 'pm', 'list', 'packages', PACKAGE), '');
  const apk = readFileSync(newApk);
  const update = { release: null, apk, mode: 'normal' };
  const site = await startEmulatorSite({ port: PORT, update });
  let debugPort;
  const shell = (...args) => adb('shell', ...args);
  const open = () => shell('am', 'start', '-W', '-n', PACKAGE + '/.MainActivity');
  const active = (id) => shell('cmd', 'notification', 'list').includes('|' + PACKAGE + '|' + id + '|');
  const version = () => Number(shell('dumpsys', 'package', PACKAGE).match(/versionCode=(\d+)/)?.[1]);
  try {
    adb('install', oldApk);
    shell('pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS');
    shell('pm', 'grant', PACKAGE, 'android.permission.RECORD_AUDIO');
    shell('appops', 'set', PACKAGE, 'REQUEST_INSTALL_PACKAGES', mode === 'install' ? 'allow' : 'deny');
    open();
    const pid = await waitFor(() => shell('pidof ' + PACKAGE + ' || true'), 10_000, 'App process did not start');
    debugPort = Number(adb('forward', 'tcp:0', 'localabstract:webview_devtools_remote_' + pid));
    const pageAt = async (path) => {
      const find = async () => {
        try {
          const pages = await fetch('http://127.0.0.1:' + debugPort + '/json/list', { signal: AbortSignal.timeout(1000) }).then(r => r.json());
          return pages.find(page => page.url === ORIGIN + path);
        } catch { return null; }
      };
      return waitFor(find, 60_000, 'Missing WebView ' + path);
    };
    const call = await pageAt('/');
    const bridgeVersion = (page) => evaluate(page, 'window.__marongApp?.version');
    await waitFor(async () => (await bridgeVersion(call)) === 3, 10_000, 'Call page bridge did not start');
    assert.deepEqual(await evaluate(call, 'window.__marongApp.installUpdate()'), { state: 'none' });
    await evaluate(call, "document.getElementById('chat-link').click(); true");
    const chat = await pageAt('/chat/');
    await waitFor(async () => (await bridgeVersion(chat)) === 3, 10_000, 'Chat page bridge did not start');
    await waitFor(() => site.reports.length, 20_000, 'WebView device report did not start');
    for (const page of [call, chat]) {
      await evaluate(page, "window.fixtureUpdates=0; addEventListener('marongupdate', () => window.fixtureUpdates++); true");
      assert.deepEqual(await evaluate(page, 'window.__marongApp.updateState()'), { state: 'none' });
    }

    const path = '/chat/app/marong-0.3.2-10.apk';
    fixture('prepare-push');
    update.release = { versionCode: 10, versionName: '0.3.2', size: apk.length,
      sha256: createHash('sha256').update(apk).digest('hex'), url: path };
    fixture('update-push', '--es', 'version', '10');
    for (const page of [call, chat]) {
      await waitFor(() => evaluate(page, 'window.fixtureUpdates'), 30_000, 'No marongupdate in a WebView');
      assert.deepEqual(await evaluate(page, 'window.__marongApp.updateState()'), { state: 'ready', versionName: '0.3.2' });
    }
    assert.equal(version(), 9);

    if (mode === 'install') {
      for (const [start, stop, id] of [['call-on', 'call-off', 101], ['ring', 'ring-off', 201]]) {
        fixture(start);
        await waitFor(() => active(id), 15_000, 'Busy notification missing: ' + id);
        assert.deepEqual(await evaluate(chat, 'window.__marongApp.installUpdate()'), { state: 'busy' });
        assert.equal(version(), 9);
        fixture(stop);
        await waitFor(() => !active(id), 8_000, 'Busy notification remained: ' + id);
      }
    }

    const marker = 'tc610_' + process.pid + '_' + Date.now();
    shell('log', '-t', 'MarongUpdate', marker);
    const logs = () => {
      const log = adb('logcat', '-d', '-s', 'MarongUpdate:I');
      assert.ok(log.includes(marker));
      return log.slice(log.lastIndexOf(marker) + marker.length);
    };
    const request = 'Promise.all([window.__marongApp.installUpdate(), window.__marongApp.installUpdate()])';
    const start = performance.now();
    assert.deepEqual(await evaluate(chat, request), [{ state: 'installing' }, { state: 'installing' }]);
    if (mode === 'install') {
      await waitFor(() => version() === 10, 45_000, 'Visible-window install did not update the app');
      open();
      await waitFor(() => site.deviceUpdateRequests.some(r => r.appVersion === '0.3.2'), 30_000, 'New app did not open');
    } else {
      await waitFor(() => /confirmation_opened code=10/.test(logs()), 20_000, 'Manual confirmation did not open');
      const foreground = shell('dumpsys', 'activity', 'activities');
      assert.match(foreground, /(?:mResumedActivity|topResumedActivity)[=:].*(?:packageinstaller|AppInstaller|unknownapps)/i);
      assert.equal(active(301), false, 'No update notification should be posted for the direct confirmation');
      assert.equal(version(), 9);
    }
    assert.equal((logs().match(/committed code=10/g) || []).length, 1);
    console.log('PASS mode=' + mode + ' windows=2 commits=1 elapsed_seconds=' + ((performance.now() - start) / 1000).toFixed(3)
      + ' version=' + version() + ' call_and_ring=' + (mode === 'install' ? 'busy' : 'not_run'));
  } finally {
    if (debugPort) adb('forward', '--remove', 'tcp:' + debugPort);
    adb('uninstall', PACKAGE);
    await site.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
