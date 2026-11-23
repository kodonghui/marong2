'use strict';

// TC-603/604. Use the TC-222 debug fixtures, with UpdateFixtureReceiver in code 9.
// For the TC-604 fault run, have the fixture's scheduler boundary return rejection
// for the expedited push check. The ordinary job still runs through Android.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const { readFileSync } = require('node:fs');
const { performance } = require('node:perf_hooks');
const { setTimeout: delay } = require('node:timers/promises');
const { startEmulatorSite } = require('./emulator-site.cjs');

const PACKAGE = 'com.corthexhq.marong';
const [serial, oldApk, newApk, bucket = 'rare', schedule = 'expedited'] = process.argv.slice(2);
assert.match(serial ?? '', /^emulator-\d+$/);
assert.match(bucket, /^(rare|restricted)$/);
assert.match(schedule, /^(expedited|fallback)$/);

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
    await delay(200);
  } while (performance.now() < until);
  assert.fail(description);
}

async function main() {
  assert.equal(adb('shell', 'getprop', 'ro.build.version.sdk'), '36');
  assert.equal(adb('shell', 'getprop', 'ro.kernel.qemu'), '1');
  assert.equal(adb('shell', 'pm', 'list', 'packages', PACKAGE), '');
  const apk = readFileSync(newApk);
  const path = '/chat/app/marong-0.3.2-10.apk';
  const update = { release: null, apk, mode: 'normal' };
  const site = await startEmulatorSite({ port: 18787, update });
  try {
    adb('install', oldApk);
    adb('shell', 'pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS');
    adb('shell', 'am', 'start', '-n', `${PACKAGE}/.MainActivity`);
    await waitFor(() => site.updateRequests.length > 0, 30_000, 'Initial release check did not run');
    adb('shell', 'input', 'keyevent', 'KEYCODE_HOME');
    adb('shell', 'am', 'set-standby-bucket', PACKAGE, bucket);
    assert.equal(adb('shell', 'am', 'get-standby-bucket', PACKAGE), bucket === 'rare' ? '40' : '45');
    fixture('prepare-push');
    site.updateRequests.length = 0;
    update.release = { versionCode: 10, versionName: '0.3.2', size: apk.length,
      sha256: createHash('sha256').update(apk).digest('hex'), url: path };
    const marker = `tc60x_${process.pid}_${Date.now()}`;
    adb('shell', 'log', '-t', 'MarongUpdate', marker);
    const start = performance.now();
    fixture('update-push', '--es', 'version', '10');
    await waitFor(() => site.updateRequests.some(r => r.path === path), 60_000, 'APK request did not start');
    const seconds = ((performance.now() - start) / 1000).toFixed(3);
    assert.deepEqual(site.updateRequests.map(r => r.path), ['/chat/api/app/release', path]);
    const log = adb('logcat', '-d', '-s', 'MarongUpdate:I');
    assert.ok(log.includes(marker));
    assert.match(log.slice(log.lastIndexOf(marker)), new RegExp(`update_push ${schedule}\\b`));
    assert.ok(!adb('shell', 'cmd', 'notification', 'list').includes(`|${PACKAGE}|`));
    console.log(`PASS bucket=${bucket} job=${schedule} download_started_seconds=${seconds} requests=2 notifications=0`);
  } finally {
    adb('uninstall', PACKAGE);
    await site.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
