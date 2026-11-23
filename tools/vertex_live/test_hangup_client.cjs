'use strict';
// The page's side of Marong's hang-up: no browser, credentials or network used.
// It asks for the tool with ?hangup=1, lets the goodbye play out, then ends the
// call once with 'stop' and never reconnects.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const crypto=require('node:crypto');
const source=fs.readFileSync(__dirname+'/static/app.js','utf8');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function page(rtcConnects){
  const nodes=new Map(),urls=[],sockets=[],sent=[],rtc=[],clock={offset:0};
  const element=()=>({textContent:'',hidden:false,disabled:false,value:'',children:[],classList:{toggle(){},remove(){},add(){},contains(){return false;}},
    setAttribute(){},replaceChildren(){},append(){}});
  class Context{
    constructor(){this.state='running';this.sampleRate=48000;this.audioWorklet={addModule:async()=>{}};}
    async resume(){} async close(){this.state='closed';}
  }
  class Worklet{constructor(){this.port={postMessage(){}};}connect(){}disconnect(){}}
  class Socket{
    constructor(url){urls.push(url);sockets.push(this);this.readyState=1;queueMicrotask(()=>this.onmessage?.({data:JSON.stringify({type:'ready',memoryConnected:false,callId:'synthetic'})}));}
    send(data){sent.push(JSON.parse(data));}close(){this.readyState=3;}
    bind(){}
  }
  class RTC{
    static async waitForLibrary(){}
    constructor(context,speaking){this.speaking=speaking;this.closed=false;this.element={paused:false};rtc.push(this);}
    async connect(){if(!rtcConnects)throw new Error('simulated ICE timeout');}
    async close(){this.closed=true;}
  }
  const sandbox={console,crypto,URL,Image:class{},matchMedia:()=>({matches:true}),
    performance:{timeOrigin:performance.timeOrigin,now:()=>performance.now()+clock.offset,getEntriesByType:()=>[]},
    document:{getElementById:id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},
      body:element(),documentElement:{dataset:{}},querySelector(){return null;},visibilityState:'visible',addEventListener(){}},
    window:{AudioContext:Context,addEventListener(){}},navigator:{},AudioWorkletNode:Worklet,
    localStorage:{getItem(){return null;},setItem(){}},location:{protocol:'https:',host:'example.test',hash:'',pathname:'/'},history:{replaceState(){}},
    WebSocket:{CONNECTING:0,OPEN:1},WorkerSocket:Socket,MarongRTC:RTC,
    fetch:async()=>({ok:true,status:200,json:async()=>({ready:true,active:false,webRTC:true,memoryConnected:false})}),
    setInterval(){return 1;},clearInterval(){},
    setTimeout(fn,delay){const timer=setTimeout(fn,delay);if(fn.name==='syncTheme')timer.unref();return timer;},clearTimeout};
  vm.createContext(sandbox);vm.runInContext(source,sandbox);
  await new Promise(setImmediate);
  assert.equal(await vm.runInContext('begin(false)',sandbox),true);
  assert.equal(new URL(urls[0]).searchParams.get('hangup'),'1','page does not ask for the hang-up tool');
  const run=code=>vm.runInContext(code,sandbox);
  const message=data=>sockets.at(-1).onmessage({data:JSON.stringify(data)});
  const playback=data=>run('player').port.onmessage({data:{bufferMs:900,...data}});
  const stops=()=>sent.filter(x=>x.type==='stop').length;
  return {run,message,playback,stops,urls,sockets,sent,rtc,clock,nodes};
}
(async()=>{
  // PCM: wait while samples are still queued, then end once, without reconnecting.
  let p=await page(false);
  p.playback({speaking:true,queuedMs:900});
  p.message({type:'hangup',epoch:1,pendingMs:0,callId:'synthetic'});
  assert.equal(p.run('hangingUp && intended'),true);
  assert.equal(p.nodes.get('send').disabled,true,'text input stays open while hanging up');
  assert.equal(p.nodes.get('connection').textContent,'통화 마치는 중');
  p.message({type:'reconnecting'});
  assert.equal(p.nodes.get('connection').textContent,'통화 마치는 중','a reconnect notice replaced the goodbye state');
  await wait(700);
  assert.equal(p.stops(),0,'ended while the goodbye was still playing');
  p.playback({speaking:false,queuedMs:0});
  await wait(900);
  assert.equal(p.stops(),1,'did not end after the goodbye');
  assert.equal(p.run('!intended && !hangingUp && socket===null && retryTimer===null'),true);
  assert.equal(p.urls.length,1,'reconnected after hanging up');
  assert.equal(p.nodes.get('status').textContent,'통화를 마쳤어. 또 이야기하자.');
  p.message({type:'hangup',epoch:1,pendingMs:0});
  await wait(200);assert.equal(p.stops(),1,'a late hangup message did anything');

  // The server closes first (its own fallback): end instead of reconnecting.
  p=await page(false);
  p.playback({speaking:true,queuedMs:300});
  p.message({type:'hangup',epoch:1,pendingMs:0});
  p.sockets[0].readyState=3;p.sockets[0].onclose();
  await wait(50);
  assert.equal(p.run('!intended && retryTimer===null'),true,'socket close during hang-up started a reconnect');
  await wait(1200);assert.equal(p.urls.length,1);

  // WebRTC: audio still in the server bridge (pendingMs) is waited for even if the track is quiet.
  p=await page(true);
  assert.equal(p.rtc.length,1);
  p.message({type:'hangup',epoch:1,pendingMs:1200});
  await wait(1000);
  assert.equal(p.stops(),0,'ended before the bridged goodbye could play');
  p.rtc[0].speaking(true);await wait(400);assert.equal(p.stops(),0);
  p.rtc[0].speaking(false);await wait(900);
  assert.equal(p.stops(),1,'WebRTC page did not end after the goodbye');
  assert.equal(p.rtc[0].closed,true);

  // A goodbye that never goes quiet still ends at the 15 s cap.
  p=await page(false);
  p.playback({speaking:true,queuedMs:5000});
  p.message({type:'hangup',epoch:1,pendingMs:0});
  await wait(300);assert.equal(p.stops(),0);
  p.clock.offset+=15000;await wait(300);
  assert.equal(p.stops(),1,'15 s cap did not end the call');

  // A new call after a hang-up starts clean.
  p=await page(false);
  p.message({type:'hangup',epoch:1,pendingMs:0});
  await p.run('end()');
  assert.equal(await p.run('begin(false)'),true);
  assert.equal(p.run('hangingUp===false && hangupTimer===null && ready && intended'),true);
  await p.run('end()');
  console.log('PASS hangup=1 opt-in, goodbye drains (PCM queue and WebRTC bridge), one stop, no reconnect, server-first close, 15 s cap, clean next call');
})().catch(error=>{console.error(error);process.exitCode=1;});
