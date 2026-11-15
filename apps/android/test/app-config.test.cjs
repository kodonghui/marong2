'use strict';
// TC-118: app settings that the device tests depend on, read from the source files.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const APP = path.join(__dirname, '..');
const read = (...parts) => fs.readFileSync(path.join(APP, ...parts), 'utf8');
const manifest = read('android', 'app', 'src', 'main', 'AndroidManifest.xml');
const config = JSON.parse(read('capacitor.config.json'));

test('TC-118: the app asks for exactly the permissions the spec names', () => {
  const permissions = [...manifest.matchAll(/<uses-permission\s+android:name="([^"]+)"/g)].map((m) => m[1]).sort();
  assert.deepEqual(permissions, [
    'android.permission.ACCESS_NETWORK_STATE', // SPEC-108: navigator.onLine and "online" in the WebView (BUG-101)
    'android.permission.FOREGROUND_SERVICE', // SPEC-103
    'android.permission.FOREGROUND_SERVICE_MICROPHONE', // SPEC-103
    'android.permission.INTERNET',
    'android.permission.MODIFY_AUDIO_SETTINGS', // SPEC-106
    'android.permission.POST_NOTIFICATIONS', // SPEC-103
    'android.permission.RECORD_AUDIO', // SPEC-106
  ]);
});

test('TC-118: no plain HTTP, mixed content or backup (SPEC-101, SPEC-109)', () => {
  assert.match(manifest, /android:usesCleartextTraffic="false"/);
  assert.match(manifest, /android:allowBackup="false"/);
  assert.match(config.server.url, /^https:\/\//);
  assert.equal(config.server.cleartext, false);
  assert.equal(config.android.allowMixedContent, false);
});

test('TC-118: build.gradle, the user agent and package.json name the same version', () => {
  const gradle = read('android', 'app', 'build.gradle');
  const versionName = gradle.match(/versionName "([^"]+)"/)[1];
  assert.match(gradle, /versionCode [1-9]\d*\n/);
  assert.equal(config.android.appendUserAgent, `MarongApp/${versionName}`);
  assert.equal(JSON.parse(read('package.json')).version, versionName);
});
