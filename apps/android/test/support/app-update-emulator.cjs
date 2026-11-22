'use strict';

// Run only on an isolated Android 16 AVD using same-key debug APKs built with
// server.url=http://10.0.2.2:18787 and cleartext enabled in the fixture copy.
// Leave at least 35 seconds between runs on the same AVD so Android's silent
// update throttling does not turn the next install into a confirmation test.
// The foreign-task mode uses a fixture whose MainActivity launchMode is standard.
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
assert.match(mode, /^(normal|idle|rare|restricted|rare-idle|restricted-idle|fallback|fallback-idle|lock|visible-alarm|foreign-task|no-backup)$/);
const fallback = mode.startsWith('fallback');
const logMarker = `tc222_${process.pid}_${Date.now()}`;

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
  return adb('shell', `dumpsys jobscheduler ${PACKAGE} | grep -A 35 '  JOB #.*/${INSTALL_JOB}:' || true`);
}

function lockedAndAwake() {
  return /mKeyguardShowing=true/.test(adb('shell', 'dumpsys', 'activity', 'activities'))
    && /mWakefulness=Awake/.test(adb('shell', 'dumpsys', 'power'));
}

function updateLogs() {
  const logs = adb('logcat', '-d', '-s', 'MarongUpdate:I');
  assert.ok(logs.includes(logMarker), 'The current trial must be present in logcat');
  return logs.slice(logs.lastIndexOf(logMarker) + logMarker.length);
}

function jobHistory(uid) {
  return adb('shell', `dumpsys jobscheduler | grep 'START: #${uid}/221[235] ' || true`);
}

