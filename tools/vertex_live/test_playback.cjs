const assert=require('node:assert/strict');
const PlaybackBuffer=require('./static/playback.js');
// Real speech packets are about 160 ms; mobile delivery can bunch or delay them.
const queue=new PlaybackBuffer();let previousEnd=0;
const arrival=[0,.21,.28,.56,.64,.86,.93,1.12,1.37,1.43,1.62,1.8];
for(let i=0;i<arrival.length;i++){
  const start=queue.schedule(arrival[i],.16,i===0);
  if(i)assert(Math.abs(start-previousEnd)<1e-8,'Jitter must not insert gaps within the sentence');
  previousEnd=start+.16;
}
assert.equal(queue.underruns,0);
const afterStall=queue.schedule(previousEnd+.25,.16);
assert(afterStall>previousEnd+.25);assert.equal(queue.underruns,1);assert(queue.delay>=1.25);
const next=queue.schedule(afterStall-.01,.16);assert.equal(next,afterStall+.16);
queue.clear();assert.equal(queue.next,0);
const short=queue.schedule(10,.02,true);assert.equal(short,10+queue.delay);
const mobile=new PlaybackBuffer();
assert.equal(mobile.schedule(0,.16,true),.9);
assert.equal(mobile.schedule(.7,.16),1.06);
const inherited=new PlaybackBuffer(1.6);assert.equal(inherited.delay,1.6);
assert.equal(new PlaybackBuffer(99).delay,2);
console.log('PASS: continuous speech under bursty/mobile delivery, adaptive reserve after a stall, interruption reset, short utterance playback');
