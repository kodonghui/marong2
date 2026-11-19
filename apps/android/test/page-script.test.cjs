'use strict';
// TC-101 to TC-105 and TC-107 at unit level: the injected page script against fake browser objects.
// From 0.2.0 also the device report and chat visibility (docs/app-chat.md TC-123, TC-133) and the
// app object's new calls (docs/app-ring.md TC-145, TC-146); from 0.2.1 the hidden text panel
// (docs/app-chat.md TC-151).
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

const INSTALL = '0f8fad5b-d9cb-469f-a165-70867728950e';
const PHONE = () => ({ installId: INSTALL, fid: 'fid_AAAAAAAAAAAAAAAAAAAA', notifications: 'granted', appVersion: '0.2.0',
  ring: { channel: 'enabled', fullScreen: 'granted' }, fullScreenSettings: true, samsung: false });

function setup({ capacitorAtStart = true, deny = false, theme = 'night', rootAtStart = true, path: pathname = '/',
  phone = PHONE(), fetchStatus = 201, storage = new Map(), now = Date.parse('2026-11-15T12:00:00Z'),
  adoptedSheets = false, styleElements = false } = {}) {
  const calls = [];
  const docListeners = {};
  const winListeners = {};
  const listeners = {};
  const requests = [];
  const events = [];
  const observers = [];
  const inline = {};
  const clock = { now };
  const net = { status: fetchStatus, pending: null };
  const root = { dataset: { theme }, style: { getPropertyValue: (name) => inline[name] || '', setProperty: (name, value) => { inline[name] = value; } } };
  let currentRoot = rootAtStart ? root : null;
  const stopButton = { clicks: 0, click() { this.clicks++; } };
  // The two ways to add a style sheet (SPEC-145): adopted sheets, or a <style> element in <head>.
  const sheets = [];
  const appended = [];
  const head = { appendChild: (child) => { appended.push(child); return child; } };
  class CSSStyleSheet { replaceSync(text) { this.text = text; } }
  const window = {};
  // Copy options into this realm so deepStrictEqual compares plain objects.
  const capacitor = {
    nativePromise: (plugin, method, options) => {
      calls.push([plugin, method, { ...options }]);
      if (plugin === 'MarongPush' && method === 'state') return Promise.resolve(phone ? JSON.parse(JSON.stringify(phone)) : null);
      return Promise.resolve();
    },
    addListener: (plugin, event, callback) => { (listeners[`${plugin}.${event}`] ||= []).push(callback); return { remove() {} }; },
  };
  if (capacitorAtStart) window.Capacitor = capacitor;
  window.addEventListener = (type, fn) => { (winListeners[type] ||= []).push(fn); };
  window.dispatchEvent = (event) => { events.push(event.type); return true; };
  window.AudioContext = FakeAudioContext;
  const document = {
    visibilityState: 'visible',
    readyState: 'loading', // the app adds the script at document start
    get documentElement() { return currentRoot; },
    getElementById: (id) => (id === 'stop' ? stopButton : null),
    querySelector: (selector) => selector === '.brand' ? { firstChild: { textContent: '군밤이' } } : null,
    addEventListener: (type, fn) => { (docListeners[type] ||= []).push(fn); },
  };
  if (adoptedSheets) document.adoptedStyleSheets = sheets;
  if (styleElements) {
    Object.defineProperty(document, 'head', { get: () => (currentRoot ? head : null) });
    document.createElement = (tag) => ({ tag, textContent: '' });
  }
  const navigator = {
    mediaDevices: {
      async getUserMedia() {
        if (deny) { const error = new Error('denied'); error.name = 'NotAllowedError'; throw error; }
        const track = new FakeTrack();
        return { getAudioTracks: () => [track], getTracks: () => [track], track };
      },
    },
  };
  const localStorage = {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => { storage.set(key, String(value)); },
  };
  const fetch = (url, options) => {
    requests.push({ url, ...options, headers: { ...options.headers }, body: JSON.parse(options.body) });
    if (net.pending) return net.pending.then(() => ({ status: net.status }));
    return Promise.resolve({ status: net.status });
  };
  class Event { constructor(type) { this.type = type; } }
  class MutationObserver { constructor(fn) { this.fn = fn; observers.push(this); } observe(target, options) { this.options = options; } }
  const context = { window, document, navigator, MediaStreamTrack: FakeTrack, MutationObserver, Object, Set, Error,
    localStorage, fetch, Event, location: { pathname }, Date: { now: () => clock.now }, JSON, Promise, Array };
  if (adoptedSheets) context.CSSStyleSheet = CSSStyleSheet;
  window.window = window;
  vm.createContext(context);
  const run = () => vm.runInContext(SCRIPT, context);
  run();
  return {
    calls, window, root, stopButton, run, requests, events, storage, clock, net, phone,
    adopted: () => Array.from(document.adoptedStyleSheets, (sheet) => sheet.text), // copied into this realm
    appended: () => appended.map((child) => [child.tag, child.textContent]),
    capacitor: () => { window.Capacitor = capacitor; },
    attachRoot: () => { currentRoot = root; },
    observerCount: () => observers.length,
    observedAttributes: () => observers.map((o) => [...o.options.attributeFilter]),
    fire: (type) => (docListeners[type] || []).forEach((fn) => fn()),
    fireWindow: (type) => (winListeners[type] || []).forEach((fn) => fn()),
    emit: (event) => (listeners[`MarongPush.${event}`] || []).forEach((fn) => fn({})),
    themeChanged: () => observers.forEach((o) => o.fn()),
    hide: () => { document.visibilityState = 'hidden'; (docListeners.visibilitychange || []).forEach((fn) => fn()); },
    show: () => { document.visibilityState = 'visible'; (docListeners.visibilitychange || []).forEach((fn) => fn()); },
    getUserMedia: () => navigator.mediaDevices.getUserMedia({ audio: true }),
    names: () => calls.map(([p, m]) => `${p}.${m}`),
    bars: () => calls.filter(([p]) => p === 'SystemBars'),
    chat: () => calls.filter(([p, m]) => p === 'MarongPush' && m === 'chatVisible').map(([, , o]) => o.visible),
  };
}

