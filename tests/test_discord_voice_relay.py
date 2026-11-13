"""Isolated Postgres and Unix socket checks. No calls to Discord or Vertex."""
import asyncio
import base64
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp import web
import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools/vertex_live')]
from pg import TestDB
from test_discord_dm import DH as OWNER, HK as OTHER, prepare
from test_relay import HTTP, Upstream, event
from tools.report import build

GUILD, CHANNEL = '100000000000000021', '100000000000000022'


class AudioUpstream(Upstream):
    async def send_json(self, data):
        await super().send_json(data)
        if 'audio' not in data.get('realtimeInput', {}):
            return
        await self.queue.put({'serverContent': {
            'inputTranscription': {'text': '동희 음성 시험', 'finished': True},
            'outputTranscription': {'text': '마롱이 음성 시험', 'finished': True},
            'modelTurn': {'parts': [{'inlineData': {'mimeType': 'audio/pcm;rate=24000',
                                                    'data': base64.b64encode(b'\x00\x01' * 480).decode()}}]},
            'generationComplete': True, 'turnComplete': True,
        }})


async def check(db, temp, module):
    dsn = db.admin_url.replace('postgres:@', 'marong_call@', 1)
    store = module.DiscordMemoryStore(dsn)
    await store.open()
    app = module.create_app(store, os.getuid(), OWNER, GUILD, CHANNEL)
    runner = web.AppRunner(app)
    await runner.setup()
    socket = str(temp / 'test.sock')
    await web.UnixSite(runner, socket).start()
    upstream = AudioUpstream()
    first = str(uuid.uuid4())
    headers = {'X-Marong-Discord-User': OWNER, 'X-Marong-Discord-Guild': GUILD,
               'X-Marong-Discord-Channel': CHANNEL, 'X-Marong-Client-Id': first}
    try:
        async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=socket)) as http:
            async with http.post('http://localhost/end', headers={**headers, 'X-Marong-Discord-User': OTHER}) as r:
                assert r.status == 403
            async with http.post('http://localhost/end', headers={**headers, 'X-Marong-Client-Id': 'bad'}) as r:
                assert r.status == 400
            person = await store.discord_principal(OWNER)
            assert not await store.discord_principal(OTHER)
            seed = await store.seed(person)
            assert 'OWNER_KAKAO' in seed and 'OWNER_DISCORD' in seed
            for forbidden in ('PRIVATE_GROUP', 'OTHER_KAKAO', 'MIXED_SUMMARY', 'MIXED_NOTE'):
                assert forbidden not in seed
                assert (await store.recall(person, forbidden))['result'] == 'not_found'
            with patch.object(module, 'google_headers', AsyncMock(return_value={})), \
                 patch('live_session.ClientSession', lambda **_: HTTP(upstream)):
                async with http.ws_connect('http://localhost/live', headers=headers) as ws:
                    ready = await event(ws, 'ready')
                    assert ready['audioTransport'] == 'discord' and ready['memoryConnected']
                    call_id = ready['callId']
                    for bad, status in (({**headers, 'X-Marong-Discord-Channel': GUILD}, 403),
                                        (headers, 409)):
                        try:
                            await http.ws_connect('http://localhost/live', headers=bad)
                            raise AssertionError('unexpected websocket acceptance')
                        except aiohttp.WSServerHandshakeError as error:
                            assert error.status == status
                    await ws.send_bytes(b'\x00\x01' * 320)
                    response = await ws.receive(timeout=3)
                    assert response.type is aiohttp.WSMsgType.BINARY
                    assert response.data.startswith(b'MRG2') and len(response.data) == 984
                    await event(ws, 'turn')
                    await ws.send_json({'type': 'stop'})
                    await ws.receive(timeout=3)
                async with http.post('http://localhost/end', headers=headers) as r:
                    assert r.status == 204
            assert json.dumps(upstream.sent).count('audio/pcm;rate=16000') == 1
            settings = upstream.sent[0]['setup']
            assert settings['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'] == 'Sulafat'
            with psycopg.connect(db.app_url, row_factory=dict_row) as report:
                now = datetime.now(timezone.utc)
                tabs, _ = build(report, now - timedelta(days=1), now, timezone.utc, vectors=False)
                sessions = next(tab for tab in tabs if tab['name'] == '통화 세션')
                rows = [row for row in sessions['rows'] if row[0] == call_id]
                assert len(rows) == 1 and rows[0][3] == '종료' and rows[0][6:9] == ['Discord 음성', 'Discord 음성', 0]
                chat = next(tab for tab in tabs if tab['name'] == '대화')
                voice = [(row, color) for row, color in zip(chat['rows'], chat['colors'])
                         if row[2].startswith('Discord 통화')]
                assert {row[3]: color for row, color in voice} == {'동희': '#d9ead3', '마롱이': '#e8f0fe'}
                assert len({row[0] for row, _ in voice}) == len(voice) == 2
            print('PASS Discord identity, lease, private memory, PCM round trip, finish and report')
    finally:
        await runner.cleanup()
        await store.close()


if __name__ == '__main__':
    db = TestDB()
    try:
        prepare(db)
        for name in ('003_transport_reporting.sql', '004_transcript_reporting.sql', '005_discord_voice.sql'):
            db.admin((ROOT / 'marong/call/migrations' / name).read_text(encoding='utf-8'), None)
        db.admin("""UPDATE marong.discord_dm_links SET channel_id=%s,last_incoming_at=now() WHERE friend_id IN (1,2)""",
                 (CHANNEL,))
        db.admin("INSERT INTO call.callers(friend_id) VALUES (1)")
        db.admin("""INSERT INTO call.caller_logins(caller_id,email_sha256,email_hint)
                    SELECT id,repeat('a',64),'t***' FROM call.callers WHERE friend_id=2""")
        db.admin("""UPDATE marong.messages SET content='OWNER_KAKAO' WHERE content='DH_OWN_KAKAO'""")
        db.admin("""UPDATE marong.messages SET content='OTHER_KAKAO' WHERE content='HK_OWN_KAKAO'""")
        db.admin("""UPDATE marong.messages SET content='PRIVATE_GROUP' WHERE content='PRIVATE_GROUP_MARKER'""")
        db.admin("""INSERT INTO marong.messages(room_key,user_key,role,content)
                    SELECT room_key,user_key,'user','OWNER_DISCORD' FROM marong.discord_dm_links WHERE friend_id=1""")
        db.admin("""INSERT INTO marong.summaries(room_key,first_id,last_id,content)
                    SELECT 'k-dh',min(id),max(id),'MIXED_SUMMARY' FROM marong.messages WHERE room_key IN ('k-dh','mixed')""")
        db.admin("""INSERT INTO marong.notes(room_key,user_key,content,summary_id)
                    SELECT 'k-dh','p-dh','MIXED_NOTE',id FROM marong.summaries WHERE content='MIXED_SUMMARY'""")
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            with patch.object(Path, 'home', return_value=temp):
                import discord_relay
            asyncio.run(check(db, temp, discord_relay))
    finally:
        db.close()
