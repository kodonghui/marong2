import {AI_NOTICE, api, banner, button, CONSENT, el, errorText, header, link, page, picture,
  show, showTabs, text} from './pet.js';
import {rechargeSheet} from './orders.js';

const DISCLOSURE = 'AI로 만든 목소리예요';
const PCM_MAGIC = 0x4d524732;
const PACKET_HEADER = 24;

function socketUrl(value) {
  const url = new URL(value);
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  if (url.protocol !== protocol || url.host !== location.host || url.pathname !== '/pet-call'
      || url.username || url.password || url.search || url.hash) throw new Error('call URL');
  return url.href;
}

function stopAudio(attempt, notify) {
  clearTimeout(attempt.timer);
  const {socket, stream, context} = attempt;
  stream?.getTracks().forEach(track => track.stop());
  if (context) context.close().catch(() => {});
  if (socket && socket.readyState < WebSocket.CLOSING) {
    if (notify && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type: 'stop'}));
    socket.close();
  }
}

function playPacket(player, buffer) {
  if (buffer.byteLength <= PACKET_HEADER || buffer.byteLength % 2 !== 0) return;
  const frame = new DataView(buffer);
  if (frame.getUint32(0) !== PCM_MAGIC || frame.getUint32(20) * 2 !== buffer.byteLength - PACKET_HEADER) return;
  const pcm = buffer.slice(PACKET_HEADER);
  player.port.postMessage({type: 'pcm', epoch: frame.getUint32(4), turn: frame.getUint32(8), pcm}, [pcm]);
}

async function loadAudio(attempt) {
  const context = attempt.context = new AudioContext({latencyHint: 'interactive'});
  const resuming = context.resume().then(() => true, () => false);
  try {
    attempt.stream = await navigator.mediaDevices.getUserMedia({
      audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true},
    });
  } catch (error) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') error.micDenied = true;
    throw error;
  }
  if (attempt.cancelled) {
    attempt.stream.getTracks().forEach(track => track.stop());
    return;
  }
  if (!(await resuming)) throw new Error('audio context');
  await Promise.all([
    context.audioWorklet.addModule('/static/call-playback.js'), context.audioWorklet.addModule('/static/call-capture.js'),
  ]);
  if (attempt.cancelled) return;
  attempt.player = new AudioWorkletNode(context, 'playback-pcm');
  attempt.capture = new AudioWorkletNode(context, 'capture-pcm');
  attempt.player.connect(context.destination);
  context.createMediaStreamSource(attempt.stream).connect(attempt.capture);
  attempt.capture.connect(context.destination);
}

