'use strict';
class WorkerSocket {
  constructor(url,player,capture,transportUrl){
    this.readyState=WebSocket.CONNECTING;this.bufferedAmount=0;
    this.worker=new Worker(transportUrl);
    this.worker.onmessage=({data})=>{
      if(data.type==='open'){this.readyState=WebSocket.OPEN;this.onopen?.();}
      else if(data.type==='close'){this.readyState=WebSocket.CLOSED;this.onclose?.();this.worker.terminate();}
      else if(data.type==='error')this.onerror?.();
      else if(data.type==='message')this.onmessage?.({data:data.data});
      else if(data.type==='first_pcm')this.onfirstpcm?.();
      else if(data.type==='transport_stats'){this.bufferedAmount=data.bufferedAmount;this.onstats?.(data);}
    };
    this.worker.onerror=()=>{this.readyState=WebSocket.CLOSED;this.onerror?.();this.onclose?.();this.worker.terminate();};
    this.worker.postMessage({type:'connect',url});
    this.bind(player,capture);
  }
  bind(player,capture){
    if(player&&!this.playerBound){
      this.playerBound=true;
      const output=new MessageChannel();
      player.port.postMessage({type:'bind',port:output.port1},[output.port1]);
      this.worker.postMessage({type:'bind',output:output.port2},[output.port2]);
    }
    if(capture&&!this.captureBound){
      this.captureBound=true;
      const input=new MessageChannel();
      capture.port.postMessage({type:'bind',port:input.port1},[input.port1]);
      this.worker.postMessage({type:'bind',microphone:input.port2},[input.port2]);
    }
  }
  send(data){if(this.readyState===WebSocket.OPEN)this.worker.postMessage({type:'send',data});}
  close(){this.readyState=WebSocket.CLOSING;this.worker.postMessage({type:'close'});}
}