// Lets the script's promise chains (bridge answer, fetch, storage) finish.
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise((resolve) => setImmediate(resolve)); };

test('TC-101: a live microphone track reports the call start once, and its stop reports the end', async () => {
  const t = setup();
  const stream = await t.getUserMedia();
  assert.deepEqual(t.names().filter((n) => n.startsWith('MarongCall')), ['MarongCall.callStarted']);
  assert.deepEqual(t.calls.find(([, method]) => method === 'callStarted')[2], {name: '군밤이'});
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
  assert.deepEqual(t.bars().at(-1), ['SystemBars', 'setStyle', { style: 'LIGHT' }]);
  t.root.dataset.theme = 'night';
  t.themeChanged();
  assert.deepEqual(t.bars().at(-1), ['SystemBars', 'setStyle', { style: 'DARK' }]);
  t.themeChanged(); // unchanged theme sends nothing new
  assert.equal(t.bars().length, 2);
});

test('TC-107: when an older WebView keeps the page below the bars, the icons stay light (BUG-102)', () => {
  const t = setup({ theme: 'chestnut' });
  assert.deepEqual(t.bars().at(-1), ['SystemBars', 'setStyle', { style: 'LIGHT' }]); // insets not known yet
  assert.deepEqual(t.observedAttributes(), [['data-theme', 'style']]);
  t.root.style.setProperty('--safe-area-inset-top', '0px'); // Capacitor: WebView < 140, bars padded
  t.themeChanged();
  assert.deepEqual(t.bars().at(-1), ['SystemBars', 'setStyle', { style: 'DARK' }]);
  t.root.style.setProperty('--safe-area-inset-top', '24px'); // the page draws behind the bars again
  t.themeChanged();
  assert.deepEqual(t.bars().at(-1), ['SystemBars', 'setStyle', { style: 'LIGHT' }]);
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
  assert.deepEqual(t.bars().at(-1), ['SystemBars', 'setStyle', { style: 'DARK' }]);
  t.root.dataset.theme = 'chestnut';
  t.themeChanged();
  assert.deepEqual(t.bars().at(-1), ['SystemBars', 'setStyle', { style: 'LIGHT' }]);
});

