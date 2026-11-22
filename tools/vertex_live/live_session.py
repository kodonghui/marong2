"""Realtime transport; storage/tool work never blocks the provider receiver."""
from __future__ import annotations
import asyncio
import base64
import json
import os
import re
import struct
import time
import uuid
from collections import deque
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone

from aiohttp import ClientSession,ClientTimeout,WSMsgType
from memory_tools import TranscriptRecorder,execute_tool
from hangup import Consent
from call_search import queries as search_queries
from call_shop import FAILED as SHOP_FAILED, LIMIT as SHOP_LIMIT, READS as SHOP_READS
from quiet_mic import QuietMic, level
from tool_trace import step as trace_step
from connect_reports import playback_report,timing_report

BUILD='20261117-hello'
FRAME=struct.Struct('!4sIIIII')
# Marong ends a call only when the friend asked (hangup.Consent). Gemini can
# send toolCall before the last goodbye audio, or say goodbye only after the
# answer, and may skip turnComplete. So the call ends once the model has been
# quiet for a while after the answer, never later than the cap. The client then
# has a while to finish playback before the server ends the call itself.
HANGUP_QUIET_S=1.2
HANGUP_REPLY_S=3
HANGUP_MAX_S=15
HANGUP_CLIENT_S=25
HANGUP_LATE_CAPTION_S=2
# Once a call's or today's searches are spent, the open Google connection still has the search tool:
# the session resumes on a new connection without it (call_search.py), only when the answer has had
# time to play out (its audio length plus this slack) and nobody has spoken since.
SEARCH_CUT_SLACK_S=2.0
OUTPUT_RATE=24000
# A call Marong placed at a time the friend set (docs/app-ring.md): the friend's answer opens it with this text,
# once, on the connection that answered the ring. It is not a turn of the friend's and is never recorded.
RING_ANSWERED_TEXT='(전화 연결됨)'
CALL_GREETING_TEXT='통화를 막 시작했어. 한국어로 짧고 편안하게 인사해 줘.'
BUDGET_GOODBYE='(이번 달 통화를 더 할 수 없어서 곧 끊어야 해. 금액은 말하지 말고, 다음에 또 얘기하자고 한 문장으로 인사해.)'
RING_CLAIM_S=1
# The picture a hello call carries (docs/04-functional-spec/call-first.md SPEC-268): served by the bot under /chat/.
TOPIC_KEY=re.compile(r'v[0-9]{1,3}/[a-z0-9-]{1,40}')


@dataclass
class Handoff:
    stack: AsyncExitStack
    upstream: object
    segment: str
    tuning: dict
    search: str | None
    lead_in: bytes
    usage_mode: str


