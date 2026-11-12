'use strict';
// Exercise the real app startup path; no browser, credentials or network used.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const crypto=require('node:crypto');
const source=fs.readFileSync(__dirname+'/static/app.js','utf8');
async function scenario(rtcConnects){
  const nodes=new Map(),urls=[],rtcInstances=[];
  const element=()=>({textContent:'',hidden:false,disabled:false,value:'',children:[],classList:{toggle(){},remove(){}},
    setAttribute(){},replaceChildren(){},append(){}});
  class Context{
    constructor(){this.state='running';this.sampleRate=48000;this.audioWorklet={addModule:async()=>{}};}
    async resume(){} async close(){this.state='closed';}
  }
  class Worklet{constructor(){this.port={postMessage(){}};}connect(){}disconnect(){}}
  class Socket{
    constructor(url){urls.push(url);this.readyState=1;queueMicrotask(()=>this.onmessage?.({data:JSON.stringify({type:'ready',memoryConnected:false,callId:'synthetic'})}));}
    send(){}close(){this.readyState=3;}
  }
  class RTC{
    constructor(){this.stats={};this.closed=false;rtcInstances.push(this);}
    async connect(){if(!rtcConnects)throw new Error('simulated ICE timeout');}
    async close(){this.closed=true;}
  }
  const sandbox={console,crypto,performance,URL,Image:class{},matchMedia:()=>({matches:true}),
    document:{getElementById:id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},
      body:element(),visibilityState:'visible',addEventListener(){}},
    window:{AudioContext:Context,addEventListener(){}},navigator:{},AudioWorkletNode:Worklet,
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
  await vm.runInContext('end()',sandbox);
}
(async()=>{
  await scenario(false);await scenario(true);
  console.log('PASS initial WebRTC failure closes the candidate and starts WebSocket PCM; successful WebRTC startup selects rtc=1');
})().catch(error=>{console.error(error);process.exitCode=1;});
