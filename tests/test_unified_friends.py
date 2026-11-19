"""Friendship state, consent and model context with isolated synthetic accounts."""

import json
from pathlib import Path
import secrets
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools" / "vertex_live")]
from call_memory import MemoryStore, Principal
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE
from marong.unified_store import UnifiedStore
from pg import TestDB
from run_app import RoomLocks


BASE = "/chat/api/friends"
ORIGIN = "https://fixture.invalid"


class FriendTests(unittest.IsolatedAsyncioTestCase):
    async def test_friend_request_lifecycle_and_scoped_context(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        store = UnifiedStore(db.app_url)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        memory = MemoryStore(db.admin_url.replace("postgres:@", "marong_call@", 1))
        await memory.open()
        self.addAsyncCleanup(memory.close)
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22))

        async def create(name):
            invite, _ = await sessions.create_invite("join")
            joined = await sessions.join(invite, name, "웹")
            who = await sessions.find_session(joined.token)
            return who, {"Cookie": f"{COOKIE}={joined.token}", "Origin": ORIGIN}

        a, aa = await create("Fixture A")
        b, bb = await create("Fixture B")
        c, cc = await create("Fixture C")
        a_id, b_id, c_id = a["friend_id"], b["friend_id"], c["friend_id"]
        chat = AppChat(store, SimpleNamespace(friend_cards=None), RoomLocks(), None, AppPush(store),
                       origin=ORIGIN, sessions=sessions, authentication="session")
        chat.profile.features["friends"] = True
        who = Principal(a["caller_id"], a_id, "Fixture A", unified=True)

        with patch.dict("os.environ", {"MARONG_FRIENDS": "1"}):
            async with TestClient(TestServer(chat.web_app())) as http:
                async def code(header):
                    return (await (await http.get("/chat/api/profile", headers=header)).json())["friendCode"]

                async def send(friend_code, header):
                    return await http.post(BASE + "/requests", headers=header, json={"friendCode": friend_code})

                async def state(header):
                    return await (await http.get(BASE, headers=header)).json()

                async def problem(response, status, reason):
                    self.assertEqual(response.status, status)
                    self.assertEqual((await response.json())["code"], reason)

                a_code, b_code, c_code = await code(aa), await code(bb), await code(cc)
                self.assertEqual((await http.get("/chat/friends", headers=aa)).status, 200)
                await problem(await send("ABCDE", aa), 400, "invalid_input")
                await problem(await send(a_code, aa), 400, "self_request")
                await problem(await send("ZZZZZZ", aa), 404, "code_not_found")
                response = await send(b_code.lower(), aa)
                self.assertEqual(response.status, 201)
                self.assertEqual((await state(bb))["incoming"][0]["friendId"], a_id)
                self.assertEqual((await state(aa))["outgoing"][0]["friendId"], b_id)
                await problem(await send(a_code, bb), 409, "request_exists")
                await problem(await http.post(BASE + f"/requests/{b_id}", headers=aa, json={"action": "accept"}),
                              404, "not_found")
                success = await http.post(BASE + f"/requests/{a_id}", headers=bb, json={"action": "accept"})
                self.assertEqual((success.status, await success.json()), (200, {"state": "accepted"}))
                await problem(await send(b_code, aa), 409, "already_friends")
                for url, headers, expected in ((f"/{b_id}", aa, False), (f"/{a_id}", bb, True)):
                    close = await http.patch(BASE + url, headers=headers, json={"close": True})
                    self.assertEqual(await close.json(), {"close": expected, "closeMine": True})
                self.assertEqual((await send(c_code, aa)).status, 201)
                b_notes = "Fixture B shares one topic."
                db.admin("INSERT INTO marong.shared_notes(friend_id,content,close_content) VALUES (%s,%s,%s)",
                         (b_id, b_notes, "Fixture close topic"))
                circle = await store.friend_circle(a["user_key"], 32)
                self.assertEqual([row["id"] for row in circle], [b_id])
                self.assertEqual(circle[0]["shared"], b_notes)
                seed = json.loads(await memory.seed(who))
                self.assertEqual([row["name"] for row in seed["shared_friends"]], ["Fixture B"])
                self.assertIn("Fixture close topic", seed["shared_friends"][0]["text"])
                self.assertEqual((await http.patch("/chat/api/profile", headers=bb, json={"share": False})).status, 200)
                self.assertIsNone((await store.friend_circle(a["user_key"], 32))[0]["shared"])
                seed = json.loads(await memory.seed(who))
                self.assertEqual(seed["shared_friends"][0]["text"], "")
                self.assertEqual((await http.delete(BASE + f"/{b_id}", headers=aa)).status, 204)
                self.assertEqual((await state(bb))["friends"], [])
                self.assertEqual((await send(b_code, aa)).status, 201)
                self.assertEqual((await http.post(BASE + f"/requests/{a_id}", headers=cc,
                                                  json={"action": "decline"})).status, 200)
                self.assertEqual((await send(c_code, aa)).status, 201)
                self.assertEqual(await store.friend_circle(a["user_key"], 32), [])
                self.assertEqual(json.loads(await memory.seed(who))["shared_friends"], [])
                for index in range(6):
                    _, newcomer = await create(f"Fixture {index}")
                    self.assertEqual((await send(await code(newcomer), aa)).status, 201)
                _, newcomer = await create("Fixture X")
                await problem(await send(await code(newcomer), aa), 429, "request_limit")


if __name__ == "__main__":
    unittest.main()
