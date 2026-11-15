// Injected by the 마롱이 Android app into the call site only (SPEC-102 to SPEC-106).
// It reads the page and reports to the app; it changes no call behaviour of the page.
(() => {
  'use strict';
  if (window.__marongApp) return;

  // Capacitor's bridge script is added after this one, so look it up when it is needed.
  const send = (plugin, method, options) => {
    try {
      const cap = window.Capacitor;
      if (!cap || typeof cap.nativePromise !== 'function') return false;
      cap.nativePromise(plugin, method, options || {}).catch(() => {});
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

  // "끊기" on the call notification presses the page's own end button (SPEC-104).
  const endCall = () => {
    const button = document.getElementById('stop');
    if (!active || !button) return false;
    button.click();
    return true;
  };

  Object.defineProperty(window, '__marongApp', {
    value: Object.freeze({ version: 1, endCall, isCallActive: () => active }),
  });
})();
