"""TC-673/681/683/684: protocol order, shadow and fallback without a real model."""

import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import WSMsgType

import live_session
from call_tuning import parse_tuning
from marong import continuity
from test_hangup import Browser, HTTP, Store, Upstream, check_setup, until


STARTED = datetime(2026, 11, 24, 5, 5, tzinfo=timezone.utc)


class HistoryStore(Store):
    def __init__(self, resumed=False):
        super().__init__()
        self.resumed = resumed
        self.picks = []

    async def start_call(self, *args, **kwargs):
        return "call-1", self.resumed, STARTED

    async def claim_ring(self, *args):
        return None

    async def seed(self, *args, **kwargs):
        return ""

    async def previous_conversation(self, person, call_id, now, segment):
        self.picks.append((call_id, segment))
        turns = [continuity.Turn(i, "call", now - timedelta(seconds=50-i), "user", f"합성 기억 {i}")
                 for i in range(6)]
        return turns, [], continuity.record_pick(segment, turns=6, chars=42, conversations=0, ms=10, result="ok")


class Provider(Upstream):
    def __init__(self, timeline, *, reject=False, blocked=False):
        super().__init__()
        self.timeline = timeline
        self.reject = reject
        self.release = asyncio.Event()
        if not blocked:
            self.release.set()

    async def receive(self, timeout=None):
        await self.release.wait()
        if self.reject:
            return SimpleNamespace(type=WSMsgType.CLOSE, data=1007)
        return await super().receive(timeout)

    async def send_json(self, payload):
        self.timeline.append(next(iter(payload)))
        await super().send_json(payload)


class Screen(Browser):
    def __init__(self, timeline):
        super().__init__()
        self.timeline = timeline

    async def send_json(self, data):
        if data.get("type") == "ready":
            self.timeline.append("ready")
        await super().send_json(data)


