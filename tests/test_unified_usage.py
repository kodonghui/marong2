"""Exercise day boundaries, paired API reads and transactional ticket redemption."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from unittest import IsolatedAsyncioTestCase, main
from unittest.mock import patch
from uuid import uuid4
import secrets

from aiohttp.test_utils import TestClient, TestServer
from call_memory import MemoryStore, Principal
from fakes import FakeEmbeddings, ScriptedLLM, message, text
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE
from marong.config import load_settings
from marong.unified_store import UnifiedStore
from marong.usage import configured_limit
from pg import TestDB
from run_app import AppAgent, RoomLocks


ORIGIN = "https://fixture.invalid"


class UsageTests(IsolatedAsyncioTestCase):
    def test_daily_default_limit_matches_admin_range(self):
        for text, expected in (("", None), ("1", 1), ("100000", 100_000)):
            with self.subTest(text=text):
                self.assertEqual(configured_limit({"MARONG_DAILY_UNITS": text}), expected)
        for text in ("0", "-1", "100001", "1.5", "１００"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "MARONG_DAILY_UNITS"):
                configured_limit({"MARONG_DAILY_UNITS": text})

    async def test_chat_and_call_meter_day_boundary_and_overflow(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        db.apply_pet_app_prerequisites()
        db.apply_pet_app()
        moment = datetime(2026, 11, 18, 18, 59, tzinfo=timezone.utc)
        store = UnifiedStore(db.app_url)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22), now=lambda: moment)
        settings = replace(load_settings(), database_url=db.app_url)
        model = ScriptedLLM(lambda _: message([text("합성 답이야.")]))
        agent = AppAgent(settings, store, FakeEmbeddings(), model)
        with patch.dict("os.environ", {"MARONG_DAILY_UNITS": ""}):
            chat = AppChat(store, agent, RoomLocks(), None, AppPush(store), origin=ORIGIN,
                           sessions=sessions, authentication="session")
            calls = MemoryStore(db.admin_url.replace("postgres:@", "marong_call@", 1))
        calls.daily_usage.clock = lambda: moment
        await calls.open()
        self.addAsyncCleanup(calls.close)
        for fixture in ("A", "B"):
            invite, _ = await sessions.create_invite("join")
            joined = await sessions.join(invite, "Fixture "+fixture, "웹")
            principal = await sessions.find_session(joined.token)
            if fixture == "A":
                ident, login = principal, {"Cookie": f"{COOKIE}={joined.token}", "Origin": ORIGIN}
            else:
                other = principal["friend_id"]
        friend = ident["friend_id"]
        voice = Principal(ident["caller_id"], friend, "Fixture A", unified=True)

        async with TestClient(TestServer(chat.web_app())) as http:
            async def read():
                return await (await http.get("/chat/api/usage", headers=login)).json()

            async def send(expected):
                response = await http.post("/chat/api/messages", headers=login, json={
                    "clientId": str(uuid4()), "text": "합성 질문"
                })
                self.assertEqual(response.status, expected)
                if expected == 202:
                    await asyncio.gather(*tuple(chat.tasks))

            await send(202)
            await send(202)
            client = str(uuid4())
            call, *_ = await calls.start_call(voice, client, "fixture", "fixture")
            segment = await calls.start_segment(voice, call, client, "fixture")
            db.admin("UPDATE call.segments SET opened_at=now()-interval '90 seconds' WHERE id=%s", (segment,))
            await calls.finish(voice, call, True, client_id=client)
            await calls.finish(voice, call, True, client_id=client)
            await chat.usage.record(friend, images=1, searches=1, shop_reads=1)
            totals = await read()
            self.assertEqual(totals, {"day": "2026-11-18", "chatTurns": 2, "callSeconds": 90, "images": 1,
                                      "units": 87, "limit": None, "tickets": 0,
                                      "callMonth": {"limited": False, "percent": None, "resetsAt": None}})
            profile = await (await http.get("/chat/api/profile", headers=login)).json()
            self.assertEqual(profile["usageToday"], totals)
            self.assertEqual(db.admin("SELECT searches,shop_reads FROM marong.usage_daily WHERE friend_id=%s",
                                      (friend,)), [(1, 1)])
            self.assertEqual((await chat.usage.get(other))["units"], 0)
            await chat.usage.record(other, chat=5000)
            self.assertFalse(await chat.usage.blocked(other))
            chat.usage.limit = 5000
            db.admin("UPDATE marong.friend_profiles SET tickets=2 WHERE friend_id=%s", (other,))
            self.assertFalse(await chat.usage.blocked(other))
            await chat.usage.record(other, chat=1)
            self.assertEqual((await chat.usage.get(other))["tickets"], 1)
            chat.usage.limit = None
            moment += timedelta(minutes=1)
            self.assertEqual((await read())["day"], "2026-11-19")
            self.assertEqual((await read())["units"], 0)
            db.admin("UPDATE marong.friend_profiles SET daily_units=1 WHERE friend_id=%s", (friend,))
            await send(202)
            await send(429)
            db.admin("UPDATE marong.friend_profiles SET tickets=2 WHERE friend_id=%s", (friend,))
            await asyncio.gather(*(chat.usage.record(friend, chat=1) for _ in range(4)))
            self.assertEqual((await read())["tickets"], 0)
            self.assertEqual((await read())["units"], 5)
            self.assertEqual(db.admin("SELECT tickets_used FROM marong.usage_daily WHERE friend_id=%s AND day='2026-11-19'",
                                      (friend,)), [(2,)])

            with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", return_value=Path(directory)):
                import server

            async def identify(_):
                return {"owner": "fixture", "principal": voice}
            with patch.object(server, "memory_store", calls), patch.object(server, "identity", identify):
                async with TestClient(TestServer(server.app)) as relay:
                    origin = str(relay.make_url("/")).rstrip("/")
                    state = await (await relay.get("/status")).json()
                    self.assertEqual(state["blockedReason"], "daily_limit")
                    ws = await relay.ws_connect("/live", headers={"Origin": origin})
                    self.assertEqual((await ws.receive_json())["type"], "daily_limit")
                    await ws.close()

            chat.usage.limit = 10
            db.admin("""UPDATE marong.friend_profiles SET usage_unlimited=true,daily_units=NULL,tickets=5
                        WHERE friend_id=%s""", (friend,))
            await chat.usage.record(friend, chat=50)
            self.assertFalse(await chat.usage.blocked(friend))
            await send(202)
            self.assertEqual((await read())["tickets"], 5)
            self.assertEqual(db.admin("SELECT tickets_used FROM marong.usage_daily WHERE friend_id=%s AND day='2026-11-19'",
                                      (friend,)), [(2,)])


if __name__ == "__main__":
    main()
