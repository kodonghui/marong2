"""Self-hosted receive-only WebRTC media. Signaling stays behind Access."""
import asyncio,json,time,uuid
from collections import deque
from datetime import timedelta
from pathlib import Path
from livekit import rtc,api

CONFIG=Path.home()/'.config/marong-call/livekit.json'
bridges={}

def enabled():return CONFIG.is_file()

class Bridge:
    def __init__(self,owner,client):
        self.owner=owner;self.client=client;self.name='marong-'+uuid.uuid4().hex
        self.config=json.loads(CONFIG.read_text());self.room=rtc.Room();self.source=rtc.AudioSource(24000,1,queue_size_ms=200)
        self.turns=deque();self.epoch=0;self.closed=False;self.task=None;self.session=None;self.idle_at=time.monotonic()
        self.stats={'rtcSourceUnderruns':0,'rtcSourcePlayedMs':0,'rtcSourceQueuedMs':0,'rtcSourceSilenceMs':0,'audioPath':'webrtc'}
        @self.room.on('disconnected')
        def disconnected(*_):
            if not self.closed:asyncio.create_task(self.close())

    def token(self,relay=False):
        return api.AccessToken(self.config['api_key'],self.config['api_secret']).with_identity(
            'relay' if relay else 'listener').with_ttl(timedelta(hours=24)).with_grants(api.VideoGrants(
            room_join=True,room=self.name,can_publish=relay,can_subscribe=not relay,can_publish_data=False)).to_jwt()

    async def open(self):
        await self.room.connect('ws://127.0.0.1:7880',self.token(True))
        track=rtc.LocalAudioTrack.create_audio_track('marong-voice',self.source)
        opts=rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await self.room.local_participant.publish_track(track,opts)
        self.task=asyncio.create_task(self.playout())

    def reset(self,epoch):
        self.epoch=epoch;self.turns.clear();self.source.clear_queue()

    def feed(self,pcm,epoch,turn,offset=0):
        if epoch<self.epoch:return
        if epoch>self.epoch:self.reset(epoch)
        if not self.turns or self.turns[-1]['id']!=turn:
            if self.turns:self.turns[-1]['end']=True
            self.turns.append({'id':turn,'offset':offset,'pcm':bytearray(),'end':False,'started':False,'stalled':False})
        if sum(len(t['pcm']) for t in self.turns)>24000*2*120:self.reset(epoch);return
        self.turns[-1]['pcm'].extend(pcm)

    def finish(self,epoch,turn):
        if epoch==self.epoch and self.turns and self.turns[-1]['id']==turn:self.turns[-1]['end']=True

    def queued_ms(self):
        """Audio fed to the bridge but not yet sent to the browser (24 kHz, 16-bit)."""
        return sum(len(t['pcm']) for t in self.turns)/48

    def take_pending(self):
        """Freeze the producer and hand unplayed samples to the ordered WS writer."""
        if self.task:self.task.cancel()
        if not self.closed:self.source.clear_queue()
        pending=[(self.epoch,t['id'],t['offset'],bytes(t['pcm']),t['end']) for t in self.turns]
        self.turns.clear()
        return pending

    async def playout(self):
        deadline=time.monotonic();silence=bytes(960)
        try:
            while not self.closed:
                await asyncio.sleep(max(0,deadline-time.monotonic()));deadline=max(deadline+.02,time.monotonic()-.02)
                data=silence
                while self.turns and self.turns[0]['end'] and not self.turns[0]['pcm']:self.turns.popleft()
                if self.turns:
                    t=self.turns[0];buf=t['pcm']
                    if not t['started'] and (len(buf)>=28800 or t['end']):t['started']=True;t['stalled']=False
                    if t['started']:
                        if len(buf)>=960 or t['end']:
                            count=min(960,len(buf));data=bytes(buf[:count]).ljust(960,b'\0');del buf[:count]
                            t['offset']+=count//2
                            self.stats['rtcSourcePlayedMs']+=count/48
                        else:
                            t['started']=False;t['stalled']=True;self.stats['rtcSourceUnderruns']+=1
                    if t['stalled']:self.stats['rtcSourceSilenceMs']+=20
                self.stats['rtcSourceQueuedMs']=sum(len(t['pcm']) for t in self.turns)/48
                await self.source.capture_frame(rtc.AudioFrame(data,24000,1,480))
                if self.session:self.session.d.update(self.stats)
                elif time.monotonic()-self.idle_at>90:break
        finally:
            if not self.closed:asyncio.create_task(self.close())

    async def close(self):
        if self.closed:return
        self.closed=True
        if self.session and self.session.rtc is self and not self.session.stop.is_set():
            await self.session.request_pcm('rtc_server_lost')
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        try:
            await self.room.disconnect();await self.source.aclose()
        finally:
            if bridges.get(self.client) is self:bridges.pop(self.client,None)

async def acquire(owner,client,*,capacity=2):
    old=bridges.get(client)
    if old and not old.closed:
        if old.owner!=owner:raise PermissionError()
        old.idle_at=time.monotonic();return old
    if len(bridges)>=capacity:raise ValueError('rtc_busy')
    bridge=Bridge(owner,client);bridges[client]=bridge
    try:await asyncio.wait_for(bridge.open(),12)
    except Exception:await bridge.close();raise
    return bridge