function assertNoFastInstall(uid) {
  assert.equal(jobState(2213), 'absent');
  assert.doesNotMatch(updateLogs(), /expedited_scheduled|started job=2213\b/,
    'The activity-triggered install was scheduled or started in the current trial');
  assert.doesNotMatch(jobHistory(uid), /\/2213\b/, 'Android ran the activity-triggered install');
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
  let siteClosed = false;
  let secured = false;
  const launch = (...extras) => adb('shell', 'am', 'start', '-a', 'android.intent.action.MAIN',
    '-n', PACKAGE + '/.MainActivity', ...extras);
  try {
    adb('shell', 'log', '-t', 'MarongUpdate', logMarker);
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
    await waitFor(() => /topResumedActivity=.*Launcher/.test(adb('shell', 'dumpsys', 'activity', 'activities')),
      10_000, 'The launcher did not take over from the warm-up activity');
    let foreignTask;
    if (mode === 'foreign-task') {
      adb('shell', 'am', 'start', '-a', 'android.settings.SETTINGS');
      await waitFor(() => {
        foreignTask = adb('shell', 'dumpsys', 'activity', 'activities')
          .match(/topResumedActivity=.* com\.android\.settings\/\S+ t(\d+)}/)?.[1];
        return foreignTask !== undefined;
      }, 10_000, 'No foreground Settings task to host the app window');
    }
    site.updateRequests.length = 0;
    update.release = {
      versionCode: 10, versionName: '0.3.2', size: apk.length,
      sha256: createHash('sha256').update(apk).digest('hex'), url: APK_PATH
    };
    update.mode = 'normal';
    // These launcher extras simulate a tap in Firebase's background notification path.
    launch(...(foreignTask ? ['--task', foreignTask] : []), '--es', 'kind', 'proactive', '--es', 'open', '/chat/');
    if (foreignTask) {
      const top = new RegExp(`topResumedActivity=.*${PACKAGE.replaceAll('.', '\\.')}\\/.MainActivity t${foreignTask}}`);
      await waitFor(() => top.test(adb('shell', 'dumpsys', 'activity', 'activities')),
        10_000, 'The app window is not visible in the foreign task');
      console.log('visible_in_settings_task=true');
    }
    await waitFor(() => site.updateRequests.some((request) => request.path === APK_PATH),
      60_000, 'Release APK was not downloaded');
    await waitFor(() => jobState(INSTALL_JOB) !== 'absent', 45_000,
      'A verified APK did not produce the deferred installation job');
    const requests = site.updateRequests.filter((request) => request.path === APK_PATH);
    assert.equal(requests.length, 1);
    assert.equal(version(), 9, 'Installer replaced the app while its activity was visible');
    const job = installJob();
    const uid = job.match(/JOB #(u\d+a\d+)\/2212:/)?.[1];
    assert.ok(uid, 'The backup job should identify the app UID');
    const deadline = job.match(/Max execution delay: .*/)?.[0];
    console.log(`mode=${mode} downloads=${requests.length} before_home=9 deadline=${deadline ?? 'absent'}`);
    assert.equal(deadline, 'Max execution delay: +14m0s0ms', 'BUG-112: backup job deadline');
    const backoff = job.match(/Backoff: .*/)?.[0];
    assert.equal(backoff, 'Backoff: policy=0 initial=+15m0s0ms', 'BUG-112: linear backup job backoff');
    console.log(backoff);
    await waitFor(() => /alarm_armed/.test(updateLogs())
      && adb('shell', `dumpsys alarm | grep '${PACKAGE}.APP_UPDATE_RETRY' || true`).includes('APP_UPDATE_RETRY'),
    5_000, 'BUG-112: no process-independent alarm was armed');
    if (mode === 'no-backup') {
      adb('shell', 'cmd', 'jobscheduler', 'cancel', PACKAGE, String(INSTALL_JOB));
      assert.equal(jobState(INSTALL_JOB), 'absent', 'The ordinary backup job must be absent');
    }
    if (mode === 'visible-alarm' || mode === 'foreign-task') {
      const held = await waitFor(() => /deferred_before_verify job=2215\b/.test(updateLogs()),
        8 * 60_000, 'The app stayed on screen without the alarm reaching its visibility check', 2_000);
      assert.equal(version(), 9, 'The visible window must still prevent installation');
      assert.equal(updateLogs().match(/update_install alarm_armed/g)?.length, 2, 'The alarm must be armed again');
      console.log(`held_seconds=${(held / 1000).toFixed(3)} version=9 before_verify=true alarm_rearmed=true`);
    }
    if (mode === 'lock') {
      assert.match(adb('shell', 'locksettings', 'set-pin', '3179'), /set to/);
      secured = true;
    }
    const bucket = mode.split('-')[0];
    const expectedBucket = { rare: '40', restricted: '45' }[bucket];
    if (mode.endsWith('idle')) {
      adb('shell', 'dumpsys', 'battery', 'unplug');
      assert.match(adb('shell', 'dumpsys', 'deviceidle', 'force-idle'), /deep idle mode/);
    }
    if (expectedBucket) {
      adb('shell', 'am', 'set-standby-bucket', PACKAGE, bucket);
    }
    const pid = fallback ? adb('shell', 'pidof', PACKAGE) : null;
    if (pid !== null) assert.match(pid, /^\d+$/);
    const backgrounded = performance.now();
    if (fallback) {
      // Isolate the durable fallback by simulating process reclamation during the transition.
      // Killing this PID, unlike force-stop, retains the job and the downloaded APK.
      adb('shell', `run-as ${PACKAGE} kill -STOP ${pid} && input keyevent KEYCODE_HOME; run-as ${PACKAGE} kill -9 ${pid}`);
      assertNoFastInstall(uid);
      await site.close();
      siteClosed = true;
    } else if (mode === 'lock') {
      adb('shell', 'input', 'keyevent', 'KEYCODE_SLEEP');
      await waitFor(() => /mKeyguardShowing=true/.test(adb('shell', 'dumpsys', 'activity', 'activities')),
        10_000, 'The secure lock screen was not engaged');
      adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP');
      await waitFor(lockedAndAwake, 10_000, 'The screen did not wake to the secure lock screen');
    } else {
      adb('shell', 'input', 'keyevent', 'KEYCODE_HOME');
    }
    let appliedBucket;
    if (expectedBucket) {
      // A usage event from the foreground activity can reset a forced bucket during Home.
      await waitFor(() => {
        adb('shell', 'am', 'set-standby-bucket', PACKAGE, bucket);
        appliedBucket = adb('shell', 'am', 'get-standby-bucket', PACKAGE);
        return appliedBucket === expectedBucket;
      }, 5_000, `Android did not apply the ${bucket} bucket`, 100);
    } else {
      appliedBucket = adb('shell', 'am', 'get-standby-bucket', PACKAGE);
    }
    const idle = adb('shell', 'cmd', 'deviceidle', 'get', 'deep');
    console.log(`bucket=${appliedBucket} idle=${idle}`);
    if (mode.endsWith('idle')) assert.equal(idle, 'IDLE');
    try {
      if (!fallback && (mode === 'normal' || mode.endsWith('idle'))) {
        await waitFor(() => jobState(2213) !== 'absent' || version() === 10, 60_000,
          'TC-222: leaving the app should enqueue the fast install when ordinary work may be delayed');
      }
      await waitFor(() => version() === 10, LIMIT_MS - (performance.now() - backgrounded),
        'TC-222: no natural 9 → 10 install within 15 minutes of leaving the app', 2_000);
      assert.ok(performance.now() - backgrounded <= LIMIT_MS, 'TC-222: installation observed after 15 minutes');
    } finally {
      console.log(`elapsed_seconds=${((performance.now() - backgrounded) / 1000).toFixed(3)} installed=${version()}`);
      console.log(`install_job=${jobState(INSTALL_JOB)}`);
      const logs = updateLogs();
      console.log(logs.split('\n').filter((line) => /update_(install|verify|download)/.test(line)).slice(-20).join('\n'));
    }
    if (fallback) {
      assertNoFastInstall(uid);
      assert.match(updateLogs(), /update_install alarm_fired/);
      assert.match(updateLogs(), /update_install started job=2215\b/);
      const starts = jobHistory(uid);
      assert.match(starts, /\/2215\b/);
      assert.doesNotMatch(starts, /\/2212\b/);
      console.log('job_2213_started=false job_2215_started=true job_2212_started=false');
    }
    if (mode === 'lock') {
      assert.ok(lockedAndAwake(), 'The lock screen should still be visible after installation');
      console.log('keyguard_showing=true screen_awake=true');
    }
    if (mode === 'no-backup') {
      const starts = jobHistory(uid);
      assert.match(starts, /\/2213\b/);
      assert.doesNotMatch(starts, /\/221[25]\b/);
      console.log('job_2212_started=false job_2213_started=true job_2215_started=false');
    }
    await waitFor(() => jobState(2211) !== 'absent', 30_000, 'The replacement did not rearm the daily check');
    await waitFor(() => !adb('shell', 'run-as', PACKAGE, 'find', 'cache', '-name', 'marong-10.apk'),
      30_000, 'The staged APK was not cleaned');
  } finally {
    try {
      if (secured) {
        adb('shell', 'locksettings', 'clear', '--old', '3179');
        adb('shell', 'wm', 'dismiss-keyguard');
      }
      if (mode.endsWith('idle')) {
        adb('shell', 'dumpsys', 'deviceidle', 'unforce');
        adb('shell', 'dumpsys', 'battery', 'reset');
      }
      adb('uninstall', PACKAGE);
    } catch (error) {
      console.error('AVD cleanup failed:', error.message);
    } finally {
      if (!siteClosed) await site.close();
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
