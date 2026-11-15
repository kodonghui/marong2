'use strict';
// TC-118 and TC-133 (docs/app-chat.md): app settings that the device tests depend on, read from the source
// files, and from the merged manifest when a build is there.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const APP = path.join(__dirname, '..');
const read = (...parts) => fs.readFileSync(path.join(APP, ...parts), 'utf8');
const manifest = read('android', 'app', 'src', 'main', 'AndroidManifest.xml');
const config = JSON.parse(read('capacitor.config.json'));

const OWN_PERMISSIONS = [
  'android.permission.ACCESS_NETWORK_STATE', // SPEC-108: navigator.onLine and "online" in the WebView (BUG-101)
  'android.permission.FOREGROUND_SERVICE', // SPEC-103
  'android.permission.FOREGROUND_SERVICE_MICROPHONE', // SPEC-103
  'android.permission.INTERNET',
  'android.permission.MODIFY_AUDIO_SETTINGS', // SPEC-106
  'android.permission.POST_NOTIFICATIONS', // SPEC-103, messages (app-chat SPEC-121), rings (app-ring SPEC-132)
  'android.permission.RECORD_AUDIO', // SPEC-106
  'android.permission.USE_FULL_SCREEN_INTENT', // app-ring SPEC-132, SPEC-133: the ring screen over the lock screen
];
// What the built app asks for once the libraries' manifests are merged in (docs/app-chat.md TC-133).
const MERGED_PERMISSIONS = [
  ...OWN_PERMISSIONS,
  'android.permission.WAKE_LOCK', // firebase-messaging: wake the phone for a message
  'com.google.android.c2dm.permission.RECEIVE', // firebase-messaging: receive FCM messages
  'com.corthexhq.marong.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION', // androidx.core: the app's own unexported receivers
].sort();
const permissionsOf = (xml) => [...xml.matchAll(/<uses-permission\s+android:name="([^"]+)"/g)].map((m) => m[1]).sort();

test('TC-118: the app asks for exactly the permissions the spec names', () => {
  assert.deepEqual(permissionsOf(manifest), OWN_PERMISSIONS);
});

test('TC-133: the built app, with the libraries merged in, asks for no more than these', (t) => {
  const merged = path.join(APP, 'android', 'app', 'build', 'intermediates', 'merged_manifests', 'release',
    'processReleaseManifest', 'AndroidManifest.xml');
  if (!fs.existsSync(merged)) {
    t.skip('No release build here: run the Gradle build first to check the merged manifest');
    return;
  }
  assert.deepEqual(permissionsOf(fs.readFileSync(merged, 'utf8')), MERGED_PERMISSIONS);
});

test('TC-133: FCM addresses this installation by its Firebase installation id, with the app\'s own channel and icon', () => {
  const meta = (name) => {
    const m = manifest.match(new RegExp(`<meta-data\\s+android:name="${name.replace(/\./g, '\\.')}"\\s+android:(?:value|resource)="([^"]+)"`));
    return m ? m[1] : null;
  };
  assert.equal(meta('firebase_messaging_installation_id_enabled'), 'true');
  assert.equal(meta('com.google.firebase.messaging.default_notification_channel_id'), 'marong_talk');
  assert.equal(meta('com.google.firebase.messaging.default_notification_icon'), '@drawable/ic_stat_marong');
  assert.equal(meta('firebase_analytics_collection_enabled'), 'false');
});

test('TC-133, TC-146: only FCM and the ring notification reach the new parts of the app', () => {
  const block = (name) => {
    const m = manifest.match(new RegExp(`<(service|activity|receiver)\\s+android:name="\\.${name}"[^>]*>`));
    assert.ok(m, `${name} is declared`);
    return m[0];
  };
  assert.match(block('MarongMessagingService'), /android:exported="false"/);
  assert.match(manifest, /<action android:name="com\.google\.firebase\.MESSAGING_EVENT" \/>/);
  assert.match(block('RingActivity'), /android:exported="false"/);
  assert.match(block('RingActivity'), /android:excludeFromRecents="true"/);
  assert.match(block('RingDeclineReceiver'), /android:exported="false"/);
});

test('TC-133: google-services.json stays out of Git (SPEC-127)', () => {
  const ignore = read('android', '.gitignore').split('\n').map((line) => line.trim());
  assert.ok(ignore.includes('google-services.json'), 'android/.gitignore blocks it');
  const tracked = execFileSync('git', ['ls-files', '--', ':(glob)**/google-services.json'], { cwd: APP, encoding: 'utf8' });
  assert.equal(tracked.trim(), '', 'no copy is tracked');
});

test('TC-118: no plain HTTP, mixed content or backup (SPEC-101, SPEC-109)', () => {
  assert.match(manifest, /android:usesCleartextTraffic="false"/);
  assert.match(manifest, /android:allowBackup="false"/);
  assert.match(config.server.url, /^https:\/\//);
  assert.equal(config.server.cleartext, false);
  assert.equal(config.android.allowMixedContent, false);
});

test('TC-118, TC-133: build.gradle, the user agent and package.json name the same version, 0.2.0 or later', () => {
  const gradle = read('android', 'app', 'build.gradle');
  const versionName = gradle.match(/versionName "([^"]+)"/)[1];
  assert.match(gradle, /versionCode [1-9]\d*\n/);
  assert.equal(config.android.appendUserAgent, `MarongApp/${versionName}`);
  assert.equal(JSON.parse(read('package.json')).version, versionName);
  // The server rings only phones whose app reports the ring state, from 0.2.0 (app-ring SPEC-139).
  const [major, minor] = versionName.split('.').map(Number);
  assert.ok(major > 0 || minor >= 2, `${versionName} is 0.2.0 or later`);
});
