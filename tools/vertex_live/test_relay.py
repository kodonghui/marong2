"""Offline HTTP/WS integration: no credentials or external messages."""
import asyncio,base64,json,tempfile,struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
import aiohttp
from aiohttp.test_utils import TestClient,TestServer
import live_session

class Upstream:
    def __init__(self):self.queue=asyncio.Queue();self.sent=[];self.closed=False;self.index=0
    async def __aenter__(self):return self
    async def __aexit__(self,*a):self.closed=True
    async def send_json(self,d):
        self.sent.append(d)
        if 'setup' in d:return
        self.index+=1
        if 'clientContent' in d:
            await self.queue.put({'serverContent':{'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(b'\x00\x01'*240).decode()}}]},'outputTranscription':{'text':'안녕'},'generationComplete':True,'turnComplete':True},'sessionResumptionUpdate':{'resumable':True,'newHandle':'test-resume','lastConsumedClientMessageIndex':self.index}})
    async def receive(self,timeout=None):return SimpleNamespace(type=aiohttp.WSMsgType.TEXT,data='{"setupComplete":{}}',extra='')
    def __aiter__(self):return self
    async def __anext__(self):return SimpleNamespace(type=aiohttp.WSMsgType.TEXT,data=json.dumps(await self.queue.get()),extra='')
class HTTP:
    def __init__(self,u):self.u=u
    async def __aenter__(self):return self
    async def __aexit__(self,*a):pass
    def ws_connect(self,url,**kw):return self.u
async def event(ws,kind):
    for _ in range(100):
        m=await ws.receive(timeout=4)
        if m.type==aiohttp.WSMsgType.TEXT:
            d=json.loads(m.data)
            if d.get('type')==kind:return d
        elif m.type in (aiohttp.WSMsgType.CLOSE,aiohttp.WSMsgType.CLOSED):raise AssertionError('unexpected close')
    raise AssertionError('missing '+kind)
async def turn(ws):
    audio=0;ended=False
    while True:
        m=await ws.receive(timeout=4)
        if m.type==aiohttp.WSMsgType.BINARY:
            magic,epoch,tid,seq,offset,count=struct.unpack('!4sIIIII',m.data[:24])
            assert magic==b'MRG2' and count==240 and len(m.data)==504 and epoch>0
            audio+=count
        else:
            d=json.loads(m.data)
            if d['type']=='audio_end':ended=True
            if d['type']=='turn':assert audio==240 and ended;return
async def main():
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(Path,'home',return_value=Path(tmp)):import server as relay
        upstreams=[]
        def factory(**kw):u=Upstream();upstreams.append(u);return HTTP(u)
        async def idle():
            for _ in range(100):
                if not relay.active:return
                await asyncio.sleep(.01)
            raise AssertionError('session cleanup')
        with patch.object(relay,'google_headers',AsyncMock(return_value={})),patch.object(live_session,'ClientSession',factory):
            async with TestClient(TestServer(relay.app)) as c:
                origin=str(c.make_url('/')).rstrip('/')
                assert (await c.get('/')).status==200
                assert (await c.get('/healthz')).status==200
                assert (await c.get('/status')).status==401
                assert (await c.post('/auth',json={'token':relay.JOIN},headers={'Origin':'https://wrong.test'})).status==403
                headers={'Origin':origin,'Cookie':'marong_live='+relay.COOKIE}
                assert (await c.get('/api/memories',headers=headers)).status==404
                assert (await c.get('/api/calls',headers=headers)).status==404
                assert (await c.get('/memories.js',headers=headers)).status==404
                assert {x['name'] for x in relay.setup(memory=True)['setup']['tools'][0]['functionDeclarations']}=={'recall','current_time'}
                assert 'memory-panel' not in await (await c.get('/')).text()
                ws=await c.ws_connect('/live?client=00000000-0000-4000-8000-000000000001',headers=headers)
                ready=await event(ws,'ready');assert not ready['memoryConnected']
                setup=upstreams[-1].sent[0]['setup']
                assert setup['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName']=='Sulafat'
                assert 'thinkingConfig' not in setup['generationConfig']
                assert not setup.get('tools')
                try:await c.ws_connect('/live?client=00000000-0000-4000-8000-000000000001',headers=headers);raise AssertionError('concurrent call')
                except aiohttp.WSServerHandshakeError as e:assert e.status==409
                for i in range(100):
                    await ws.send_json({'type':'text','id':str(i),'text':'테스트'});await turn(ws)
                async def slow_tool(*args):await asyncio.sleep(2);return {'result':'time'}
                with patch.object(live_session,'execute_tool',slow_tool):
                    await upstreams[-1].queue.put({'toolCall':{'functionCalls':[{'id':'slow-db','name':'current_time','args':{}}]}})
                    start=asyncio.get_running_loop().time()
                    await ws.send_json({'type':'text','text':'도구 처리 중에도 음성'});await turn(ws)
                    assert asyncio.get_running_loop().time()-start<.5,'tool blocked audio receive loop'
                await upstreams[-1].queue.put({'goAway':{'timeLeft':'60s'}})
                await event(ws,'reconnecting');assert (await event(ws,'ready'))['resumed']
                assert upstreams[-1].sent[0]['setup']['sessionResumption']['handle']=='test-resume'
                assert not any('clientContent' in x for x in upstreams[-1].sent)
                await ws.send_bytes(b'\0'*32002)
                await ws.send_json({'type':'text','text':'재연결 뒤 대화'});await turn(ws)
                await ws.close();await idle()
                ws=await c.ws_connect('/live?client=00000000-0000-4000-8000-000000000001',headers=headers)
                assert (await event(ws,'ready'))['resumed']
                await ws.send_json({'type':'stop'});await ws.receive();await ws.close();await idle()
                assert not relay.resume_state
                for _ in range(7):
                    ws=await c.ws_connect('/live?client=00000000-0000-4000-8000-000000000001',headers=headers);await event(ws,'ready')
                    await ws.send_json({'type':'stop'});await ws.receive();await ws.close();await idle()
                state=await (await c.get('/status',headers=headers)).json()
                assert state['durationLimit'] is None and state['callCountLimit'] is None
    print('PASS: HTTP identity boundaries, framed PCM, 100 turns, GoAway/browser resume, ACK replay, 8+ calls, explicit stop, Sulafat and no thinking configuration')
asyncio.run(main())
