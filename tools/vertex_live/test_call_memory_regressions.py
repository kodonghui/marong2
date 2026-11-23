"""Offline regressions for call instructions, metering, and organization."""

import asyncio
from contextlib import nullcontext
from datetime import datetime, timezone
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from test_hangup import Browser, HTTP, Upstream, check_setup, until
from test_connect_server import TestDB

import live_session
from call_memory import MemoryStore, Principal
from call_tuning import BASE
from cost_admin import cli, run as run_admin
from organizer import Organizer


class CallMemoryRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = TestDB()
        cls.addClassCleanup(cls.db.close)
        cls.db.apply_unified_prerequisites()
        cls.db.apply_unified()
        cls.db.apply_pet_app_prerequisites()

    def run_async(self, test):
        if sys.platform == "win32":
            asyncio.run(test, loop_factory=asyncio.SelectorEventLoop)
        else:
            asyncio.run(test)

    def person(self):
        [(friend,)] = self.db.admin("INSERT INTO marong.friends(name) VALUES ('시험친구 가') RETURNING id")
        [(caller,)] = self.db.admin("INSERT INTO call.callers(friend_id) VALUES (%s) RETURNING id", (friend,))
        return Principal(caller, friend, "시험친구 가")

    def store(self):
        return MemoryStore(self.db.app_url.replace("marong@", "marong_call@", 1))

    async def connect(self, store, person, client, *, hold=False):
        server = await check_setup()
        browser, upstream = Browser(), Upstream()
        session = live_session.LiveSession(browser, "fixture", store, person, server.setup,
            AsyncMock(return_value={}), {}, {}, "fixture", "fixture", "fixture", client)
        session.hold_requested = hold
        with patch.object(live_session, "ClientSession", lambda **_: HTTP(upstream)):
            task = asyncio.create_task(session.run())
            try:
                await until(lambda: "ready" in browser.kinds(), what="fake call ready")
            except Exception:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise
        return session, browser, upstream, task

    @staticmethod
    async def stop(browser, task, *, hangup=True):
        if hangup:
            browser.say({"type": "stop"})
        else:
            browser.incoming.put_nowait(None)
        await asyncio.wait_for(task, 4)

    def test_tuning_and_estimates_without_meter(self):
        self.run_async(self.check_tuning())

    async def check_tuning(self):
        person = self.person()
        store = self.store()
        await store.open()
        try:
            self.assertIsNone(await store.live_usage.mode())
            name = "fixture-independent"
            for args in (["add", name, "max_output_tokens=768"], ["use", name]):
                await run_admin(store, cli().parse_args(["call-tuning", *args]), datetime.now(timezone.utc))
            for lookup, expected, tokens in (
                (None, name, 768),
                (AsyncMock(return_value=None), BASE, 1024),
                (AsyncMock(side_effect=TimeoutError), BASE, 1024),
            ):
                with self.subTest(tuning=expected):
                    with patch.object(store, "tuning", lookup) if lookup else nullcontext():
                        session, browser, upstream, task = await self.connect(store, person, str(uuid4()))
                        await self.stop(browser, task)
                    config = upstream.sent[0][1]["setup"]
                    self.assertEqual(config["generationConfig"]["maxOutputTokens"], tokens)
                    self.assertEqual(self.db.admin("""
                        SELECT s.tuning, c.estimated, (SELECT count(*) FROM call.live_usage u WHERE u.segment_ref=s.id)
                        FROM call.segments s JOIN call.segment_costs c ON c.segment_id=s.id WHERE s.id=%s
                        """, (session.segment,)), [(expected, True, 0)])
        finally:
            await store.close()

    def test_uses_original_korean_start_time_on_a_new_socket(self):
        self.run_async(self.check_time())

    async def check_time(self):
        person = self.person()
        client = str(uuid4())
        started = datetime(2026, 11, 22, 15, 3, tzinfo=timezone.utc)
        store = self.store()
        await store.open()
        try:
            call_id, *_ = await store.start_call(person, client, "fixture", "fixture")
            self.db.admin("UPDATE call.calls SET started_at=%s WHERE id=%s", (started, call_id))
            for hangup in (False, True):
                session, browser, upstream, task = await self.connect(store, person, client)
                await self.stop(browser, task, hangup=hangup)
                self.assertEqual(session.call_id, call_id)
                parts = upstream.sent[0][1]["setup"]["systemInstruction"]["parts"]
                lines = [line for part in parts for line in part["text"].splitlines() if "통화 시작 시각" in line]
                self.assertEqual(lines, ["통화 시작 시각(한국 시각) 2026-11-23 월요일 00:03"])
        finally:
            await store.close()

    def test_greeting_is_sent_once_and_never_saved(self):
        self.run_async(self.check_greeting())

    async def check_greeting(self):
        person = self.person()
        store = self.store()
        await store.open()
        try:
            for hold in (False, True):
                with self.subTest(hold=hold):
                    session, browser, upstream, task = await self.connect(store, person, str(uuid4()), hold=hold)
                    greeting = {"type": "text", "id": "intro", "text": live_session.CALL_GREETING_TEXT}
                    user_text = "시험 통화에 남겨야 하는 친구의 글입니다."
                    try:
                        browser.say(greeting)
                        browser.say(greeting)
                        browser.say({"type": "audio_ready", "path": "pcm"})
                        browser.say({"type": "text", "id": "turn", "text": user_text})
                        await until(lambda: any(
                            "clientContent" in packet and packet["clientContent"]["turns"][0]["parts"][0]["text"] == user_text
                            for _, packet in upstream.sent), what="user text forwarded")
                        await until(lambda: any(
                            "clientContent" in packet and packet["clientContent"]["turns"][0]["parts"][0]["text"] == greeting["text"]
                            for _, packet in upstream.sent), what="greeting forwarded")
                    finally:
                        await self.stop(browser, task)
                    self.assertEqual(self.db.admin("SELECT content FROM call.turns WHERE call_id=%s AND role='user'",
                                                  (session.call_id,)), [(user_text,)])
                    messages = [packet["clientContent"]["turns"][0]["parts"][0]["text"]
                                for _, packet in upstream.sent if "clientContent" in packet]
                    self.assertCountEqual(messages, [greeting["text"], user_text])
        finally:
            await store.close()

    def test_short_call_threshold_excludes_legacy_greeting(self):
        self.run_async(self.check_organization())

    async def check_organization(self):
        person = self.person()
        store = self.store()
        await store.open()
        try:
            with patch.dict(os.environ, {"MARONG_FRIEND_MEMORY": "off"}):
                extractor = AsyncMock(return_value=({"memories": []}, {}))
                worker = Organizer(store, extractor)
            for number, greeting in ((0, False), (0, True), (19, True), (20, True)):
                with self.subTest(user_chars=number, legacy_greeting=greeting):
                    extractor.reset_mock()
                    client = str(uuid4())
                    call, *_ = await store.start_call(person, client, "fixture", "fixture")
                    segment = await store.start_segment(person, call, client, "fixture")
                    if greeting:
                        await store.save_turn(person, call, segment, "text:intro", "user", live_session.CALL_GREETING_TEXT)
                    for idx, size in enumerate((min(10, number), max(0, number-10))):
                        if size:
                            await store.save_turn(person, call, segment, f"spoken:{idx}", "user", "가"*size)
                    await store.save_turn(person, call, segment, "reply", "assistant", "나"*50)
                    await store.finish(person, call, explicit=True, client_id=client)
                    state = {"call_id": call, "caller_id": person.caller_id, "revision": 0, "saved": 0}
                    await worker.graph().ainvoke(state)
                    organized = number >= 20
                    self.assertEqual(extractor.await_count, int(organized))
                    if organized:
                        self.assertNotIn(live_session.CALL_GREETING_TEXT,
                                         [turn["content"] for turn in extractor.await_args.args[0]])
                    self.assertEqual(self.db.admin("""
                        SELECT organize_status, (SELECT count(*) FROM call.cards WHERE call_id=c.id),
                        (SELECT count(*) FROM call.ai_runs WHERE call_id=c.id AND kind='organize')
                        FROM call.calls c WHERE id=%s
                        """, (call,)), [("done", 1, 1) if organized else ("skipped", 0, 0)])
        finally:
            await store.close()


if __name__ == "__main__":
    unittest.main()