test('TC-133: at page load the app reports this phone once, to the same address, with no redirect followed', async () => {
  const t = setup();
  assert.equal(t.requests.length, 0, 'not before the page has loaded');
  t.fire('DOMContentLoaded');
  await settle();
  assert.equal(t.requests.length, 1);
  assert.deepEqual(t.requests[0], {
    url: `/chat/api/devices/${INSTALL}`, method: 'PUT', credentials: 'same-origin', redirect: 'manual', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: { fid: 'fid_AAAAAAAAAAAAAAAAAAAA', notifications: 'granted', appVersion: '0.2.0', ring: { channel: 'enabled', fullScreen: 'granted' } },
  });
  assert.deepEqual(t.events, ['marongdevice'], 'the chat menu hears about it');
  const saved = JSON.parse(t.storage.get('marong.app.deviceReport'));
  assert.equal(saved.installId, INSTALL);
  assert.equal(saved.at, t.clock.now);
});

test('TC-133: the same phone is reported again only after 12 hours, a change at once', async () => {
  const storage = new Map();
  const first = setup({ storage });
  first.fire('DOMContentLoaded');
  await settle();
  assert.equal(first.requests.length, 1);

  const again = setup({ storage, now: first.clock.now + 11 * 3_600_000 }); // the next page, 11 hours later
  again.fire('DOMContentLoaded');
  await settle();
  assert.equal(again.requests.length, 0, 'nothing changed');
  again.clock.now = first.clock.now + 12 * 3_600_000;
  again.hide();
  again.show();
  await settle();
  assert.equal(again.requests.length, 1, '12 hours: the server learns the phone is still here');

  const phone = PHONE();
  phone.notifications = 'denied';
  const changed = setup({ storage, phone, now: again.clock.now + 60_000 });
  changed.fire('DOMContentLoaded');
  await settle();
  assert.equal(changed.requests.length, 1);
  assert.equal(changed.requests[0].body.notifications, 'denied');

  const back = setup({ storage, phone, now: first.clock.now - 3_600_000 }); // the phone's clock went back
  back.fire('DOMContentLoaded');
  await settle();
  assert.equal(back.requests.length, 1, 'a report from the future does not count');
});

test('TC-133: a report that failed (signed out, server down) is tried again when the page comes back', async () => {
  const t = setup({ fetchStatus: 0 }); // Access answered with its sign-in redirect
  t.fire('DOMContentLoaded');
  await settle();
  assert.equal(t.requests.length, 1);
  assert.equal(t.storage.has('marong.app.deviceReport'), false);
  assert.deepEqual(t.events, []);
  t.net.status = 200;
  t.hide();
  t.show();
  await settle();
  assert.equal(t.requests.length, 2);
  assert.equal(t.storage.has('marong.app.deviceReport'), true);
});

test('TC-133: a new id from FCM is reported at once, and reports never overlap', async () => {
  const t = setup();
  t.fire('DOMContentLoaded');
  await settle();
  let release;
  t.net.pending = new Promise((resolve) => { release = resolve; });
  t.phone.fid = 'fid_BBBBBBBBBBBBBBBBBBBB';
  t.emit('registered');
  await settle();
  t.emit('registered');
  t.emit('resumed');
  await settle();
  assert.equal(t.requests.length, 2, 'one report in flight at a time');
  release();
  t.net.pending = null;
  await settle();
  assert.equal(t.requests.length, 2, 'the queued check finds nothing new');
  assert.equal(t.requests[1].body.fid, 'fid_BBBBBBBBBBBBBBBBBBBB');
});

