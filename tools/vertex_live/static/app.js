'use strict';
const $=id=>document.getElementById(id);
const faceNames={1:'01-neutral',3:'03-listening',15:'15-mouth-slightly-open',16:'16-mouth-wide-open',18:'18-eyes-half-closed',19:'19-eyes-closed',20:'20-mouth-slightly-open-eyes-half-closed',21:'21-mouth-slightly-open-eyes-closed',22:'22-mouth-wide-open-eyes-half-closed',23:'23-mouth-wide-open-eyes-closed'};
const faceURL=n=>`/face/v1/${faceNames[n]}.webp`;
for(const n of Object.keys(faceNames)){const image=new Image();image.src=faceURL(n);}
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
const mouthFrames=[[1,210],[15,90],[16,170],[15,100],[1,120],[15,80],[16,120],[15,130],[1,230],[15,110],[16,230],[15,130],[1,260]];
let socket=null,stream=null,audioContext=null,worklet=null,micSource=null,wakeLock=null;
function newPlaybackBuffer(){let reserve;try{reserve=localStorage.getItem('marong.playbackReserve');}catch{}return new PlaybackBuffer(reserve);}
let playback=newPlaybackBuffer(),outputTurnOpen=false,playing=new Set(),retryTimer=null,starting=false,ready=false,intended=false;
let lastSpeaker=null,lastText=null,retryDelay=1000,firstReady=null,micMode=false,muted=false,hasConnected=false;
let speakingSince=0,lastFace=0,listenUntil=0,blinkAt=performance.now()+3500,blinkStarted=0;
let generation=0;
function status(text){$('status').textContent=text;}
function connection(text){$('connection').textContent=text;}
function callView(active){
  document.body.classList.toggle('in-call',active);
  $('start').hidden=active;$('stop').hidden=!active;$('mute').hidden=!active||!micMode;
  $('eyebrow').textContent=active?'지금, 우리 이야기':'너의 이야기 곁에';
  $('headline').textContent=active?'마롱이':'마롱이한테 전화할래?';
  $('control-caption').textContent=active?(micMode?'마이크 끄기 · 통화 끝내기':'통화 끝내기'):'편하게 전화해';
}
function clearAudio(){for(const item of playing){try{item.source.stop();}catch{}}playing.clear();playback.clear();outputTurnOpen=false;}
function transcript(who,text){
  if(who!==lastSpeaker||!lastText){const box=document.createElement('div');box.className='bubble '+who;const label=document.createElement('span');label.className='speaker';label.textContent=who==='user'?'나':'마롱이';lastText=document.createElement('span');box.append(label,lastText);$('transcript').append(box);lastSpeaker=who;}
  lastText.textContent+=text;
  while($('transcript').children.length>200)$('transcript').firstChild.remove();
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
  if(!audioContext||buffer.byteLength%2)return;
  const pcm=new Int16Array(buffer),audio=audioContext.createBuffer(1,pcm.length,24000),data=audio.getChannelData(0);
  for(let i=0;i<pcm.length;i++)data[i]=pcm[i]/32768;
  const source=audioContext.createBufferSource();source.buffer=audio;source.connect(audioContext.destination);
  const previousDelay=playback.delay;
  const start=playback.schedule(audioContext.currentTime,audio.duration,!outputTurnOpen);outputTurnOpen=true;
  if(playback.delay!==previousDelay)try{localStorage.setItem('marong.playbackReserve',String(playback.delay));}catch{}
  const item={source,start,end:start+audio.duration};playing.add(item);
  source.start(start);source.onended=()=>playing.delete(item);
}
async function keepAwake(){
  if(intended&&document.visibilityState==='visible'&&'wakeLock' in navigator){
    try{wakeLock=await navigator.wakeLock.request('screen');}catch{}
  }
}
async function end(message='또 이야기하자. 여기 있을게.'){
  generation++;
  intended=false;ready=false;starting=false;clearTimeout(retryTimer);retryTimer=null;
  const resolve=firstReady;firstReady=null;if(resolve)resolve(false);
  const old=socket;socket=null;
  if(old){old.onclose=null;try{if(old.readyState===WebSocket.OPEN)old.send(JSON.stringify({type:'stop'}));old.close();}catch{}}
  if(worklet){worklet.port.onmessage=null;worklet.disconnect();worklet=null;}
  if(micSource){micSource.disconnect();micSource=null;}
  if(stream){stream.getTracks().forEach(track=>track.stop());stream=null;}
  clearAudio();
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
  const current=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/live`);
  socket=current;current.binaryType='arraybuffer';
  if(previous){previous.onclose=null;previous.close();}
  current.onmessage=event=>{
    if(current!==socket||!intended)return;
    if(event.data instanceof ArrayBuffer){audioOut(event.data);return;}
    let message;try{message=JSON.parse(event.data);}catch{return;}
    if(message.type==='ready'){
      ready=true;starting=false;retryDelay=1000;document.body.classList.remove('reconnecting');$('send').disabled=false;
      connection('함께 이야기 중');status(micMode?'듣고 있어. 편하게 말해 줘.':'글로 말해도 괜찮아. 목소리로 답할게.');
      if(!hasConnected&&!message.resumed&&micMode)current.send(JSON.stringify({type:'text',text:'통화를 막 시작했어. 한국어로 짧고 편안하게 인사해 줘.'}));
      hasConnected=true;const resolve=firstReady;firstReady=null;if(resolve)resolve(true);
    }else if(message.type==='transcript'){transcript(message.who,message.text);}
    else if(message.type==='interrupted'){clearAudio();lastSpeaker=null;}
    else if(message.type==='turn'){lastSpeaker=null;outputTurnOpen=false;}
    else if(message.type==='reconnecting'){ready=false;$('send').disabled=true;document.body.classList.add('reconnecting');connection('다시 잇는 중');status('연결을 다시 잇고 있어. 잠깐만 기다려 줘.');}
  };
  current.onerror=()=>{if(intended&&current===socket)status('연결을 다시 잇고 있어. 곁에 있을게.');};
  current.onclose=()=>{
    if(!intended||current!==socket)return;
    ready=false;$('send').disabled=true;document.body.classList.add('reconnecting');connection('다시 잇는 중');status('연결을 다시 잇고 있어. 통화는 계속 유지할게.');
    clearTimeout(retryTimer);retryTimer=setTimeout(connect,retryDelay);retryDelay=Math.min(10000,retryDelay*2);
  };
}
async function begin(microphone){
  if(intended){if(ready)return true;return false;}
  const run=++generation;
  intended=true;starting=true;micMode=microphone;retryDelay=1000;hasConnected=false;
  playback=newPlaybackBuffer();outputTurnOpen=false;
  $('transcript').replaceChildren();lastSpeaker=null;lastText=null;
  callView(true);$('send').disabled=true;connection('연결 중');status('마롱이를 부르고 있어…');
  try{
    const Context=window.AudioContext||window.webkitAudioContext;
    audioContext=new Context();await audioContext.resume();
    if(run!==generation)return false;
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
        if(!muted&&event.data.rms>.018)listenUntil=performance.now()+800;
        if(intended&&ready&&socket?.readyState===WebSocket.OPEN&&socket.bufferedAmount<64000)socket.send(event.data.pcm);
      };
    }
    if(run!==generation)return false;
    keepAwake();const waiting=new Promise(resolve=>{firstReady=resolve;});connect();return await waiting;
  }catch(error){
    if(run!==generation)return false;
    await end(error.name==='NotAllowedError'?'마이크 사용을 허용해 줘. 준비되면 다시 전화해.':error.name==='NotFoundError'?'연결된 마이크가 없어. 글로도 이야기할 수 있어.':error.message);
    return false;
  }
}
$('start').onclick=()=>begin(true);
$('stop').onclick=()=>end();
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
    socket.send(JSON.stringify({type:'text',text}));$('message').value='';
  }
};
// Never end a call because of silence, elapsed time or tab visibility.
window.addEventListener('online',()=>{if(intended&&socket?.readyState!==WebSocket.OPEN){clearTimeout(retryTimer);connect();}});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&intended){audioContext?.resume().catch(()=>{});keepAwake();}});
window.addEventListener('pagehide',()=>{intended=false;clearTimeout(retryTimer);if(socket)socket.close();if(stream)stream.getTracks().forEach(track=>track.stop());});
setInterval(()=>{
  const now=performance.now(),audioTime=audioContext?.currentTime||0;
  const speaking=intended&&[...playing].some(item=>audioTime>=item.start&&audioTime<item.end);
  document.body.classList.toggle('speaking',speaking);
  let frame=intended&&now<listenUntil&&!muted?3:1;
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
setInterval(()=>{
  if(intended&&ready&&socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'playback_stats',underruns:playback.underruns,maxGapMs:playback.maxGapMs,bufferMs:Math.round(playback.delay*1000),contextState:audioContext?.state}));
},10000);
(async()=>{
  const token=location.hash.slice(1);
  if(token){
    try{const response=await fetch('/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});if(response.ok)history.replaceState(null,'',location.pathname);}catch{}
  }
  const state=await refresh();if(state?.ready&&!state.active)status('준비됐어. 네 이야기를 들려줘.');
})();
