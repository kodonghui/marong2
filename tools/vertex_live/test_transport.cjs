'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const media=[],control=[],mic={};let upstream;
class WebSocketMock {
 static OPEN=1;
 constructor(){upstream=this;this.readyState=1;this.bufferedAmount=0;this.sent=[];}
 send(x){this.sent.push(x);}close(){this.onclose?.();}
}
const self={postMessage:x=>control.push(x),close:()=>{}};
vm.runInNewContext(fs.readFileSync(__dirname+'/static/transport.js','utf8'),{self,WebSocket:WebSocketMock,ArrayBuffer,DataView,performance:{now:()=>100},setInterval:()=>{}});
self.onmessage({data:{type:'connect',url:'wss://example.invalid/live',output:{postMessage:x=>media.push(x)},microphone:mic}});
upstream.onopen();upstream.onmessage({data:JSON.stringify({type:'audio_reset',epoch:3})});upstream.onmessage({data:JSON.stringify({type:'ready'})});
function packet(epoch){const b=new ArrayBuffer(24+6),h=new DataView(b);[0x4d524732,epoch,7,1,0,3].forEach((x,i)=>h.setUint32(i*4,x));new Int16Array(b,24).set([100,200,300]);return b;}
upstream.onmessage({data:packet(3)});upstream.onmessage({data:packet(2)});
upstream.onmessage({data:JSON.stringify({type:'audio_end',epoch:3,turn:7})});
assert.deepEqual(media.map(x=>x.type),['clear','pcm','turn']);
assert.deepEqual([...new Int16Array(media[1].pcm)],[100,200,300]);
assert(!control.some(x=>x.data instanceof ArrayBuffer),'PCM passed through UI');
mic.onmessage({data:{pcm:new ArrayBuffer(3200)}});assert.equal(upstream.sent.length,1);
upstream.onmessage({data:JSON.stringify({type:'audio_transport',mode:'pcm',switched:true,epoch:3})});
upstream.onmessage({data:packet(3)});
const before=media.length;
upstream.onmessage({data:JSON.stringify({type:'audio_transport',mode:'pcm',switched:false,epoch:3})});
assert.equal(media.length,before,'duplicate ACK cleared PCM already playing');
mic.onmessage({data:{pcm:new ArrayBuffer(3200)}});assert.equal(upstream.sent.length,2,'fallback disabled microphone');
upstream.onmessage({data:JSON.stringify({type:'reconnecting'})});mic.onmessage({data:{pcm:new ArrayBuffer(3200)}});assert.equal(upstream.sent.length,2);
console.log('PASS: worker routes PCM directly to playback port, rejects old epochs, preserves end ordering, routes mic only when ready; UI receives no audio');
