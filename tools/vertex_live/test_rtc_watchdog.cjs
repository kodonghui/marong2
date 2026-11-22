'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/static/rtc-client.js','utf8');
async function setup(){
  let now=100,packets=10,concealed=0;const faults=[],handlers={};
  class Room{on(event,fn){handlers[event]=fn;}async connect(){}async startAudio(){}async disconnect(){}}
  const box={LivekitClient:{Room,RoomEvent:{Disconnected:'disconnected',Reconnecting:'reconnecting',TrackSubscribed:'track',TrackUnsubscribed:'untrack'},Track:{Kind:{Audio:'audio'}}},
    document:{createElement:()=>({setAttribute(){},pause(){},remove(){}}),body:{append(){}}},
    performance:{now:()=>now},setInterval(){},clearInterval(){},setTimeout,clearTimeout,AbortController,
    fetch:async()=>({ok:true,json:async()=>({url:'synthetic',token:'synthetic'})})};
  vm.createContext(box);vm.runInContext(source,box);
  box.fault=reason=>faults.push(reason);
  const client=vm.runInContext('new MarongRTC({},()=>{},fault)',box);await client.connect('synthetic');
  client.track={getRTCStatsReport:async()=>new Map([['audio',{type:'inbound-rtp',kind:'audio',packetsReceived:packets,totalSamplesReceived:concealed,concealedSamples:concealed}]])};
  return {client,faults,handlers,time:n=>{now=n;},packets:n=>{packets=n;},concealed:n=>{concealed=n;}};
}
(async()=>{
  const s=await setup();await s.client.measure();s.time(4099);s.concealed(999999);await s.client.measure();assert.equal(s.faults.length,0);
  s.time(4100);await s.client.measure();assert.deepEqual(s.faults,['rtc_media_stalled']);
  s.handlers.disconnected();s.handlers.reconnecting();assert.equal(s.faults.length,1);await s.client.close();
  const r=await setup();await r.client.measure();r.time(4000);r.packets(11);await r.client.measure();r.time(7999);await r.client.measure();assert.equal(r.faults.length,0);await r.client.close();
  const n=await setup();n.client.track=null;n.time(8100);await n.client.measure();assert.deepEqual(n.faults,['rtc_no_media']);await n.client.close();
  const e=await setup();e.handlers.reconnecting();assert.deepEqual(e.faults,['rtc_reconnecting']);await e.client.close();
  console.log('PASS RTC media-only packet black hole (concealment is not receipt), transient recovery, no track, reconnect event and duplicate suppression');
})().catch(e=>{console.error(e);process.exitCode=1;});
