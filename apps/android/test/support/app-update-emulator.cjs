'use strict';

// Run only on an isolated Android 16 AVD using same-key debug APKs built with
// server.url=http://10.0.2.2:18787 and cleartext enabled in the fixture copy.
// node test/support/app-update-emulator.cjs <emulator-serial> <old.apk> <new.apk> <mode>
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const { readFileSync } = require('node:fs');
const { performance } = require('node:perf_hooks');
const { setTimeout: delay } = require('node:timers/promises');
const { startEmulatorSite } = require('./emulator-site.cjs');

const PACKAGE = 'com.corthexhq.marong';
const PORT = 18787;
const APK_PATH = '/chat/app/marong-0.3.2-10.apk';
const INSTALL_JOB = 2212;
const LIMIT_MS = 15 * 60 * 1000;
const [serial, oldApk, newApk, mode = 'normal'] = process.argv.slice(2);

assert.match(serial ?? '', /^emulator-\d+$/);
assert.ok(oldApk && newApk, 'Supply version-code 9 and 10 debug APKs');
assert.match(mode, /^(normal|idle|rare|restricted|rare-idle|restricted-idle|fallback)$/);

function adb(...args) {
  return execFileSync(process.env.ADB || 'adb', ['-s', serial, ...args], {
    encoding: 'utf8', timeout: 30_000, maxBuffer: 8 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe']
  }).replace(/\r/g, '').trim();
}

function jobState(id) {
  try {
    return adb('shell', 'cmd', 'jobscheduler', 'get-job-state', PACKAGE, String(id));
  } catch (error) {
    if (error.status === 23 && error.stderr.includes('Could not find job')) return 'absent';
    throw error;
  }
}

function version() {
  return Number(adb('shell', 'dumpsys', 'package', PACKAGE).match(/versionCode=(\d+)/)?.[1]);
}

function installJob() {
  const jobs = adb('shell', 'dumpsys', 'jobscheduler', PACKAGE);
  return jobs.match(new RegExp(`  JOB #.*?/${INSTALL_JOB}:.*(?:\\n(?!  JOB #).*)*`))?.[0] ?? '';
}

async function waitFor(probe, timeoutMs, description, interval = 500) {
  const start = performance.now();
  do {
    if (probe()) return performance.now() - start;
    await delay(interval);
  } while (performance.now() - start < timeoutMs);
  assert.fail(description);
}

