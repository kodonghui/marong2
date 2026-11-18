// Injected by the 마롱이 Android app into the call site only (SPEC-102 to SPEC-106).
// It reads the page and reports to the app; it changes no call behaviour of the page.
// From 0.2.0 it also reports this phone for messages and rings (docs/app-chat.md SPEC-123,
// docs/app-ring.md SPEC-135, SPEC-139 and SPEC-140). From 0.2.1 it hides the call screen's own text
// panel, because the app opens the chat in a window of its own (D20, docs/app-chat.md SPEC-145).
(() => {
  'use strict';
  if (window.__marongApp) return;

  // Capacitor's bridge script is added after this one, so look it up when it is needed.
  const ask = (plugin, method, options) => {
    try {
      const cap = window.Capacitor;
      if (!cap || typeof cap.nativePromise !== 'function') return null;
      return cap.nativePromise(plugin, method, options || {});
    } catch {
      return null;
    }
  };
  const send = (plugin, method, options) => {
    const answer = ask(plugin, method, options);
    if (!answer) return false;
    Promise.resolve(answer).catch(() => {});
    return true;
  };
  const listen = (plugin, event, callback) => {
    try {
      const cap = window.Capacitor;
      if (!cap || typeof cap.addListener !== 'function') return false;
      cap.addListener(plugin, event, callback);
      return true;
    } catch {
      return false;
    }
  };

  // A call is active while the page holds a live microphone track (REQ-103).
  const microphones = new Set();
  let active = false;
  const hasLiveMicrophone = () => {
    for (const track of microphones) {
      if (track.readyState === 'live') return true;
      microphones.delete(track);
    }
    return false;
  };
  const syncCall = () => {
    const next = hasLiveMicrophone();
    if (next === active) return;
    active = next;
    send('MarongCall', next ? 'callStarted' : 'callEnded');
    syncKeepAudible();
  };

  // A hidden page (screen off, app in the background) that plays nothing audible for 5 minutes is
  // frozen by the WebView, and the microphone audio stops reaching the server (BUG-103). During a
  // call in a hidden page, a 20 Hz tone at -57 dBFS RMS, far below hearing and below what phone
  // speakers play, keeps the page audible for the WebView (REQ-103, SPEC-103).
  const audioContexts = new Set();
  const NativeAudioContext = window.AudioContext;
  if (typeof NativeAudioContext === 'function') {
    window.AudioContext = class extends NativeAudioContext {
      constructor(...args) {
        super(...args);
        audioContexts.add(this);
      }
    };
  }
  let keepAudible = null;
  const syncKeepAudible = () => {
    const hidden = document.visibilityState === 'hidden';
    if (active && hidden && !keepAudible) {
      for (const context of audioContexts) if (context.state === 'closed') audioContexts.delete(context);
      const context = [...audioContexts].reverse().find((c) => c.state === 'running');
      if (!context) return;
      try {
        const tone = context.createOscillator();
        const level = context.createGain();
        tone.frequency.value = 20;
        level.gain.value = 0.002;
        tone.connect(level);
        level.connect(context.destination);
        tone.start();
        keepAudible = { tone, level };
      } catch {
        keepAudible = null;
      }
    } else if ((!active || !hidden) && keepAudible) {
      const { tone, level } = keepAudible;
      keepAudible = null;
      try {
        tone.stop();
        tone.disconnect();
        level.disconnect();
      } catch {
        // The page may already have closed its audio context.
      }
    }
  };
  document.addEventListener('visibilitychange', syncKeepAudible);

  const media = navigator.mediaDevices;
  if (media && typeof media.getUserMedia === 'function') {
    const getUserMedia = media.getUserMedia.bind(media);
    media.getUserMedia = async function marongGetUserMedia(constraints) {
      let stream;
      try {
        stream = await getUserMedia(constraints);
      } catch (error) {
        if (error && error.name === 'NotAllowedError') send('MarongCall', 'microphoneDenied');
        throw error;
      }
      for (const track of stream.getAudioTracks()) {
        microphones.add(track);
        track.addEventListener('ended', syncCall);
      }
      syncCall();
      return stream;
    };
  }
  if (typeof MediaStreamTrack === 'function') {
    const stop = MediaStreamTrack.prototype.stop;
    MediaStreamTrack.prototype.stop = function marongStop() {
      const result = stop.apply(this, arguments);
      if (microphones.has(this)) syncCall();
      return result;
    };
  }

  // Status bar icons follow the page's cream day theme and night theme (SPEC-107). With a WebView
  // older than 140, Capacitor keeps the page below the bars and sets --safe-area-inset-top to 0px;
  // the window's night colour then shows behind the bars, so the icons stay light (BUG-102).
  let barStyle = null;
  const syncBars = () => {
    const root = document.documentElement;
    if (!root) return;
    const belowBars = root.style.getPropertyValue('--safe-area-inset-top').trim() === '0px';
    const next = !belowBars && root.dataset.theme === 'chestnut' ? 'LIGHT' : 'DARK';
    if (next !== barStyle && send('SystemBars', 'setStyle', { style: next })) barStyle = next;
  };
  // At document start the <html> element may not exist yet; then start watching once the page has loaded.
  let watching = false;
  const watchTheme = () => {
    const root = document.documentElement;
    if (!root) return;
    if (!watching) {
      new MutationObserver(syncBars).observe(root, { attributes: true, attributeFilter: ['data-theme', 'style'] });
      watching = true;
    }
    syncBars();
  };
  watchTheme();
  document.addEventListener('DOMContentLoaded', watchTheme, { once: true });
  window.addEventListener('pageshow', syncBars);

  // The call screen's '글로도 이야기하기' (its captions and typing into the call) stays out of the app:
  // the app's chat is a window of its own (D20, docs/app-chat.md SPEC-145). A style sheet adopted at
  // document start hides it before the first paint; without that, a <style> element does it.
  const HIDE_TEXT_PANEL = '#conversation{display:none!important}';
  let textPanelHidden = false;
  const hideTextPanel = () => {
    if (textPanelHidden) return;
    try {
      if (typeof CSSStyleSheet === 'function' && Array.isArray(document.adoptedStyleSheets)) {
        const sheet = new CSSStyleSheet();
        sheet.replaceSync(HIDE_TEXT_PANEL);
        document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
        textPanelHidden = true;
        return;
      }
    } catch {
      // Fall back to a style element.
    }
    try {
      const parent = document.head || document.documentElement;
      if (!parent || typeof document.createElement !== 'function') return;
      const style = document.createElement('style');
      style.textContent = HIDE_TEXT_PANEL;
      parent.appendChild(style);
      textPanelHidden = true;
    } catch {
      // The panel stays visible; the call works the same.
    }
  };
  hideTextPanel();
  document.addEventListener('DOMContentLoaded', hideTextPanel, { once: true });

  // "끊기" on the call notification presses the page's own end button (SPEC-104).
  const endCall = () => {
    const button = document.getElementById('stop');
    if (!active || !button) return false;
    button.click();
    return true;
  };

  // This phone for 선톡, reminders, replies and rings (docs/app-chat.md SPEC-123, docs/app-ring.md
  // SPEC-139): sent when it changed, when FCM gives a new id, and at least every 12 hours.
  const REPORT_KEY = 'marong.app.deviceReport';
  const REPORT_EVERY_MS = 12 * 60 * 60 * 1000;
  const INSTALL_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const lastReport = () => {
    try {
      const last = JSON.parse(localStorage.getItem(REPORT_KEY) || 'null');
      return last && typeof last === 'object' ? last : null;
    } catch {
      return null;
    }
  };
  const sendReport = async () => {
    const state = await ask('MarongPush', 'state');
    if (!state || !INSTALL_ID.test(state.installId)) return;
    const body = JSON.stringify({
      fid: typeof state.fid === 'string' ? state.fid : null,
      notifications: state.notifications,
      appVersion: state.appVersion,
      ring: state.ring,
    });
    const last = lastReport();
    const age = last ? Date.now() - last.at : NaN;
    if (last && last.installId === state.installId && last.body === body && age >= 0 && age < REPORT_EVERY_MS) return;
    const res = await fetch(`/chat/api/devices/${state.installId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body,
      credentials: 'same-origin',
      redirect: 'manual',
      cache: 'no-store',
    });
    // Anything else (signed out, server down) is tried again when a page opens or comes back.
    if (res.status !== 200 && res.status !== 201) return;
    try {
      localStorage.setItem(REPORT_KEY, JSON.stringify({ installId: state.installId, body, at: Date.now() }));
    } catch {
      // Without storage the page reports again next time.
    }
    window.dispatchEvent(new Event('marongdevice'));
  };
  let reporting = null;
  let reportAgain = false;
  const report = () => {
    if (reporting) {
      reportAgain = true;
      return reporting;
    }
    reporting = sendReport()
      .catch(() => {})
      .then(() => {
        reporting = null;
        if (reportAgain) {
          reportAgain = false;
          report();
        }
      });
    return reporting;
  };

  // While the chat is on screen, its messages show there and not as notifications (SPEC-121, SPEC-123).
  let chatShown = null;
  const syncChat = (leaving, force) => {
    const path = location.pathname;
    const visible = !leaving && path.startsWith('/chat/') && document.visibilityState === 'visible';
    if (!force && visible === chatShown) return;
    if (send('MarongPush', 'chatVisible', { visible })) chatShown = visible;
  };

  let started = false;
  const startApp = () => {
    if (started || !window.Capacitor) return;
    started = true;
    listen('MarongPush', 'registered', () => report());
    // Back from Android's settings or another app: notifications may have been turned on or off.
    listen('MarongPush', 'resumed', () => {
      syncChat(false, true);
      window.dispatchEvent(new Event('marongdevice'));
      report();
    });
    syncChat(false, true);
    report();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', startApp, { once: true });
  else startApp();
  window.addEventListener('pageshow', () => {
    startApp();
    syncChat(false, true);
  });
  window.addEventListener('pagehide', () => syncChat(true, false));
  document.addEventListener('visibilitychange', () => {
    syncChat(false, false);
    if (started && document.visibilityState === 'visible') report();
  });

  Object.defineProperty(window, '__marongApp', {
    value: Object.freeze({
      version: 2,
      // A ring answered in the app starts the call without a second tap (docs/app-ring.md SPEC-135).
      autoAnswer: true,
      endCall,
      isCallActive: () => active,
      // The chat menu's buttons (SCR-109, SPEC-140). Each returns false when the app cannot do it.
      openNotificationSettings: (channel) => send('MarongPush', 'openNotificationSettings', channel === 'ring' ? { channel: 'ring' } : {}),
      openFullScreenSettings: () => send('MarongPush', 'openFullScreenSettings'),
      openInstallSettings: () => send('MarongPush', 'openInstallSettings'),
      deviceState: () => Promise.resolve(ask('MarongPush', 'state')).catch(() => null),
    }),
  });
})();
