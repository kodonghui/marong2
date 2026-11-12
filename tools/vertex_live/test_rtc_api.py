"""RTC authorization and recovery binding without a real SFU or credentials."""
import asyncio,tempfile,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from aiohttp.test_utils import TestClient,TestServer

async def main():
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(Path,'home',return_value=Path(tmp)):import server
        client=str(uuid.uuid4())
        bridge=SimpleNamespace(name='synthetic-room',token=lambda:'synthetic-token',session=None)
        async def identity(req):
            owner=req.headers.get('X-Test-Owner')
            return {'owner':owner,'email_hash':None} if owner else None
        acquire=AsyncMock(return_value=bridge)
        with patch.object(server,'identity',identity),patch.object(server.rtc_transport,'enabled',return_value=True),patch.object(server.rtc_transport,'acquire',acquire):
            async with TestClient(TestServer(server.app)) as c:
                origin=str(c.make_url('/')).rstrip('/')
                headers={'Origin':origin,'X-Test-Owner':'a'}
                assert (await c.post('/api/rtc',json={'client':client})).status==403
                assert (await c.get('/rtc')).status==401
                assert (await c.post('/api/rtc',json={'client':client},headers=headers|{'Origin':'https://outside.invalid'})).status==403
                assert (await c.get('/rtc',headers=headers|{'Upgrade':'websocket','Origin':'https://outside.invalid'})).status==403
                assert (await c.post('/api/rtc',json={'client':'bad'},headers=headers)).status==400
                response=await c.post('/api/rtc',json={'client':client},headers=headers)
                assert response.status==200 and (await response.json())['room']=='synthetic-room'
                session=SimpleNamespace(owner='a',client_id=client,rtc=None,pcm_forced=False)
                server.active=True;server.active_session=session
                assert (await c.post('/api/rtc',json={'client':client},headers=headers|{'X-Test-Owner':'b'})).status==409
                assert (await c.post('/api/rtc',json={'client':str(uuid.uuid4())},headers=headers)).status==409
                assert (await c.post('/api/rtc',json={'client':client},headers=headers)).status==200
                assert session.rtc is bridge and bridge.session is session
                session.pcm_forced=True
                assert (await c.post('/api/rtc',json={'client':client},headers=headers)).status==409
                server.active=False;server.active_session=None
    print('PASS RTC authorization, same-call binding and no RTC reattachment after PCM failover')

asyncio.run(main())
