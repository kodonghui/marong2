'use strict';
class MarongRTC {
  constructor(context,onSpeaking,onDisconnected=()=>{}){
    this.context=context;this.onSpeaking=onSpeaking;this.room=new LivekitClient.Room({adaptiveStream:false,dynacast:false});
    this.element=document.createElement('audio');this.element.autoplay=true;this.element.setAttribute('playsinline','');
    this.element.hidden=true;document.body.append(this.element);this.stats={};this.closed=false;
    this.room.on(LivekitClient.RoomEvent.Disconnected,()=>{if(!this.closed)onDisconnected();});
    this.room.on(LivekitClient.RoomEvent.TrackSubscribed,(track)=>{
      if(track.kind!==LivekitClient.Track.Kind.Audio)return;
      this.track=track;track.attach(this.element);this.element.play().catch(()=>{});
      this.source=this.context.createMediaStreamSource(new MediaStream([track.mediaStreamTrack]));
      this.analyser=this.context.createAnalyser();this.analyser.fftSize=256;this.source.connect(this.analyser);
      this.silent=this.context.createGain();this.silent.gain.value=0;this.analyser.connect(this.silent);this.silent.connect(this.context.destination);
    });
    this.timer=setInterval(()=>this.sample(),100);
    this.statsTimer=setInterval(()=>this.measure(),2000);
  }
  async connect(client){
    const response=await fetch('/api/rtc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client})});
    if(!response.ok)throw new Error('rtc_unavailable');
    const config=await response.json();await this.room.connect(config.url,config.token,{autoSubscribe:true});
    await this.room.startAudio();
  }
  sample(){
    if(!this.analyser)return;
    const data=new Float32Array(this.analyser.fftSize);this.analyser.getFloatTimeDomainData(data);
    const rms=Math.sqrt(data.reduce((sum,x)=>sum+x*x,0)/data.length);this.onSpeaking(rms>.008);
  }
  async measure(){
    try{
      const report=await this.track?.getRTCStatsReport();
      report?.forEach(row=>{if(row.type==='inbound-rtp'&&(row.kind==='audio'||row.mediaType==='audio')){
        this.stats={rtcConcealedSamples:row.concealedSamples||0,rtcSilentConcealedSamples:row.silentConcealedSamples||0,
          rtcConcealmentEvents:row.concealmentEvents||0,rtcPacketsLost:Math.max(0,row.packetsLost||0),rtcJitterMs:(row.jitter||0)*1000,rtcTotalSamples:row.totalSamplesReceived||0};
      }});
    }catch{}
  }
  async close(){
    if(this.closed)return;this.closed=true;clearInterval(this.timer);clearInterval(this.statsTimer);
    this.source?.disconnect();this.analyser?.disconnect();this.silent?.disconnect();
    this.element.pause();this.element.remove();await this.room.disconnect();
  }
}
