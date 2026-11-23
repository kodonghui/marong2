'use strict';
const appStartedAt=performance.timeOrigin+performance.now();
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
const updateBannerReady=(()=>{
  if(!(window.__marongApp?.version>=3)||!$('update-banner'))return Promise.resolve();
  const deadline=performance.now()+500;
  let timer;
  return Promise.race([
    import('/chat/update-banner.js?v=20261123').then(({mountUpdateBanner})=>mountUpdateBanner($('update-banner'),deadline)),
    new Promise(resolve=>{timer=setTimeout(resolve,500);}),
  ]).catch(()=>{}).finally(()=>clearTimeout(timer));
})();
const CLIENT_VERSION='20261119-call-wait1';
let assetVersions={};
try{assetVersions=JSON.parse(document.documentElement.dataset.assets||'{}');}catch{}
const assetUrl=name=>'/'+name+(assetVersions[name]?'?v='+assetVersions[name]:'');
const clientId=crypto.randomUUID();
const faceNames={1:'01-neutral',4:'04-thinking',15:'15-mouth-slightly-open',16:'16-mouth-wide-open',18:'18-eyes-half-closed',19:'19-eyes-closed',20:'20-mouth-slightly-open-eyes-half-closed',21:'21-mouth-slightly-open-eyes-closed',22:'22-mouth-wide-open-eyes-half-closed',23:'23-mouth-wide-open-eyes-closed',6:'06-sad'};
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
let rtcCandidate=null,rtcPreparing=false,rtcPlaybackReady=false,audioReadySocket=null;
let currentAudioPath='pcm',lastPlaybackMessage='',lastPlaybackReport=-Infinity,rtcSilentMs=0;
let fallbackNoticeTimer=null;
let callTiming=null,timingTimer=null,statusReadyAt=null,callAttempts=0;
let nativeAnswerAt=null,coldNativeAnswer=false,nativeRoute={device:'unknown',ringer:'unknown'},preparedCall=false;

function startTiming(){
  clearTimeout(timingTimer);
  const time=performance.timeOrigin+performance.now();
  const base=nativeAnswerAt!==null?'answer':ringId?'page':'button';
  const origin=nativeAnswerAt??(ringId?performance.timeOrigin:time);
  callTiming={
    origin,sent:false,expired:false,fields:{
      base,entry:ringId?'ring':callAttempts?'redial':'button',
      reloaded:Boolean(ringId&&(nativeAnswerAt===null||coldNativeAnswer)),
    },
  };
  callAttempts++;
  nativeAnswerAt=null;
  coldNativeAnswer=false;
  markTiming('pageStart',performance.timeOrigin);
  markTiming('appStart',appStartedAt);
  if(statusReadyAt!==null)markTiming('statusReady',statusReadyAt);
  timingTimer=setTimeout(()=>{if(callTiming){callTiming.expired=true;flushTiming();}},15000);
}

function markTiming(name,time=performance.timeOrigin+performance.now()){
  if(name==='statusReady')statusReadyAt=time;
  if(callTiming&&!callTiming.sent&&!(name in callTiming.fields)){
    callTiming.fields[name]=Math.max(0,Math.min(600000,Math.round(time-callTiming.origin)));
  }
}

function flushTiming(){
  if(!callTiming||callTiming.sent||socket?.readyState!==WebSocket.OPEN)return;
  const assets=new Map();
  for(const resource of performance.getEntriesByType('resource')){
    const url=new URL(resource.name,location.origin);
    const name=url.pathname.slice(1);
    if(url.origin===location.origin&&name in assetVersions)assets.set(name,resource.transferSize===0);
  }
  const cached=[...assets.values()].filter(Boolean).length;
  callTiming.sent=true;
  clearTimeout(timingTimer);
  socket.send(JSON.stringify({type:'timing',v:1,client:{...callTiming.fields,cachedAssets:cached,fetchedAssets:assets.size-cached}}));
}