test('TC-133: without the bridge or an install id nothing is sent', async () => {
  const outside = setup({ capacitorAtStart: false });
  outside.fire('DOMContentLoaded');
  await settle();
  assert.deepEqual(outside.calls, []);
  assert.equal(outside.requests.length, 0);

  const phone = PHONE();
  phone.installId = '../me';
  const odd = setup({ phone });
  odd.fire('DOMContentLoaded');
  await settle();
  assert.equal(odd.requests.length, 0);
  const none = setup({ phone: null });
  none.fire('DOMContentLoaded');
  await settle();
  assert.equal(none.requests.length, 0);
});

test('TC-123: the chat page tells the app while it is on screen', async () => {
  const t = setup({ path: '/chat/' });
  t.fire('DOMContentLoaded');
  assert.deepEqual(t.chat(), [true]);
  t.hide();
  assert.deepEqual(t.chat(), [true, false]);
  t.hide();
  assert.deepEqual(t.chat(), [true, false], 'no repeat');
  t.show();
  assert.deepEqual(t.chat(), [true, false, true]);
  t.emit('resumed'); // the app forgot it while paused
  assert.deepEqual(t.chat(), [true, false, true, true]);
  t.fireWindow('pagehide');
  assert.deepEqual(t.chat(), [true, false, true, true, false]);
  t.fireWindow('pageshow'); // back from the back-forward cache
  assert.equal(t.chat().at(-1), true);
  await settle();

  const call = setup({ path: '/' });
  call.fire('DOMContentLoaded');
  assert.deepEqual(call.chat(), [false], 'the call page is not the chat');
  await settle();
});

test('TC-145, TC-146: version 2 answers rings by itself and opens the settings the chat menu names', async () => {
  const t = setup();
  const app = t.window.__marongApp;
  assert.equal(app.version, 2);
  assert.equal(app.autoAnswer, true);
  assert.equal(Object.isFrozen(app), true);
  assert.equal(app.openNotificationSettings('ring'), true);
  assert.equal(app.openNotificationSettings(), true);
  assert.equal(app.openNotificationSettings('anything'), true);
  assert.equal(app.openFullScreenSettings(), true);
  assert.deepEqual(t.calls.filter(([p]) => p === 'MarongPush'), [
    ['MarongPush', 'openNotificationSettings', { channel: 'ring' }],
    ['MarongPush', 'openNotificationSettings', {}],
    ['MarongPush', 'openNotificationSettings', {}],
    ['MarongPush', 'openFullScreenSettings', {}],
  ]);
  const device = await app.deviceState();
  assert.equal(device.samsung, false);
  assert.equal(device.fullScreenSettings, true);

  const outside = setup({ capacitorAtStart: false });
  assert.equal(outside.window.__marongApp.openFullScreenSettings(), false, 'no bridge, nothing opens');
  assert.equal(await outside.window.__marongApp.deviceState(), null);
});

test('TC-151: at document start the call screen\'s text panel is hidden with an adopted style sheet, once', () => {
  const t = setup({ adoptedSheets: true, styleElements: true });
  assert.deepEqual(t.adopted(), ['#conversation{display:none!important}']);
  t.fire('DOMContentLoaded');
  t.run(); // a second run of the script adds nothing
  assert.deepEqual(t.adopted(), ['#conversation{display:none!important}']);
  assert.deepEqual(t.appended(), [], 'no <style> element as well');
});

test('TC-151: without adopted style sheets a <style> element hides it, from page load when <head> is not there yet', () => {
  const t = setup({ styleElements: true, rootAtStart: false });
  assert.deepEqual(t.appended(), []);
  t.attachRoot();
  t.fire('DOMContentLoaded');
  assert.deepEqual(t.appended(), [['style', '#conversation{display:none!important}']]);
  t.fire('DOMContentLoaded');
  assert.equal(t.appended().length, 1);
});

test('TC-151: with neither way the page script still runs and reports the call', async () => {
  const t = setup();
  t.fire('DOMContentLoaded');
  await t.getUserMedia();
  assert.deepEqual(t.names().filter((n) => n.startsWith('MarongCall')), ['MarongCall.callStarted']);
});