class ContinuityLiveTests(unittest.IsolatedAsyncioTestCase):
    async def open(self, mode, *, resumed=False, handle=False, reject=False, early_input=False):
        server = await check_setup()
        timeline = []
        failed = Provider(timeline, reject=True) if reject else None
        provider = Provider(timeline, blocked=early_input)
        screen = Screen(timeline)
        store = HistoryStore(resumed)
        from time import time
        resume = {"owner": "fixture", "call_id": "call-1", "revision": 0, "updated": time(),
                  "handle": "fixture-handle"} if handle else {}
        diagnostics = {}
        session = live_session.LiveSession(
            screen, "fixture", store, SimpleNamespace(revision=0, name="시험친구 가"),
            server.setup, AsyncMock(return_value={}), resume, diagnostics,
            "fixture", "fixture", "fixture", "fixture-client",
        )
        sockets = iter([failed, provider] if failed else [provider])
        with patch.object(continuity, "MODE", mode), patch.object(
            live_session, "ClientSession", lambda **kwargs: HTTP(next(sockets)),
        ), redirect_stdout(StringIO()) as output:
            task = asyncio.create_task(session.run())
            try:
                if early_input:
                    await until(lambda: provider.sent)
                    screen.mic()
                    screen.say({"type": "text", "text": "합성 일찍 온 글"})
                    await until(lambda: session.controls.qsize() > 0)
                    await asyncio.sleep(.05)
                    self.assertFalse("ready" in timeline)
                    self.assertEqual([next(iter(item)) for _, item in provider.sent], ["setup"])
                    provider.release.set()
                await until(lambda: "ready" in screen.kinds())
                if not resumed and not handle:
                    screen.say({"type": "text", "text": live_session.CALL_GREETING_TEXT})
                    await until(lambda: any(live_session.CALL_GREETING_TEXT in str(item) for _, item in provider.sent))
                if early_input:
                    await until(lambda: "realtimeInput" in timeline)
            finally:
                screen.say({"type": "stop"})
                await asyncio.wait_for(task, 3)
        return provider, failed, timeline, diagnostics, store.picks, output.getvalue()

    async def test_handshake_history_precedes_ready_and_queued_inputs(self):
        provider, _, timeline, diagnostics, picks, log = await self.open("on", early_input=True)
        setup = provider.sent[0][1]["setup"]
        history = provider.sent[1][1]["clientContent"]
        self.assertTrue(setup["historyConfig"]["initialHistoryInClientContent"])
        self.assertTrue(history["turnComplete"])
        self.assertEqual(len(history["turns"]), 8)
        self.assertEqual(timeline[:2], ["setup", "clientContent"])
        self.assertLess(timeline.index("clientContent"), timeline.index("ready"))
        self.assertLess(timeline.index("clientContent"), timeline.index("realtimeInput"))
        self.assertEqual(diagnostics["continuity"]["result"], "ok")
        self.assertEqual(picks, [("call-1", "start")])
        self.assertNotIn("합성 기억", log)
        self.assertNotIn("시험친구", str(diagnostics["continuity"]))

    async def test_off_and_shadow_send_same_messages(self):
        off, _, _, off_diagnostic, off_picks, _ = await self.open("off")
        shadow, _, _, shadow_diagnostic, shadow_picks, log = await self.open("shadow")
        self.assertEqual([item for _, item in off.sent], [item for _, item in shadow.sent])
        self.assertNotIn("continuity", off_diagnostic)
        self.assertEqual(shadow_diagnostic["continuity"]["mode"], "shadow")
        self.assertEqual(off_picks, [])
        self.assertEqual(shadow_picks, [("call-1", "start")])
        self.assertEqual(log.count("continuity_pick"), 1)

    async def test_reconnect_without_handle_and_with_handle(self):
        unhandled, _, _, _, picks, _ = await self.open("on", resumed=True)
        history = unhandled.sent[1][1]["clientContent"]
        self.assertIn("인사하지 마", history["turns"][-1]["parts"][0]["text"])
        self.assertEqual(picks, [("call-1", "reconnect")])
        handled, _, _, _, picks, _ = await self.open("on", resumed=True, handle=True)
        self.assertNotIn("historyConfig", handled.sent[0][1]["setup"])
        self.assertEqual(len(handled.sent), 1)
        self.assertEqual(picks, [])

    async def test_setup_rejection_uses_one_legacy_connection(self):
        provider, failed, _, diagnostics, picks, log = await self.open("on", reject=True)
        self.assertIn("historyConfig", failed.sent[0][1]["setup"])
        self.assertEqual(len(failed.sent), 1)
        setup = provider.sent[0][1]["setup"]
        self.assertNotIn("historyConfig", setup)
        self.assertIn("previous_conversation", str(setup["systemInstruction"]))
        self.assertEqual(diagnostics["continuity"]["result"], "fallback")
        self.assertEqual(len(picks), 1)
        self.assertEqual(log.count("continuity_fallback"), 1)

    async def test_reset_reselects_history_and_preserves_same_call(self):
        server = await check_setup()
        timeline = []
        first, second = Provider(timeline), Provider(timeline)
        sockets = iter((first, second))
        screen = Screen(timeline)
        store = HistoryStore()
        current = ["합성 이전 기억"]

        async def pick(person, call_id, now, segment):
            store.picks.append((call_id, segment))
            turns = [continuity.Turn(1, "text", now - timedelta(minutes=2), "user", current[0])]
            return turns, [], continuity.record_pick(segment, turns=1, chars=len(current[0]),
                                                       conversations=0, ms=1, result="ok")

        store.previous_conversation = pick
        session = live_session.LiveSession(
            screen, "fixture", store, SimpleNamespace(revision=0, name="시험친구 가"),
            server.setup, AsyncMock(return_value={}), {}, {},
            "fixture", "fixture", "fixture", "fixture-client",
        )
        with patch.object(continuity, "MODE", "on"), patch.object(
            live_session, "ClientSession", lambda **_: HTTP(next(sockets)),
        ):
            task = asyncio.create_task(session.run())
            try:
                await until(lambda: screen.kinds().count("ready") == 1)
                self.assertTrue(any("합성 이전 기억" in str(value) for _, value in first.sent))
                session.handle = "stale-handle"
                current[0] = "합성 새 글"
                session.reset.set()
                await until(lambda: screen.kinds().count("ready") == 2)
                self.assertEqual(store.picks, [("call-1", "start"), ("call-1", "reconnect")])
                self.assertNotIn("handle", second.sent[0][1]["setup"]["sessionResumption"])
                self.assertTrue(any("합성 새 글" in str(value) for _, value in second.sent))
                self.assertFalse(any("합성 이전 기억" in str(value) for _, value in second.sent))
            finally:
                screen.say({"type": "stop"})
                await asyncio.wait_for(task, 3)

    async def test_handoff_seeds_history_before_sending_lead_in(self):
        server = await check_setup()
        timeline = []
        first, warmed = Provider(timeline), Provider(timeline)
        sockets = iter((first, warmed))
        screen = Screen(timeline)
        store = HistoryStore()
        store.tuning = AsyncMock(return_value=parse_tuning("base-20261116", ["text_handoff=on"]))
        session = live_session.LiveSession(
            screen, "fixture", store, SimpleNamespace(revision=0, name="시험친구 가"),
            server.setup, AsyncMock(return_value={}), {}, {},
            "fixture", "fixture", "fixture", "fixture-client",
        )
        with patch.object(continuity, "MODE", "on"), patch.object(
            live_session, "ClientSession", lambda **_: HTTP(next(sockets)),
        ):
            task = asyncio.create_task(session.run())
            try:
                await until(lambda: "ready" in screen.kinds())
                self.assertTrue(await session.prepare_handoff(lambda: True, "turn"))
                self.assertEqual([next(iter(value)) for _, value in warmed.sent], ["setup", "clientContent"])
                history = warmed.sent[1][1]["clientContent"]["turns"]
                self.assertIn("인사하지 마", history[-1]["parts"][0]["text"])
                self.assertEqual(store.picks[-1], ("call-1", "handoff"))
            finally:
                screen.say({"type": "stop"})
                await asyncio.wait_for(task, 3)

    async def test_timed_seed_guide_and_instruction_limit(self):
        server = await check_setup()
        seed = json.dumps({
            "as_of": "2026-11-24 화 14:05",
            "call_memories": [{"text": "가" * 1000} for _ in range(20)],
            "current_call": [{"text": "합성 현재 통화"}],
        }, ensure_ascii=False)
        with patch.object(continuity, "MODE", "on"):
            parts = server.setup(seed=seed, call_started_at=STARTED)["setup"]["systemInstruction"]["parts"]
        self.assertLessEqual(sum(len(part["text"]) for part in parts), 14000)
        self.assertTrue(any("'when'은 'as_of' 기준" in part["text"] for part in parts))
        self.assertTrue(any("합성 현재 통화" in part["text"] for part in parts))

    async def test_sensitive_topics_instruction_is_only_added_on(self):
        server = await check_setup()
        rule = "건강·마음·성·돈·연애 얘기는 친구가 이번 통화에서 먼저 꺼내기 전에는 먼저 말하지 마."
        for mode in ("off", "shadow", "on"):
            with patch.object(continuity, "MODE", mode):
                setup = server.setup(call_started_at=STARTED)["setup"]
            base = setup["systemInstruction"]["parts"][0]["text"]
            self.assertEqual(rule in base, mode == "on")
            self.assertNotIn("<!-- MARONG_CONTINUITY=on -->", base)


if __name__ == "__main__":
    unittest.main()