function firstPlayback(){
  markTiming('firstAudioPlayed');
  flushTiming();
}
let budgetBlocked=false,dailyBlocked=false;
const DAILY_MESSAGE='오늘 쓸 수 있는 양을 다 썼어. 새벽 4시에 다시 채워져';
const BUDGET_MESSAGE='이번 달 통화는 여기까지야. 다음 달에 또 걸어 줘. 글로는 계속 얘기할 수 있어';
// A call Marong placed at a time the friend set (docs/app-ring.md SPEC-135): the app opens /?ring=<id>.
const UUID_RE=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
let ringId=null,ringShown=false,botName='마롱이',characterId=null,lastCharacterFace=null;
{
  // Take the ring out of the address at once, so a reload or a shared link never answers it again.
  const search=location.search||'',found=/[?&]ring=([^&#]*)/.exec(search);
  if(found){
    let value='';try{value=decodeURIComponent(found[1]).toLowerCase();}catch{}
    const rest=search.replace(/([?&])ring=[^&#]*&?/,'$1').replace(/[?&]$/,'');
    history.replaceState(null,'',location.pathname+rest+(location.hash||''));
    if(UUID_RE.test(value)){
      ringId=value;
      if(Number.isFinite(window.__marongColdAnswerAt)&&window.__marongColdAnswerAt>0){
        nativeAnswerAt=window.__marongColdAnswerAt;coldNativeAnswer=true;
      }
    }
  }
}
// The picture of a hello call (docs/04-functional-spec/call-first.md SPEC-269): the first 'ready' of the call that
// answered it carries {picture, title}; the face circle shows the picture for 15 seconds, once per picture.
const TOPIC_RE=/^\/chat\/(?:topics\/v[0-9]{1,3}\/[a-z0-9-]{1,40}\.webp|api\/scenes\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/,TOPIC_MS=15000;
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
  rtcSilentMs=old?.silentMs||rtcSilentMs;
  currentAudioPath='pcm';
  // Silence RTC synchronously; disconnect must never hold up the PCM request.
  old?.close().catch(()=>{});clearAudio();
  status('소리 연결을 바꾸고 있어. 통화는 계속 이어갈게.');
  clearTimeout(fallbackNoticeTimer);
  fallbackNoticeTimer=setTimeout(endFallbackNotice,3000);
  audioContext?.resume().catch(()=>{});requestPCM();
}
function endFallbackNotice(){
  if(fallbackNoticeTimer===null)return;
  clearTimeout(fallbackNoticeTimer);fallbackNoticeTimer=null;
  if(intended&&ready)status(micMode?'듣고 있어. 편하게 말해 줘.':'글로 말해도 괜찮아. 목소리로 답할게.');
}
const captionNodes=new Map();
function status(text){
  const line=$('status');
  line.textContent=text;
  if(text!==DAILY_MESSAGE)return;
  const link=document.createElement('a');
  link.href='/chat/me';
  link.textContent='내 사용량 보기';
  line.append(' ',link);
}
const WAIT_TEXT='찾아보는 중…';
let waitTimer=null,waitCutoff=null,waitSource=null,waitBuffer=null,waiting=false,statusBeforeWait='';
function stopWaiting(){
  clearTimeout(waitTimer);waitTimer=null;
  clearTimeout(waitCutoff);waitCutoff=null;
  if(waitSource){waitSource.stop();waitSource.disconnect();waitSource=null;}
  if(waiting&&$('status').textContent===WAIT_TEXT)status(statusBeforeWait);
  waiting=false;
}
function startWaiting(){
  if(waiting||waitTimer!==null||!ready||hangingUp)return;
  waitTimer=setTimeout(()=>{
    waitTimer=null;
    if(!intended||!ready||hangingUp||speaking||outputTurnOpen||playbackStats.queuedMs>0)return;
    waiting=true;statusBeforeWait=$('status').textContent;status(WAIT_TEXT);
    if(waitBuffer&&audioContext?.state==='running'){
      waitSource=audioContext.createBufferSource();
      waitSource.buffer=waitBuffer;waitSource.loop=true;
      const gain=audioContext.createGain();gain.gain.value=0.25;
      waitSource.connect(gain);gain.connect(audioContext.destination);
      waitSource.onended=()=>gain.disconnect();waitSource.start();
    }
    waitCutoff=setTimeout(stopWaiting,19200);
  },800);
}
function connection(text){$('connection').textContent=text;}
function callView(active){
  document.body.classList.toggle('in-call',active);
  $('start').hidden=active;$('stop').hidden=!active;$('mute').hidden=!active||!micMode;
  $('eyebrow').textContent=active?'지금, 우리 이야기':'너의 이야기 곁에';
  $('headline').textContent=active?botName:botName+'한테 전화할래?';
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
function botParticle(withBatchim,withoutBatchim){
  const last=botName.charCodeAt(botName.length-1);
  return botName+(last>=0xac00&&last<=0xd7a3&&(last-0xac00)%28?withBatchim:withoutBatchim);
}
async function refreshProfile(){
  try{
    const response=await fetch('/chat/api/profile',{cache:'no-store'});
    if(!response.ok||intended)return;
    const profile=await response.json();
    if(!profile.botName)return;
    botName=profile.botName;
    const brand=document.querySelector('.brand');
    if(brand?.firstChild?.nodeType===Node.TEXT_NODE)brand.firstChild.textContent=botName;
    document.title=botName+' · 너의 이야기 곁에';
    characterId=profile.character?.id||null;
    const face=$('face');
    face.parentElement.querySelectorAll('.outfit-layer').forEach(layer=>layer.remove());
    for(const slot of ['body','neck','head']){
      const url=profile.character?.outfit?.[slot]?.layerUrl;
      if(typeof url!=='string'||!/^\/chat\/decor\/v[0-9]{1,3}\/[a-z0-9-]{3,40}\/[a-z_]+\.png$/.test(url))continue;
      const layer=new Image();
      layer.className='outfit-layer';layer.src=url;layer.alt='';
      layer.addEventListener('error',()=>layer.remove(),{once:true});
      $('topic-picture').before(layer);
    }
    const pending=profile.pendingRing;
    if(!ringId&&pending&&UUID_RE.test(pending.ringId)&&Date.parse(pending.until)>Date.now())ringId=pending.ringId;
  }catch{/* older chat servers may not have a profile API */}
}
async function refresh(){
  try{
    const profile=intended?Promise.resolve():refreshProfile();
    const response=await fetch('/status',{headers:{'X-Requested-With':'XMLHttpRequest'}});
    if(response.status===401||response.status===403||response.redirected){
      document.body.classList.remove('active-elsewhere');
      budgetBlocked=false;dailyBlocked=false;
      $('start').disabled=true;$('send').disabled=true;$('login').hidden=false;
      connection('로그인 필요');status('로그인하면 바로 이야기할 수 있어.');return null;
    }
    if(!response.ok)throw new Error('잠시 연결을 확인하고 있어.');
    const state=await response.json();
    const wasBudgetBlocked=budgetBlocked||dailyBlocked;
    budgetBlocked=state.canCall===false&&state.blockedReason==='budget';
    dailyBlocked=state.canCall===false&&state.blockedReason==='daily_limit';
    rtcEnabled=Boolean(state.webRTC);
    memoryConnected=Boolean(state.memoryConnected);
    document.body.classList.toggle('active-elsewhere',Boolean(state.active&&!intended));
    await Promise.all([profile,updateBannerReady]);
    document.body.classList.remove('checking-call');
    markTiming('statusReady');
    if(!intended)ringOffer(Boolean(ringId&&!state.active));
    $('login').hidden=true;$('start').disabled=!state.ready||intended||state.active||budgetBlocked||dailyBlocked;
    $('send').disabled=!state.ready||starting||(!intended&&(state.active||budgetBlocked||dailyBlocked));
    if(!intended){connection(state.active?'통화 중':'곁에 있어요');if(state.active)status('다른 창에서 통화 중이야. 그 통화를 마치면 여기서 걸 수 있어.');}
    if(!intended&&(budgetBlocked||dailyBlocked))status(dailyBlocked?DAILY_MESSAGE:BUDGET_MESSAGE);
    else if(!intended&&!state.active&&wasBudgetBlocked)status('준비됐어. 네 이야기를 들려줘.');
    return state;
  }catch{
    $('start').disabled=true;$('send').disabled=true;connection('연결 확인 중');
    if(!intended)status('연결을 확인하고 있어. 잠시 후 다시 준비할게.');return null;
  }finally{
    if(document.body.classList.contains('checking-call')){
      await updateBannerReady;
      document.body.classList.remove('checking-call');
    }
  }
}
function audioOut(buffer){
  if(!player||buffer.byteLength<24)return;
  const header=new DataView(buffer);
  if(header.getUint32(0)!==0x4d524732)return;
  const packetEpoch=header.getUint32(4),turn=header.getUint32(8),count=header.getUint32(20);
  if(packetEpoch<epoch||buffer.byteLength!==24+count*2)return;
  if(packetEpoch>epoch)clearAudio(packetEpoch);
  stopWaiting();
  const now=performance.now();if(outputTurnOpen)maxArrivalGapMs=Math.max(maxArrivalGapMs,Math.round(now-lastAudioAt));
  lastAudioAt=now;outputTurnOpen=true;
  const pcm=buffer.slice(24);player.port.postMessage({type:'pcm',pcm,turn,epoch:packetEpoch},[pcm]);
}
function sendPlaybackStats(){
  if(!intended||!ready||socket?.readyState!==WebSocket.OPEN)return;
  socket.send(JSON.stringify({type:'playback_stats',...(rtcClient?rtcClient.stats:playbackStats),clientVersion:CLIENT_VERSION,engine:rtcClient?'webrtc':'audio-worklet',maxArrivalGapMs,contextInterruptions,contextState:audioContext?.state,sampleRate:audioContext?.sampleRate,micMode}));
  const rtc=currentAudioPath==='webrtc'?rtcClient||rtcCandidate:null;
  const report=JSON.stringify({type:'playback',v:1,path:currentAudioPath,
    element:rtc?(rtc.element.paused?'paused':'playing'):'none',
    context:audioContext?.state,playout:rtc?.playout||'unsupported',
    silentMs:Math.min(600000,rtc?.silentMs||rtcSilentMs),...nativeRoute});
  const now=performance.now();
  if(report!==lastPlaybackMessage&&now-lastPlaybackReport>=30000){
    lastPlaybackMessage=report;lastPlaybackReport=now;socket.send(report);
  }
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
    if(now-started>=15000||(now-started>=minimum&&quietSince!==null&&now-quietSince>=600)){void end(HANGUP_MESSAGE,{hangup:true});return;}
    hangupTimer=setTimeout(check,100);
  };
  check();
}
async function end(message='또 이야기하자. 여기 있을게.',{hangup=false}={}){
  stopWaiting();waitBuffer=null;
  sendPlaybackStats();flushTiming();clearTimeout(timingTimer);ringId=null;if(ringShown)ringOffer(false);closeTopic();
  if(hangup&&memoryConnected&&callId)fetch(`/api/calls/${encodeURIComponent(callId)}/end`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{});
  generation++;
  intended=false;ready=false;starting=false;clearTimeout(retryTimer);retryTimer=null;
  hangingUp=false;clearTimeout(hangupTimer);hangupTimer=null;
  clearTimeout(fallbackTimer);fallbackTimer=null;fallbackPending=false;
  clearTimeout(fallbackNoticeTimer);fallbackNoticeTimer=null;
  const resolve=firstReady;firstReady=null;if(resolve)resolve(false);
  const old=socket;socket=null;
  if(old){old.onclose=null;try{if(hangup&&old.readyState===WebSocket.OPEN)old.send(JSON.stringify({type:'stop'}));old.close();}catch{}}
  if(worklet){worklet.port.onmessage=null;worklet.disconnect();worklet=null;}
  if(micSource){micSource.disconnect();micSource=null;}
  if(stream){stream.getTracks().forEach(track=>track.stop());stream=null;}
  if(rtcClient){await rtcClient.close();rtcClient=null;}
  if(rtcCandidate){await rtcCandidate.close();rtcCandidate=null;}
  clearAudio();
  if(player){player.port.onmessage=null;player.disconnect();player=null;}
  if(audioContext){const context=audioContext;audioContext=null;await context.close().catch(()=>{});}
  if(wakeLock){await wakeLock.release().catch(()=>{});wakeLock=null;}
  muted=false;$('mute').setAttribute('aria-pressed','false');$('mute').setAttribute('aria-label','마이크 끄기');
  document.body.classList.remove('speaking','reconnecting');callView(false);
  await refresh();status(message);
}
function connect(){
  if(!intended||socket?.readyState===WebSocket.CONNECTING||socket?.readyState===WebSocket.OPEN)return;
  ready=false;
  const previous=socket;
  const current=new WorkerSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/live?client=${encodeURIComponent(clientId)}&hangup=1&hold=1${(rtcPreparing||rtcClient)&&!pcmFallback?'&rtc=1':''}${ringId?'&ring='+ringId:''}`,player,worklet,assetUrl('transport.js'));
  current.onstats=data=>{maxArrivalGapMs=data.maxArrivalGapMs;};
  socket=current;current.binaryType='arraybuffer';
  current.onopen=()=>{if(socket===current){markTiming('liveOpen');sendAudioReady();if(callTiming?.expired)flushTiming();}};
  current.onfirstpcm=()=>{if(socket===current){currentAudioPath='pcm';markTiming('firstAudioIn');}};
  if(previous){previous.onclose=null;previous.close();}
  current.onmessage=event=>{
    if(current!==socket||!intended)return;
    if(event.data instanceof ArrayBuffer){audioOut(event.data);return;}
    let message;try{message=JSON.parse(event.data);}catch{return;}
    if(message.type==='ready'){
      markTiming('ready');
      callId=message.callId;memoryConnected=Boolean(message.memoryConnected);
      ready=true;starting=false;retryDelay=1000;document.body.classList.remove('reconnecting');$('send').disabled=false;
      sendPlaybackStats();
      connection('함께 이야기 중');status(micMode?'듣고 있어. 편하게 말해 줘.':'글로 말해도 괜찮아. 목소리로 답할게.');
      // Marong's own call: the server lets her speak first. A ring past its time is an ordinary call.
      if(ringId&&!hasConnected&&!message.ring)status('벨이 울린 지 오래돼서 보통 전화로 이어졌어.');
      if(message.topic)topicCard(message.topic);
      if(!hasConnected&&!message.resumed&&!message.ring&&micMode)current.send(JSON.stringify({type:'text',id:crypto.randomUUID(),text:'통화를 막 시작했어. 한국어로 짧고 편안하게 인사해 줘.'}));
      hasConnected=true;const resolve=firstReady;firstReady=null;if(resolve)resolve(true);
      if(fallbackPending)requestPCM();
    }else if(message.type==='budget_exhausted'){budgetBlocked=true;void end(BUDGET_MESSAGE);}
    else if(message.type==='daily_limit'){dailyBlocked=true;void end(DAILY_MESSAGE);}
    else if(message.type==='call_busy'){void end('다른 기기에서 '+botParticle('이랑','랑')+' 통화 중이야. 그 통화를 끝내고 다시 걸어 줘');}
    else if(message.type==='calls_full'){void end('지금은 전화가 꽉 찼어. 조금 있다가 다시 걸어 줘');}
    else if(message.type==='wait'){if(message.on)startWaiting();else stopWaiting();}
    else if(message.type==='hangup'){stopWaiting();hangUpAfterPlayback(message.pendingMs);}
    else if(message.type==='transcript'){transcript(message.who,message.text,message.key,message.replace);}
    else if(message.type==='audio_transport'&&message.mode==='pcm'){
      pcmFallback=true;fallbackPending=false;clearTimeout(fallbackTimer);fallbackTimer=null;
      const old=rtcClient;rtcClient=null;old?.close().catch(()=>{});
      if(ready)connection('함께 이야기 중');
      sendPlaybackStats();
    }
    else if(message.type==='audio_reset'||message.type==='interrupted'){stopWaiting();rtcClient?.nextTurn();epoch=message.epoch;speaking=false;lastSpeaker=null;}
    else if(message.type==='audio_end'){outputTurnOpen=false;}
    else if(message.type==='turn'){rtcClient?.nextTurn();lastSpeaker=null;}
    else if(message.type==='reconnecting'&&!hangingUp){stopWaiting();ready=false;$('send').disabled=true;document.body.classList.add('reconnecting');connection('다시 잇는 중');status('연결을 다시 잇고 있어. 잠깐만 기다려 줘.');}
  };
  current.onerror=()=>{if(intended&&current===socket)status('연결을 다시 잇고 있어. 곁에 있을게.');};
  current.onclose=()=>{
    if(!intended||current!==socket)return;
    flushTiming();
    stopWaiting();
    if(hangingUp){void end(HANGUP_MESSAGE,{hangup:true});return;}
    if(rtcClient)fallbackToPCM('control_reconnect');
    ready=false;$('send').disabled=true;document.body.classList.add('reconnecting');connection('다시 잇는 중');status('연결을 다시 잇고 있어. 통화는 계속 유지할게.');
    clearTimeout(retryTimer);retryTimer=setTimeout(connect,retryDelay);retryDelay=Math.min(10000,retryDelay*2);
  };
}

function sendAudioReady(){
  if(!intended||!socket||socket===audioReadySocket||socket.readyState!==WebSocket.OPEN)return;
  const path=rtcPlaybackReady&&!pcmFallback?'webrtc':!rtcPreparing&&player?'pcm':null;
  if(!path)return;
  audioReadySocket=socket;
  markTiming('audioReady');
  socket.send(JSON.stringify({type:'audio_ready',path}));
}

async function prepareRTC(context,run){
  if(!rtcPreparing)return;
  let rtc;
  try{
    const deadline=performance.now()+12000;
    await MarongRTC.waitForLibrary(deadline);
    if(run!==generation||pcmFallback)return;
    rtc=new MarongRTC(context,value=>{
      if(value){currentAudioPath='webrtc';markTiming('firstAudioIn');}
      speaking=value;
      if(value)stopWaiting();
    },reason=>{if(rtcClient===rtc)fallbackToPCM(reason);});
    rtcCandidate=rtc;
    rtc.onAudible=firstPlayback;
    rtc.onGesture=()=>{if(run===generation&&intended)status('화면을 한 번 눌러 줘. 바로 이어질게.');};
    rtc.onPlayable=()=>{
      if(run!==generation||pcmFallback)return;
      markTiming('rtcReady');
      rtcPlaybackReady=true;
      sendAudioReady();
    };
    await rtc.connect(clientId,deadline);
    if(run!==generation||pcmFallback){await rtc.close();return;}
    rtcClient=rtc;
  }catch{
    await rtc?.close();
    if(run===generation){
      status('실시간 소리 연결을 다시 확인하고 있어.');
      if(rtcPlaybackReady)fallbackToPCM('rtc_disconnected');
      rtcPlaybackReady=false;
    }
  }finally{
    if(run===generation){
      rtcCandidate=null;rtcPreparing=Boolean(rtcClient&&!rtcPlaybackReady);
      sendAudioReady();
    }
  }
}

async function preparePlayer(context,run){
  await context.audioWorklet.addModule(assetUrl('playback.js'));
  if(run!==generation)return;
  let reserve;try{reserve=localStorage.getItem('marong.playbackReserve');}catch{}
  player=new AudioWorkletNode(context,'playback-pcm',{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[1],processorOptions:{reserve}});
  player.port.onmessage=({data})=>{
    if(data.bufferMs!==playbackStats.bufferMs)try{localStorage.setItem('marong.playbackReserve',String(data.bufferMs/1000));}catch{}
    playbackStats=data;if(!rtcClient)speaking=data.speaking;
    if(data.playedMs>0){firstPlayback();endFallbackNotice();}
    if(speaking||data.queuedMs>0)stopWaiting();
  };
  player.onprocessorerror=()=>{status('소리 재생에 문제가 생겼어. 화면을 새로고침해 줘.');};
  player.connect(context.destination);
  socket?.bind(player,null);
  sendAudioReady();
}

async function prepareMicrophone(context,run){
  if(!navigator.mediaDevices?.getUserMedia)throw new Error('마이크를 쓸 수 있는 HTTPS 주소로 열어 줘.');
  const media=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
  if(run!==generation){media.getTracks().forEach(track=>track.stop());return;}
  stream=media;
  await context.audioWorklet.addModule(assetUrl('capture.js'));
  if(run!==generation)return;
  await context.resume();
  if(run!==generation)return;
  micSource=context.createMediaStreamSource(stream);
  worklet=new AudioWorkletNode(context,'capture-pcm');
  micSource.connect(worklet);worklet.connect(context.destination);
  socket?.bind(null,worklet);
  markTiming('micReady');
}
async function begin(microphone){
  if(budgetBlocked||dailyBlocked)return false;
  if(intended){if(ready)return true;return false;}
  const run=++generation;
  startTiming();
  intended=true;starting=true;micMode=microphone;retryDelay=1000;hasConnected=false;
  pcmFallback=false;fallbackPending=false;fallbackReason=null;clearTimeout(fallbackTimer);
  currentAudioPath='pcm';lastPlaybackReport=-Infinity;lastPlaybackMessage='';rtcSilentMs=0;
  hangingUp=false;clearTimeout(hangupTimer);hangupTimer=null;
  playbackStats={};outputTurnOpen=false;lastAudioAt=0;maxArrivalGapMs=0;contextInterruptions=0;speaking=false;
  $('transcript').replaceChildren();captionNodes.clear();lastSpeaker=null;lastText=null;epoch=0;callId=null;
  callView(true);$('send').disabled=true;connection('연결 중');status('마롱이를 부르고 있어…');
  try{
    const Context=window.AudioContext||window.webkitAudioContext;
    audioContext=new Context({latencyHint:'interactive'});await audioContext.resume();
    if(run!==generation)return false;
    const context=audioContext;
    fetch(assetUrl('wait-tone.wav'))
      .then(response=>response.ok?response.arrayBuffer():null)
      .then(data=>data?context.decodeAudioData(data):null)
      .then(buffer=>{if(context===audioContext)waitBuffer=buffer;}).catch(()=>{});
    context.onstatechange=()=>{if(context.state==='interrupted'||context.state==='suspended'){contextInterruptions++;sendPlaybackStats();}};
    rtcPreparing=rtcEnabled;
    rtcPlaybackReady=false;
    const waiting=new Promise(resolve=>{firstReady=resolve;});
    connect();
    void prepareRTC(context,run);
    await Promise.all([preparePlayer(context,run),microphone?prepareMicrophone(context,run):Promise.resolve()]);
    if(run!==generation)return false;
    keepAwake();
    return await waiting;
  }catch(error){
    if(run!==generation)return false;
    await end(error.name==='NotAllowedError'?'마이크 사용을 허용해 줘. 준비되면 다시 전화해.':error.name==='NotFoundError'?'연결된 마이크가 없어. 글로도 이야기할 수 있어.':error.message);
    return false;
  }
}
function ringOffer(show){
  // In a browser (or an app without autoAnswer) Marong's call waits for the friend's tap on 받기.
  ringShown=show;
  const subject=botParticle('이가','가');
  $('headline').textContent=show?subject+' 건 전화예요':botName+'한테 전화할래?';
  $('start').setAttribute('aria-label',show?botName+' 전화 받기':botName+'한테 전화하기');
  const label=$('start').querySelector?.('.button-label');if(label)label.textContent=show?'받기':botName+'한테 전화하기';
  $('control-caption').textContent=show?'받으면 '+subject+' 먼저 말할게':'편하게 전화해';
}
function answerRing(state){
  if(!ringId||!state?.ready||state.active||intended||budgetBlocked)return;
  if(window.__marongApp?.autoAnswer===true){
    // The app's answer button was the tap. If audio still waits for a gesture, any tap on the page resumes it.
    const run=generation+1;
    setTimeout(()=>{if(intended&&generation===run&&starting&&audioContext?.state!=='running')status('화면을 한 번 눌러 줘. 바로 이어질게.');},2000);
    void begin(true);
  }else{ringOffer(true);status(botParticle('이가','가')+' 전화를 걸었어. 받기를 누르면 바로 이어져.');}
}
if(!window.__marongCall){
  window.__marongCall=Object.freeze({
    version:1,
    answerRing(id,answeredAt){
      if(location.pathname!=='/'||intended||budgetBlocked||dailyBlocked
        ||typeof id!=='string'||!UUID_RE.test(id.toLowerCase())
        ||!Number.isFinite(answeredAt)||answeredAt<=0)return false;
      ringId=id.toLowerCase();nativeAnswerAt=answeredAt;
      const run=generation+1;
      setTimeout(()=>{if(intended&&generation===run&&starting&&audioContext?.state!=='running')status('화면을 한 번 눌러 줘. 바로 이어질게.');},2000);
      void begin(true);
      return true;
    },
    prepareCall(){
      if(location.pathname!=='/'||preparedCall)return false;
      preparedCall=true;
      void refresh();
      if(!window.LivekitClient&&!document.querySelector('script[src^="/livekit-client.js"]')){
        const script=document.createElement('script');script.async=true;script.src=assetUrl('livekit-client.js');
        document.head.append(script);
      }
      return true;
    },
    audioRoute(route){
      if(!route||typeof route!=='object')return false;
      const device=['speaker','wired','usb','bluetooth','earpiece'].includes(route.device)?route.device:'unknown';
      const ringer=['normal','vibrate','silent'].includes(route.ringer)?route.ringer:'unknown';
      nativeRoute={device,ringer};
      for(const key of ['voiceVolume','voiceVolumeMax']){
        const value=route[key];
        if(Number.isInteger(value)&&value>=0&&value<=100)nativeRoute[key]=value;
      }
      return true;
    },
  });
}
$('start').onclick=()=>begin(true);
$('stop').onclick=()=>end(undefined,{hangup:true});
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
window.addEventListener('pagehide',()=>{stopWaiting();flushTiming();intended=false;clearTimeout(retryTimer);if(socket)socket.close();if(stream)stream.getTracks().forEach(track=>track.stop());});
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
  if(waiting&&!speaking)frame=4;
  if((budgetBlocked||dailyBlocked)&&!intended)frame=6;
  if(frame!==lastFace||characterId!==lastCharacterFace){
    lastFace=frame;lastCharacterFace=characterId;
    const expression=({4:'surprised',6:'sad',15:'smile',16:'excited',18:'sleepy',19:'sleepy',20:'smile',21:'smile',22:'excited',23:'excited'})[frame]||'front';
    $('face').src=characterId?'/chat/api/characters/'+characterId+'/images/'+expression:faceURL(frame);
    $('face').alt=speaking?'말하고 있는 '+botName:'곁에서 기다리는 '+botName;
  }
},50);
setInterval(()=>{if(!intended)refresh();},15000);
setInterval(sendPlaybackStats,2000);
(async()=>{
  const token=location.hash.slice(1);
  if(token){
    try{const response=await fetch('/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});if(response.ok)history.replaceState(null,'',location.pathname);}catch{}
  }
  const state=await refresh();if(state?.ready&&!state.active&&!budgetBlocked&&!dailyBlocked)status('준비됐어. 네 이야기를 들려줘.');
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
