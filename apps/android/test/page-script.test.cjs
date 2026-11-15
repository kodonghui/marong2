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

// Records the audio graph a script builds; the page makes its contexts through window.AudioContext.
class FakeAudioContext {
  constructor() { this.state = 'running'; this.nodes = []; this.destination = { kind: 'destination' }; }
  node(kind, extra) {
    const node = { kind, connected: [], started: false, stopped: false, ...extra,
      connect(target) { this.connected.push(target); return target; },
      disconnect() { this.connected = []; },
      start() { this.started = true; },
      stop() { this.stopped = true; } };
    this.nodes.push(node);
    return node;
  }
  createOscillator() { return this.node('oscillator', { frequency: { value: 440 } }); }
  createGain() { return this.node('gain', { gain: { value: 1 } }); }
}

function setup({ capacitorAtStart = true, deny = false, theme = 'night', rootAtStart = true } = {}) {
  const calls = [];
  const docListeners = {};
  const observers = [];
  const inline = {};
  const root = { dataset: { theme }, style: { getPropertyValue: (name) => inline[name] || '', setProperty: (name, value) => { inline[name] = value; } } };
  let currentRoot = rootAtStart ? root : null;
  const stopButton = { clicks: 0, click() { this.clicks++; } };
  const window = {};
  // Copy options into this realm so deepStrictEqual compares plain objects.
  const capacitor = { nativePromise: (plugin, method, options) => { calls.push([plugin, method, { ...options }]); return Promise.resolve(); } };
  if (capacitorAtStart) window.Capacitor = capacitor;
  window.addEventListener = () => {};
  window.AudioContext = FakeAudioContext;
  const document = {
    visibilityState: 'visible',
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
  class MutationObserver { constructor(fn) { this.fn = fn; observers.push(this); } observe(target, options) { this.options = options; } }
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
    observedAttributes: () => observers.map((o) => [...o.options.attributeFilter]),
    fire: (type) => (docListeners[type] || []).forEach((fn) => fn()),
    themeChanged: () => observers.forEach((o) => o.fn()),
    hide: () => { document.visibilityState = 'hidden'; (docListeners.visibilitychange || []).forEach((fn) => fn()); },
    show: () => { document.visibilityState = 'visible'; (docListeners.visibilitychange || []).forEach((fn) => fn()); },
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

test('TC-107: when an older WebView keeps the page below the bars, the icons stay light (BUG-102)', () => {
  const t = setup({ theme: 'chestnut' });
  assert.deepEqual(t.calls.at(-1), ['SystemBars', 'setStyle', { style: 'LIGHT' }]); // insets not known yet
  assert.deepEqual(t.observedAttributes(), [['data-theme', 'style']]);
  t.root.style.setProperty('--safe-area-inset-top', '0px'); // Capacitor: WebView < 140, bars padded
  t.themeChanged();
  assert.deepEqual(t.calls.at(-1), ['SystemBars', 'setStyle', { style: 'DARK' }]);
  t.root.style.setProperty('--safe-area-inset-top', '24px'); // the page draws behind the bars again
  t.themeChanged();
  assert.deepEqual(t.calls.at(-1), ['SystemBars', 'setStyle', { style: 'LIGHT' }]);
});

test('TC-110: a call in a hidden page plays a 20 Hz tone below hearing so the WebView does not freeze it (BUG-103)', async () => {
  const t = setup();
  const context = new t.window.AudioContext(); // the page's own context, made through the wrapper
  assert.ok(context instanceof FakeAudioContext);
  t.hide();
  assert.equal(context.nodes.length, 0, 'no call, no tone');
  t.show();
  const { track } = await t.getUserMedia();
  t.hide();
  const [tone, level] = context.nodes;
  assert.equal(tone.frequency.value, 20);
  assert.equal(level.gain.value, 0.002);
  assert.ok(tone.started && tone.connected[0] === level && level.connected[0] === context.destination);
  t.hide();
  assert.equal(context.nodes.length, 2, 'one tone at a time');
  t.show();
  assert.ok(tone.stopped, 'visible again: the tone stops');
  t.hide();
  assert.equal(context.nodes.length, 4);
  track.end(); // the call ends while the page is hidden
  assert.ok(context.nodes[2].stopped);
  context.state = 'closed';
  const second = new t.window.AudioContext();
  const next = await t.getUserMedia();
  t.hide();
  assert.equal(second.nodes.length, 2, 'the newest running context carries the tone');
  next.track.end();
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