class LiveSession:
    def __init__(self,ws,owner,store,principal,setup,headers,resume,diagnostics,location,model,voice,client_id,*,entry_transport=None,hangup=False,search=None,ring=None):
        self.ws=ws;self.owner=owner;self.store=store;self.p=principal;self.setup=setup;self.headers=headers
        self.resume=resume;self.d=diagnostics;self.location=location;self.model=model;self.voice=voice;self.client_id=client_id
        self.shop=None;self.shop_reads=int(resume.get('shop_reads',0))
        self.wait_enabled=False;self.waiting=False
        self.call_id=str(uuid.uuid4());self.segment=None;self.logical_resumed=False
        self.stop=asyncio.Event();self.reset=asyncio.Event();self.available=asyncio.Event()
        self.controls=asyncio.Queue(maxsize=64);self.audio=deque();self.pending=deque()
        self.output=asyncio.Queue(maxsize=256);self.tasks=set();self.explicit=False
        self.handle=None;self.epoch=0;self.turn=0;self.sequence=0;self.offset=0;self.in_turn=False
        self.revision=principal.revision if principal else 0;self.recorder=None;self.ready=False;self.turn_segments={}
        self.legacy_pcm=False
        self.rtc=None
        self.quiet_mic=None
        self.tuning=None
        self.prepared=None
        self.input_history=deque()
        self.input_loud_at=0.
        self.entry_transport=entry_transport
        self.pcm_forced=False;self.connection_id=str(uuid.uuid4());self.transport_log=[]
        # The client ends the call on a 'hangup' message: the web page asks with
        # ?hangup=1, the Discord bot with X-Marong-Hangup. Older clients get no tool.
        self.hangup=hangup;self.consent=Consent();self.hanging_up=None;self.hangup_answered=None
        self.goodbye_done=asyncio.Event();self.last_model_audio=0.;self.close_reason=None
        # Google Search: call_search.SearchBudget shared by this process, or None (no search, no guide).
        self.search=search;self.searches=0;self.search_live=False;self.planned_reconnect=False
        self.forget_ack = None
        self.activity_at=0.;self.turn_done_at=None;self.turn_started_at=0.;self.playback_end=0.
        # ring: the ring id the page was opened with (/?ring=), or None. ring_info: the promise this call answers.
        # ring_topic: the picture card of a hello call, sent once with the first 'ready' (SPEC-268, SPEC-269).
        self.ring_id=ring;self.ring_info=None;self.ring_greet=False;self.ring_topic=None
        self.call_safety=None
        self.safety_queue=asyncio.Queue(maxsize=32)
        self.ws_opened=time.monotonic()
        self.server_timing={'wsOpen':0}
        self.client_timing=None;self.timing_segment=None;self.playback_reports={}
        self.hold_requested=False;self.hold_greeting=False;self.ready_sent=asyncio.Event()
        self.audio_ready=asyncio.Event();self.audio_path_ready=None;self.greeting_queued=False
        self.rtc_pending=None;self.pcm_turn=None;self.pcm_drain_until=0.

    def mark(self, name):
        self.server_timing.setdefault(name,min(600000,max(0,round((time.monotonic()-self.ws_opened)*1000))))

    def offer_rtc(self, bridge):
        bridge.session=self
        if self.hold_requested:self.rtc_pending=bridge
        else:self.rtc=bridge

    def promote_rtc(self):
        bridge=self.rtc_pending
        if (not self.rtc and bridge and not bridge.closed and not self.pcm_forced
                and self.audio_path_ready=='webrtc' and self.pcm_turn is None
                and time.monotonic()>=self.pcm_drain_until):
            self.rtc=bridge;self.rtc_pending=None
            self.log_transport('webrtc','start')

    async def queue_greeting(self, control):
        if self.greeting_queued:return
        self.greeting_queued=True
        if self.hold_greeting:
            await self.ready_sent.wait()
            try:await asyncio.wait_for(self.audio_ready.wait(),3)
            except TimeoutError:pass
        if not self.stop.is_set():
            await self.controls.put(control)
            self.available.set()
            if self.entry_transport!='discord':self.mark('greetingSent')

    async def flush_connection_reports(self):
        if self.timing_segment:
            await self.store.record_connection(self.timing_segment,timing={
                'v':1,'client':self.client_timing or {},'server':self.server_timing})
        for segment,report in self.playback_reports.items():
            await self.store.record_connection(segment,playback=report)

    def log_transport(self,mode,reason):
        self.d['audioPath']=mode
        self.transport_log.append((mode,reason))

    async def flush_transport(self):
        if not self.store or not self.p:return
        while self.transport_log:
            mode,reason=self.transport_log[0]
            await self.store.record_transport(self.p,self.call_id,self.connection_id,mode,reason)
            self.transport_log.pop(0)

    async def request_pcm(self,reason):
        await self.output.put(('transport',reason))

    async def switch_pcm(self,reason):
        # This runs only in browser_writer: ACK, pending samples and new audio
        # share one ordered writer. Neither the microphone nor Google reconnects.
        self.pcm_forced=True;bridge=self.rtc;self.rtc=None
        if self.rtc_pending:
            self.rtc_pending.session=None
            self.background(self.rtc_pending.close())
            self.rtc_pending=None
        pending=[];path_epoch=bridge.epoch if bridge else self.epoch
        if bridge:
            bridge.session=None;pending=bridge.take_pending()
            self.background(bridge.close())
            self.log_transport('pcm',reason)
            self.d['transportFallbacks']=self.d.get('transportFallbacks',0)+1
            self.d['transportFallbackReason']=reason
        await self.ws.send_json({'type':'audio_transport','mode':'pcm','switched':bool(bridge),
            'epoch':path_epoch,'callId':self.call_id})
        for epoch,turn,offset,pcm,ended in pending:
            for start in range(0,len(pcm),8192):
                chunk=pcm[start:start+8192]
                packet=FRAME.pack(b'MRG2',epoch,turn,0,offset+start//2,len(chunk)//2)+chunk
                await asyncio.wait_for(self.ws.send_bytes(chunk if self.legacy_pcm else packet),5)
            if ended:await self.ws.send_json({'type':'audio_end','epoch':epoch,'turn':turn})
        self.d['audioPath']='pcm'

    async def save(self,key,role,content,finalized,interrupted):
        if self.store and self.p and self.segment:
            segment=self.turn_segments.setdefault(key,self.segment)
            result=await self.store.save_turn(self.p,self.call_id,segment,key,role,content,finalized,interrupted)
            if self.call_safety and not interrupted and finalized:
                if self.safety_queue.full():print('crisis_queue_full',flush=True)
                else:self.safety_queue.put_nowait((key,role,content,finalized))
            return result

    async def safety_loop(self):
        while True:
            item=await self.safety_queue.get()
            try:
                prompt=await asyncio.wait_for(self.call_safety.caption(*item),5)
                if prompt and not self.stop.is_set() and not self.controls.full():
                    await self.controls.put({'clientContent':{'turns':[{'role':'user','parts':[{'text':'[알림] '+prompt}]}],'turnComplete':True}})
                    self.available.set()
            except Exception as error:print('crisis_judge_error',type(error).__name__,flush=True)
            finally:self.safety_queue.task_done()

    def caption(self,role,text,key):
        self.turn_segments.setdefault(key,self.segment)
        self.consent.note(role,key,text)
        if self.entry_transport=='discord':return
        if not self.output.full():self.output.put_nowait(('json',{'type':'transcript','who':'user' if role=='user' else 'marong','text':text,'key':key,'replace':True}))

    async def emit(self,data):await self.output.put(('json',data))

    async def wait_signal(self, reason=None):
        if not self.wait_enabled:
            return
        before, self.waiting = self.waiting, bool(reason)
        if reason is not None:
            await self.emit({'type':'wait','on':True,'reason':reason})
        elif before:
            await self.emit({'type':'wait','on':False})

    async def shop_read(self, arguments):
        if self.shop is None:
            return SHOP_FAILED
        if self.shop_reads >= SHOP_READS:
            return SHOP_LIMIT
        query = arguments.get('query') if isinstance(arguments,dict) else None
        if not isinstance(query,str) or not 1 <= len(query.strip()) <= 600:
            return SHOP_FAILED
        self.shop_reads += 1
        self.resume.update(shop_reads=self.shop_reads,owner=self.owner,call_id=self.call_id,updated=time.time(),
                           revision=self.revision)
        result = await self.shop(query.strip())
        if result.get("ok") and self.p and getattr(self.p, "unified", False) and self.store:
            await self.store.daily_usage.record(self.p.friend_id, shop_reads=1)
        return result

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
                    if kind=='transport':await self.switch_pcm(data)
                    elif kind=='hangup':
                        # Sent after every queued sample. WebRTC audio may still be
                        # waiting in the bridge, so the page waits that much longer.
                        pending=round(self.rtc.queued_ms()) if self.rtc else 0
                        await asyncio.wait_for(self.ws.send_json({'type':'hangup','epoch':data,'pendingMs':pending,'callId':self.call_id}),5)
                    elif kind=='bytes':
                        if self.rtc and self.rtc.closed:await self.switch_pcm('rtc_server_lost')
                        self.promote_rtc()
                        _,epoch,turn,_,offset,count=FRAME.unpack(data[:24])
                        if self.rtc:
                            self.rtc.feed(data[24:],epoch,turn,offset)
                        else:
                            self.pcm_turn=(epoch,turn)
                            self.pcm_drain_until=max(time.monotonic(),self.pcm_drain_until)+count/OUTPUT_RATE
                            await asyncio.wait_for(self.ws.send_bytes(data[24:] if self.legacy_pcm else data),5)
                        if self.entry_transport!='discord':self.mark('firstAudioOut')
                    else:
                        if data.get('type') in ('audio_reset','interrupted'):
                            self.pcm_turn=None;self.pcm_drain_until=0.
                            if self.rtc:self.rtc.reset(data['epoch'])
                        elif data.get('type')=='audio_end':
                            self.pcm_turn=None
                            if self.rtc:self.rtc.finish(data['epoch'],data['turn'])
                        await asyncio.wait_for(self.ws.send_json(data),5)
                        if data.get('type')=='ready':self.ready_sent.set()
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
                    if self.tuning and self.tuning['text_handoff']:
                        self.input_history.append((now,msg.data))
                        while self.input_history and now-self.input_history[0][0]>1:
                            self.input_history.popleft()
                        if level(msg.data)>=float(self.tuning['quiet_rms']):self.input_loud_at=now
                    while self.audio and (now-self.audio[0][0]>.4 or len(self.audio)>=10):
                        self.audio.popleft();self.d['inputDroppedFrames']=self.d.get('inputDroppedFrames',0)+1
                    self.audio.append((now,msg.data));self.available.set()
                elif msg.type==WSMsgType.TEXT:
                    try:item=json.loads(msg.data)
                    except (ValueError,TypeError):continue
                    if not isinstance(item,dict):continue
                    if item.get('type')=='stop':self.explicit=True;return
                    if self.entry_transport=='discord':continue
                    if item.get('type')=='timing':
                        if len(msg.data.encode('utf-8'))>4096:print('timing_rejected reason=size',flush=True)
                        elif self.client_timing is None:self.client_timing=timing_report(item)
                        continue
                    if item.get('type')=='audio_ready':
                        path=item.get('path')
                        if path in ('webrtc','pcm') and not self.audio_ready.is_set():
                            self.audio_path_ready=path;self.audio_ready.set()
                        continue
                    if item.get('type')=='playback':
                        report=playback_report(item)
                        if report is not None and self.segment:
                            report['changes']=self.playback_reports.get(self.segment,{}).get('changes',0)+1
                            self.playback_reports[self.segment]=report
                        continue
                    if item.get('type')=='playback_stats':self.stats(item);continue
                    if item.get('type')=='audio_transport' and item.get('mode')=='pcm':
                        reason=item.get('reason')
                        if reason not in ('rtc_disconnected','rtc_reconnecting','rtc_media_stalled','rtc_track_lost',
                                          'rtc_no_media','control_reconnect','network_change','server_pcm','rtc_silent'):
                            reason='rtc_disconnected'
                        await self.request_pcm(reason);continue
                    if item.get('type')=='text':
                        if self.close_reason=='budget_hard_stop':continue
                        text=str(item.get('text',''))[:2000]
                        if not text:continue
                        if self.hold_greeting and text==CALL_GREETING_TEXT:
                            if not self.greeting_queued:self.background(self.queue_greeting({
                                'clientContent':{'turns':[{'role':'user','parts':[{'text':text}]}],'turnComplete':True}}))
                            continue
                        key=str(item.get('id') or uuid.uuid4())[:100]
                        self.consent.note('user','text:'+key,text);self.activity_at=time.monotonic()
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
            self.call_id,self.logical_resumed=await self.store.start_call(
                self.p,self.client_id,self.voice,BUILD,
                entrypoint='discord' if self.entry_transport=='discord' else 'web')
            self.mark('callRow')
            if getattr(self.store, "friend_marks", False):
                self.revision = await self.store.revision(self.p)
            await self.claim_ring()
            if os.getenv('MARONG_SAFETY')=='on':
                from call_safety import CallSafety
                from server import PROJECT
                self.call_safety=CallSafety(self.store,self.p,self.call_id,self.headers,PROJECT)
        elif self.resume.get('owner')==self.owner and time.time()-self.resume.get('updated',0)<600:
            self.call_id=self.resume.get('call_id',self.call_id)
        self.d.update(build=BUILD,callId=self.call_id,startedAt=time.time(),providerInterruptions=0,providerReconnects=0)
        self.log_transport(self.entry_transport or ('webrtc' if self.rtc else 'pcm'),'start')
        if self.resume.get('owner')==self.owner and self.resume.get('call_id')==self.call_id and time.time()-self.resume.get('updated',0)<600 and self.resume.get('revision')==self.revision:
            self.handle=self.resume.get('handle')
        self.hold_greeting=self.hold_requested and not self.logical_resumed and not self.handle
        self.recorder=TranscriptRecorder(self.save,self.caption)
        running=[asyncio.create_task(self.browser_writer()),asyncio.create_task(self.browser_input()),asyncio.create_task(self.google_loop()),asyncio.create_task(self.watch_revision())]
        if self.call_safety:running.append(asyncio.create_task(self.safety_loop()))
        try:
            done,_=await asyncio.wait(running,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
        finally:
            self.stop.set()
            for task in running:task.cancel()
            for task in list(self.tasks):task.cancel()
            await asyncio.gather(*running,*list(self.tasks),return_exceptions=True)
            if self.prepared:
                await self.prepared.stack.aclose()
                self.prepared=None
            await self.recorder.close()
            if self.store and self.p:
                try:await asyncio.wait_for(self.flush_transport(),4)
                except Exception:self.d['transportLogFailed']=True
                if self.timing_segment or self.playback_reports:
                    try:await asyncio.wait_for(self.flush_connection_reports(),1)
                    except Exception:print('call_connect_report_write_error',flush=True)
                try:await asyncio.wait_for(self.store.finish(self.p,self.call_id,self.explicit,client_id=self.client_id,reason=self.close_reason),4)
                except Exception:self.d['memoryCloseFailed']=True
            if self.explicit:self.resume.clear()
            if self.rtc:
                self.rtc.session=None;self.rtc.idle_at=time.monotonic()
                if self.explicit:await self.rtc.close()
            if self.rtc_pending:
                self.rtc_pending.session=None
                await self.rtc_pending.close()
            self.d['endedAt']=time.time();self.d['memoryWriteFailures']=self.recorder.failed+self.d.get('memoryWriteFailures',0)

    async def claim_ring(self):
        """Is this the call Marong placed (SPEC-136)? A slow or failing database means an ordinary call."""
        try:got=await asyncio.wait_for(self.store.claim_ring(self.p,self.call_id,self.ring_id),RING_CLAIM_S)
        except asyncio.CancelledError:raise
        except Exception as error:
            print('ring_claim_failed',type(error).__name__,flush=True);got=None
        if not got:
            if self.ring_id:self.d['ring']='none';print('ring_not_answered',flush=True)
            return
        at=got['created_at'];reason='hello' if got.get('reason')=='hello' else 'promise'
        self.ring_info={'title':got['title'],'say':got['say'],'at':at,'reason':reason}
        self.d['ring']='answered' if got['fresh'] else 'again'
        if got['fresh']:
            # A new Gemini session that carries the promise: never resume a handle left from before the ring.
            self.ring_greet=True;self.handle=None;self.pending.clear();self.resume.clear()
            topic,title=got.get('topic'),got['title']
            if reason=='hello' and 1<=len(title or '')<=20:
                if got.get('scene_picture_id'):
                    self.ring_topic={'picture':f'/chat/api/scenes/{got["scene_picture_id"]}','title':title}
                elif isinstance(topic,str) and TOPIC_KEY.fullmatch(topic):
                    self.ring_topic={'picture':f'/chat/topics/{topic}.webp','title':title}
            print('ring_answered',f"wait_s={int(got['waited'].total_seconds())}",f'reason={reason}',
                  f'topic={int(self.ring_topic is not None)}',flush=True)

    async def watch_revision(self):
        while not self.stop.is_set():
            await asyncio.sleep(2)
            if not self.store or not self.p:continue
            try:await self.flush_transport()
            except Exception:self.d['transportLogFailed']=True
            try:
                revision=await self.store.revision(self.p)
                if revision != self.revision or self.forget_ack:
                    if self.forget_ack:
                        expected, started = self.forget_ack
                        now = time.monotonic()
                        if expected == revision and now - started < 5 and (
                            self.turn_done_at is None or self.turn_done_at < started or now < self.playback_end
                        ):
                            continue
                    self.revision = revision
                    self.reset.set()
            except Exception:pass

    def search_mode(self):
        return self.search.mode(self.searches) if self.search else None

    def searched(self,count):
        self.searches+=count;self.d['webSearches']=self.searches
        if self.search:self.search.spend(count)
        print('web_search',f'n={count}',f'call={self.searches}',f'today_left={self.search.left() if self.search else "-"}',flush=True)

    def quiet_for_reconnect(self,tool_tasks):
        """Nothing would be cut by moving to a new connection: the last answer has played, nobody spoke since."""
        return bool(self.handle and self.hanging_up is None and self.turn_done_at is not None
            and self.turn_done_at>=self.activity_at and time.monotonic()>=self.playback_end
            and not self.in_turn and self.controls.empty() and not (self.rtc and self.rtc.queued_ms()>0)
            and all(task.done() for task in tool_tasks.values()))

    async def open_provider(self,stack,handle,seed,memory,tuning,mode,*,ring=None,timeout=20,handoff=False):
        url=f'wss://{self.location}-aiplatform.googleapis.com/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent'
        http=await stack.enter_async_context(ClientSession(timeout=ClientTimeout(total=None,connect=15)))
        upstream=await stack.enter_async_context(http.ws_connect(
            url,headers=await self.headers(),max_msg_size=2_000_000,heartbeat=20))
        options={'hangup':self.hangup}
        if mode:options['search']=mode
        if ring:options['ring']=ring
        if tuning:options['tuning']=tuning
        if handoff:options['handoff']=True
        if self.store and hasattr(self.store, "friend_memory_enabled"):
            options["friend_memory"] = self.store.friend_memory_enabled()
        if self.p and hasattr(self.store,'friend_instruction'):
            try:
                friend_instruction=await asyncio.wait_for(self.store.friend_instruction(self.p),.5)
                if friend_instruction:options['friend_instruction']=friend_instruction
            except Exception:
                print('card_read_error',flush=True)
        surface = 'discord_voice' if self.entry_transport == 'discord' else 'web_voice'
        with trace_step('voice_setup', surface=surface) as trace:
            await upstream.send_json(self.setup(handle,seed,memory,**options))
            first=await upstream.receive(timeout=timeout)
            if first.type not in (WSMsgType.TEXT,WSMsgType.BINARY) or 'setupComplete' not in json.loads(first.data):
                raise ConnectionError('setup_rejected')
            if trace:
                trace.record(result='ok')
        return upstream

    def configure_mic(self,tuning):
        self.tuning=tuning
        if not tuning or not tuning['text_handoff']:
            self.input_history.clear()
        if tuning and tuning['web_quiet_mic'] and self.entry_transport!='discord':
            if self.quiet_mic is None:self.quiet_mic=QuietMic(tuning['quiet_rms'])
            else:self.quiet_mic.threshold=float(tuning['quiet_rms'])
        else:self.quiet_mic=None

    async def ready_message(self):
        self.ready=True
        ready={'type':'ready','resumed':bool(self.handle) or self.logical_resumed,'callId':self.call_id,
            'build':BUILD,'audioFormat':2,'epoch':self.epoch,'audioTransport':self.entry_transport or ('webrtc' if self.rtc else 'pcm'),
            'memoryConnected':bool(self.p and self.segment),'ring':bool(self.ring_info)}
        if self.ring_greet and self.ring_topic:ready['topic']=self.ring_topic
        self.ring_topic=None
        await self.emit(ready)
        self.logical_resumed=True
        if self.ring_greet:
            self.ring_greet=False
            greeting={'clientContent':{'turns':[{'role':'user','parts':[{'text':RING_ANSWERED_TEXT}]}],'turnComplete':True}}
            if self.hold_greeting:self.background(self.queue_greeting(greeting))
            else:await self.queue_greeting(greeting)

    async def run_provider(self,upstream,ledger,usage_mode,tuning,lead_in):
        if not usage_mode or not self.segment:
            await self.provider(upstream)
            return
        entrypoint='discord' if self.entry_transport=='discord' else 'web'
        async def check_budget():
            if not self.stop.is_set() and self.hanging_up is None and self.segment==meter.segment:
                state=await self.store.monthly_cost.status(entrypoint)
                if (state=='hard_stop' and not self.stop.is_set() and self.hanging_up is None
                        and self.segment==meter.segment):
                    self.begin_budget_goodbye()
        meter=ledger.meter(self.call_id,self.segment,entrypoint,self.model,usage_mode,self.searches,
                           tuning=tuning['name'] if tuning else None,after_flush=check_budget)
        try:await self.provider(upstream,meter,lead_in=lead_in)
        finally:
            meter.close()
            if self.quiet_mic:
                try:await asyncio.wait_for(self.store.record_mic(meter.segment,*self.quiet_mic.counts()),.4)
                except Exception:self.d['micCountsFailed']=True

    async def google_loop(self):
        delay=1
        while not self.stop.is_set():
            if not self.prepared:self.ready=False
            self.epoch+=1;self.in_turn=False;self.offset=0;self.sequence=0
            await self.emit({'type':'audio_reset','epoch':self.epoch})
            if self.reset.is_set():
                if self.prepared:
                    await self.prepared.stack.aclose();self.prepared=None
                self.handle=None;self.pending.clear();self.resume.clear();self.recorder.parts.clear();self.reset.clear()
                self.forget_ack = None
                self.available.set()
                if self.store and self.p:self.revision=await self.store.revision(self.p)
            ledger=getattr(self.store,'live_usage',None)
            usage_mode=self.prepared.usage_mode if self.prepared else await ledger.mode() if ledger else None
            lead_in=b''
            try:
                async with AsyncExitStack() as stack:
                    if self.prepared:
                        warmed=self.prepared
                        self.prepared=None
                        await stack.enter_async_context(warmed.stack)
                        self.segment,tuning,mode=warmed.segment,warmed.tuning,warmed.search
                        self.handle=None;self.pending.clear();self.resume.clear()
                        self.turn_done_at=None;self.playback_end=0
                        upstream=warmed.upstream
                        lead_in=warmed.lead_in
                        usage_mode=warmed.usage_mode
                    else:
                        self.audio.clear()
                        seed='';self.segment=None;tuning=None
                        if usage_mode and self.p:
                            try:tuning=await asyncio.wait_for(self.store.tuning(),.4)
                            except Exception:print('call_tuning_fallback',flush=True)
                        if self.store and self.p:
                            try:
                                segment_options={'tuning':tuning['name']} if tuning else {}
                                if self.entry_transport!='discord':
                                    segment_options['await_provider']=True
                                memory_options={'memory_limit':tuning['seed_call_memories']} if tuning else {}
                                self.segment=await asyncio.wait_for(self.store.start_segment(
                                    self.p,self.call_id,self.client_id,self.model,**segment_options),3)
                                seed=await asyncio.wait_for(self.store.seed(self.p,self.call_id,**memory_options),1)
                                self.d['memoryConnected']=True
                            except Exception:self.d['memoryConnected']=False
                        mode=self.search_mode()
                        try:
                            upstream=await self.open_provider(stack,self.handle,seed,bool(self.p and self.segment),
                                                              tuning,mode,ring=self.ring_info)
                        except Exception as error:
                            if isinstance(error, ConnectionError) and str(error)=='setup_rejected' and self.handle:
                                self.handle=None;self.pending.clear()
                            if self.segment and self.entry_transport!='discord':
                                try:await asyncio.wait_for(self.store.segment_start_failed(self.segment), .4)
                                except Exception:print('segment_start_failed_write_error',flush=True)
                            raise
                        if self.segment and self.entry_transport!='discord':
                            self.mark('providerReady')
                            try:await asyncio.wait_for(self.store.segment_ready(self.segment), .4)
                            except Exception:print('segment_ready_write_error',flush=True)
                            self.timing_segment=self.timing_segment or self.segment
                        if self.entry_transport!='discord':self.mark('providerReady')
                    self.search_live=mode=='on'
                    self.configure_mic(tuning)
                    await self.ready_message();delay=1
                    await self.run_provider(upstream,ledger,usage_mode,tuning,lead_in)
            except asyncio.CancelledError:raise
            except Exception as error:
                print('connection_retry',type(error).__name__,flush=True)
            if not self.prepared:self.ready=False
            if self.close_reason=='budget_hard_stop':
                self.stop.set();return
            if self.reset.is_set() or self.prepared:continue
            if self.planned_reconnect:
                self.planned_reconnect=False;continue
            if not self.stop.is_set() and not self.ws.closed:
                self.d['providerReconnects']=self.d.get('providerReconnects',0)+1
                await self.emit({'type':'reconnecting'})
                try:await asyncio.wait_for(self.stop.wait(),delay)
                except TimeoutError:pass
                delay=min(30,delay*2)

    async def prepare_handoff(self,quiet,usage_mode):
        """Keep the former provider running until the new one is ready and the quiet interval still holds."""
        async with AsyncExitStack() as stack:
            tuning=await asyncio.wait_for(self.store.tuning(),.4)
            if not tuning:return False
            seed=await asyncio.wait_for(self.store.seed(self.p,self.call_id,
                memory_limit=tuning['seed_call_memories'],history_chars=tuning['handoff_chars']),1)
            mode=self.search_mode()
            if not quiet():return False
            upstream=await asyncio.wait_for(self.open_provider(stack,None,seed,True,tuning,mode,timeout=10,handoff=True),10)
            if not quiet():return False
            replacement=await asyncio.wait_for(self.store.start_segment(self.p,self.call_id,self.client_id,self.model,
                tuning=tuning['name'],handoff_from=self.segment),1)
            now=time.monotonic()
            lead=b''.join(frame for at,frame in self.input_history if now-at<=1)[-32000:]
            self.audio.clear()
            self.prepared=Handoff(stack.pop_all(),upstream,replacement,tuning,mode,lead,usage_mode)
            self.d['textHandoffs']=self.d.get('textHandoffs',0)+1
            return True

    async def end_call_requested(self):
        """Answer Gemini's end_call. Only the friend's own words in this call allow it."""
        if not self.hangup:
            return {'result':'unavailable','reason':'이 화면에서는 네가 통화를 끊을 수 없어. 친구가 직접 끊으면 된다고 짧게 말해 줘.'}
        if self.hanging_up is None:
            # Input captions arrive independently of tool calls: allow the last words to land.
            deadline=time.monotonic()+HANGUP_LATE_CAPTION_S
            while not self.consent.asked() and time.monotonic()<deadline:await asyncio.sleep(.1)
            if not self.consent.asked():
                self.d['hangupRefused']=self.d.get('hangupRefused',0)+1;print('hangup_refused',flush=True)
                return {'result':'refused','reason':"친구가 이 통화를 끊어 달라고 하지 않았어. 통화는 계속돼. 끊을지 헷갈리면 '이제 끊을까?' 하고 한 번만 묻고, 아니면 하던 얘기를 이어 가."}
            self.hanging_up=time.monotonic();self.close_reason='close_requested'
            self.d['hangup']='accepted';print('hangup_accepted',flush=True)
            self.background(self.finish_after_goodbye())
        return {'result':'ending','note':'친구 부탁대로 통화가 곧 끊겨. 작별 인사를 아직 안 했으면 한 문장으로만 하고, 이미 했으면 아무 말도 하지 마.'}

    def begin_budget_goodbye(self):
        self.hanging_up=time.monotonic()
        self.close_reason='budget_hard_stop'
        self.explicit=True
        if not self.ready:
            self.stop.set();return
        self.audio.clear();self.pending.clear()
        while not self.controls.empty():self.controls.get_nowait()
        self.goodbye_done.clear()
        self.hangup_answered=self.hanging_up
        self.controls.put_nowait({'clientContent':{'turns':[{'role':'user','parts':[{'text':BUDGET_GOODBYE}]}],'turnComplete':True}})
        self.available.set()
        self.background(self.finish_after_goodbye())

    async def finish_after_goodbye(self):
        """Send 'hangup' after the goodbye's last sample, then end the call if the client does not."""
        budget=self.close_reason=='budget_hard_stop'
        deadline=self.hanging_up+HANGUP_MAX_S
        while not self.stop.is_set():
            now=time.monotonic();answered=self.hangup_answered
            if now>=deadline-(.2 if budget else 0):break
            if answered is not None:
                spoke=self.last_model_audio>answered;quiet=now-max(answered,self.last_model_audio)
                # turnComplete after goodbye audio that followed the answer: the goodbye is out.
                if spoke and self.goodbye_done.is_set() and quiet>=.5:break
                # Otherwise wait for silence, and give a goodbye that only starts after the answer time to begin.
                if not budget and quiet>=HANGUP_QUIET_S and (spoke or now-answered>=HANGUP_REPLY_S):break
            await asyncio.sleep(.1)
        if self.stop.is_set():return
        async def finish():
            if self.in_turn:
                # A tool call can end the turn without turnComplete: close the turn for playback.
                self.in_turn=False;await self.emit({'type':'audio_end','epoch':self.epoch,'turn':self.turn})
            await self.output.put(('hangup',self.epoch))
            await self.stop.wait()
        wait=max(0.01,deadline-time.monotonic()) if budget else HANGUP_CLIENT_S
        try:await asyncio.wait_for(finish(),wait)
        except TimeoutError:
            self.d['hangupServerEnded']=True;self.explicit=True;self.stop.set()

    async def provider(self,upstream,meter=None,*,lead_in=b''):
        sequence=0;last_audio=None;tool_tasks={};speaking=False;go_away=False;audio_finished=False;turn_queries=set()
        threshold=self.tuning['handoff_tokens'] if self.tuning and self.tuning['text_handoff'] else None
        last_input=0
        surface = 'discord_voice' if self.entry_transport == 'discord' else 'web_voice'
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
        if lead_in:
            await send({'realtimeInput':{'audio':{'mimeType':'audio/pcm;rate=16000',
                                                  'data':base64.b64encode(lead_in).decode()}}})

        async def sender():
            while True:
                await self.available.wait();self.available.clear()
                if self.forget_ack:
                    self.audio.clear()
                    continue
                while not self.controls.empty():await send(await self.controls.get())
                while self.audio:
                    at,pcm=self.audio.popleft()
                    # After the friend's hang-up request the microphone no longer
                    # reaches Gemini: an overlapping '응 잘 자' must not cut the goodbye.
                    if self.hanging_up is not None:continue
                    if time.monotonic()-at>.4:
                        self.d['inputDroppedFrames']=self.d.get('inputDroppedFrames',0)+1;continue
                    blocks=self.quiet_mic.feed(pcm) if self.quiet_mic else (pcm,)
                    for block in blocks:
                        if self.hanging_up is not None:break
                        value=({'audioStreamEnd':True} if block is None else
                               {'audio':{'mimeType':'audio/pcm;rate=16000','data':base64.b64encode(block).decode()}})
                        await send({'realtimeInput':value})

        async def tool(call):
            name=call.get('name','');identifier=str(call.get('id',''))[:200]
            started = time.monotonic()
            with trace_step('voice_tool', surface=surface, tool=name) as trace:
                try:
                    with trace_step('tool_dispatch', trace) as dispatch:
                        if name == 'end_call':
                            result = await self.end_call_requested()
                        elif name == 'shop_read':
                            result = await asyncio.wait_for(self.shop_read(call.get('args')),20)
                        else:
                            result = await asyncio.wait_for(execute_tool(
                                self.store, self.p, self.call_id, self.segment, name, call.get('args', {}),
                                self.segment + ':' + identifier if self.segment else identifier, self.recorder), 6)
                        if dispatch:
                            if isinstance(result, dict):
                                outcome = result.get('result')
                                dispatch.record(result=result.get('reason', outcome) if outcome == 'not_saved' else outcome)
                            else:
                                dispatch.record(result='invalid_result')
                except Exception:
                    if name == 'end_call':
                        raise
                    result = SHOP_FAILED if name == 'shop_read' else {'result': 'not_saved', 'reason': 'temporary_error'}
                    if trace:
                        trace.record(result='temporary_error')
                if name == "memory_forget" and result.get("ok"):
                    try:
                        self.forget_ack = (await self.store.revision(self.p), time.monotonic())
                    except Exception:
                        self.reset.set()
                another_tool = any(not task.done() and task is not asyncio.current_task()
                                   for task in tool_tasks.values())
                if not another_tool and (time.monotonic() - started < 0.8 or
                                         (name == 'shop_read' and not result.get('ok'))):
                    await self.wait_signal()
                with trace_step('provider_send', trace) as delivery:
                    await send({'toolResponse':{'functionResponses':[{'id':identifier,'name':name,'response':result}]}})
                    if delivery:
                        delivery.record(results_sent=1)
                if name == 'end_call' and result['result'] == 'ending' and self.hangup_answered is None:
                    self.hangup_answered = time.monotonic()

        async def receiver():
            nonlocal last_audio,speaking,go_away,audio_finished,last_input
            async for msg in upstream:
                if msg.type not in (WSMsgType.TEXT,WSMsgType.BINARY):return
                data=json.loads(msg.data)
                usage=data.get('usageMetadata') if meter else None
                received=datetime.now(timezone.utc) if isinstance(usage,dict) else None
                update=data.get('sessionResumptionUpdate',{})
                if update.get('resumable') and update.get('newHandle'):
                    self.handle=update['newHandle'];self.resume.update(handle=self.handle,owner=self.owner,call_id=self.call_id,revision=self.revision,updated=time.time())
                    ack=update.get('lastConsumedClientMessageIndex')
                    if ack is not None:
                        while self.pending and self.pending[0][0]<=int(ack):self.pending.popleft()
                content=data.get('serverContent',{});now=time.monotonic()
                if content.get('speechState')=='SPEECH' or content.get('inputTranscription') or content.get('modelTurn') or data.get('toolCall'):
                    self.activity_at=now
                if content.get('speechState')=='SPEECH':
                    self.recorder.speech_start();await self.wait_signal()
                elif content.get('speechState')=='NON_SPEECH':
                    self.recorder.boundary('user');await self.wait_signal('think')
                if content.get('interrupted'):
                    await self.wait_signal()
                    self.d['providerInterruptions']=self.d.get('providerInterruptions',0)+1
                    self.recorder.feed('assistant',finished=True,interrupted=True)
                    self.epoch+=1;self.in_turn=False;speaking=False;audio_finished=False;last_audio=None;turn_queries.clear()
                    await self.emit({'type':'interrupted','epoch':self.epoch})
                for part in content.get('modelTurn',{}).get('parts',[]):
                    inline=part.get('inlineData',{})
                    if inline.get('mimeType','').startswith('audio/pcm') and inline.get('data'):
                        await self.wait_signal()
                        now=time.monotonic()
                        if audio_finished:self.in_turn=False
                        if not self.in_turn:
                            self.turn+=1;self.offset=0;self.in_turn=True;last_audio=None;audio_finished=False;self.turn_started_at=now
                        if last_audio:self.d['maxProviderArrivalGapMs']=max(self.d.get('maxProviderArrivalGapMs',0),round((now-last_audio)*1000))
                        last_audio=now;speaking=True;self.last_model_audio=now
                        if self.hangup_answered is not None:self.goodbye_done.clear()
                        pcm=base64.b64decode(inline['data']);count=len(pcm)//2;self.sequence+=1
                        packet=FRAME.pack(b'MRG2',self.epoch,self.turn,self.sequence,self.offset,count)+pcm
                        self.offset+=count;self.d['receivedSamples']=self.d.get('receivedSamples',0)+count
                        await self.output.put(('bytes',packet))
                for key,role in [('inputTranscription','user'),('outputTranscription','assistant')]:
                    item=content.get(key)
                    if item:self.recorder.feed(role,item.get('text',''),bool(item.get('finished')))
                if content.get('modelTurn') or data.get('toolCall') or content.get('turnComplete'):
                    self.recorder.boundary('user')
                fresh=[q for q in search_queries(content) if q not in turn_queries]
                if fresh:
                    turn_queries.update(fresh);self.searched(len(fresh))
                    if self.p and getattr(self.p, "unified", False) and self.store:
                        self.background(self.store.daily_usage.record(self.p.friend_id, searches=len(fresh)))
                    with trace_step('voice_search', surface=surface, web_searches=len(fresh)):
                        pass
                if received:
                    turn=meter.receive(usage,self.searches,received)
                    if turn and threshold:
                        last_input=sum(turn.values[:4])
                if content.get('generationComplete') and self.in_turn and not audio_finished:
                    audio_finished=True;await self.emit({'type':'audio_end','epoch':self.epoch,'turn':self.turn})
                if content.get('turnComplete'):
                    if all(task.done() for task in tool_tasks.values()):
                        await self.wait_signal()
                    self.recorder.feed('assistant',finished=True)
                    turn_queries.clear();self.turn_done_at=now
                    self.playback_end=max(now,self.turn_started_at+self.offset/OUTPUT_RATE)+SEARCH_CUT_SLACK_S
                    if self.in_turn and not audio_finished:await self.emit({'type':'audio_end','epoch':self.epoch,'turn':self.turn})
                    speaking=False;self.in_turn=False;await self.emit({'type':'turn'})
                    if self.hangup_answered is not None:self.goodbye_done.set()
                    if go_away and self.handle:return
                for call in data.get('toolCall',{}).get('functionCalls',[]):
                    identifier=str(call.get('id',''))
                    if identifier not in tool_tasks:
                        await self.wait_signal('tool')
                        tool_tasks[identifier]=self.background(tool(call))
                for identifier in data.get('toolCallCancellation',{}).get('ids',[]):
                    if identifier in tool_tasks:tool_tasks[identifier].cancel()
                if data.get('goAway'):
                    go_away=True
                    if not speaking and self.handle:return
                if data.get('error'):raise ConnectionError('provider_error')
        async def search_cut():
            # Searches spent while this connection still has the tool: resume without it once all is quiet.
            while True:
                await asyncio.sleep(.25)
                if self.search_live and self.search_mode()!='on' and self.quiet_for_reconnect(tool_tasks):
                    self.planned_reconnect=True;self.d['searchReconnects']=self.d.get('searchReconnects',0)+1
                    print('search_reconnect',flush=True);return

        async def handoff_cut():
            def quiet():
                return bool(self.hanging_up is None and not self.stop.is_set() and not self.reset.is_set()
                    and self.turn_done_at is not None and self.turn_done_at>=max(self.input_loud_at,self.activity_at)
                    and time.monotonic()>=self.playback_end and not self.in_turn and self.controls.empty()
                    and not (self.rtc and self.rtc.queued_ms()>0) and all(task.done() for task in tool_tasks.values()))
            while True:
                await asyncio.sleep(.25)
                if last_input<=threshold or not quiet():continue
                try:
                    if await self.prepare_handoff(quiet,meter.mode):return
                except Exception as error:
                    print('handoff_retry',type(error).__name__,flush=True)
                await asyncio.sleep(30)

        tasks=[asyncio.create_task(sender()),asyncio.create_task(receiver()),asyncio.create_task(self.stop.wait()),asyncio.create_task(self.reset.wait())]
        if self.search:tasks.append(asyncio.create_task(search_cut()))
        if threshold and meter:tasks.append(asyncio.create_task(handoff_cut()))
        try:
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
        finally:
            if self.forget_ack and not self.stop.is_set():
                self.reset.set()
            for task in tasks:task.cancel()
            for task in tool_tasks.values():task.cancel()
            await asyncio.gather(*tasks,*tool_tasks.values(),return_exceptions=True)
