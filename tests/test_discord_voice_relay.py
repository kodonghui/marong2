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
OTHER_GUILD, OTHER_CHANNEL = '100000000000000023', '100000000000000024'


class HangupUpstream(Upstream):
    """The owner asks to end the call; Marong says goodbye and calls end_call mid-turn."""
    async def send_json(self, data):
        await super().send_json(data)
        if 'audio' in data.get('realtimeInput', {}) and not getattr(self, 'asked', False):
            self.asked = True
            goodbye = base64.b64encode(b'\x00\x01' * 480).decode()
            await self.queue.put({'serverContent': {'inputTranscription': {'text': '나 이제 끊을게', 'finished': True}}})
            await self.queue.put({'serverContent': {
                'outputTranscription': {'text': '응, 알겠어. 또 얘기하자!'},
                'modelTurn': {'parts': [{'inlineData': {'mimeType': 'audio/pcm;rate=24000', 'data': goodbye}}]}}})
            await self.queue.put({'toolCall': {'functionCalls': [{'id': 'bye', 'name': 'end_call', 'args': {}}]}})
        for response in data.get('toolResponse', {}).get('functionResponses', []):
            self.answer = response['response']
            await self.queue.put({'serverContent': {'turnComplete': True}})


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
    rooms = [(OWNER, GUILD, CHANNEL), (OTHER, OTHER_GUILD, OTHER_CHANNEL)]
    app = module.create_app(store, os.getuid(), rooms)
    runner = web.AppRunner(app)
    await runner.setup()
    socket = str(temp / 'test.sock')
    await web.UnixSite(runner, socket).start()
    upstream = AudioUpstream()
    first = str(uuid.uuid4())
    headers = {'X-Marong-Discord-User': OWNER, 'X-Marong-Discord-Guild': GUILD,
               'X-Marong-Discord-Channel': CHANNEL, 'X-Marong-Client-Id': first}
    other_headers = {'X-Marong-Discord-User': OTHER, 'X-Marong-Discord-Guild': OTHER_GUILD,
                     'X-Marong-Discord-Channel': OTHER_CHANNEL, 'X-Marong-Client-Id': str(uuid.uuid4())}
    try:
        async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=socket)) as http:
            async with http.post('http://localhost/end', headers={**headers, 'X-Marong-Discord-User': OTHER}) as r:
                assert r.status == 403
            async with http.post('http://localhost/end', headers={**headers, 'X-Marong-Client-Id': 'bad'}) as r:
                assert r.status == 400
            person = await store.discord_principal(OWNER)
            other = await store.discord_principal(OTHER)
            assert other.caller_id != person.caller_id
            seed = await store.seed(person)
            assert 'OWNER_KAKAO' in seed and 'OWNER_DISCORD' in seed
            for forbidden in ('PRIVATE_GROUP', 'OTHER_KAKAO', 'MIXED_SUMMARY', 'MIXED_NOTE'):
                assert forbidden not in seed
                assert (await store.recall(person, forbidden))['result'] == 'not_found'
            other_seed = await store.seed(other)
            assert 'OTHER_KAKAO' in other_seed and 'OWNER_KAKAO' not in other_seed and 'OWNER_DISCORD' not in other_seed
            web_person = await store.principal('a' * 64)
            assert web_person.caller_id == other.caller_id
            web_client = str(uuid.uuid4())
            web_id, _ = await store.start_call(web_person, web_client, 'Sulafat', 'web-test')
            async with http.get('http://localhost/available', headers=other_headers) as r:
                assert r.status == 409
            try:
                await http.ws_connect('http://localhost/live', headers=other_headers)
                raise AssertionError('Discord interrupted an active web call')
            except aiohttp.WSServerHandshakeError as error:
                assert error.status == 409
            assert (await store.detail(web_person, web_id))['status'] == 'live'
            await store.finish(web_person, web_id, False, entrypoint='web', client_id=web_client)
            async with http.get('http://localhost/available', headers=other_headers) as r:
                assert r.status == 204
            with patch.object(module, 'google_headers', AsyncMock(return_value={})), \
                 patch('live_session.ClientSession', lambda **_: HTTP(Upstream())):
                async with http.ws_connect('http://localhost/live', headers=other_headers) as ws:
                    ready = await event(ws, 'ready')
                    other_id = ready['callId']
                    assert other_id != web_id and not ready['resumed']
                    assert (await store.detail(web_person, web_id))['status'] == 'ended'
                    try:
                        await store.start_call(web_person, web_client, 'Sulafat', 'web-test')
                        raise AssertionError('Web interrupted an active Discord call')
                    except module.CallBusy:
                        pass
                    try:
                        await store.finish(web_person, other_id, True, entrypoint='web')
                        raise AssertionError('Web ended a Discord call')
                    except PermissionError:
                        pass
                    assert (await store.detail(other, other_id))['status'] == 'live'
                    await ws.close()
                async with http.post('http://localhost/end', headers=other_headers) as r:
                    assert r.status == 204
                assert (await store.detail(other, other_id))['status'] == 'ended'
            resumed_web_id, resumed = await store.start_call(web_person, web_client, 'Sulafat', 'web-test')
            assert resumed_web_id not in (web_id, other_id) and not resumed
            await store.finish(web_person, resumed_web_id, True, entrypoint='web', client_id=web_client)
            with patch.object(module, 'google_headers', AsyncMock(return_value={})), \
                 patch('live_session.ClientSession', lambda **_: HTTP(upstream)):
                async with http.ws_connect('http://localhost/live', headers=headers) as ws:
                    ready = await event(ws, 'ready')
                    assert ready['audioTransport'] == 'discord' and ready['memoryConnected']
                    call_id = ready['callId']
                    async with http.get('http://localhost/available', headers=other_headers) as r:
                        assert r.status == 204
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
            # The bot that can leave the room asks for the hang-up tool; the owner's request ends the call.
            assert [d['name'] for d in settings['tools'][0]['functionDeclarations']] == ['recall', 'current_time']
            hang = HangupUpstream()
            with patch.object(module, 'google_headers', AsyncMock(return_value={})), \
                 patch('live_session.ClientSession', lambda **_: HTTP(hang)):
                async with http.ws_connect('http://localhost/live', headers={**headers, 'X-Marong-Hangup': '1'}) as ws:
                    hang_id = (await event(ws, 'ready'))['callId']
                    names = [d['name'] for d in hang.sent[0]['setup']['tools'][0]['functionDeclarations']]
                    assert names == ['recall', 'current_time', 'end_call'], names
                    await ws.send_bytes(b'\x00\x01' * 320)
                    order = []
                    while 'hangup' not in order:
                        message = await ws.receive(timeout=5)
                        order.append('bytes' if message.type is aiohttp.WSMsgType.BINARY else json.loads(message.data)['type'])
                    assert hang.answer['result'] == 'ending'
                    assert order.index('bytes') < order.index('audio_end') < order.index('hangup'), order
                    await ws.send_bytes(b'\x00\x01' * 320)
                    await ws.send_json({'type': 'stop'})
                    await ws.receive(timeout=3)
            assert json.dumps(hang.sent).count('audio/pcm;rate=16000') == 1, 'microphone reached Vertex after the goodbye'
            assert (await store.detail(person, hang_id))['status'] == 'ended'
            assert db.admin('SELECT close_reason FROM call.segments WHERE call_id=%s', (hang_id,)) == [('close_requested',)]
            print('PASS two Discord identities, separate room gates and memory, web/Discord ownership, PCM round trip and report, '
                  'owner-requested hang-up (end_call only with X-Marong-Hangup, goodbye before hangup, close_requested)')
    finally:
        await runner.cleanup()
        await store.close()


if __name__ == '__main__':
    db = TestDB()
    try:
        prepare(db)
        for name in ('003_transport_reporting.sql', '004_transcript_reporting.sql', '005_discord_voice.sql',
                     '006_discord_shared_callers.sql'):
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
