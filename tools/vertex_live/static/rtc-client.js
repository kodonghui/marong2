'use strict';
class MarongRTC {
  static async waitForLibrary(deadline){
    while(!window.LivekitClient){
      const remaining=deadline-performance.now();
      if(remaining<=0)throw new Error('rtc_timeout');
      await new Promise(resolve=>setTimeout(resolve,Math.min(remaining,25)));
    }
  }

  constructor(context,onSpeaking,onDisconnected=()=>{}){
    this.context=context;this.onSpeaking=onSpeaking;this.room=new LivekitClient.Room({adaptiveStream:false,dynacast:false});
    this.element=document.createElement('audio');this.element.autoplay=true;this.element.setAttribute('playsinline','');
    this.element.hidden=true;document.body.append(this.element);this.stats={};this.closed=false;
    this.connectedAt=0;this.lastPacketAt=0;this.lastPackets=null;this.fault=null;
    this.receiving=false;this.silentMs=0;this.playout='unsupported';this.turnSilent=0;
    this.lastPlayedSamples=null;this.retried=false;
    this.fail=reason=>{if(this.closed||this.fault)return;this.fault=reason;onDisconnected(reason);};
    this.room.on(LivekitClient.RoomEvent.Disconnected,()=>this.fail('rtc_disconnected'));
    this.room.on(LivekitClient.RoomEvent.Reconnecting,()=>this.fail('rtc_reconnecting'));
    this.room.on(LivekitClient.RoomEvent.TrackUnsubscribed,track=>{if(track===this.track)this.fail('rtc_track_lost');});
    if(LivekitClient.RoomEvent.AudioPlaybackStatusChanged){
      this.room.on(LivekitClient.RoomEvent.AudioPlaybackStatusChanged,()=>{
        if(this.room.canPlaybackAudio===false)this.room.startAudio().catch(()=>this.onGesture?.());
      });
    }
    this.room.on(LivekitClient.RoomEvent.TrackSubscribed,(track)=>{
      if(track.kind!==LivekitClient.Track.Kind.Audio)return;
      this.track=track;track.attach(this.element);this.play().catch(()=>{});
      this.source=this.context.createMediaStreamSource(new MediaStream([track.mediaStreamTrack]));
      this.analyser=this.context.createAnalyser();this.analyser.fftSize=256;this.source.connect(this.analyser);
      this.silent=this.context.createGain();this.silent.gain.value=0;this.analyser.connect(this.silent);this.silent.connect(this.context.destination);
    });
    this.timer=setInterval(()=>this.sample(),100);
    this.statsTimer=setInterval(()=>this.measure(),1000);
    this.playbackTimer=setInterval(()=>{void this.checkPlayback();},500);
  }
  async connect(client,deadline=performance.now()+12000){
    const remaining=deadline-performance.now();
    if(remaining<=0)throw new Error('rtc_timeout');
    const controller=new AbortController();
    let timeout;
    const init=async()=>{
      const response=await fetch('/api/rtc',{method:'POST',signal:controller.signal,
        headers:{'Content-Type':'application/json'},body:JSON.stringify({client})});
      if(!response.ok)throw new Error('rtc_unavailable');
      const config=await response.json();
      await this.room.connect(config.url,config.token,{autoSubscribe:true});
      if(this.closed||this.fault)throw new Error('rtc_unavailable');
      await this.room.startAudio().catch(()=>this.onGesture?.());
      this.connectedAt=performance.now();this.lastPacketAt=this.connectedAt;
    };
    try{
      await Promise.race([init(),new Promise((_,reject)=>{
        timeout=setTimeout(()=>{controller.abort();reject(new Error('rtc_timeout'));},remaining);
      })]);
    }finally{clearTimeout(timeout);}
  }
  sample(){
    if(!this.analyser)return;
    const data=new Float32Array(this.analyser.fftSize);this.analyser.getFloatTimeDomainData(data);
    const rms=Math.sqrt(data.reduce((sum,x)=>sum+x*x,0)/data.length);
    this.receiving=rms>.008;
    this.onSpeaking(this.receiving);
  }
  async play(){
    await this.element.play();
    this.onPlayable?.();
  }
  nextTurn(){
    this.turnSilent=0;this.retried=false;
  }
  async checkPlayback(){
    if(!this.track||this.closed||this.checkingPlayback)return;
    this.checkingPlayback=true;
    try{
      let samples=null;
      try{
        const stats=await this.track.getRTCStatsReport();
        stats?.forEach(row=>{
          if(row.type==='media-playout'&&Number.isFinite(row.totalSamplesCount))samples=row.totalSamplesCount;
        });
      }catch{}
      if(this.closed)return;
      const advancing=samples!==null&&this.lastPlayedSamples!==null&&samples>this.lastPlayedSamples;
      this.playout=samples===null?'unsupported':advancing?'advancing':'stalled';
      this.lastPlayedSamples=samples;
      if(!this.receiving)return;
      if(this.context.state!=='running'){this.onGesture?.();return;}
      if(!this.element.paused&&(samples===null?this.room.canPlaybackAudio!==false:advancing)){
        this.onAudible?.();
        return;
      }
      this.turnSilent+=500;this.silentMs+=500;
      if(!this.retried){
        this.retried=true;
        Promise.allSettled([this.play(),this.room.startAudio()]);
      }
      if(this.turnSilent>=2000)this.fail('rtc_silent');
    }finally{
      this.checkingPlayback=false;
    }
  }
  async measure(){
    if(this.closed||!this.connectedAt)return;
    try{
      const report=await this.track?.getRTCStatsReport();
      report?.forEach(row=>{if(row.type==='inbound-rtp'&&(row.kind==='audio'||row.mediaType==='audio')){
        if(Number.isFinite(row.packetsReceived)&&row.packetsReceived!==this.lastPackets){this.lastPackets=row.packetsReceived;this.lastPacketAt=performance.now();}
        this.stats={rtcConcealedSamples:row.concealedSamples||0,rtcSilentConcealedSamples:row.silentConcealedSamples||0,
          rtcConcealmentEvents:row.concealmentEvents||0,rtcPacketsLost:Math.max(0,row.packetsLost||0),rtcJitterMs:(row.jitter||0)*1000,rtcTotalSamples:row.totalSamplesReceived||0};
      }});
    }catch{}
    // The relay publishes continuous audio, including idle silence. A frozen
    // packet counter detects a media-only black hole even with live signaling.
    const elapsed=performance.now()-this.lastPacketAt;
    if(this.lastPackets!==null&&elapsed>=4000)this.fail('rtc_media_stalled');
    else if(this.lastPackets===null&&elapsed>=8000)this.fail('rtc_no_media');
  }
  async close(){
    if(this.closed)return;this.closed=true;clearInterval(this.timer);clearInterval(this.statsTimer);clearInterval(this.playbackTimer);
    this.source?.disconnect();this.analyser?.disconnect();this.silent?.disconnect();
    this.element.pause();this.element.remove();await this.room.disconnect();
  }
}
