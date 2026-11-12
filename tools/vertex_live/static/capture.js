// Integrate source samples over each 16 kHz output interval. This preserves
// fractional boundaries between callbacks for Safari's 44.1/48 kHz capture.
class CaptureProcessor extends AudioWorkletProcessor {
  constructor(){
    super();this.block=new Int16Array(1600);this.used=0;
    this.ratio=sampleRate/16000;this.remaining=this.ratio;this.sum=0;this.energy=0;
    this.media=null;this.port.onmessage=({data})=>{if(data.type==='bind'){this.media?.close();this.media=data.port;}};
  }
  process(inputs,outputs){
    const input=inputs[0]?.[0];
    if(input)for(const value of input){
      let available=1;
      while(available>1e-8){
        const take=Math.min(available,this.remaining);
        this.sum+=value*take;this.remaining-=take;available-=take;
        if(this.remaining<1e-8){
          const sample=this.sum/this.ratio;
          this.energy+=sample*sample;
          this.block[this.used++]=Math.max(-32768,Math.min(32767,Math.round(sample*32768)));
          this.sum=0;this.remaining=this.ratio;
          if(this.used===this.block.length){
            const rms=Math.sqrt(this.energy/this.used);
            if(this.media){this.media.postMessage({pcm:this.block.buffer},[this.block.buffer]);this.port.postMessage({rms});}
            else this.port.postMessage({pcm:this.block.buffer,rms},[this.block.buffer]);
            this.block=new Int16Array(1600);this.used=0;this.energy=0;
          }
        }
      }
    }
    for(const output of outputs)for(const channel of output)channel.fill(0);
    return true;
  }
}
registerProcessor('capture-pcm',CaptureProcessor);
