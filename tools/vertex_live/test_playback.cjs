'use strict';
const assert=require('node:assert/strict');
const PCMPlayback=require('./static/playback.js');
const signal=n=>Int16Array.from({length:n},(_,i)=>Math.round(9000+2000*Math.sin(i*.071)));
function collect(p,frames){const out=[];for(let n=0;n<frames;n+=128){const block=new Float32Array(Math.min(128,frames-n));p.render(block);out.push(...block);}return out;}
function trim(a){let l=0,r=a.length;while(l<r&&a[l]===0)l++;while(r>l&&a[r-1]===0)r--;return a.slice(l,r);}
for(const rate of [24000,44100,48000]){
 const pcm=signal(24000*4),whole=new PCMPlayback(rate),fragmented=new PCMPlayback(rate);
 whole.append(pcm);whole.finish();const expected=trim(collect(whole,rate*5));
 let input=0,clock=0,output=[],next=0;const chunks=[137,3840,997,2081,480];
 while(clock<rate*6){
  if(input<pcm.length&&clock>=next){const size=Math.min(chunks[input%chunks.length],pcm.length-input);fragmented.append(pcm.slice(input,input+size));input+=size;next+=Math.round(size/24000*rate*.75);if(input===pcm.length)fragmented.finish();}
  const block=new Float32Array(128);fragmented.render(block);output.push(...block);clock+=128;
 }
 const actual=trim(output);assert.equal(actual.length,expected.length,rate+' sample count');
 for(let i=0;i<actual.length;i++)assert(Math.abs(actual[i]-expected[i])<1e-7,rate+' phase at '+i);
 assert.equal(fragmented.underruns,0);
}
// A small first packet followed by a long delay must not start a doomed timer.
const sparse=new PCMPlayback(48000);sparse.append(new Int16Array(480).fill(10000));
assert(collect(sparse,48000*1.3).every(x=>x===0));
sparse.append(new Int16Array(24000).fill(10000));sparse.finish();
const sparseOut=trim(collect(sparse,48000*2));assert(sparseOut.every(x=>x>0));assert.equal(sparse.underruns,0);
// A true outage is counted once; completion releases a short tail immediately.
const stalled=new PCMPlayback(48000);stalled.append(new Int16Array(24000).fill(10000));collect(stalled,48000*2.2);
assert.equal(stalled.underruns,1);stalled.append(new Int16Array(2400).fill(10000));stalled.finish();
assert(collect(stalled,480)[0]>0);assert.equal(stalled.underruns,1);assert(stalled.stats().networkStarvationMs>1000);
// Clear invalidates an older audio epoch; turn-end events cannot close newer turns.
const epoch=new PCMPlayback(48000);epoch.append(signal(1000),1,1);epoch.clear(2);epoch.append(signal(1000),1,1);
assert.equal(epoch.write,0);epoch.append(new Int16Array(1000).fill(9000),2,2);epoch.finish(1,2);
assert.equal(epoch.turns[0].end,null);epoch.finish(2,2);assert(trim(collect(epoch,3000)).every(x=>x>0));
// 100 complete turns, mixed packet sizes; no new silence within any turn.
for(let n=0;n<100;n++){const p=new PCMPlayback(n%2?44100:48000);const pcm=signal(1200+n*19);for(let i=0;i<pcm.length;i+=317)p.append(pcm.slice(i,i+317),n);p.finish(n);assert(trim(collect(p,Math.ceil(pcm.length*p.rate/24000)+256)).every(x=>x>0));assert.equal(p.underruns,0);}
console.log('PASS: rendered PCM continuity at 24/44.1/48 kHz, jitter/sparse startup, outage recovery, epochs, 100 short turns');
