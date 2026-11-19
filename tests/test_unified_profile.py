"""TC-450 and the profile side of TC-447, TC-452, and TC-453."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import secrets
import sys
import unittest
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fakes import FakeEmbeddings, ScriptedLLM, message, text
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE
from marong.config import load_settings
from marong.unified_prompt import ADULT_END, ADULT_START, PET_HEALTH_REFERRAL, PET_LINES, character_section, common_prompt
from marong.unified_store import UnifiedStore
from pg import TestDB
from run_app import AppAgent, RoomLocks


ORIGIN = "https://fixture.invalid"
PROFILE = "/chat/api/profile"


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_profile_and_model_prefix_and_pending_ring(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        store = UnifiedStore(db.app_url, call_bridge=True)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22))
        invite, _ = await sessions.create_invite("join")
        auth = await sessions.join(invite, "Fixture", "웹")
        who = await sessions.find_session(auth.token)
        settings = replace(load_settings(), database_url=db.app_url)
        model = ScriptedLLM(lambda _: message([text("합성 답이야.")]))
        agent = AppAgent(settings, store, FakeEmbeddings(), model)
        chat = AppChat(store, agent, RoomLocks(), None, AppPush(store), origin=ORIGIN,
                       sessions=sessions, authentication="session")
        async with TestClient(TestServer(chat.web_app())) as client:
            cookie = {"Cookie": f"{COOKIE}={auth.token}"}
            headers = {**cookie, "Origin": ORIGIN}
            self.assertEqual((await client.get(PROFILE)).status, 401)
            manifest = await client.get("/chat/manifest.webmanifest")
            self.assertEqual(manifest.content_type, "application/manifest+json")
            metadata = await manifest.json(content_type="application/manifest+json")
            self.assertEqual((metadata["start_url"], metadata["display"]), ("/chat/", "standalone"))
            self.assertEqual([icon["sizes"] for icon in metadata["icons"]], ["192x192", "512x512"])
            for icon in ("/chat/icon-180.png", *(item["src"] for item in metadata["icons"])):
                asset = await client.get(icon)
                self.assertEqual(asset.content_type, "image/png")
                self.assertTrue((await asset.read()).startswith(b"\x89PNG"))
            homepage = await client.get("/chat/", headers=cookie)
            markup = await homepage.text()
            self.assertIn('rel="apple-touch-icon"', markup)
            self.assertNotIn("serviceWorker", markup)
            self.assertEqual((await client.get("/chat/me", allow_redirects=False)).status, 302)
            self.assertEqual((await client.get("/chat/me", headers=cookie)).status, 200)
            initial = await (await client.get(PROFILE, headers=cookie)).json()
            self.assertEqual(initial["botName"], "마롱이")
            self.assertIsNone(initial["pendingRing"])
            self.assertEqual((await client.patch(PROFILE, json={"botName": "군밤이"}, headers=cookie)).status, 403)
            for bad in ("   ", "가" * 13, None):
                self.assertEqual((await client.patch(PROFILE, json={"botName": bad}, headers=headers)).status, 400)
            changed = await client.patch(PROFILE, json={"botName": " 군밤이 "}, headers=headers)
            self.assertEqual(changed.status, 200)
            self.assertEqual((await changed.json())["botName"], "군밤이")
            user = await client.post("/chat/api/messages", headers=headers,
                json={"clientId": "2cad99f0-17b9-46d1-b1ca-f5b9bdf828df", "text": "합성 문장이야."})
            self.assertEqual(user.status, 202)
            tasks = list(chat.tasks)
            if tasks:
                await asyncio.gather(*tasks)
            self.assertTrue(model.bodies)
            system = model.bodies[-1]["system"]
            self.assertEqual(system[0]["text"], agent.persona())
            self.assertTrue(any("네 이름은 군밤이야" in block["text"] for block in system))
            schedule = db.admin("""
                INSERT INTO marong.schedules(friend_id,room_key,source,title,remind_at,action)
                VALUES (%s,%s,'app','Fixture call',now(),'call') RETURNING id
            """, (who["friend_id"], who["room_key"]))[0][0]
            ring = await store.ring_add({"id": schedule, "friend_id": who["friend_id"], "title": "Fixture call", "say": None},
                                        who["caller_id"], "app", "ringing", timedelta(minutes=10))
            ringing = await (await client.get(PROFILE, headers=cookie)).json()
            self.assertEqual(ringing["pendingRing"]["ringId"], ring["id"])
            db.admin("UPDATE marong.app_rings SET answer_until=now()-interval '1 second' WHERE id=%s", (ring["id"],))
            expired = await (await client.get(PROFILE, headers=cookie)).json()
            self.assertIsNone(expired["pendingRing"])

    async def test_explicit_pet_health_questions_use_only_the_referral(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        store = UnifiedStore(db.app_url, call_bridge=True)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22))
        invite, _ = await sessions.create_invite("join")
        auth = await sessions.join(invite, "Fixture", "웹")
        who = await sessions.find_session(auth.token)
        friend_id = who["friend_id"]
        character_id = db.admin("""
            INSERT INTO marong.characters(friend_id,kind,name,template,status,stage,ready_at)
            VALUES(%s,'dog','Fixture pet','dog_small','ready','done',now()) RETURNING id
        """, (friend_id,))[0][0]
        db.admin("UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s", (character_id, friend_id))

        settings = replace(load_settings(), database_url=db.app_url, reply_wait_s=0)
        model = ScriptedLLM(lambda _: message([text("일반 합성 답이야.")]))
        agent = AppAgent(settings, store, FakeEmbeddings(), model)
        chat = AppChat(store, agent, RoomLocks(), None, AppPush(store), origin=ORIGIN,
                       sessions=sessions, authentication="session")
        headers = {"Cookie": f"{COOKIE}={auth.token}", "Origin": ORIGIN}
        questions = (
            "강아지가 두 번 토했는데 무슨 병인지 알려 줘.",
            "오늘 강아지가 사료를 안 먹어. 네가 진단해 줘.",
            "강아지가 계속 떨면 무슨 약을 먹여야 해?",
            "기침하는 강아지에게 집에 있는 사람 약을 줘도 돼?",
            "강아지가 절뚝거려. 상처인지 병인지 알려 줘.",
        )

        async def ask(client, sentence):
            response = await client.post("/chat/api/messages", headers=headers,
                json={"clientId": str(uuid4()), "text": sentence})
            self.assertEqual(response.status, 202)
            if chat.tasks:
                await asyncio.gather(*tuple(chat.tasks))
            history = await (await client.get("/chat/api/messages?limit=2", headers=headers)).json()
            return history["messages"][-1]["text"]

        async with TestClient(TestServer(chat.web_app())) as client:
            for question in questions:
                self.assertEqual(await ask(client, question), PET_HEALTH_REFERRAL)
            self.assertEqual(len(model.bodies), 0)
            for question in ("강아지랑 아침에 산책했어.", "강아지 사진을 봤어. 내가 기침을 해."):
                self.assertEqual(await ask(client, question), "일반 합성 답이야.")
            db.admin("UPDATE marong.friend_profiles SET character_id=NULL WHERE friend_id=%s", (friend_id,))
            self.assertEqual(await ask(client, questions[0]), "일반 합성 답이야.")
            self.assertEqual(len(model.bodies), 3)

    def test_marked_text_is_byte_identical_for_default_and_removed_for_pets(self):
        marked = f"common\n{ADULT_START}\nprivate adult section\n{ADULT_END}\nrest\n"
        self.assertTrue(common_prompt(marked) == "common\nprivate adult section\nrest\n")
        self.assertTrue(common_prompt(marked, pet=True) == "common\nrest\n")
        with self.assertRaises(ValueError):
            common_prompt("missing markers", pet=True)
        for kind in ("dog", "cat"):
            section = character_section({"kind": kind, "bot_name": "#초코\n<", "has_friends": True,
                                         "tone": "짧게 말해 줘", "traits": {"coatColors": ["갈색", "흰색"]}})
            self.assertIn("네 이름은 초코야", section)
            for line in PET_LINES:
                self.assertIn(line, section)
            self.assertLessEqual(len(section), 600)
        default = character_section({"kind": None, "bot_name": "마롱이"})
        self.assertFalse(any(line in default for line in PET_LINES))


if __name__ == "__main__":
    unittest.main()
