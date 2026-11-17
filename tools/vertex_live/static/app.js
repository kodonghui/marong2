'use strict';
(() => {
  const hour = 3_600_000, day = 24 * hour;
  const morning = 8 * hour, evening = 20 * hour;
  const root = document.documentElement;
  const themeColor = document.querySelector('meta[name="theme-color"]');
  const colorScheme = document.querySelector('meta[name="color-scheme"]');
  let timer;

  function syncTheme() {
    clearTimeout(timer);
    // Korean standard time stays UTC+9, independently of the device's time zone.
    const seoulTime = (Date.now() + 9 * hour) % day;
    const cream = seoulTime >= morning && seoulTime < evening;
    const theme = cream ? 'chestnut' : 'night';
    if (root.dataset.theme !== theme) {
      root.dataset.theme = theme;
      if (themeColor) themeColor.content = cream ? '#fbf6ee' : '#121729';
      if (colorScheme) colorScheme.content = cream ? 'light' : 'dark';
    }
    const next = seoulTime < morning ? morning : seoulTime < evening ? evening : day + morning;
    // Reach the boundary exactly and recheck if the device clock moves.
    timer = setTimeout(syncTheme, Math.min(next - seoulTime, 60_000));
  }

  syncTheme();
  window.addEventListener('pageshow', syncTheme);
  window.addEventListener('focus', syncTheme);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') syncTheme();
  });
})();

