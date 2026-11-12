"""Realtime transport; storage/tool work never blocks the provider receiver."""
from __future__ import annotations
import asyncio
import base64
import json
import struct
import time
import uuid
from collections import deque

from aiohttp import ClientSession,ClientTimeout,WSMsgType
from memory_tools import TranscriptRecorder,execute_tool

BUILD='20261112-memory6'
FRAME=struct.Struct('!4sIIIII')


class LiveSession:
    def __init__(self,ws,owner,store,principal,setup,headers,resume,diagnostics,location,model,voice,client_id):
        self.ws=ws;self.owner=owner;self.store=store;self.p=principal;self.setup=setup;self.headers=headers
        self.resume=resume;self.d=diagnostics;self.location=location;self.model=model;self.voice=voice;self.client_id=client_id
        self.call_id=str(uuid.uuid4());self.segment=None;self.logical_resumed=False
        self.stop=asyncio.Event();self.reset=asyncio.Event();self.available=asyncio.Event()
        self.controls=asyncio.Queue(maxsize=64);self.audio=deque();self.pending=deque()
        self.output=asyncio.Queue(maxsize=256);self.tasks=set();self.explicit=False
        self.handle=None;self.epoch=0;self.turn=0;self.sequence=0;self.offset=0;self.in_turn=False
        self.revision=principal.revision if principal else 0;self.recorder=None;self.ready=False;self.turn_segments={}
        self.legacy_pcm=False
        self.rtc=None

    async def save(self,key,role,content,finalized,interrupted):
        if self.store and self.p and self.segment:
            segment=self.turn_segments.setdefault(key,self.segment)
            return await self.store.save_turn(self.p,self.call_id,segment,key,role,content,finalized,interrupted)

    def caption(self,role,text,key):
        self.turn_segments.setdefault(key,self.segment)
        if not self.output.full():self.output.put_nowait(('json',{'type':'transcript','who':'user' if role=='user' else 'marong','text':text,'key':key,'replace':True}))

    async def emit(self,data):await self.output.put(('json',data))

    def background(self,coro):
        task=asyncio.create_task(coro);self.tasks.add(task)
        def done(t):
            self.tasks.discard(t)
            if not t.cancelled() and t.exception():self.d['toolTransportFailures']=self.d.get('toolTransportFailures',0)+1
        task.add_done_callback(done);return task

    async def browser_writer(self):
        try:
            while not self.stop.is_set():
                kind,data=await self.output.get();before=time.monotonic()
                try:
                    if kind=='bytes':
                        if self.rtc:
                            _,epoch,turn,_,_,_=FRAME.unpack(data[:24]);self.rtc.feed(data[24:],epoch,turn)
                        else:await asyncio.wait_for(self.ws.send_bytes(data[24:] if self.legacy_pcm else data),5)
                    else:
                        if self.rtc and data.get('type') in ('audio_reset','interrupted'):self.rtc.reset(data['epoch'])
                        elif self.rtc and data.get('type')=='audio_end':self.rtc.finish(data['epoch'],data['turn'])
                        await asyncio.wait_for(self.ws.send_json(data),5)
                finally:self.output.task_done()
                self.d['maxBrowserSendWaitMs']=max(self.d.get('maxBrowserSendWaitMs',0),round((time.monotonic()-before)*1000))
        finally:self.stop.set()

    async def browser_input(self):
        allowance=96000.;last=time.monotonic()
        try:
            async for msg in self.ws:
                if msg.type==WSMsgType.BINARY:
                    now=time.monotonic();allowance=min(96000.,allowance+(now-last)*32000);last=now
                    if len(msg.data)>32000 or len(msg.data)%2 or len(msg.data)>allowance:continue
                    allowance-=len(msg.data)
                    if not self.ready:continue
                    while self.audio and (now-self.audio[0][0]>.4 or len(self.audio)>=10):
                        self.audio.popleft();self.d['inputDroppedFrames']=self.d.get('inputDroppedFrames',0)+1
                    self.audio.append((now,msg.data));self.available.set()
                elif msg.type==WSMsgType.TEXT:
                    try:item=json.loads(msg.data)
                    except (ValueError,TypeError):continue
                    if not isinstance(item,dict):continue
                    if item.get('type')=='stop':self.explicit=True;return
                    if item.get('type')=='playback_stats':self.stats(item);continue
                    if item.get('type')=='text':
                        text=str(item.get('text',''))[:2000]
                        if not text:continue
                        key=str(item.get('id') or uuid.uuid4())[:100]
                        try:await asyncio.wait_for(self.recorder.text(text,'text:'+key),3)
                        except Exception:self.d['memoryWriteFailures']=self.d.get('memoryWriteFailures',0)+1
                        if not self.controls.full():
                            await self.controls.put({'clientContent':{'turns':[{'role':'user','parts':[{'text':text}]}],'turnComplete':True}})
                            self.available.set()
        finally:self.stop.set()

    def stats(self,item):
        mapping={'underruns':'playbackUnderruns','maxGapMs':'maxAudioGapMs','bufferMs':'bufferMs',
          'queuedMs':'queuedMs','playedMs':'playedMs','networkStarvationMs':'networkStarvationMs',
          'rebufferWaitMs':'rebufferWaitMs','insertedSilenceSamples':'insertedSilenceSamples',
          'maxArrivalGapMs':'maxArrivalGapMs','contextInterruptions':'contextInterruptions',
          'sampleRate':'sampleRate','overflows':'playbackOverflows','completedTurns':'completedTurns'}
        for src,dst in mapping.items():
            value=item.get(src)
            if isinstance(value,(int,float)) and not isinstance(value,bool) and 0<=value<=1e12:self.d[dst]=round(value)
        for key,allowed in [('contextState',{'running','suspended','interrupted','closed'}),('engine',{'audio-worklet','webrtc'})]:
            if item.get(key) in allowed:self.d[key]=item[key]
        for key in ('rtcConcealedSamples','rtcSilentConcealedSamples','rtcConcealmentEvents','rtcPacketsLost','rtcJitterMs','rtcTotalSamples'):
            value=item.get(key)
            if isinstance(value,(int,float)) and 0<=value<1e12:self.d[key]=round(value,3)
        version=item.get('clientVersion','')
        if isinstance(version,str) and len(version)<60 and all(c.isalnum() or c in '-.' for c in version):self.d['clientVersion']=version
        self.d['updatedAt']=time.time();self.d['micMode']=item.get('micMode') is True

    async def run(self):
        if self.store and self.p:
            self.call_id,self.logical_resumed=await self.store.start_call(self.p,self.client_id,self.voice,BUILD)
        elif self.resume.get('owner')==self.owner and time.time()-self.resume.get('updated',0)<600:
            self.call_id=self.resume.get('call_id',self.call_id)
        self.d.update(build=BUILD,callId=self.call_id,startedAt=time.time(),providerInterruptions=0,providerReconnects=0)
        if self.resume.get('owner')==self.owner and self.resume.get('call_id')==self.call_id and time.time()-self.resume.get('updated',0)<600 and self.resume.get('revision')==self.revision:
            self.handle=self.resume.get('handle')
        self.recorder=TranscriptRecorder(self.save,self.caption)
        running=[asyncio.create_task(self.browser_writer()),asyncio.create_task(self.browser_input()),asyncio.create_task(self.google_loop()),asyncio.create_task(self.watch_revision())]
        try:
            done,_=await asyncio.wait(running,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
        finally:
            self.stop.set()
            for task in running:task.cancel()
            for task in list(self.tasks):task.cancel()
            await asyncio.gather(*running,*list(self.tasks),return_exceptions=True)
            await self.recorder.close()
            if self.store and self.p:
                try:await asyncio.wait_for(self.store.finish(self.p,self.call_id,self.explicit),4)
                except Exception:self.d['memoryCloseFailed']=True
            if self.explicit:self.resume.clear()
            if self.rtc:
                self.rtc.session=None;self.rtc.idle_at=time.monotonic()
                if self.explicit:await self.rtc.close()
            self.d['endedAt']=time.time();self.d['memoryWriteFailures']=self.recorder.failed+self.d.get('memoryWriteFailures',0)

    async def watch_revision(self):
        while not self.stop.is_set():
            await asyncio.sleep(2)
            if not self.store or not self.p:continue
            try:
                revision=await self.store.revision(self.p)
                if revision!=self.revision:self.revision=revision;self.reset.set()
            except Exception:pass

    async def google_loop(self):
        delay=1
        while not self.stop.is_set():
            self.ready=False;self.audio.clear();self.epoch+=1;self.in_turn=False;self.offset=0;self.sequence=0
            await self.emit({'type':'audio_reset','epoch':self.epoch})
            if self.reset.is_set():
                self.handle=None;self.pending.clear();self.resume.clear();self.recorder.parts.clear();self.reset.clear()
                if self.store and self.p:self.revision=await self.store.revision(self.p)
            seed='';self.segment=None
            if self.store and self.p:
                try:
                    self.segment=await asyncio.wait_for(self.store.start_segment(self.p,self.call_id,self.client_id,self.model),3)
                    seed=await asyncio.wait_for(self.store.seed(self.p,self.call_id),1)
                    self.d['memoryConnected']=True
                except Exception:self.d['memoryConnected']=False
            try:
                url=f'wss://{self.location}-aiplatform.googleapis.com/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent'
                async with ClientSession(timeout=ClientTimeout(total=None,connect=15)) as http:
                    async with http.ws_connect(url,headers=await self.headers(),max_msg_size=2_000_000,heartbeat=20) as upstream:
                        await upstream.send_json(self.setup(self.handle,seed,bool(self.p and self.segment)))
                        first=await upstream.receive(timeout=20)
                        if first.type not in (WSMsgType.TEXT,WSMsgType.BINARY) or 'setupComplete' not in json.loads(first.data):
                            if self.handle:self.handle=None;self.pending.clear()
                            raise ConnectionError('setup_rejected')
                        self.ready=True;delay=1
                        await self.emit({'type':'ready','resumed':bool(self.handle) or self.logical_resumed,'callId':self.call_id,
                            'build':BUILD,'audioFormat':2,'epoch':self.epoch,'memoryConnected':bool(self.p and self.segment)})
                        self.logical_resumed=True
                        await self.provider(upstream)
            except asyncio.CancelledError:raise
            except Exception as error:
                print('connection_retry',type(error).__name__,flush=True)
            self.ready=False
            if self.reset.is_set():continue
            if not self.stop.is_set() and not self.ws.closed:
                self.d['providerReconnects']=self.d.get('providerReconnects',0)+1
                await self.emit({'type':'reconnecting'})
                try:await asyncio.wait_for(self.stop.wait(),delay)
                except TimeoutError:pass
                delay=min(30,delay*2)

    async def provider(self,upstream):
        sequence=0;last_audio=None;tool_tasks={};speaking=False;go_away=False;audio_finished=False
        async def send(payload,remember=True):
            nonlocal sequence
            sequence+=1
            if remember:
                self.pending.append((sequence,time.monotonic(),payload))
                while self.pending and (len(self.pending)>100 or time.monotonic()-self.pending[0][1]>1):self.pending.popleft()
            await upstream.send_json(payload)
        # Replay only very recent unacknowledged inputs, never a long microphone backlog.
        replay=[p for _,at,p in self.pending if time.monotonic()-at<.5] if self.handle else []
        self.pending.clear()
        for payload in replay:await send(payload)

        async def sender():
            while True:
                await self.available.wait();self.available.clear()
                while not self.controls.empty():await send(await self.controls.get())
                while self.audio:
                    at,pcm=self.audio.popleft()
                    if time.monotonic()-at>.4:
                        self.d['inputDroppedFrames']=self.d.get('inputDroppedFrames',0)+1;continue
                    await send({'realtimeInput':{'audio':{'mimeType':'audio/pcm;rate=16000','data':base64.b64encode(pcm).decode()}}})

        async def tool(call):
            name=call.get('name','');identifier=str(call.get('id',''))[:200]
            try:
                result=await asyncio.wait_for(execute_tool(self.store,self.p,self.call_id,self.segment,name,call.get('args',{}),self.segment+':'+identifier if self.segment else identifier,self.recorder),6)
            except asyncio.CancelledError:raise
            except Exception:result={'result':'not_saved','reason':'temporary_error'}
            await send({'toolResponse':{'functionResponses':[{'id':identifier,'name':name,'response':result}]}})

        async def receiver():
            nonlocal last_audio,speaking,go_away,audio_finished
            async for msg in upstream:
                if msg.type not in (WSMsgType.TEXT,WSMsgType.BINARY):return
                data=json.loads(msg.data)
                update=data.get('sessionResumptionUpdate',{})
                if update.get('resumable') and update.get('newHandle'):
                    self.handle=update['newHandle'];self.resume.update(handle=self.handle,owner=self.owner,call_id=self.call_id,revision=self.revision,updated=time.time())
                    ack=update.get('lastConsumedClientMessageIndex')
                    if ack is not None:
                        while self.pending and self.pending[0][0]<=int(ack):self.pending.popleft()
                content=data.get('serverContent',{})
                if content.get('speechState')=='SPEECH':self.recorder.speech_start()
                elif content.get('speechState')=='NON_SPEECH':self.recorder.boundary('user')
                if content.get('interrupted'):
                    self.d['providerInterruptions']=self.d.get('providerInterruptions',0)+1
                    self.recorder.feed('assistant',finished=True,interrupted=True)
                    self.epoch+=1;self.in_turn=False;speaking=False;audio_finished=False;last_audio=None
                    await self.emit({'type':'interrupted','epoch':self.epoch})
                for part in content.get('modelTurn',{}).get('parts',[]):
                    inline=part.get('inlineData',{})
                    if inline.get('mimeType','').startswith('audio/pcm') and inline.get('data'):
                        now=time.monotonic()
                        if audio_finished:self.in_turn=False
                        if not self.in_turn:
                            self.turn+=1;self.offset=0;self.in_turn=True;last_audio=None;audio_finished=False
                        if last_audio:self.d['maxProviderArrivalGapMs']=max(self.d.get('maxProviderArrivalGapMs',0),round((now-last_audio)*1000))
                        last_audio=now;speaking=True
                        pcm=base64.b64decode(inline['data']);count=len(pcm)//2;self.sequence+=1
                        packet=FRAME.pack(b'MRG2',self.epoch,self.turn,self.sequence,self.offset,count)+pcm
                        self.offset+=count;self.d['receivedSamples']=self.d.get('receivedSamples',0)+count
                        await self.output.put(('bytes',packet))
                for key,role in [('inputTranscription','user'),('outputTranscription','assistant')]:
                    item=content.get(key)
                    if item:self.recorder.feed(role,item.get('text',''),bool(item.get('finished')))
                if content.get('modelTurn') or data.get('toolCall') or content.get('turnComplete'):
                    self.recorder.boundary('user')
                if content.get('generationComplete') and self.in_turn and not audio_finished:
                    audio_finished=True;await self.emit({'type':'audio_end','epoch':self.epoch,'turn':self.turn})
                if content.get('turnComplete'):
                    self.recorder.feed('assistant',finished=True)
                    if self.in_turn and not audio_finished:await self.emit({'type':'audio_end','epoch':self.epoch,'turn':self.turn})
                    speaking=False;self.in_turn=False;await self.emit({'type':'turn'})
                    if go_away and self.handle:return
                for call in data.get('toolCall',{}).get('functionCalls',[]):
                    identifier=str(call.get('id',''))
                    if identifier not in tool_tasks:tool_tasks[identifier]=self.background(tool(call))
                for identifier in data.get('toolCallCancellation',{}).get('ids',[]):
                    if identifier in tool_tasks:tool_tasks[identifier].cancel()
                if data.get('goAway'):
                    go_away=True
                    if not speaking and self.handle:return
                if data.get('error'):raise ConnectionError('provider_error')
        tasks=[asyncio.create_task(sender()),asyncio.create_task(receiver()),asyncio.create_task(self.stop.wait()),asyncio.create_task(self.reset.wait())]
        try:
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
        finally:
            for task in tasks:task.cancel()
            for task in tool_tasks.values():task.cancel()
            await asyncio.gather(*tasks,*tool_tasks.values(),return_exceptions=True)
