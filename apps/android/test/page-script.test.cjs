'use strict';
// TC-101 to TC-105 and TC-107 at unit level: the injected page script against fake browser objects.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SCRIPT = fs.readFileSync(path.join(__dirname, '..', 'android', 'app', 'src', 'main', 'assets', 'marong_page.js'), 'utf8');

class FakeTrack {
  constructor(kind = 'audio') { this.kind = kind; this.readyState = 'live'; this.listeners = {}; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  stop() { this.readyState = 'ended'; }
  end() { this.readyState = 'ended'; for (const fn of this.listeners.ended || []) fn(); }
}

function setup({ capacitorAtStart = true, deny = false, theme = 'night', rootAtStart = true } = {}) {
  const calls = [];
  const docListeners = {};
  const observers = [];
  const root = { dataset: { theme } };
  let currentRoot = rootAtStart ? root : null;
  const stopButton = { clicks: 0, click() { this.clicks++; } };
  const window = {};
  // Copy options into this realm so deepStrictEqual compares plain objects.
  const capacitor = { nativePromise: (plugin, method, options) => { calls.push([plugin, method, { ...options }]); return Promise.resolve(); } };
  if (capacitorAtStart) window.Capacitor = capacitor;
  window.addEventListener = () => {};
  const document = {
    get documentElement() { return currentRoot; },
    getElementById: (id) => (id === 'stop' ? stopButton : null),
    addEventListener: (type, fn) => { (docListeners[type] ||= []).push(fn); },
  };
  const navigator = {
    mediaDevices: {
      async getUserMedia() {
        if (deny) { const error = new Error('denied'); error.name = 'NotAllowedError'; throw error; }
        const track = new FakeTrack();
        return { getAudioTracks: () => [track], getTracks: () => [track], track };
      },
    },
  };
  class MutationObserver { constructor(fn) { this.fn = fn; observers.push(this); } observe() {} }
  const context = { window, document, navigator, MediaStreamTrack: FakeTrack, MutationObserver, Object, Set, Error };
  window.window = window;
  vm.createContext(context);
  const run = () => vm.runInContext(SCRIPT, context);
  run();
  return {
    calls, window, root, stopButton, run,
    capacitor: () => { window.Capacitor = capacitor; },
    attachRoot: () => { currentRoot = root; },
    observerCount: () => observers.length,
    fire: (type) => (docListeners[type] || []).forEach((fn) => fn()),
    themeChanged: () => observers.forEach((o) => o.fn()),
    getUserMedia: () => navigator.mediaDevices.getUserMedia({ audio: true }),
    names: () => calls.map(([p, m]) => `${p}.${m}`),
  };
}

test('TC-101: a live microphone track reports the call start once, and its stop reports the end', async () => {
  const t = setup();
  const stream = await t.getUserMedia();
  assert.deepEqual(t.names().filter((n) => n.startsWith('MarongCall')), ['MarongCall.callStarted']);
  assert.equal(t.window.__marongApp.isCallActive(), true);
  stream.track.stop();
  assert.deepEqual(t.names().filter((n) => n.startsWith('MarongCall')), ['MarongCall.callStarted', 'MarongCall.callEnded']);
  assert.equal(t.window.__marongApp.isCallActive(), false);
});

test('TC-102: a second microphone keeps the call active until both are released', async () => {
  const t = setup();
  const first = await t.getUserMedia();
  const second = await t.getUserMedia();
  first.track.stop();
  assert.equal(t.window.__marongApp.isCallActive(), true);
  second.track.end(); // the device went away: the "ended" event, not stop()
  assert.equal(t.window.__marongApp.isCallActive(), false);
  assert.equal(t.names().filter((n) => n === 'MarongCall.callStarted').length, 1);
  assert.equal(t.names().filter((n) => n === 'MarongCall.callEnded').length, 1);
});

test('TC-105: a refused microphone tells the app and still rejects for the page', async () => {
  const t = setup({ deny: true });
  await assert.rejects(t.getUserMedia(), { name: 'NotAllowedError' });
  assert.deepEqual(t.names().filter((n) => n.startsWith('MarongCall')), ['MarongCall.microphoneDenied']);
});

test('TC-104: endCall presses the page end button only during a call', async () => {
  const t = setup();
  assert.equal(t.window.__marongApp.endCall(), false);
  assert.equal(t.stopButton.clicks, 0);
  await t.getUserMedia();
  assert.equal(t.window.__marongApp.endCall(), true);
  assert.equal(t.stopButton.clicks, 1);
});

test('TC-107: status bar style follows the page theme and waits for the Capacitor bridge', () => {
  const t = setup({ capacitorAtStart: false, theme: 'chestnut' });
  assert.deepEqual(t.calls, []); // no bridge yet at document start
  t.capacitor();
  t.fire('DOMContentLoaded');
  assert.deepEqual(t.calls.at(-1), ['SystemBars', 'setStyle', { style: 'LIGHT' }]);
  t.root.dataset.theme = 'night';
  t.themeChanged();
  assert.deepEqual(t.calls.at(-1), ['SystemBars', 'setStyle', { style: 'DARK' }]);
  t.themeChanged(); // unchanged theme sends nothing new
  assert.equal(t.calls.filter(([p]) => p === 'SystemBars').length, 2);
});

test('TC-103: running the script twice keeps one wrapper and one app object', async () => {
  const t = setup();
  const app = t.window.__marongApp;
  t.run();
  assert.equal(t.window.__marongApp, app);
  await t.getUserMedia();
  assert.equal(t.names().filter((n) => n === 'MarongCall.callStarted').length, 1);
});

test('TC-107: without an <html> element at document start, the theme is watched from page load', () => {
  const t = setup({ rootAtStart: false });
  assert.equal(t.observerCount(), 0);
  t.attachRoot();
  t.fire('DOMContentLoaded');
  assert.equal(t.observerCount(), 1);
  assert.deepEqual(t.calls.at(-1), ['SystemBars', 'setStyle', { style: 'DARK' }]);
  t.root.dataset.theme = 'chestnut';
  t.themeChanged();
  assert.deepEqual(t.calls.at(-1), ['SystemBars', 'setStyle', { style: 'LIGHT' }]);
});
