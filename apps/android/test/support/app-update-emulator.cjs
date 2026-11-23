'use strict';

// Run only on an isolated Android 16 AVD using same-key debug APKs built with
// server.url=http://10.0.2.2:18787 and cleartext enabled in the fixture copy.
// Leave at least 35 seconds between runs on the same AVD so Android's silent
// update throttling does not turn the next install into a confirmation test.
// The foreign-task mode uses a fixture whose MainActivity launchMode is standard.
// Call modes use UpdateFixtureReceiver in a test-only APK. The reopen-at-commit
// fixture calls its pauseBeforeCommit() on the worker just before the final commit decision.
// See docs/12-qa/app-update.md for the BUG-112 fixture build steps.
// node test/support/app-update-emulator.cjs <emulator-serial> <old.apk> <new.apk> <mode>
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const { readFileSync, writeFileSync } = require('node:fs');
const { performance } = require('node:perf_hooks');
const { setTimeout: delay } = require('node:timers/promises');
const { startEmulatorSite } = require('./emulator-site.cjs');

const PACKAGE = 'com.corthexhq.marong';
const PORT = 18787;
const APK_PATH = '/chat/app/marong-0.3.2-10.apk';
const INSTALL_JOB = 2212;
const LIMIT_MS = 15 * 60 * 1000;
const BUSY_RETRY_MS = 2 * 60 * 1000;
const [serial, oldApk, newApk, mode = 'normal'] = process.argv.slice(2);

assert.match(serial ?? '', /^emulator-\d+$/);
assert.ok(oldApk && newApk, 'Supply version-code 9 and 10 debug APKs');
assert.match(mode, /^(normal|idle|rare|restricted|rare-idle|restricted-idle|fallback|fallback-idle|fallback-busy-idle|lock|visible-alarm|foreign-task|no-backup|call|call-no-permission|call-dismissed|ring|reopen-at-commit)$/);
const fallback = mode.startsWith('fallback');
const call = mode.startsWith('call');
const logMarker = `tc222_${process.pid}_${Date.now()}`;

