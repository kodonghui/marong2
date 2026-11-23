'use strict';

// TC-606 on an empty Android 16 AVD with the TC-222 fixtures plus UpdateFixtureReceiver.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const { readFileSync } = require('node:fs');
const { performance } = require('node:perf_hooks');
const { setTimeout: delay } = require('node:timers/promises');
const { startEmulatorSite } = require('./emulator-site.cjs');

const PACKAGE = 'com.corthexhq.marong';
const [serial, oldApk, newApk, mode = 'states'] = process.argv.slice(2);
assert.match(serial ?? '', /^emulator-\d+$/);
assert.match(mode, /^(states|retry)$/);

function adb(...args) {
  return execFileSync(process.env.ADB || 'adb', ['-s', serial, ...args], {
    encoding: 'utf8', timeout: 120_000, stdio: ['ignore', 'pipe', 'pipe']
  }).trim();
}

function fixture(mode, ...args) {
  adb('shell', 'am', 'broadcast', '-n', `${PACKAGE}/.UpdateFixtureReceiver`, '--es', 'mode', mode, ...args);
}

async function waitFor(probe, timeout, description) {
  const until = performance.now() + timeout;
  do {
    if (probe()) return;
    await delay(400);
  } while (performance.now() < until);
  assert.fail(description);
}

async function main() {
  assert.equal(adb('shell', 'getprop', 'ro.build.version.sdk'), '36');
  assert.equal(adb('shell', 'getprop', 'ro.kernel.qemu'), '1');
  assert.equal(adb('shell', 'pm', 'list', 'packages', PACKAGE), '');
  const apk = readFileSync(newApk);
  const path = '/chat/app/marong-0.3.2-10.apk';
  const update = { release: null, apk, mode: 'normal', apkDelayMs: 5000 };
  const deviceUpdate = {};
  const site = await startEmulatorSite({ port: 18787, update, deviceUpdate });
  const requests = site.deviceUpdateRequests;
  const open = () => adb('shell', 'am', 'start', '-n', `${PACKAGE}/.MainActivity`);
  const home = () => adb('shell', 'input', 'keyevent', 'KEYCODE_HOME');
  const failure = (status) => fixture('report-failure', '--ei', 'status', String(status));
  const count = (number, timeout = 30_000) => waitFor(() => requests.length >= number, timeout, `Expected ${number} device updates`);
  try {
    adb('install', oldApk);
    adb('shell', 'pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS');
    adb('shell', 'appops', 'set', PACKAGE, 'REQUEST_INSTALL_PACKAGES', 'allow');
    open();
    await waitFor(() => site.reports.length && site.updateRequests.length, 45_000, 'App did not register');
    home();
    await delay(1500);
    if (mode === 'retry') {
      deviceUpdate.status = 503;
      failure(101);
      await count(1);
      const start = performance.now();
      await waitFor(() => /Minimum latency: \+14m\d+s/.test(adb('shell', `dumpsys jobscheduler ${PACKAGE} | grep -A 35 '  JOB #.*/2217:'`)),
        10_000, 'Android did not schedule a 15-minute network retry');
      deviceUpdate.status = 200;
      await count(2, 18 * 60_000);
      const seconds = (performance.now() - start) / 1000;
      assert.ok(seconds >= 895, 'Retry occurred before the 15-minute delay');
      assert.deepEqual(requests.map(r => r.status), [503, 200]);
      console.log(`PASS retry_seconds=${seconds.toFixed(3)} statuses=503,200`);
      return;
    }

    const ring = site.reports[0].ring;
    fixture('prepare-push');
    update.release = { versionCode: 10, versionName: '0.3.2', size: apk.length,
      sha256: createHash('sha256').update(apk).digest('hex'), url: path };
    fixture('update-push', '--es', 'version', '10');
    await waitFor(() => site.updateRequests.some(request => request.path === path), 30_000, 'Background download did not start');
    open();
    await count(2);
    assert.deepEqual(requests.map(request => request.update.state), ['downloaded', 'waiting_quiet']);
    home();
    await count(3, 5 * 60_000);
    assert.match(adb('shell', 'dumpsys', 'package', PACKAGE), /versionCode=10\b/);
    assert.deepEqual(requests[2].update, { versionCode: 10, state: 'installed' });
    assert.equal(requests[2].appVersion, '0.3.2');
    for (const request of requests) {
      assert.deepEqual(request.ring, ring);
      assert.equal(request.method, 'PUT');
      assert.deepEqual(request.keys, ['appVersion', 'fid', 'notifications', 'ring', 'update']);
      assert.equal(request.origin, 'http://10.0.2.2:18787');
      assert.match(request.agent, /^MarongApp\/0\.3\.[12]$/);
      assert.ok(request.hasFixtureCookie);
      const transportHeaders = new Set(['host', 'connection', 'content-length', 'accept-encoding']);
      assert.deepEqual(request.headers.filter(header => !transportHeaders.has(header)),
        ['accept', 'content-type', 'cookie', 'origin', 'user-agent']);
    }

    failure(101);
    await count(4);
    failure(101);
    await delay(1000);
    assert.equal(requests.length, 4);
    failure(102);
    await count(5);
    assert.deepEqual(requests.slice(3).map(r => r.update.status), [101, 102]);

    deviceUpdate.status = 302;
    failure(111);
    await count(6);
    await delay(1000);
    deviceUpdate.status = 200;
    assert.equal(requests.length, 6);
    const pageReports = site.reports.length;
    open();
    await count(7);
    assert.ok(site.reports.length >= pageReports + 2, 'A successful WebView report must precede the native retry');
    home();

    for (const [http, number, expected] of [[400, 112, 8], [409, 113, 9]]) {
      deviceUpdate.status = http;
      failure(number);
      await count(expected);
      assert.equal(requests[expected - 1].status, http);
      await waitFor(() => !adb('shell', `dumpsys jobscheduler ${PACKAGE} | grep '  JOB #.*/2217:' || true`),
        10_000, `Native job remained queued after ${http}`);
    }
    assert.equal(requests.length, 9);
    console.log('PASS reports=9 states=downloaded,waiting_quiet,installed dedup=101,102 resume=302,200 discarded=400,409 ring=preserved');
  } finally {
    adb('uninstall', PACKAGE);
    await site.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
