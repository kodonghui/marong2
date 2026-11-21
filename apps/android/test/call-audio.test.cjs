'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../android/app/src/main/java/com/corthexhq/marong/CallAudioPhone.java'), 'utf8');
const reportScript = JSON.parse(source.match(/REPORT_JS =\s*("(?:[^"\\]|\\.)*")/)[1]);
const sample = { device: 'speaker', voiceVolume: 9, voiceVolumeMax: 15, ringer: 'normal' };
const report = (window) => vm.runInNewContext(reportScript + '(' + JSON.stringify(sample) + ')', { window });

test('TC-595: the current call page can omit the audio route hook', () => {
  assert.doesNotThrow(() => report({}));
  assert.doesNotThrow(() => report({ __marongCall: {} }));
});

test('TC-595: errors in the page audio route hook stay in the page', () => {
  assert.doesNotThrow(() => report({ __marongCall: { audioRoute() { throw new Error('page error'); } } }));
});

test('TC-595: the call page receives only the four route fields', () => {
  let received;
  report({ __marongCall: { audioRoute(route) { received = JSON.parse(JSON.stringify(route)); } } });
  assert.deepEqual(received, sample);
});
