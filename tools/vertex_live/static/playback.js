'use strict';
// One continuous PCM stream on the audio rendering thread. Packet boundaries
// must not reset resampling, insert silence, or depend on UI timer scheduling.
class PCMPlayback {
  constructor(outputRate, reserve=.9) {
    this.rate=outputRate;this.step=24000/outputRate;
    this.reserve=Math.max(.9,Math.min(2,Number(reserve)||.9));
    this.ring=new Float32Array(24000*120);this.read=0;this.write=0;
    this.turns=[];this.underruns=0;this.maxGapMs=0;this.overflows=0;
    this.playedFrames=0;this.speaking=false;this.epoch=0;
    this.starvationFrames=0;this.rebufferFrames=0;this.silenceFrames=0;this.completed=0;
    this.stableTurns=0;
  }
  append(pcm,turnId=0,epoch=this.epoch) {
    if(epoch<this.epoch)return;
    if(epoch>this.epoch)this.clear(epoch);
    if(pcm.length>this.ring.length)return;
    if(!pcm.length)return;
    if(this.write-Math.floor(this.read)+pcm.length>this.ring.length){this.overflows++;this.clear();}
    if(this.turns.length&&this.turns.at(-1).id!==turnId&&this.turns.at(-1).end===null)this.finish(this.turns.at(-1).id);
    if(!this.turns.length||this.turns.at(-1).end!==null)this.turns.push({id:turnId,end:null,started:false,gap:0,stalled:false});
    for(const value of pcm)this.ring[this.write++%this.ring.length]=value/32768;
  }
  finish(turnId=0,epoch=this.epoch){if(epoch===this.epoch&&this.turns.length&&this.turns.at(-1).id===turnId)this.turns.at(-1).end=this.write;}
  clear(epoch=this.epoch){this.read=0;this.write=0;this.turns=[];this.speaking=false;this.epoch=epoch;}
  render(output) {
    output.fill(0);this.speaking=false;
    for(let i=0;i<output.length;i++){
      while(this.turns.length&&this.turns[0].end!==null&&this.read>=this.turns[0].end-1e-7){
        this.stableTurns=this.turns[0].stalled?0:this.stableTurns+1;
        if(this.stableTurns>=10){this.reserve=Math.max(.9,this.reserve-.1);this.stableTurns=0;}
        this.read=this.turns[0].end;this.turns.shift();this.completed++;
      }
      const turn=this.turns[0];if(!turn)continue;
      const end=turn.end??this.write,available=end-this.read;
      // Wait for actual buffered samples, not a timer after the first packet.
      // A finished short reply can play immediately without filling the reserve.
      if(!turn.started){
        if(turn.end!==null||available>=this.reserve*24000){
          turn.started=true;this.maxGapMs=Math.max(this.maxGapMs,Math.round(turn.gap*1000/this.rate));turn.gap=0;
        }else{if(turn.gap){turn.gap++;this.silenceFrames++;if(available<2)this.starvationFrames++;else this.rebufferFrames++;}continue;}
      }
      const index=Math.floor(this.read),fraction=this.read-index;
      if(turn.end===null&&index+1>=end){
        turn.started=false;turn.gap=1;turn.stalled=true;this.stableTurns=0;this.underruns++;
        this.reserve=Math.min(2,this.reserve+.3);this.silenceFrames++;this.starvationFrames++;continue;
      }
      const left=this.ring[index%this.ring.length];
      const right=this.ring[Math.min(index+1,end-1)%this.ring.length];
      output[i]=left+(right-left)*fraction;
      this.read+=this.step;this.playedFrames++;this.speaking=true;
    }
  }
  stats(){return {underruns:this.underruns,maxGapMs:this.maxGapMs,bufferMs:Math.round(this.reserve*1000),queuedMs:Math.round(Math.max(0,this.write-this.read)/24),playedMs:Math.round(this.playedFrames*1000/this.rate),networkStarvationMs:Math.round(this.starvationFrames*1000/this.rate),rebufferWaitMs:Math.round(this.rebufferFrames*1000/this.rate),insertedSilenceSamples:this.silenceFrames,overflows:this.overflows,speaking:this.speaking,epoch:this.epoch,completedTurns:this.completed};}
}
if(typeof AudioWorkletProcessor!=='undefined'){
  class PlaybackProcessor extends AudioWorkletProcessor {
    constructor(options){
      super();this.audio=new PCMPlayback(sampleRate,options.processorOptions?.reserve);this.frames=0;
      const receive=({data})=>{
        if(data.type==='pcm')this.audio.append(new Int16Array(data.pcm),data.turn,data.epoch);
        else if(data.type==='turn')this.audio.finish(data.turn,data.epoch);
        else if(data.type==='clear'){this.audio.clear(data.epoch);this.report();}
      };
      this.port.onmessage=event=>{
        if(event.data.type==='bind'){
          this.media?.close();this.audio.clear(0);this.media=event.data.port;this.media.onmessage=receive;
        }else receive(event);
      };
    }
    report(){this.port.postMessage(this.audio.stats());}
    process(inputs,outputs){
      const channels=outputs[0];if(!channels?.length)return true;
      this.audio.render(channels[0]);for(let n=1;n<channels.length;n++)channels[n].set(channels[0]);
      this.frames+=channels[0].length;
      if(this.frames>=sampleRate/20){this.frames=0;this.report();}
      return true;
    }
  }
  registerProcessor('playback-pcm',PlaybackProcessor);
}
if(typeof module!=='undefined')module.exports=PCMPlayback;
