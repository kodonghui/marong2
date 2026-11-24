"""Offline timing and asset delivery checks for SPEC-400 and SPEC-401."""

import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, main
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer
from aiohttp import WSMsgType

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from pg import TestDB

from call_memory import MemoryStore, Principal
from live_session import FRAME, LiveSession
import server


class ConnectServerTests(IsolatedAsyncioTestCase):
    def session(self, ws=None):
        return LiveSession(ws, "fixture", None, None, None, None, {}, {}, "local", "fixture", "fixture", str(uuid4()))

    async def test_hold_releases_once_at_readiness_or_timeout(self):
        early = self.session()
        early.hold_greeting = True
        control = {"fixture": "greeting"}
        queued = asyncio.create_task(early.queue_greeting(control))
        await asyncio.sleep(0)
        self.assertTrue(early.controls.empty())
        early.ready_sent.set()
        early.audio_ready.set()
        await queued
        await early.queue_greeting(control)
        self.assertEqual(early.controls.qsize(), 1)
        self.assertIn("greetingSent", early.server_timing)

        late = self.session()
        late.hold_greeting = True
        late.ready_sent.set()
        start = asyncio.get_running_loop().time()
        await late.queue_greeting(control)
        self.assertGreaterEqual(asyncio.get_running_loop().time() - start, 3)
        late.audio_ready.set()
        await late.queue_greeting(control)
        self.assertEqual(late.controls.qsize(), 1)

    async def test_browser_reports_discard_extra_fields_and_keep_first_timing(self):
        async def messages():
            for payload in [
                {"type": "timing", "v": 1, "client": {"over": "x" * 4100}},
                {"type": "timing", "v": 1, "client": {"base": "button", "ready": 170, "micReady": True,
                                                     "appStart": -1, "liveOpen": 600001, "text": "omit"}},
                {"type": "timing", "v": 1, "client": {"base": "answer"}},
                {"type": "playback", "v": 1, "path": "pcm"},
                {"type": "playback", "v": 1, "path": "webrtc", "device": "speaker", "changes": 10,
                 "volume": 7, "voiceVolume": 7, "ringer": ["ignore"], "private": "omit"},
                {"type": "audio_ready", "path": "webrtc"},
                {"type": "audio_ready", "path": "pcm"},
            ]:
                yield SimpleNamespace(type=WSMsgType.TEXT, data=json.dumps(payload))

        call = self.session(messages())
        call.segment = "fixture"
        await call.browser_input()
        self.assertEqual(call.client_timing, {"base": "button", "ready": 170})
        self.assertEqual(call.playback_reports["fixture"],
                         {"path": "webrtc", "device": "speaker", "voiceVolume": 7, "changes": 2})
        self.assertEqual(call.audio_path_ready, "webrtc")

    async def test_late_rtc_keeps_one_transport_for_the_whole_turn(self):
        pcm, rtc = [], []

        async def send_bytes(frame):
            pcm.append(FRAME.unpack_from(frame)[2])

        async def send_json(_):
            pass

        call = self.session(SimpleNamespace(send_bytes=send_bytes, send_json=send_json))
        call.hold_requested = True
        writer = asyncio.create_task(call.browser_writer())
        self.addCleanup(writer.cancel)

        def packet(turn):
            return FRAME.pack(b'MRG2', 1, turn, 0, 0, 1) + b'\0\0'

        await call.output.put(("bytes", packet(1)))
        await call.output.join()
        call.offer_rtc(SimpleNamespace(session=None, closed=False, feed=lambda _, _epoch, turn, _offset: rtc.append(turn),
                                       finish=lambda *args: None))
        call.audio_path_ready = "webrtc"
        await call.output.put(("bytes", packet(1)))
        await call.emit({"type": "audio_end", "epoch": 1, "turn": 1})
        await call.output.join()
        await asyncio.sleep(.01)
        await call.output.put(("bytes", packet(2)))
        await call.output.join()
        self.assertEqual(pcm, [1, 1])
        self.assertEqual(rtc, [2])
        writer.cancel()
        await asyncio.gather(writer, return_exceptions=True)

    async def test_segments_move_from_opening_to_setup_complete(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        db.apply_sql(ROOT / "marong/migrations/021_usage_limit.sql",
                     ROOT / "marong/call/migrations/009_usage_limit.sql",
                     ROOT / "marong/call/migrations/010_call_connect.sql")
        friend, = db.admin("INSERT INTO marong.friends(name) VALUES ('Fixture') RETURNING id")[0]
        caller, = db.admin("INSERT INTO call.callers(friend_id) VALUES (%s) RETURNING id", (friend,))[0]
        person = Principal(caller, friend, "Fixture")
        store = MemoryStore(db.app_url.replace("marong@", "marong_call@", 1))
        await store.open()
        self.addAsyncCleanup(store.close)
        browser = str(uuid4())
        call, *_ = await store.start_call(person, browser, "fixture", "fixture")

        async def start():
            return await store.start_segment(person, call, browser, "fixture", await_provider=True)

        def status(segment):
            return db.admin("""
                SELECT mode,state,extract(epoch FROM provider_ready_at-opened_at),close_reason
                FROM call.segments WHERE id=%s
            """, (segment,))[0]

        start_id = await start()
        self.assertEqual(status(start_id), ("start", "opening", None, None))
        await asyncio.sleep(1.5)
        await store.segment_ready(start_id)
        mode, state, delay, reason = status(start_id)
        self.assertEqual((mode, state, reason), ("start", "open", None))
        self.assertGreaterEqual(delay, 1.5)
        await store.record_connection(start_id, timing={"v": 1})
        await store.record_connection(start_id, playback={"path": "pcm", "changes": 1})
        self.assertEqual(db.admin("SELECT connect_timing,playback FROM call.segments WHERE id=%s", (start_id,)),
                         [({"v": 1}, {"path": "pcm", "changes": 1})])
        reconnect = await start()
        self.assertEqual(status(reconnect), ("reconnect", "opening", None, None))
        await store.segment_start_failed(reconnect)
        await store.segment_ready(reconnect)
        self.assertEqual(status(reconnect), ("reconnect", "closed", None, "start_failed"))
        reconnect = await start()
        await store.segment_ready(reconnect)
        handoff = await store.start_segment(person, call, browser, "fixture", handoff_from=reconnect)
        self.assertEqual(status(handoff)[:2], ("handoff", "open"))
        await store.record_transport(person, call, str(uuid4()), "pcm", "rtc_silent")

    async def test_static_asset_versions_cache_headers_and_script_order(self):
        async with TestClient(TestServer(server.app)) as client:
            response = await client.get("/")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            html = await response.text()
            versions = json.loads(re.search(r"data-assets='([^']+)'", html)[1])
            self.assertEqual(set(versions), set(server.ASSET_NAMES))
            for name, version in versions.items():
                with self.subTest(asset=name):
                    asset = await client.get(f"/{name}?v={version}")
                    self.assertEqual(asset.status, 200)
                    self.assertEqual(hashlib.sha256(await asset.read()).hexdigest()[:12], version)
                    self.assertEqual(asset.headers["Cache-Control"], "private, max-age=31536000, immutable")
                    self.assertEqual(asset.headers["Content-Security-Policy"], response.headers["Content-Security-Policy"])
                    for suffix in ("", "?v=bad", f"?v={version}&v=bad"):
                        stale = await client.get(f"/{name}{suffix}")
                        self.assertEqual(stale.headers["Cache-Control"], "no-store")
                        await stale.read()
            self.assertIn(f'/livekit-client.js?v={versions["livekit-client.js"]}" async', html)
            self.assertIn(f'/style.css?v={versions["style.css"]}"', html)
            scripts = re.findall(r'<script src="/([^?]+)\?[^"]+" defer', html)
            self.assertEqual(scripts, ["worker-socket.js", "rtc-client.js", "app.js"])
            face = await client.get("/face/v1/01-neutral.webp")
            self.assertEqual(face.headers["Cache-Control"], "public, max-age=31536000, immutable")
            invalid = await client.get("/missing.js?v=a")
            self.assertEqual(invalid.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    main()
