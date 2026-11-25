'use strict';
// Network and PCM transfer run independently of captions, animation and UI work.
let ws,output,microphone,ready=false,epoch=0,lastAudio=0,openTurn=false,maxGap=0;
let firstPCM=false;
const pending=[];
function media(message,transfer=[]){
  if(output){output.postMessage(message,transfer);return;}
  if(message.type==='clear')pending.length=0;
  if(pending.length<500)pending.push([message,transfer]);
}
function bind(data){
  if(data.output){
    output=data.output;
    for(const [message,transfer] of pending)output.postMessage(message,transfer);
    pending.length=0;
  }
  if(data.microphone){
    microphone=data.microphone;
    microphone.onmessage=({data:m})=>{
      if(ready&&ws?.readyState===WebSocket.OPEN&&ws.bufferedAmount<64000)ws.send(m.pcm);
    };
  }
}
self.onmessage=({data})=>{
  if(data.type==='connect'){
    bind(data);
    const notice=data.notice;
    ws=notice?new WebSocket(data.url,'marong-notified-v1'):new WebSocket(data.url);ws.binaryType='arraybuffer';
    ws.onopen=()=>{
      if(notice&&ws.protocol!=='marong-notified-v1'){ws.close();return;}
      if(notice)ws.send(JSON.stringify(notice.frame));
      self.postMessage({type:'open'});
    };
    ws.onerror=()=>self.postMessage({type:'error'});
    ws.onclose=()=>{ready=false;self.postMessage({type:'close'});self.close();};
    ws.onmessage=({data:payload})=>{
      if(payload instanceof ArrayBuffer){
        if(notice&&!ready)return;
        if(payload.byteLength<24)return;
        const h=new DataView(payload),count=h.getUint32(20),packetEpoch=h.getUint32(4);
        if(h.getUint32(0)!==0x4d524732||payload.byteLength!==24+count*2||packetEpoch<epoch)return;
        if(packetEpoch>epoch){epoch=packetEpoch;media({type:'clear',epoch});openTurn=false;}
        const now=performance.now();if(openTurn)maxGap=Math.max(maxGap,Math.round(now-lastAudio));
        lastAudio=now;openTurn=true;
        if(!firstPCM){firstPCM=true;self.postMessage({type:'first_pcm'});}
        const pcm=payload.slice(24);media({type:'pcm',pcm,turn:h.getUint32(8),epoch},[pcm]);
        return;
      }
      let msg;try{msg=JSON.parse(payload);}catch{return;}
      if(msg.type==='ready')ready=!notice||(msg.memoryConnected===true&&msg.ring===notice.ring
        &&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(msg.callId)
        &&(!notice.expected||notice.expected===msg.callId));
      else if(msg.type==='reconnecting')ready=false;
      else if(msg.type==='audio_reset'||msg.type==='interrupted'||(msg.type==='audio_transport'&&msg.switched)){
        epoch=msg.epoch;openTurn=false;media({type:'clear',epoch});
      }else if(msg.type==='audio_end'){
        openTurn=false;media({type:'turn',turn:msg.turn,epoch:msg.epoch});
      }
      self.postMessage({type:'message',data:payload});
    };
  }else if(data.type==='bind')bind(data);
  else if(data.type==='send'&&ws?.readyState===WebSocket.OPEN)ws.send(data.data);
  else if(data.type==='close'){ready=false;if(ws)ws.close();else self.close();}
};
setInterval(()=>self.postMessage({type:'transport_stats',maxArrivalGapMs:maxGap,bufferedAmount:ws?.bufferedAmount||0}),1000);