async function main() {
  assert.equal(adb('shell', 'getprop', 'ro.build.version.sdk'), '36');
  assert.equal(adb('shell', 'getprop', 'ro.kernel.qemu'), '1');
  assert.ok(!adb('shell', 'pm', 'list', 'packages', PACKAGE), 'Use an AVD with no Marong installation');
  const apk = readFileSync(newApk);
  const update = {
    release: null, apk, mode: 'redirect'
  };
  const site = await startEmulatorSite({ port: PORT, update });
  const launch = (...extras) => adb('shell', 'am', 'start', '-a', 'android.intent.action.MAIN',
    '-n', PACKAGE + '/.MainActivity', ...extras);
  try {
    assert.match(adb('install', oldApk), /Success/);
    assert.equal(version(), 9);
    adb('shell', 'pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS');
    adb('shell', 'appops', 'set', PACKAGE, 'REQUEST_INSTALL_PACKAGES', 'allow');
    adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP');
    adb('shell', 'wm', 'dismiss-keyguard');
    // Establish an existing app task before simulating the notification tap.
    // The initial sign-in redirect does not advance the six-hour clock.
    launch();
    await waitFor(() => site.updateRequests.some((request) => request.path.endsWith('/release')),
      60_000, 'Warm-up release request did not arrive');
    await waitFor(() => jobState(2210) === 'absent', 30_000, 'Warm-up check still pending');
    adb('shell', 'input', 'keyevent', 'KEYCODE_HOME');
    site.updateRequests.length = 0;
    update.release = {
      versionCode: 10, versionName: '0.3.2', size: apk.length,
      sha256: createHash('sha256').update(apk).digest('hex'), url: APK_PATH
    };
    update.mode = 'normal';
    // These launcher extras simulate a tap in Firebase's background notification path.
    launch('--es', 'kind', 'proactive', '--es', 'open', '/chat/');
    await waitFor(() => site.updateRequests.some((request) => request.path === APK_PATH),
      60_000, 'Release APK was not downloaded');
    await waitFor(() => jobState(INSTALL_JOB) !== 'absent', 45_000,
      'A verified APK did not produce the deferred installation job');
    const requests = site.updateRequests.filter((request) => request.path === APK_PATH);
    assert.equal(requests.length, 1);
    assert.equal(version(), 9, 'Installer replaced the app while its activity was visible');
    const deadline = installJob().match(/Max execution delay: .*/)?.[0];
    console.log(`mode=${mode} downloads=${requests.length} before_home=9 deadline=${deadline ?? 'absent'}`);
    const bucket = mode.split('-')[0];
    if (mode.endsWith('idle')) {
      adb('shell', 'dumpsys', 'battery', 'unplug');
      assert.match(adb('shell', 'dumpsys', 'deviceidle', 'force-idle'), /deep idle mode/);
    }
    if (bucket === 'rare' || bucket === 'restricted') {
      adb('shell', 'am', 'set-standby-bucket', PACKAGE, bucket);
    }
    const pid = mode === 'fallback' ? adb('shell', 'pidof', PACKAGE) : null;
    if (pid !== null) assert.match(pid, /^\d+$/);
    const backgrounded = performance.now();
    if (mode === 'fallback') {
      // Isolate the durable fallback by simulating process reclamation during the transition.
      // Killing this PID, unlike force-stop, retains the job and the downloaded APK.
      adb('shell', `run-as ${PACKAGE} kill -STOP ${pid} && input keyevent KEYCODE_HOME; run-as ${PACKAGE} kill -9 ${pid}`);
      assert.equal(jobState(2213), 'absent', 'Fast job ran during the backup-only trial');
    } else {
      adb('shell', 'input', 'keyevent', 'KEYCODE_HOME');
    }
    console.log(`bucket=${adb('shell', 'am', 'get-standby-bucket', PACKAGE)} idle=${adb('shell', 'cmd', 'deviceidle', 'get', 'deep')}`);
    try {
      if (mode === 'normal') {
        await waitFor(() => jobState(2213) !== 'absent' || version() === 10, 60_000,
          'TC-222: leaving the app should enqueue the fast install in the active bucket');
      }
      await waitFor(() => version() === 10, LIMIT_MS - (performance.now() - backgrounded),
        'TC-222: no natural 9 → 10 install within 15 minutes of leaving the app', 2_000);
    } finally {
      console.log(`elapsed_seconds=${((performance.now() - backgrounded) / 1000).toFixed(3)} installed=${version()}`);
      console.log(`install_job=${jobState(INSTALL_JOB)}`);
      const logs = adb('logcat', '-d', '-s', 'MarongUpdate:I');
      console.log(logs.split('\n').filter((line) => /update_(install|verify|download)/.test(line)).slice(-20).join('\n'));
    }
    assert.equal(deadline, 'Max execution delay: +14m0s0ms', 'BUG-112: backup job deadline');
    await waitFor(() => jobState(2211) !== 'absent', 30_000, 'The replacement did not rearm the daily check');
    await waitFor(() => !adb('shell', 'run-as', PACKAGE, 'find', 'cache', '-name', 'marong-10.apk'),
      30_000, 'The staged APK was not cleaned');
  } finally {
    try {
      if (mode.endsWith('idle')) {
        adb('shell', 'dumpsys', 'deviceidle', 'unforce');
        adb('shell', 'dumpsys', 'battery', 'reset');
      }
      adb('uninstall', PACKAGE);
    } catch (error) {
      console.error('AVD cleanup failed:', error.message);
    } finally {
      await site.close();
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
