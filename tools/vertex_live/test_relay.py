"""Offline integration checks; no Google calls or real credentials."""
import asyncio,base64,json,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
import aiohttp
from aiohttp.test_utils import TestClient,TestServer

class Upstream:
    def __init__(self):self.queue=asyncio.Queue();self.sent=[];self.closed=False;self.index=0
    async def __aenter__(self):return self
    async def __aexit__(self,*a):self.closed=True
    async def send_json(self,d):
        self.sent.append(d)
        if 'setup' in d:return
        self.index+=1
        if 'clientContent' in d:
            await self.queue.put({'serverContent':{'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(b'\x00\x01'*240).decode()}}]},'outputTranscription':{'text':'안녕'},'turnComplete':True},'sessionResumptionUpdate':{'resumable':True,'newHandle':'resume-test-handle','lastConsumedClientMessageIndex':self.index}})
    async def receive(self,timeout=None):return SimpleNamespace(type=aiohttp.WSMsgType.TEXT,data='{"setupComplete":{}}',extra='')
    def __aiter__(self):return self
    async def __anext__(self):return SimpleNamespace(type=aiohttp.WSMsgType.TEXT,data=json.dumps(await self.queue.get()),extra='')

class HTTP:
    def __init__(self,upstream):self.upstream=upstream
    async def __aenter__(self):return self
    async def __aexit__(self,*a):pass
    def ws_connect(self,url,**kwargs):
        assert url.startswith('wss://us-central1-aiplatform.googleapis.com/')
        assert kwargs['headers']=={'x-goog-api-key':'fake-for-test'}
        return self.upstream

async def run():
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(Path,'home',return_value=Path(tmp)):
            import server as relay
        upstreams=[]
        def factory(**kw):
            u=Upstream();upstreams.append(u);return HTTP(u)
        async def wait_idle():
            for _ in range(50):
                if not relay.active:return
                await asyncio.sleep(.01)
            raise AssertionError('Relay did not release session')
        with patch.object(relay,'google_headers',AsyncMock(return_value={'x-goog-api-key':'fake-for-test'})),patch.object(relay,'ClientSession',factory):
            async with TestClient(TestServer(relay.app)) as c:
                origin=str(c.make_url('/')).rstrip('/')
                r=await c.get('/');assert r.status==200 and 'frame-ancestors' in r.headers['Content-Security-Policy']
                image=await c.get('/face/v1/01-neutral.webp');assert image.status==200 and image.headers['Content-Type']=='image/webp',(image.status,dict(image.headers))
                assert 'immutable' in image.headers['Cache-Control']
                assert (await c.get('/face/v1/join-token')).status==404
                assert (await c.get('/status')).status==401
                assert (await c.post('/auth',json={'token':relay.JOIN},headers={'Origin':'https://wrong.example'})).status==403
                assert (await c.post('/auth',json={'token':'wrong'},headers={'Origin':origin})).status==401
                r=await c.post('/auth',json={'token':relay.JOIN},headers={'Origin':origin});assert r.status==200 and 'HttpOnly' in r.headers['Set-Cookie']
                assert 'Max-Age=2592000' in r.headers['Set-Cookie']
                headers={'Origin':origin,'Cookie':'marong_live='+relay.COOKIE}
                try:await c.ws_connect('/live',headers={'Origin':origin});raise AssertionError('Unauthenticated WS allowed')
                except aiohttp.WSServerHandshakeError as e:assert e.status==403
                ws=await c.ws_connect('/live',headers=headers)
                assert (await ws.receive_json())['type']=='ready'
                assert upstreams[0].sent[0]['setup']['contextWindowCompression']
                assert upstreams[0].sent[0]['setup']['sessionResumption']['transparent']
                try:await c.ws_connect('/live',headers=headers);raise AssertionError('Concurrent session allowed')
                except aiohttp.WSServerHandshakeError as e:assert e.status==409
                for n in range(25):
                    await ws.send_json({'type':'text','text':str(n)})
                    m=await ws.receive(timeout=2);assert m.type==aiohttp.WSMsgType.BINARY and len(m.data)==480
                    assert (await ws.receive_json())['text']=='안녕'
                    assert (await ws.receive_json())['type']=='turn'
                # Provider timeout must keep the browser call alive and resume its context.
                await upstreams[0].queue.put({'goAway':{'timeLeft':'60s'}})
                assert (await ws.receive_json(timeout=3))['type']=='reconnecting'
                ready=await ws.receive_json(timeout=3);assert ready['type']=='ready' and ready['resumed']
                assert upstreams[0].closed
                assert upstreams[1].sent[0]['setup']['sessionResumption']['handle']=='resume-test-handle'
                assert not any('clientContent' in d for d in upstreams[1].sent),'Acknowledged messages replayed'
                # Invalid audio is dropped, without hanging up a valid call.
                await ws.send_bytes(b'\0'*32002)
                await ws.send_json({'type':'text','text':'still connected'})
                assert (await ws.receive()).type==aiohttp.WSMsgType.BINARY
                await ws.receive_json();await ws.receive_json()
                await ws.close();await wait_idle()
                assert relay.resume_state['handle']=='resume-test-handle'
                for _ in range(8):
                    ws=await c.ws_connect('/live',headers=headers)
                    assert (await ws.receive_json())['type']=='ready'
                    await ws.send_json({'type':'stop'})
                    assert (await ws.receive()).type==aiohttp.WSMsgType.CLOSE
                    await ws.close();await wait_idle()
                assert relay.resume_state['handle'] is None
                state=await (await c.get('/status',headers=headers)).json()
                assert state['ready'] and state['durationLimit'] is None and state['callCountLimit'] is None
    print('PASS: authentication, origin checks, PCM/transcript relay, >20 turns, provider GoAway resume, replay acknowledgement, reconnect context, >6 calls, explicit-stop cleanup, no duration/count limits')

asyncio.run(run())
