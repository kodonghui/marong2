'use strict';
// Exercise the real app startup path; no browser, credentials or network used.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const crypto=require('node:crypto');
const source=fs.readFileSync(__dirname+'/static/app.js','utf8');
async function scenario(rtcConnects,midCall=false){
  const nodes=new Map(),urls=[],rtcInstances=[],sockets=[],sent=[],listeners={};
  const element=()=>({textContent:'',hidden:false,disabled:false,value:'',children:[],classList:{toggle(){},remove(){},add(){}},
    setAttribute(){},replaceChildren(){},append(){}});
  class Context{
    constructor(){this.state='running';this.sampleRate=48000;this.audioWorklet={addModule:async()=>{}};}
    async resume(){} async close(){this.state='closed';}
  }
  class Worklet{constructor(){this.port={postMessage(){}};}connect(){}disconnect(){}}
  class Socket{
    constructor(url){urls.push(url);sockets.push(this);this.readyState=1;queueMicrotask(()=>this.onmessage?.({data:JSON.stringify({type:'ready',memoryConnected:false,callId:'synthetic'})}));}
    send(data){sent.push(JSON.parse(data));}close(){this.readyState=3;}
  }
  class RTC{
    constructor(context,speaking,failed){this.stats={};this.closed=false;this.failed=failed;rtcInstances.push(this);}
    async connect(){if(!rtcConnects)throw new Error('simulated ICE timeout');}
    async close(){this.closed=true;}
  }
  const sandbox={console,crypto,performance,URL,Image:class{},matchMedia:()=>({matches:true}),
    document:{getElementById:id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},
      body:element(),visibilityState:'visible',addEventListener(){}},
    window:{AudioContext:Context,addEventListener(name,fn){listeners[name]=fn;}},navigator:{},AudioWorkletNode:Worklet,
    localStorage:{getItem(){return null;},setItem(){}},location:{protocol:'https:',host:'example.test',hash:'',pathname:'/'},history:{replaceState(){}},
    WebSocket:{OPEN:1},WorkerSocket:Socket,MarongRTC:RTC,
    fetch:async()=>({ok:true,status:200,json:async()=>({ready:true,active:false,webRTC:true,memoryConnected:false})}),
    setInterval(){return 1;},clearInterval(){},setTimeout,clearTimeout};
  vm.createContext(sandbox);vm.runInContext(source,sandbox);
  await new Promise(setImmediate);
  assert.equal(await vm.runInContext('begin(false)',sandbox),true);
  assert.equal(urls.length,1);
  assert.equal(new URL(urls[0]).searchParams.get('rtc'),rtcConnects?'1':null);
  assert.equal(rtcInstances[0].closed,!rtcConnects);
  assert.equal(vm.runInContext('ready && intended',sandbox),true);
  if(midCall){
    const original=vm.runInContext('({socket,player,audioContext,callId,generation})',sandbox);
    rtcInstances[0].failed('rtc_media_stalled');
    rtcInstances[0].failed('rtc_disconnected');
    assert.equal(rtcInstances[0].closed,true);
    assert.equal(sent.filter(x=>x.type==='audio_transport').length,1,'duplicate RTC errors started extra transitions');
    assert.equal(sent.at(-1).reason,'rtc_media_stalled');
    assert.equal(vm.runInContext('ready && intended && !rtcClient',sandbox),true);
    for(const [key,value] of Object.entries(original))assert.equal(vm.runInContext(key,sandbox),value,`${key} changed during fallback`);
    // A lost ACK is retried on the same socket, without another clear or call.
    await vm.runInContext('requestPCM()',sandbox);
    assert.equal(sent.filter(x=>x.type==='audio_transport').length,2);
    sockets[0].onmessage({data:JSON.stringify({type:'audio_transport',mode:'pcm',switched:true,epoch:1,callId:'synthetic'})});
    assert.equal(vm.runInContext('!fallbackPending && fallbackTimer===null',sandbox),true);
    listeners.online();assert.equal(urls.length,1,'healthy control WS reconnected');
    // When Wi-Fi also drops the control socket, reconnect in PCM and retain call intent.
    sockets[0].readyState=3;sockets[0].onclose();listeners.online();
    await new Promise(setImmediate);
    assert.equal(urls.length,2);assert.equal(new URL(urls[1]).searchParams.has('rtc'),false);
    assert.equal(vm.runInContext('callId',sandbox),original.callId);
    assert.equal(rtcInstances.length,1,'RTC retried on blocked network');
    assert(!sent.some(x=>x.type==='stop'),'failover hung up the call');
  }
  await vm.runInContext('end()',sandbox);
}
(async()=>{
  await scenario(false);await scenario(true);await scenario(true,true);
  console.log('PASS initial RTC failure, same-call PCM fallback, duplicate faults, ACK retry, control WS recovery, sticky PCM and cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