function adb(...args) {
  return execFileSync(process.env.ADB || 'adb', ['-s', serial, ...args], {
    encoding: 'utf8', timeout: args[0] === 'install' ? 120_000 : 30_000, maxBuffer: 8 * 1024 * 1024,
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

function activeNotification(id) {
  return adb('shell', 'cmd', 'notification', 'list').includes(`|${PACKAGE}|${id}|`);
}

const callNotification = () => activeNotification(101);

function foregroundCall() {
  return /isForeground=true\s+foregroundId=101\b/.test(adb('shell', 'dumpsys', 'activity', 'services', PACKAGE));
}

async function dismissCallNotification() {
  adb('shell', 'cmd', 'statusbar', 'expand-notifications');
  try {
    const shadeImage = process.env.MARONG_TC222_SHADE_PNG;
    if (shadeImage) {
      // The live call timer can prevent UI Automator from reaching an idle state.
      await delay(1_000);
      writeFileSync(shadeImage, execFileSync(process.env.ADB || 'adb', ['-s', serial, 'exec-out', 'screencap', '-p'], { timeout: 30_000 }));
      console.log(`notification_shade=${shadeImage}`);
      await waitFor(() => !callNotification(), 120_000, 'Swipe the call card off the synthetic AVD');
      return;
    }
    let bounds;
    await waitFor(() => {
      const tree = adb('shell', 'uiautomator dump /sdcard/marong-tc222.xml >/dev/null && cat /sdcard/marong-tc222.xml');
      bounds = tree.match(/text="Fixture[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]/);
      return Boolean(bounds);
    }, 15_000, 'The call notification was not visible in the shade');
    const [, left, top, , bottom] = bounds.map(Number);
    const y = Math.floor((top + bottom) / 2);
    const widths = [...adb('shell', 'wm', 'size').matchAll(/size: (\d+)x\d+/g)];
    const rightEdge = Number(widths.at(-1)?.[1]) - 1;
    assert.ok(rightEdge > left, 'No usable screen width for the swipe');
    adb('shell', 'input', 'swipe', String(left + 8), String(y), String(rightEdge), String(y), '300');
    await waitFor(() => !callNotification(), 10_000, 'Android did not dismiss the call notification');
  } finally {
    adb('shell', 'cmd', 'statusbar', 'collapse');
    adb('shell', 'rm', '-f', '/sdcard/marong-tc222.xml');
  }
}

async function waitFor(probe, timeoutMs, description, interval = 500) {
  const start = performance.now();
  do {
    if (probe()) return performance.now() - start;
    await delay(interval);
  } while (performance.now() - start < timeoutMs);
  assert.fail(description);
}

async function assertBusyAlarm(uid) {
  const held = await waitFor(() => /alarm_busy|committed code=10/.test(updateLogs()),
    8 * 60_000, 'The alarm did not inspect the busy app', 2_000);
  const logs = updateLogs();
  assert.match(logs, /alarm_busy/);
  assert.equal(version(), 9, 'A busy alarm must leave the staged update uninstalled');
  assert.doesNotMatch(jobHistory(uid), /\/2215\b/, 'A busy alarm must not start the install job');
  const delays = [...logs.matchAll(/update_install alarm_armed delay_ms=(\d+)/g)];
  assert.equal(delays.length, 2, 'The first busy alarm must arm one follow-up');
  const nextDelay = Number(delays[1][1]);
  const alarm = adb('shell', `dumpsys alarm | grep -A 1 -F 'tag=*walarm*:${PACKAGE}.APP_UPDATE_RETRY' || true`)
    .match(/\btype=ELAPSED_WAKEUP origWhen=([^\s]+) window=([^\s]+)/);
  assert.ok(alarm, 'Android must retain the new wakeup alarm');
  console.log(`busy_wait_seconds=${(held / 1000).toFixed(3)} version=9 alarm_job_started=false next_alarm_ms=${nextDelay}`);
  console.log(`alarm_requested_in=${alarm[1]} alarm_window=${alarm[2]}`);
  assert.equal(nextDelay, BUSY_RETRY_MS, 'TC-222: the process-independent retry must use the short delay');
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
  const fixture = (action) => adb('shell', 'am', 'broadcast', '-n', `${PACKAGE}/.UpdateFixtureReceiver`, '--es', 'mode', action);
  try {
    adb('shell', 'log', '-t', 'MarongUpdate', logMarker);
    assert.match(adb('install', oldApk), /Success/);
    assert.equal(version(), 9);
    adb('shell', 'pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS');
    if (mode === 'call-no-permission') {
      adb('shell', 'pm', 'revoke', PACKAGE, 'android.permission.POST_NOTIFICATIONS');
      assert.doesNotMatch(adb('shell', 'dumpsys', 'package', PACKAGE), /POST_NOTIFICATIONS: granted=true/);
      console.log('notification_permission=false');
    }
    if (call) adb('shell', 'pm', 'grant', PACKAGE, 'android.permission.RECORD_AUDIO');
    adb('shell', 'appops', 'set', PACKAGE, 'REQUEST_INSTALL_PACKAGES', 'allow');
    adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP');
    adb('shell', 'wm', 'dismiss-keyguard');
    // Establish an existing app task before simulating the notification tap.
    // The initial sign-in redirect does not advance the six-hour clock.
    launch();
    await waitFor(() => site.updateRequests.some((request) => request.path.endsWith('/release')),
      120_000, 'Warm-up release request did not arrive');
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
    // A slow fixture transfer must not use up the post-deferral installation budget.
    await waitFor(() => jobState(INSTALL_JOB) !== 'absent', 180_000,
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
    if (mode === 'visible-alarm' || mode === 'foreign-task' || mode === 'fallback-busy-idle') {
      await assertBusyAlarm(uid);
    }
    if (mode === 'fallback-busy-idle') {
      assert.match(adb('shell', 'dumpsys', 'activity', 'activities'), /topResumedActivity=.*com\.corthexhq\.marong/,
        'The app must still be on screen when the first alarm defers');
    }
    if (mode === 'lock') {
      assert.match(adb('shell', 'locksettings', 'set-pin', '3179'), /set to/);
      secured = true;
    }
    if (call) {
      fixture('call-on');
      await waitFor(foregroundCall, 15_000, 'The native microphone service did not reach foreground');
      if (mode !== 'call-no-permission') await waitFor(callNotification, 15_000, 'The call notification did not appear');
      if (mode === 'call-dismissed') await dismissCallNotification();
      assert.equal(callNotification(), mode === 'call');
      assert.ok(foregroundCall(), 'Hiding the notification must leave the microphone service running');
    }
    if (mode === 'ring') {
      fixture('ring');
      await waitFor(() => activeNotification(201), 15_000, 'The bell notification did not appear');
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
    let backgrounded = performance.now();
    if (fallback) {
      // Isolate the durable fallback by simulating process reclamation during the transition.
      // Killing this PID, unlike force-stop, retains the job and the downloaded APK.
      adb('shell', `run-as ${PACKAGE} kill -STOP ${pid} && input keyevent KEYCODE_HOME; run-as ${PACKAGE} kill -9 ${pid}`);
      await waitFor(() => adb('shell', `pidof ${PACKAGE} || true`) !== pid,
        5_000, 'The original app process was not reclaimed');
      console.log('original_process_reclaimed=true');
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
    if (call) {
      await delay(8_000);
      assert.equal(version(), 9, 'TC-222: installed while the microphone service was active');
      if (mode === 'call-no-permission') {
        await assertBusyAlarm(uid);
      }
      assert.ok(foregroundCall());
      assert.equal(callNotification(), mode === 'call');
      assertNoFastInstall(uid);
      console.log(`call_held_seconds=${((performance.now() - backgrounded) / 1000).toFixed(3)} foreground=true notification_101=${callNotification()} version=9`);
      fixture('call-off');
      await waitFor(() => !foregroundCall(), 15_000, 'The microphone service did not stop');
      backgrounded = performance.now();
    }
    if (mode === 'ring') {
      await delay(3_000);
      assert.equal(version(), 9, 'TC-222: installed while the bell was active');
      assert.ok(activeNotification(201));
      assertNoFastInstall(uid);
      await waitFor(() => !activeNotification(201), 75_000, 'The bell notification did not expire');
      console.log('ring_held=true version=9');
      backgrounded = performance.now();
    }
    if (mode === 'reopen-at-commit') {
      await waitFor(() => /fixture_waiting_to_commit/.test(updateLogs()), 5 * 60_000, 'The job did not reach the commit barrier');
      launch();
      await waitFor(() => /topResumedActivity=.*com\.corthexhq\.marong/.test(adb('shell', 'dumpsys', 'activity', 'activities')),
        10_000, 'The app window did not reopen during the install');
      await waitFor(() => /deferred_before_commit|committed code=10/.test(updateLogs()), 30_000,
        'The commit barrier was not released');
      assert.doesNotMatch(updateLogs(), /committed code=10/, 'TC-222: committed after the app window reopened');
      assert.equal(version(), 9);
      console.log('reopened_during_install=true deferred_before_commit=true version=9');
      backgrounded = performance.now();
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
