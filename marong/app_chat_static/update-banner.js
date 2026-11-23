// SCR-001 / SCR-107. Both pages use the same native bridge and state transitions.
export async function mountUpdateBanner(banner, deadline, renderLayout = render => render()) {
  const bridge = window.__marongApp;
  const message = banner.querySelector('.update-message');
  const version = banner.querySelector('.update-version');
  const button = banner.querySelector('button');
  const progress = banner.querySelector('.update-progress');
  const copy = {
    ready: ['새 버전 준비됨', '지금 설치'],
    installing: ['설치하는 중… 앱이 잠깐 닫혀', ''],
    busy: ['통화 끝나고 깔 수 있어', '지금 설치'],
    failed: ['설치하지 못했어. 나중에 다시 해 볼게', '다시 설치'],
    off: ['자동 업데이트 꺼짐 · 켜 두면 새 버전이 저절로 깔려', '켜기'],
  };
  let state = 'none';
  let stagedVersion;
  let failedVersion;
  let request = 0;
  let acting = false;
  let refreshAfterBusy = false;

  function show(next, animate = false) {
    const [text, action] = copy[next] || ['', ''];
    renderLayout(() => {
      if (banner.hidden || next === 'none') {
        banner.classList.toggle('update-reveal', animate && next !== 'none');
      }
      state = next;
      banner.dataset.updateState = next;
      banner.hidden = next === 'none';
      message.textContent = text;
      version.textContent = next === 'ready' ? ` (${stagedVersion})` : '';
      button.textContent = action;
      button.hidden = !action;
      button.disabled = next === 'busy';
      progress.hidden = next !== 'installing';
    });
  }

  async function refresh(timeout = 500, animate = true) {
    const current = ++request;
    let timer;
    const snapshot = await Promise.race([
      Promise.resolve().then(() => Promise.all([bridge.updateState(), bridge.deviceState()])),
      new Promise(resolve => { timer = setTimeout(resolve, timeout); }),
    ]).catch(() => null).finally(() => clearTimeout(timer));
    if (current !== request) return;

    const [update, device] = snapshot || [];
    if (typeof device?.installUpdates !== 'boolean' || !update) {
      show('none');
    } else if (update.state === 'installing') {
      show('installing', animate);
    } else if (update.state === 'ready' && typeof update.versionName === 'string'
        && /^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$/.test(update.versionName)) {
      stagedVersion = update.versionName;
      show(failedVersion === stagedVersion ? 'failed' : 'ready', animate);
    } else {
      failedVersion = undefined;
      stagedVersion = undefined;
      show(update.state === 'none' && !device.installUpdates ? 'off' : 'none', animate);
    }
  }

  function reread() {
    if (state === 'busy') refreshAfterBusy = true;
    else if (!acting) void refresh();
  }

  button.addEventListener('click', async () => {
    if (acting) return;
    if (state === 'off') {
      bridge.openInstallSettings();
      return;
    }
    if (state !== 'ready' && state !== 'failed') return;
    acting = true;
    ++request;
    failedVersion = undefined;
    show('installing');
    const result = await Promise.resolve().then(() => bridge.installUpdate()).catch(() => null);
    acting = false;
    if (result?.state === 'busy') {
      show('busy');
      setTimeout(() => {
        show('ready');
        if (refreshAfterBusy) {
          refreshAfterBusy = false;
          reread();
        }
      }, 3000);
    } else if (result?.state === 'none') {
      show('none');
      await refresh(500, false);
    } else if (result?.state !== 'installing') {
      failedVersion = stagedVersion;
      show('failed');
    }
  });

  const remaining = deadline - performance.now();
  if (remaining > 0) await refresh(remaining, false);
  // The first screen is already unblocked, but the bridge hasn't been read yet.
  else void refresh();
  window.addEventListener('marongupdate', reread);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') reread();
  });
}