export async function callScreen(id) {
  header('통화');
  showTabs(null);
  show(el('div', {class: 'call-face skeleton', 'aria-hidden': 'true'}),
    el('div', {class: 'skeleton call-button-placeholder', 'aria-hidden': 'true'}));
  page.setAttribute('aria-busy', 'true');
  const petPath = '/pets/' + id;
  const petApi = '/api' + petPath;
  const [me, pet, quota] = await Promise.all([api('/api/me'), api(petApi), api('/api/me/quota')]);
  header(pet.name, {label: '대화', url: petPath});
  const back = (label = '대화로 돌아가기') => link(label, petPath);
  const body = el('section', {class: 'card stack call-card'});
  const status = el('div', {class: 'stack', role: 'status'});
  const controls = el('div', {class: 'stack'});
  let expression;
  let portrait;
  let active;
  let state;
  const face = name => {
    if (expression === name) return;
    expression = name;
    portrait?.remove();
    portrait = picture(pet.sheet[name] || pet.sheet.front, pet.name, 'call-face');
    body.prepend(portrait);
  };
  body.append(status, controls);
  show(banner(AI_NOTICE), body);

  function render(next, message, action, emotion = 'front') {
    state = next;
    face(emotion);
    status.replaceChildren(message ? text(message) : '');
    if (next === 'connecting' || next === 'talking' || next === 'sleepy') {
      status.append(el('small', {}, DISCLOSURE));
    }
    controls.replaceChildren(action);
  }

  const again = (label = '다시 해 보기') => button(label, start, 'primary');
  const hang = () => button('끊기', () => finish('member'));
  const ready = () => render('ready', '통화는 1분마다 오늘 한도를 써요 · 지금 ' + quota.percent + '%', again('전화 걸기'));

  function finish(reason) {
    if (!active) return;
    const attempt = active;
    active = null;
    attempt.cancelled = true;
    stopAudio(attempt, reason === 'member');
    if (reason === 'error') render('dropped', '연결이 끊겼어요', again('다시 걸기'));
    else render('ended', '통화했어요', back());
  }

  function failed(error) {
    if (error.micDenied) {
      render('mic-denied', '마이크를 허용해야 통화할 수 있어요', again());
      status.append(el('small', {}, /Safari/.test(navigator.userAgent) && !/Chrome|CriOS|Edg/.test(navigator.userAgent)
        ? 'Safari의 이 웹사이트 설정에서 마이크를 허용해 주세요.'
        : '주소창의 사이트 설정에서 마이크를 허용해 주세요.'));
    } else if (error.code === 'call_in_progress') {
      render('busy', '이미 통화 중이에요.', back());
    } else if (error.code === 'quota_exhausted_memorial' || error.prompt === 'none') {
      render('quota', '오늘은 여기까지, 새벽 4시 뒤에 또 이야기해요.', back());
    } else if (error.code === 'quota_exhausted') {
      render('quota', '오늘 한도를 다 썼어요. 새벽 4시에 다시 차요.', back());
      if (error.prompt === 'recharge') rechargeSheet(pet, true);
    } else if (error.code === 'budget_paused') {
      render('budget', '', back());
      errorText(error, status);
    } else if (error.code === 'archived') {
      render('permission', '보관한 아이예요. 꺼내면 다시 이야기할 수 있어요.', back('돌아가기'));
    } else if (error.code === 'consent_required') {
      render('permission', CONSENT, link('설정에서 바꾸기', '/me#consents'));
    } else if (error.code === 'call_unavailable' || !error.status) {
      render('unavailable', '지금은 통화를 걸 수 없어요.', again());
    } else {
      render('error', '', back());
      errorText(error, status);
    }
  }

  function connect(attempt, session) {
    const socket = attempt.socket = new WebSocket(socketUrl(session.wsUrl));
    socket.binaryType = 'arraybuffer';
    const {player, capture} = attempt;
    attempt.timer = setTimeout(() => { if (active === attempt) finish('error'); }, 20_000);
    socket.addEventListener('open', () => socket.send(JSON.stringify({type: 'auth', token: session.token})));
    socket.addEventListener('close', () => { if (active === attempt) finish('error'); });
    socket.addEventListener('message', ({data}) => {
      if (active !== attempt) return;
      if (data instanceof ArrayBuffer) {
        playPacket(player, data);
        return;
      }
      let event;
      try { event = JSON.parse(data); } catch { return; }
      if (event.type === 'ready') {
        clearTimeout(attempt.timer);
        render('talking', '', hang());
      } else if (event.type === 'audio_end') {
        player.port.postMessage({type: 'turn', epoch: event.epoch, turn: event.turn});
      } else if (event.type === 'audio_reset' || event.type === 'interrupted') {
        player.port.postMessage({type: 'clear', epoch: event.epoch});
      } else if (event.type === 'ending' && event.reason === 'quota') {
        render('sleepy', pet.name + '가 졸려서 자러 가요', hang(), 'sleepy');
      } else if (event.type === 'ended') {
        finish(event.reason);
      }
    });
    player.port.onmessage = ({data}) => {
      if (active === attempt && state === 'talking') face(data.speaking ? 'smile' : 'front');
    };
    capture.port.onmessage = ({data}) => {
      if (active === attempt && data.pcm && (state === 'talking' || state === 'sleepy')
          && socket.readyState === WebSocket.OPEN && socket.bufferedAmount < 32_000) socket.send(data.pcm);
    };
  }

  async function start() {
    if (active) return;
    const attempt = {cancelled: false};
    active = attempt;
    render('connecting', '연결하고 있어요', hang());
    try {
      await loadAudio(attempt);
      if (active !== attempt) return;
      const session = await api(petApi + '/calls', {method: 'POST'});
      if (active !== attempt) return;
      connect(attempt, session);
    } catch (error) {
      if (active !== attempt) return;
      active = null;
      stopAudio(attempt, false);
      failed(error);
    }
  }

  window.addEventListener('pagehide', () => { if (active) finish('member'); });
  if (pet.status === 'archived') failed({code: 'archived'});
  else if (!me.overseasTransfer) failed({code: 'consent_required'});
  else ready();
}
