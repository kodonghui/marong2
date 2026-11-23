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
assert.match(mode, /^(install|confirm|confirm-retained|paused|superseded|current|offline)$/);

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
      const timer = setTimeout(() => reject(new Error('WebView did not answer: ' + expression)), 20_000);
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
  const candidate = () => {
    const prefs = shell('run-as', PACKAGE, 'cat', 'shared_prefs/marong_update.xml');
    const release = prefs.match(/<string name="release">(.*?)<\/string>/)?.[1];
    return release ? JSON.parse(release.replaceAll('&quot;', '"')) : null;
  };
  const power = () => shell('dumpsys', 'power');
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
    let installPage = call;
    const pages = [call];
    if (mode === 'install') {
      await evaluate(call, "document.getElementById('chat-link').click(); true");
      installPage = await pageAt('/chat/');
      await waitFor(async () => (await bridgeVersion(installPage)) === 3, 10_000, 'Chat page bridge did not start');
      pages.push(installPage);
    }
    await waitFor(() => site.reports.length, 20_000, 'WebView device report did not start');
    for (const page of pages) {
      await evaluate(page, "window.fixtureUpdates=0; addEventListener('marongupdate', () => window.fixtureUpdates++); true");
      assert.deepEqual(await evaluate(page, 'window.__marongApp.updateState()'), { state: 'none' });
    }

    const path = '/chat/app/marong-0.3.2-10.apk';
    fixture('prepare-push');
    update.release = { versionCode: 10, versionName: '0.3.2', size: apk.length,
      sha256: createHash('sha256').update(apk).digest('hex'), url: path };
    fixture('update-push', '--es', 'version', '10');
    const ready = { state: 'ready', versionName: '0.3.2' };
    await waitFor(async () => (await evaluate(installPage, 'window.__marongApp.updateState()')).state === ready.state,
      45_000, 'Candidate was not ready in the WebView');
    if (mode === 'install') {
      for (const page of pages) {
        await waitFor(() => evaluate(page, 'window.fixtureUpdates'), 30_000, 'No marongupdate in a WebView');
        assert.deepEqual(await evaluate(page, 'window.__marongApp.updateState()'), ready);
      }
    }
    assert.equal(version(), 9);

    if (mode === 'install') {
      for (const [start, stop, id] of [['call-on', 'call-off', 101], ['ring', 'ring-off', 201]]) {
        fixture(start);
        await waitFor(() => active(id), 15_000, 'Busy notification missing: ' + id);
        assert.deepEqual(await evaluate(installPage, 'window.__marongApp.installUpdate()'), { state: 'busy' });
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
    if (['paused', 'superseded', 'current', 'offline'].includes(mode)) {
      fixture('prepare-push');
      if (mode === 'paused') update.release = null;
      if (mode === 'superseded') update.release = { ...update.release, sha256: 'a'.repeat(64) };
      if (mode === 'offline') update.mode = 'disconnect';
      const before = site.updateRequests.length;
      const expected = mode === 'paused' || mode === 'superseded' ? 'none' : 'installing';
      assert.deepEqual(await evaluate(installPage, 'window.__marongApp.installUpdate()'), { state: expected });
      const checks = site.updateRequests.slice(before);
      assert.ok(checks.length > 0);
      assert.ok(checks.every(check => check.path === '/chat/api/app/release'));
      if (mode !== 'offline') assert.equal(checks.length, 1);
      if (expected === 'none') {
        assert.deepEqual(await evaluate(installPage, 'window.__marongApp.updateState()'), { state: 'none' });
        await waitFor(() => candidate() === null, 10_000, 'The discarded candidate remained on disk');
        assert.equal(version(), 9);
        assert.doesNotMatch(logs(), /committed code=10/);
        console.log(`PASS mode=${mode} release_checks=1 commits=0 version=9`);
        return;
      }
      console.log(`PASS mode=${mode} release_checks=${checks.length} proceeded=true`);
    } else {
      assert.deepEqual(await evaluate(installPage, request), [{ state: 'installing' }, { state: 'installing' }]);
    }
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
      if (mode === 'confirm-retained') {
        const session = candidate()?.session;
        assert.ok(session >= 0, 'Manual confirmation must have an installer session');
        const runBackup = async () => {
          await waitFor(() => /mWakefulness=(?:Asleep|Dozing)/.test(power()),
            15_000, 'Screen did not turn off');
          const starts = (logs().match(/started job=2212\b/g) || []).length;
          assert.match(shell('cmd', 'jobscheduler', 'run', '-f', PACKAGE, '2212'), /Running job/);
          await waitFor(() => (logs().match(/started job=2212\b/g) || []).length > starts,
            15_000, 'Backup job did not run');
          await waitFor(() => !/\bactive\b/.test(shell(`cmd jobscheduler get-job-state ${PACKAGE} 2212 || true`)),
            15_000, 'Backup job did not finish');
        };
        shell('input', 'keyevent', 'KEYCODE_SLEEP');
        await runBackup();
        assert.equal(candidate()?.session, session, 'The backup job replaced the open manual session');
        assert.equal(active(301), false);

        shell('input', 'keyevent', 'KEYCODE_WAKEUP');
        shell('wm', 'dismiss-keyguard');
        shell('input', 'keyevent', 'KEYCODE_BACK');
        await waitFor(() => /permission_session_ended code=10/.test(logs()),
          15_000, 'Installer did not report cancellation after Back');
        assert.equal(candidate()?.session, -1);
        fixture('schedule-install-job');
        shell('input', 'keyevent', 'KEYCODE_SLEEP');
        await runBackup();
        assert.equal(candidate()?.session, -1, 'The backup job restarted the cancelled manual installation');
        assert.equal(active(301), false);
        console.log('PASS manual_session_retained=true permission_cancel_retained=true install_notifications=0');
      }
    }
    assert.equal((logs().match(/committed code=10/g) || []).length, 1);
    console.log('PASS mode=' + mode + ' windows=' + pages.length + ' commits=1 elapsed_seconds=' + ((performance.now() - start) / 1000).toFixed(3)
      + ' version=' + version() + ' call_and_ring=' + (mode === 'install' ? 'busy' : 'not_run'));
  } finally {
    shell('input', 'keyevent', 'KEYCODE_WAKEUP');
    if (debugPort) adb('forward', '--remove', 'tcp:' + debugPort);
    adb('uninstall', PACKAGE);
    await site.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
