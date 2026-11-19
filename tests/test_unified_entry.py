"""TASK-384: competing processes must not run the same periodic job."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from aiohttp import ClientSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_app
from fakes import FakeEmbeddings, ScriptedLLM, message, text
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE
from marong.config import load_settings
from marong.proactive import slot
from marong.unified_delivery import AppProactive, AppReminders, UnifiedDelivery
from marong.unified_store import UnifiedStore
from marong.work_loops import loops_home, run_locked
from pg import TestDB


class FakeLLM(ScriptedLLM):
    async def close(self):
        pass


class WorkLoopsTest(unittest.IsolatedAsyncioTestCase):
    def test_validates_loop_location(self):
        self.assertEqual(loops_home("bot"), "bot")
        self.assertEqual(loops_home("app"), "app")
        with self.assertRaises(ValueError):
            loops_home("unknown")

    async def test_only_one_session_runs_and_cancellation_hands_the_lock_over(self):
        db = TestDB()
        self.addCleanup(db.close)
        first_entered = asyncio.Event()
        second_entered = asyncio.Event()

        async def job(entered):
            entered.set()
            await asyncio.Future()

        first = asyncio.create_task(run_locked(db.app_url, "proactive", lambda: job(first_entered), retry=0.05))
        second = None
        try:
            await asyncio.wait_for(first_entered.wait(), 2)
            second = asyncio.create_task(run_locked(db.app_url, "proactive", lambda: job(second_entered), retry=0.05))
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(second_entered.wait(), 0.2)
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await asyncio.wait_for(second_entered.wait(), 2)
        finally:
            tasks = [task for task in (first, second) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def database(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        return db

    async def test_standalone_entry_runs_chat_with_no_discord_configuration(self):
        db = self.database()
        origin = "https://fixture.invalid"
        settings = replace(load_settings(), database_url=db.app_url, timezone="Asia/Seoul")
        fake = FakeLLM(lambda _: message([text("합성 대답이야.")]))
        ready = asyncio.Future()
        stop = asyncio.Event()
        listen = AppChat.serve

        async def start_http(chat):
            runner = await listen(chat)
            ready.set_result((runner.addresses[0][1], chat.sessions))
            return runner

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), (
            patch.object(run_app, "LLM", return_value=fake)
        ), patch.object(run_app, "Embeddings", return_value=FakeEmbeddings()), (
            patch.object(AppChat, "serve", new=start_http)
        ), patch.object(run_app, "run_locked", new_callable=AsyncMock) as jobs:
            runtime = asyncio.create_task(run_app.serve(settings, Path(directory),
                {"origin": origin, "port": 0, "ring": True, "fcm": None, "access": None},
                b"s" * 32, "session", "bot", stop))
            try:
                port, sessions = await asyncio.wait_for(ready, 5)
                invite, _ = await sessions.create_invite("join")
                async with ClientSession(base_url=f"http://127.0.0.1:{port}") as client:
                    async with client.post("/chat/api/join", json={"token": invite, "name": "Fixture"},
                                           headers={"Origin": origin}) as response:
                        self.assertEqual(response.status, 201)
                        cookie = {COOKIE: response.cookies[COOKIE].value}
                    async with client.post("/chat/api/messages", cookies=cookie, headers={"Origin": origin},
                                           json={"clientId": "88e8627c-c9ac-42a8-acfb-f10b8433d408",
                                                 "text": "합성 대화"}) as response:
                        self.assertEqual(response.status, 202)
                    async with asyncio.timeout(5):
                        while True:
                            async with client.get("/chat/api/messages", cookies=cookie) as feed:
                                self.assertEqual(feed.status, 200)
                                saved = (await feed.json())["messages"]
                                if any(row["from"] == "marong" and row["text"] == "합성 대답이야." for row in saved):
                                    break
                            await asyncio.sleep(.02)
                self.assertTrue(fake.bodies)
                jobs.assert_not_called()
            finally:
                stop.set()
                await asyncio.wait_for(runtime, 5)

    async def test_web_only_proactive_reminder_and_scheduled_call(self):
        db = self.database()
        store = UnifiedStore(db.app_url, call_bridge=True)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, b"t" * 32, contact_schedule=(1, 8, 22))
        invite, _ = await sessions.create_invite("join")
        user = await sessions.join(invite, "Fixture", "웹")
        friend = (await sessions.find_session(user.token))["friend_id"]
        room_key = f"app:{friend}"
        push = AppPush(store, ring_enabled=True)
        saved = []
        delivery = UnifiedDelivery(store, push, "session", lambda: saved.append(True))
        tz = ZoneInfo("Asia/Seoul")
        now = datetime.now(tz).replace(hour=21, minute=0, second=0, microsecond=0)
        settings = replace(load_settings(), database_url=db.app_url, timezone="Asia/Seoul", proactive=True)
        agent = run_app.AppAgent(settings, store, FakeEmbeddings(), FakeLLM(lambda _: message([text("합성 선톡")])))
        agent.proactive_allowed = AsyncMock(return_value=True)
        agent.proactive_message = AsyncMock(return_value=("합성 선톡", {}))
        task = AppProactive(settings, store, agent, run_app.RoomLocks(), delivery, clock=lambda: now)
        room = (await store.proactive_rooms(room_key))[0]
        begin = slot(now, (8, 22), 1)[0]
        self.assertIsNone(room["last_incoming_at"])
        self.assertTrue(await store.claim_slot(room, begin))
        self.assertFalse(await store.claim_slot(room, begin))
        self.assertTrue((await task._send(room, begin, "합성 선톡", {}))["ok"])
        self.assertEqual((await store.proactive_rooms(room_key))[0]["failures"], 0)
        db.admin("""INSERT INTO marong.schedules(friend_id,room_key,title,source,remind_at,action)
                    VALUES (%s,%s,'Fixture reminder','app',now()-interval '5 seconds','remind'),
                           (%s,%s,'Fixture call','app',now()-interval '2 seconds','call')""",
                 (friend, room_key, friend, room_key))
        reminders = AppReminders(settings, store, agent, delivery, origin="https://fixture.invalid")
        self.assertEqual(await reminders.step(), 2)
        self.assertEqual(await reminders.step(), 0)
        ring = db.admin("SELECT id,via,devices,status,answer_until-created_at FROM marong.app_rings WHERE friend_id=%s",
                        (friend,))[0]
        self.assertEqual(ring[1:4], ("app", 0, "ringing"))
        self.assertLess(abs(ring[4] - timedelta(minutes=10)), timedelta(seconds=1))
        self.assertEqual(len(saved), 3)
        items = await store.app_messages(room_key, before=None, limit=20)
        self.assertEqual(len(items), 3)
        self.assertTrue(all(row["meta"]["transport"] == "app" and row["meta"]["delivered"] for row in items))
        self.assertTrue(any(f"/?ring={ring[0]}" in row["content"] for row in items))
        push.fcm = object()
        push.notify = AsyncMock(side_effect=RuntimeError("fixture"))
        self.assertEqual(await delivery.say(friend, "합성 알림", kind="system"), "later")
        push.notify.assert_awaited_once()
        await sessions.logout(user.token)
        self.assertEqual(await delivery.say(friend, "합성 알림", kind="system"), "later")
        self.assertEqual(push.notify.await_count, 1)

        db.admin("""INSERT INTO marong.call_texts(friend_id,call_id,request_key,text,created_at)
                    VALUES (%s,'00000000-0000-0000-0000-000000000001','fresh','Fixture call text',now()),
                           (%s,'00000000-0000-0000-0000-000000000001','expired','Fixture late text',
                            now()-interval '30 seconds')""", (friend, friend))
        await delivery.send_call_texts(None)
        await delivery.send_call_texts(None)
        states = db.admin("SELECT request_key,status,via,error_code,text FROM marong.call_texts ORDER BY id")
        self.assertEqual(states, [("fresh", "sent", "app", None, None), ("expired", "failed", None, "too_late", None)])
        items = await store.app_messages(room_key, before=None, limit=20)
        sent = [m for m in items if "from_call" in m["meta"]]
        self.assertEqual([m["content"] for m in sent], ["Fixture call text"])

    async def test_proactive_and_schedule_notifications_use_the_app_device(self):
        db = self.database()
        store = UnifiedStore(db.app_url, call_bridge=True)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, b"z" * 32, contact_schedule=(1, 8, 22))
        invite, _ = await sessions.create_invite("join")
        user = await sessions.join(invite, "Fixture", "웹")
        friend = (await sessions.find_session(user.token))["friend_id"]
        room_key = f"app:{friend}"
        await store.app_device_put("256369f0-36a6-4d30-9c19-345e352a9839", friend, "fixture-fcm-id-not-real",
                                   "granted", "0.2.4", "enabled", "granted")
        fcm = AsyncMock()
        fcm.send.return_value = "ok"
        push = AppPush(store, fcm, ring_enabled=True)
        settings = replace(load_settings(), database_url=db.app_url, timezone="Asia/Seoul", proactive=True)
        agent = run_app.AppAgent(settings, store, FakeEmbeddings(), FakeLLM(lambda _: message([text("합성 선톡")])))
        delivery = UnifiedDelivery(store, push, "session", agent.on_saved)
        now = datetime.now(ZoneInfo(settings.timezone)).replace(hour=21, minute=0, second=0, microsecond=0)
        proactive = AppProactive(settings, store, agent, run_app.RoomLocks(), delivery, clock=lambda: now)
        room = (await store.proactive_rooms(room_key))[0]
        begin = slot(now, (8, 22), 1)[0]
        self.assertTrue(await store.claim_slot(room, begin))
        self.assertTrue((await proactive._send(room, begin, "합성 선톡", {}))["ok"])
        db.admin("""INSERT INTO marong.schedules(friend_id,room_key,title,source,remind_at)
                    VALUES (%s,%s,'Fixture reminder','app',now()-interval '5 seconds')""", (friend, room_key))
        reminders = AppReminders(settings, store, agent, delivery)
        self.assertEqual(await reminders.step(), 1)
        self.assertEqual(await reminders.step(), 0)
        kinds = [call.args[0]["data"]["kind"] for call in fcm.send.await_args_list]
        self.assertEqual(kinds, ["proactive", "reminder"])
        items = await store.app_messages(room_key, before=None, limit=20)
        self.assertEqual(len(items), 2)
        self.assertTrue(all(row["meta"]["transport"] == "app" and row["meta"]["delivered"] for row in items))


if __name__ == "__main__":
    unittest.main()
