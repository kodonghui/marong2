"""Real HTTP/WebSocket relay, fake Google: fail media while control/mic stay live."""
import asyncio,json,tempfile,uuid
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
import aiohttp
from aiohttp.test_utils import TestClient,TestServer
import live_session
from rtc_transport import Bridge
from test_relay import Upstream,HTTP,event,turn

async def main():
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(Path,'home',return_value=Path(tmp)):import server
        upstreams=[]
        def factory(**kwargs):
            u=Upstream();upstreams.append(u);return HTTP(u)
        client=str(uuid.uuid4());bridge=Bridge.__new__(Bridge)
        bridge.closed=False;bridge.owner='invite';bridge.client=client;bridge.session=None
        bridge.turns=deque();bridge.epoch=0;bridge.task=None
        bridge.source=SimpleNamespace(clear_queue=lambda:None);bridge.close=AsyncMock()
        with patch.object(server,'google_headers',AsyncMock(return_value={})),patch.object(live_session,'ClientSession',factory):
            async with TestClient(TestServer(server.app)) as c:
                headers={'Origin':str(c.make_url('/')).rstrip('/'),'Cookie':'marong_live='+server.COOKIE}
                auth=await server.identity(SimpleNamespace(headers=headers,cookies={'marong_live':server.COOKIE}))
                bridge.owner=auth['owner'];server.rtc_transport.bridges[client]=bridge
                ws=await c.ws_connect('/live?client='+client+'&rtc=1',headers=headers)
                initial=await event(ws,'ready');session=next(iter(server.active_calls.values())).session
                assert initial['audioTransport']=='webrtc'
                # A queued, partly played sentence: pending tail must be handed over.
                bridge.feed(b'\x01\x02'*9000,session.epoch,42,1200);bridge.finish(session.epoch,42)
                await ws.send_json({'type':'audio_transport','mode':'pcm','reason':'rtc_media_stalled'})
                ack=await event(ws,'audio_transport')
                assert ack['switched'] and ack['callId']==initial['callId']
                restored=b'';offset=1200
                while True:
                    msg=await ws.receive(timeout=2)
                    if msg.type==aiohttp.WSMsgType.BINARY:
                        _,epoch,tid,seq,at,count=live_session.FRAME.unpack(msg.data[:24])
                        assert epoch==session.epoch and tid==42 and at==offset
                        restored+=msg.data[24:];offset+=count
                    elif json.loads(msg.data)['type']=='audio_end':break
                assert restored==b'\x01\x02'*9000,'unplayed sentence lost or duplicated'
                assert session.rtc is None and session.pcm_forced and not session.stop.is_set()
                for _ in range(3):
                    await ws.send_json({'type':'audio_transport','mode':'pcm','reason':'rtc_disconnected'})
                    assert not (await event(ws,'audio_transport'))['switched']
                assert session.d['transportFallbacks']==1
                await ws.send_bytes(b'\0'*3200)
                await ws.send_json({'type':'text','text':'전환 뒤에도 같은 통화로 대화'});await turn(ws)
                assert len(upstreams)==1 and not session.explicit
                assert any('realtimeInput' in x for x in upstreams[0].sent),'microphone stopped at fallback'
                assert (await c.post('/api/rtc',json={'client':client},headers=headers)).status in (409,503)
                await ws.send_json({'type':'stop'});await ws.receive();await ws.close()
                server.rtc_transport.bridges.pop(client,None)
    print('PASS mid-sentence PCM handover, exact queued samples/offset/end ordering, one call/provider/socket, live mic, duplicate ACKs and no RTC reattachment')

asyncio.run(main())
