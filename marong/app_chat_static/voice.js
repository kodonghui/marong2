'use strict';

(() => {
  const {node, button, request, signal} = Unified;
  const screen = document.getElementById('voice-screen');
  const title = document.getElementById('voice-title');
  const group = document.getElementById('voice-choices');
  const error = document.getElementById('voice-error');
  const notice = document.getElementById('voice-notice');
  const retry = document.getElementById('voice-retry');
  const player = new Audio();
  const afterIntro = new URLSearchParams(location.search).get('afterIntro');
  let profile, voices, current, noticeTimer, writing = false, loading = false;

  function stop() {
    player.pause();
    player.removeAttribute('src');
    if (current) {
      current.control.textContent = '▶';
      current.control.setAttribute('aria-label', current.label + ' 견본 듣기');
    }
    current = null;
  }

  function relogin() {
    try { sessionStorage.setItem('marong.session.return', location.pathname); } catch {}
    location.replace('/chat/login?expired=1');
  }

  function listen(voice, control, feedback) {
    const wasPlaying = current?.control === control;
    stop();
    if (wasPlaying) return;
    signal(feedback);
    const playback = {control, label: voice.label};
    current = playback;
    control.textContent = '■';
    control.setAttribute('aria-label', voice.label + ' 견본 멈추기');
    player.src = voice.sampleUrl;
    const failure = () => {
      if (current !== playback) return;
      signal(feedback, '지금은 견본을 못 틀었어');
      stop();
    };
    player.onerror = failure;
    player.onended = () => { if (current === playback) stop(); };
    player.play().catch(failure);
  }

  function render() {
    stop();
    title.textContent = profile.botName + '의 통화 목소리를 골라 줘';
    const selectedName = voices.some(voice => voice.name === profile.voice) ?
      profile.voice : voices.find(voice => voice.default)?.name;
    group.replaceChildren(...voices.map((voice) => {
      const card = node('div', '', 'card');
      const row = node('div', '', 'row');
      const selected = voice.name === selectedName;
      const select = button((selected ? '✓ ' : '') + voice.label + (voice.default ? ' · 기본' : ''),
        () => choose(voice), 'btn2');
      select.setAttribute('role', 'radio');
      select.setAttribute('aria-checked', String(selected));
      const feedback = node('p', '', 'err');
      feedback.hidden = true;
      const sample = button('▶', () => listen(voice, sample, feedback), 'btnt');
      sample.setAttribute('aria-label', voice.label + ' 견본 듣기');
      sample.disabled = !voice.sampleUrl;
      row.append(select, sample);
      card.append(row, feedback);
      if (!voice.sampleUrl) card.append(node('p', '견본은 아직 없어', 'caption'));
      return card;
    }));
    document.getElementById('voice-count').hidden = voices.length !== 1;
  }

  async function choose(voice) {
    if (writing) return;
    signal(error);
    writing = true;
    const controls = Array.from(group.querySelectorAll('button:not(:disabled)'));
    controls.forEach(control => { control.disabled = true; });
    const reply = await request('/chat/api/profile', {voice: voice.name}, 'PATCH');
    writing = false;
    controls.forEach(control => { control.disabled = false; });
    if (reply.status === 200) {
      if (afterIntro === 'profile' || /^[1-9][0-9]{0,18}$/.test(afterIntro || '')) {
        location.replace(afterIntro === 'profile' ? '/chat/me' : '/chat/character/' + afterIntro + '/try');
        return;
      }
      profile = reply.body;
      render();
      signal(notice, '다음 통화부터 이 목소리야');
      clearTimeout(noticeTimer);
      noticeTimer = setTimeout(() => signal(notice), 3000);
    } else if (reply.status === 401) relogin();
    else if (reply.body?.code === 'voice_unknown') {
      await load();
      signal(error, '그 목소리는 지금 고를 수 없어. 다른 걸 골라 줄래?');
    } else {
      signal(error, reply.body?.code === 'cross_site' ? '이 화면에서 다시 해 줘' :
        '잠깐 문제가 생겼어. 다시 해 볼래?', reply);
    }
  }

  async function load() {
    if (writing || loading) return;
    loading = true;
    const [me, list] = await Promise.all([request('/chat/api/profile'), request('/chat/api/voices')]);
    loading = false;
    screen.setAttribute('aria-busy', 'false');
    if (me.status === 401 || list.status === 401) { relogin(); return; }
    if (me.status !== 200 || list.status !== 200) {
      signal(error, '잠깐 문제가 생겼어. 다시 해 볼래?', me.status === 200 ? list : me);
      retry.replaceChildren(button('다시 해 볼게', load, 'btnt'));
      return;
    }
    signal(error);
    retry.replaceChildren();
    profile = me.body;
    voices = list.body.voices;
    render();
  }

  window.addEventListener('pagehide', stop);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') load();
    else stop();
  });
  load();
})();
