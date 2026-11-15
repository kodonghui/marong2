// Exercise real worklet code at desktop and Safari input rates.
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
for(const rate of [16000,44100,48000]){
  const packets=[];let Processor;
  const context={sampleRate:rate,AudioWorkletProcessor:class{constructor(){this.port={postMessage:m=>packets.push(m)};}},registerProcessor:(_,p)=>{Processor=p;}};
  vm.runInNewContext(fs.readFileSync(__dirname+'/static/capture.js','utf8'),context);
  const processor=new Processor();
  for(let offset=0;offset<rate*2;offset+=128){
    const input=new Float32Array(Math.min(128,rate*2-offset)).fill(.25);
    const output=new Float32Array(128).fill(1);
    assert.equal(processor.process([[input]],[[output]]),true);
    assert(output.every(v=>v===0),'Microphone must never echo to speakers');
  }
  assert.equal(packets.length,20,`${rate} Hz must produce exactly two seconds of 16 kHz PCM`);
  for(const packet of packets){assert.equal(packet.pcm.byteLength,3200);assert(new Int16Array(packet.pcm).every(v=>v===8192));assert(Math.abs(packet.rms-.25)<1e-6);}
}
console.log('PASS: 16/44.1/48 kHz capture, continuous fractional resampling, PCM levels, RMS, silent output');