const $=id=>document.getElementById(id);
const CLIENT_VERSION='20261117-topic1';
const clientId=crypto.randomUUID();
const faceNames={1:'01-neutral',15:'15-mouth-slightly-open',16:'16-mouth-wide-open',18:'18-eyes-half-closed',19:'19-eyes-closed',20:'20-mouth-slightly-open-eyes-half-closed',21:'21-mouth-slightly-open-eyes-closed',22:'22-mouth-wide-open-eyes-half-closed',23:'23-mouth-wide-open-eyes-closed'};
const faceURL=n=>`/face/v1/${faceNames[n]}.webp`;
for(const n of Object.keys(faceNames)){const image=new Image();image.src=faceURL(n);}
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
const mouthFrames=[[1,210],[15,90],[16,170],[15,100],[1,120],[15,80],[16,120],[15,130],[1,230],[15,110],[16,230],[15,130],[1,260]];
let socket=null,stream=null,audioContext=null,worklet=null,player=null,micSource=null,wakeLock=null;
let playbackStats={},outputTurnOpen=false,lastAudioAt=0,maxArrivalGapMs=0,contextInterruptions=0,speaking=false;
let retryTimer=null,starting=false,ready=false,intended=false,hangingUp=false,hangupTimer=null;
let lastSpeaker=null,lastText=null,retryDelay=1000,firstReady=null,micMode=false,muted=false,hasConnected=false;
let speakingSince=0,lastFace=0,blinkAt=performance.now()+3500,blinkStarted=0;
let generation=0,epoch=0,callId=null,memoryConnected=false;
let rtcClient=null,rtcEnabled=false;
// A call Marong placed at a time the friend set (docs/app-ring.md SPEC-135): the app opens /?ring=<id>.
const UUID_RE=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
let ringId=null,ringShown=false;
{
  // Take the ring out of the address at once, so a reload or a shared link never answers it again.
  const search=location.search||'',found=/[?&]ring=([^&#]*)/.exec(search);
  if(found){
    let value='';try{value=decodeURIComponent(found[1]).toLowerCase();}catch{}
    const rest=search.replace(/([?&])ring=[^&#]*&?/,'$1').replace(/[?&]$/,'');
    history.replaceState(null,'',location.pathname+rest+(location.hash||''));
    if(UUID_RE.test(value))ringId=value;
  }
}
// The picture of a hello call (docs/04-functional-spec/call-first.md SPEC-269): the first 'ready' of the call that
// answered it carries {picture, title}; the face circle shows the picture for 15 seconds, once per picture.
const TOPIC_RE=/^\/chat\/topics\/v[0-9]{1,3}\/[a-z0-9-]{1,40}\.webp$/,TOPIC_MS=15000;
const topicSeen=new Set();let topicTimer=null,topicOn=false;
function topicCard(topic){
  const picture=topic?.picture,title=typeof topic?.title==='string'?topic.title.trim():'';
  if(typeof picture!=='string'||!TOPIC_RE.test(picture)||!title||title.length>20||topicSeen.has(picture))return;
  topicSeen.add(picture);
  const run=generation,image=new Image();
  // A picture that does not load shows nothing: the call goes on with her face.
  image.onload=()=>{
    if(!intended||generation!==run)return;
    const shown=$('topic-picture');shown.src=picture;shown.alt=title;shown.hidden=false;
    $('topic-title').textContent=title;$('topic-title').hidden=false;$('topic-close').hidden=false;
    document.body.classList.add('topic-on');topicOn=true;
    clearTimeout(topicTimer);topicTimer=setTimeout(closeTopic,TOPIC_MS);
  };
  image.src=picture;
}
function closeTopic(){
  clearTimeout(topicTimer);topicTimer=null;
  if(!topicOn)return;
  topicOn=false;
  const focused=document.activeElement===$('topic-close');
  document.body.classList.remove('topic-on');
  $('topic-picture').hidden=true;$('topic-picture').removeAttribute('src');$('topic-picture').alt='';
  $('topic-title').hidden=true;$('topic-close').hidden=true;
  if(focused&&!$('mute').hidden)$('mute').focus();
}
let pcmFallback=false,fallbackPending=false,fallbackReason=null,fallbackTimer=null;
function requestPCM(){
  clearTimeout(fallbackTimer);fallbackTimer=null;
  if(!intended||!fallbackPending)return;
  if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'audio_transport',mode:'pcm',reason:fallbackReason}));
  fallbackTimer=setTimeout(requestPCM,1500);
}
function fallbackToPCM(reason='rtc_disconnected'){
  if(!intended||pcmFallback)return;
  pcmFallback=true;fallbackPending=true;fallbackReason=reason;
  const old=rtcClient;rtcClient=null;
  // Silence RTC synchronously; disconnect must never hold up the PCM request.
  old?.close().catch(()=>{});clearAudio();
  status('소리 연결을 바꾸고 있어. 통화는 계속 이어갈게.');
  audioContext?.resume().catch(()=>{});requestPCM();
}
const captionNodes=new Map();
function status(text){$('status').textContent=text;}
function connection(text){$('connection').textContent=text;}
function callView(active){
  document.body.classList.toggle('in-call',active);
  $('start').hidden=active;$('stop').hidden=!active;$('mute').hidden=!active||!micMode;
  $('eyebrow').textContent=active?'지금, 우리 이야기':'너의 이야기 곁에';
  $('headline').textContent=active?'마롱이':'마롱이한테 전화할래?';
  $('control-caption').textContent=active?(micMode?'마이크 끄기 · 통화 끝내기':'통화 끝내기'):'편하게 전화해';
}
function clearAudio(nextEpoch=epoch){epoch=nextEpoch;player?.port.postMessage({type:'clear',epoch});speaking=false;outputTurnOpen=false;}
function transcript(who,text,key=null,replace=false){
  if(key&&captionNodes.has(key)){const node=captionNodes.get(key);node.textContent=replace?text:node.textContent+text;return;}
  if(key)lastSpeaker=null;
  if(who!==lastSpeaker||!lastText){const box=document.createElement('div');box.className='bubble '+who;const label=document.createElement('span');label.className='speaker';label.textContent=who==='user'?'나':'마롱이';lastText=document.createElement('span');box.append(label,lastText);$('transcript').append(box);lastSpeaker=who;}
  if(key)captionNodes.set(key,lastText);
  lastText.textContent+=text;
  while($('transcript').children.length>200){const box=$('transcript').firstChild;for(const [id,node] of captionNodes)if(box.contains(node))captionNodes.delete(id);box.remove();}
  $('transcript').scrollTop=$('transcript').scrollHeight;
}
async function refresh(){
  try{
    const response=await fetch('/status',{headers:{'X-Requested-With':'XMLHttpRequest'}});
    if(response.status===401||response.status===403||response.redirected){
      $('start').disabled=true;$('send').disabled=true;$('login').hidden=false;
      connection('로그인 필요');status('로그인하면 바로 이야기할 수 있어.');return null;
    }
    if(!response.ok)throw new Error('잠시 연결을 확인하고 있어.');
    const state=await response.json();
    rtcEnabled=Boolean(state.webRTC);
    memoryConnected=Boolean(state.memoryConnected);
    $('login').hidden=true;$('start').disabled=!state.ready||intended||state.active;
    $('send').disabled=!state.ready||starting||(!intended&&state.active);
    if(!intended){connection(state.active?'통화 중':'곁에 있어요');if(state.active)status('다른 창에서 통화 중이야. 그 통화를 마치면 여기서 걸 수 있어.');}
    return state;
  }catch{
    $('start').disabled=true;$('send').disabled=true;connection('연결 확인 중');
    if(!intended)status('연결을 확인하고 있어. 잠시 후 다시 준비할게.');return null;
  }
}
function audioOut(buffer){
  if(!player||buffer.byteLength<24)return;
  const header=new DataView(buffer);
  if(header.getUint32(0)!==0x4d524732)return;
  const packetEpoch=header.getUint32(4),turn=header.getUint32(8),count=header.getUint32(20);
  if(packetEpoch<epoch||buffer.byteLength!==24+count*2)return;
  if(packetEpoch>epoch)clearAudio(packetEpoch);
  const now=performance.now();if(outputTurnOpen)maxArrivalGapMs=Math.max(maxArrivalGapMs,Math.round(now-lastAudioAt));
  lastAudioAt=now;outputTurnOpen=true;
  const pcm=buffer.slice(24);player.port.postMessage({type:'pcm',pcm,turn,epoch:packetEpoch},[pcm]);
}
function sendPlaybackStats(){
  if(intended&&ready&&socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'playback_stats',...(rtcClient?rtcClient.stats:playbackStats),clientVersion:CLIENT_VERSION,engine:rtcClient?'webrtc':'audio-worklet',maxArrivalGapMs,contextInterruptions,contextState:audioContext?.state,sampleRate:audioContext?.sampleRate,micMode}));
}
async function keepAwake(){
  if(intended&&document.visibilityState==='visible'&&'wakeLock' in navigator){
    try{wakeLock=await navigator.wakeLock.request('screen');}catch{}
  }
}
const HANGUP_MESSAGE='통화를 마쳤어. 또 이야기하자.';
// Marong ends the call only on the friend's request (server-checked). Let her
// goodbye finish playing first: WebRTC audio can still be on its way.
function hangUpAfterPlayback(pendingMs=0){
  if(hangingUp||!intended)return;
  hangingUp=true;$('send').disabled=true;connection('통화 마치는 중');status('마롱이가 인사하고 통화를 마칠게.');
  const started=performance.now(),minimum=Math.min(10000,Math.max(0,Number(pendingMs)||0))+300;
  let quietSince=null;
  const check=()=>{
    hangupTimer=null;
    if(!intended||!hangingUp)return;
    const now=performance.now();
    const playing=rtcClient?speaking:(speaking||(playbackStats.queuedMs||0)>0);
    if(playing)quietSince=null;else if(quietSince===null)quietSince=now;
    if(now-started>=15000||(now-started>=minimum&&quietSince!==null&&now-quietSince>=600)){void end(HANGUP_MESSAGE);return;}
    hangupTimer=setTimeout(check,100);
  };
  check();
}
async function end(message='또 이야기하자. 여기 있을게.'){
  sendPlaybackStats();ringId=null;if(ringShown)ringOffer(false);closeTopic();
  if(memoryConnected&&callId)fetch(`/api/calls/${encodeURIComponent(callId)}/end`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{});
  generation++;
  intended=false;ready=false;starting=false;clearTimeout(retryTimer);retryTimer=null;
  hangingUp=false;clearTimeout(hangupTimer);hangupTimer=null;
  clearTimeout(fallbackTimer);fallbackTimer=null;fallbackPending=false;
  const resolve=firstReady;firstReady=null;if(resolve)resolve(false);
  const old=socket;socket=null;
  if(old){old.onclose=null;try{if(old.readyState===WebSocket.OPEN)old.send(JSON.stringify({type:'stop'}));old.close();}catch{}}
  if(worklet){worklet.port.onmessage=null;worklet.disconnect();worklet=null;}
  if(micSource){micSource.disconnect();micSource=null;}
  if(stream){stream.getTracks().forEach(track=>track.stop());stream=null;}
  if(rtcClient){await rtcClient.close();rtcClient=null;}
  clearAudio();
  if(player){player.port.onmessage=null;player.disconnect();player=null;}
  if(audioContext){const context=audioContext;audioContext=null;await context.close().catch(()=>{});}
  if(wakeLock){await wakeLock.release().catch(()=>{});wakeLock=null;}
  muted=false;$('mute').setAttribute('aria-pressed','false');$('mute').setAttribute('aria-label','마이크 끄기');
  document.body.classList.remove('speaking','reconnecting');callView(false);
  await refresh();status(message);
}
function connect(){
  if(!intended)return;
  ready=false;
  const previous=socket;
  const current=new WorkerSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/live?client=${encodeURIComponent(clientId)}&hangup=1${rtcClient?'&rtc=1':''}${ringId?'&ring='+ringId:''}`,player,worklet,CLIENT_VERSION);
  current.onstats=data=>{maxArrivalGapMs=data.maxArrivalGapMs;};
  socket=current;current.binaryType='arraybuffer';
  if(previous){previous.onclose=null;previous.close();}
  current.onmessage=event=>{
    if(current!==socket||!intended)return;
    if(event.data instanceof ArrayBuffer){audioOut(event.data);return;}
    let message;try{message=JSON.parse(event.data);}catch{return;}
    if(message.type==='ready'){
      callId=message.callId;memoryConnected=Boolean(message.memoryConnected);
      ready=true;starting=false;retryDelay=1000;document.body.classList.remove('reconnecting');$('send').disabled=false;
      sendPlaybackStats();
      connection('함께 이야기 중');status(micMode?'듣고 있어. 편하게 말해 줘.':'글로 말해도 괜찮아. 목소리로 답할게.');
      // Marong's own call: the server lets her speak first. A ring past its time is an ordinary call.
      if(ringId&&!hasConnected&&!message.ring)status('벨이 울린 지 오래돼서 보통 전화로 이어졌어.');
      if(message.topic)topicCard(message.topic);
      if(!hasConnected&&!message.resumed&&!message.ring&&micMode)current.send(JSON.stringify({type:'text',id:crypto.randomUUID(),text:'통화를 막 시작했어. 한국어로 짧고 편안하게 인사해 줘.'}));
      hasConnected=true;const resolve=firstReady;firstReady=null;if(resolve)resolve(true);
      if(rtcClient&&message.audioTransport==='pcm')fallbackToPCM('server_pcm');
      if(fallbackPending)requestPCM();
    }else if(message.type==='call_busy'){void end('디스코드 통화가 진행 중이야. 거기서 통화를 마치면 여기서 다시 걸 수 있어.');}
    else if(message.type==='hangup'){hangUpAfterPlayback(message.pendingMs);}
    else if(message.type==='transcript'){transcript(message.who,message.text,message.key,message.replace);}
    else if(message.type==='audio_transport'&&message.mode==='pcm'){
      pcmFallback=true;fallbackPending=false;clearTimeout(fallbackTimer);fallbackTimer=null;
      const old=rtcClient;rtcClient=null;old?.close().catch(()=>{});
      if(ready){connection('함께 이야기 중');status(micMode?'듣고 있어. 편하게 말해 줘.':'글로 말해도 괜찮아. 목소리로 답할게.');}
      sendPlaybackStats();
    }
    else if(message.type==='audio_reset'||message.type==='interrupted'){epoch=message.epoch;speaking=false;lastSpeaker=null;}
    else if(message.type==='audio_end'){outputTurnOpen=false;}
    else if(message.type==='turn'){lastSpeaker=null;}
    else if(message.type==='reconnecting'&&!hangingUp){ready=false;$('send').disabled=true;document.body.classList.add('reconnecting');connection('다시 잇는 중');status('연결을 다시 잇고 있어. 잠깐만 기다려 줘.');}
  };
  current.onerror=()=>{if(intended&&current===socket)status('연결을 다시 잇고 있어. 곁에 있을게.');};
  current.onclose=()=>{
    if(!intended||current!==socket)return;
    if(hangingUp){void end(HANGUP_MESSAGE);return;}
    if(rtcClient)fallbackToPCM('control_reconnect');
    ready=false;$('send').disabled=true;document.body.classList.add('reconnecting');connection('다시 잇는 중');status('연결을 다시 잇고 있어. 통화는 계속 유지할게.');
    clearTimeout(retryTimer);retryTimer=setTimeout(connect,retryDelay);retryDelay=Math.min(10000,retryDelay*2);
  };
}
async function begin(microphone){
  if(intended){if(ready)return true;return false;}
  const run=++generation;
  intended=true;starting=true;micMode=microphone;retryDelay=1000;hasConnected=false;
  pcmFallback=false;fallbackPending=false;fallbackReason=null;clearTimeout(fallbackTimer);
  hangingUp=false;clearTimeout(hangupTimer);hangupTimer=null;
  playbackStats={};outputTurnOpen=false;lastAudioAt=0;maxArrivalGapMs=0;contextInterruptions=0;speaking=false;
  $('transcript').replaceChildren();captionNodes.clear();lastSpeaker=null;lastText=null;epoch=0;callId=null;
  callView(true);$('send').disabled=true;connection('연결 중');status('마롱이를 부르고 있어…');
  try{
    const Context=window.AudioContext||window.webkitAudioContext;
    audioContext=new Context({latencyHint:'interactive'});await audioContext.resume();
    if(run!==generation)return false;
    const context=audioContext;
    context.onstatechange=()=>{if(context.state==='interrupted'||context.state==='suspended'){contextInterruptions++;sendPlaybackStats();}};
    await context.audioWorklet.addModule(`/playback.js?v=${CLIENT_VERSION}`);
    if(run!==generation)return false;
    let reserve;try{reserve=localStorage.getItem('marong.playbackReserve');}catch{}
    player=new AudioWorkletNode(context,'playback-pcm',{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[1],processorOptions:{reserve}});
    player.port.onmessage=({data})=>{
      if(data.bufferMs!==playbackStats.bufferMs)try{localStorage.setItem('marong.playbackReserve',String(data.bufferMs/1000));}catch{}
      playbackStats=data;if(!rtcClient)speaking=data.speaking;
    };
    player.onprocessorerror=()=>{status('소리 재생에 문제가 생겼어. 화면을 새로고침해 줘.');};
    player.connect(context.destination);
    if(microphone){
      if(!navigator.mediaDevices?.getUserMedia)throw new Error('마이크를 쓸 수 있는 HTTPS 주소로 열어 줘.');
      const media=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
      if(run!==generation){media.getTracks().forEach(track=>track.stop());return false;}
      stream=media;
      await audioContext.audioWorklet.addModule('/capture.js');
      if(run!==generation)return false;
      await audioContext.resume();
      if(run!==generation)return false;
      micSource=audioContext.createMediaStreamSource(stream);worklet=new AudioWorkletNode(audioContext,'capture-pcm');micSource.connect(worklet);worklet.connect(audioContext.destination);
      worklet.port.onmessage=event=>{
        if(event.data.pcm&&intended&&ready&&socket?.readyState===WebSocket.OPEN&&socket.bufferedAmount<64000)socket.send(event.data.pcm);
      };
    }
    if(run!==generation)return false;
    if(rtcEnabled){
      const rtc=new MarongRTC(context,value=>{speaking=value;},reason=>{if(rtcClient===rtc)fallbackToPCM(reason);});
      try{await rtc.connect(clientId);if(run!==generation){await rtc.close();return false;}rtcClient=rtc;}
      catch{await rtc.close();status('실시간 소리 연결을 다시 확인하고 있어.');}
    }
    keepAwake();const waiting=new Promise(resolve=>{firstReady=resolve;});connect();return await waiting;
  }catch(error){
    if(run!==generation)return false;
    await end(error.name==='NotAllowedError'?'마이크 사용을 허용해 줘. 준비되면 다시 전화해.':error.name==='NotFoundError'?'연결된 마이크가 없어. 글로도 이야기할 수 있어.':error.message);
    return false;
  }
}
function ringOffer(show){
  // In a browser (or an app without autoAnswer) Marong's call waits for the friend's tap on 받기.
  ringShown=show;
  $('headline').textContent=show?'마롱이가 건 전화예요':'마롱이한테 전화할래?';
  $('start').setAttribute('aria-label',show?'마롱이 전화 받기':'마롱이한테 전화하기');
  const label=$('start').querySelector?.('.button-label');if(label)label.textContent=show?'받기':'마롱이한테 전화하기';
  $('control-caption').textContent=show?'받으면 마롱이가 먼저 말할게':'편하게 전화해';
}
function answerRing(state){
  if(!ringId||!state?.ready||state.active||intended)return;
  if(window.__marongApp?.autoAnswer===true){
    // The app's answer button was the tap. If audio still waits for a gesture, any tap on the page resumes it.
    const run=generation+1;
    setTimeout(()=>{if(intended&&generation===run&&starting&&audioContext?.state!=='running')status('화면을 한 번 눌러 줘. 바로 이어질게.');},2000);
    void begin(true);
  }else{ringOffer(true);status('마롱이가 전화를 걸었어. 받기를 누르면 바로 이어져.');}
}
$('start').onclick=()=>begin(true);
$('stop').onclick=()=>end();
for(const id of ['topic-close','topic-picture','topic-title'])$(id).onclick=closeTopic;
$('login').onclick=()=>location.assign('/');
$('mute').onclick=()=>{
  muted=!muted;if(stream)stream.getAudioTracks().forEach(track=>{track.enabled=!muted;});
  $('mute').setAttribute('aria-pressed',String(muted));$('mute').setAttribute('aria-label',muted?'마이크 켜기':'마이크 끄기');
  $('control-caption').textContent=muted?'마이크 켜기 · 통화 끝내기':'마이크 끄기 · 통화 끝내기';
  status(muted?'마이크를 껐어. 다시 켤 때까지 기다릴게.':'듣고 있어. 편하게 말해 줘.');
  audioContext?.resume().catch(()=>{});
};
$('text-form').onsubmit=async event=>{
  event.preventDefault();const text=$('message').value.trim();if(!text)return;
  if(await begin(false)){
    await audioContext.resume();transcript('user',text);lastSpeaker=null;
    socket.send(JSON.stringify({type:'text',id:crypto.randomUUID(),text}));$('message').value='';
  }
};
// Never end a call because of silence, elapsed time or tab visibility.
window.addEventListener('online',()=>{if(intended){if(rtcClient)fallbackToPCM('network_change');if(socket?.readyState!==WebSocket.OPEN){clearTimeout(retryTimer);connect();}}});
navigator.connection?.addEventListener('change',()=>{if(intended&&rtcClient)fallbackToPCM('network_change');});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&intended){audioContext?.resume().catch(()=>{});keepAwake();}});
document.addEventListener('pointerdown',()=>{if(intended&&audioContext?.state!=='running')audioContext?.resume().catch(()=>{});},{passive:true});
window.addEventListener('pagehide',()=>{intended=false;clearTimeout(retryTimer);if(socket)socket.close();if(stream)stream.getTracks().forEach(track=>track.stop());});
setInterval(()=>{
  const now=performance.now();
  document.body.classList.toggle('speaking',intended&&speaking);
  let frame=1;  // 친구가 말하는 동안도 기본 얼굴(03 '듣는 얼굴'은 두 눈 높이가 달라 삐뚤어져 보여서 뺌, 2026-11-16)
  if(speaking){
    if(!speakingSince)speakingSince=now;
    let phase=(now-speakingSince+210)%1980;
    frame=15;
    if(!reducedMotion.matches)for(const [mouth,duration] of mouthFrames){if(phase<duration){frame=mouth;break;}phase-=duration;}
  }else speakingSince=0;
  if(!reducedMotion.matches){
    if(now>=blinkAt&&!blinkStarted)blinkStarted=now;
    if(blinkStarted){
      const elapsed=now-blinkStarted;
      if(elapsed<180){const closed=elapsed>=50&&elapsed<120;frame=frame===15?(closed?21:20):frame===16?(closed?23:22):(closed?19:18);}
      else{blinkStarted=0;blinkAt=now+3000+Math.random()*3000;}
    }
  }
  if(frame!==lastFace){lastFace=frame;$('face').src=faceURL(frame);$('face').alt=speaking?'말하고 있는 마롱이':'곁에서 기다리는 마롱이';}
},50);
setInterval(()=>{if(!intended)refresh();},15000);
setInterval(sendPlaybackStats,2000);
(async()=>{
  const token=location.hash.slice(1);
  if(token){
    try{const response=await fetch('/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});if(response.ok)history.replaceState(null,'',location.pathname);}catch{}
  }
  const state=await refresh();if(state?.ready&&!state.active)status('준비됐어. 네 이야기를 들려줘.');
  answerRing(state);
})();
// The in-app chat link (docs/app-chat.md SPEC-124): only when the chat answers 200 for this sign-in.
// An Access sign-in redirect comes back opaque (status 0) and keeps the link hidden.
(async()=>{
  try{
    const response=await fetch('/chat/api/me',{credentials:'same-origin',redirect:'manual',cache:'no-store'});
    if(response.status===200)$('chat-link').hidden=false;
  }catch{}
})();
