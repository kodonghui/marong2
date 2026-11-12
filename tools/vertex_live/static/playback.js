'use strict';
// Keep a small playout reserve so jitter in a streamed sentence does not insert
// silence between each packet. Grow the reserve after a genuine underrun.
class PlaybackBuffer {
  constructor(reserve=.9){this.next=0;this.delay=Math.max(.9,Math.min(2,Number(reserve)||.9));this.underruns=0;this.maxGapMs=0;}
  schedule(now,duration,first=false){
    if(first||this.next===0)this.next=Math.max(this.next,now+this.delay);
    else if(this.next<now+.005){
      this.underruns++;
      this.maxGapMs=Math.max(this.maxGapMs,Math.round(Math.max(0,now-this.next)*1000));
      this.delay=Math.min(2,this.delay+Math.max(.15,now-this.next+.1));
      this.next=now+this.delay;
    }
    const start=this.next;this.next+=duration;return start;
  }
  clear(){this.next=0;}
}
if(typeof module!=='undefined')module.exports=PlaybackBuffer;
