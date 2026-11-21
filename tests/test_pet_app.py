"""Pet intro API and voice recommendation with synthetic accounts (TC-514–516)."""

from pathlib import Path
import secrets
import sys
from types import SimpleNamespace
import unittest

from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE
from marong.pet_app_settings import PetAppSettings
from marong.pet_intro import recommended_voice
from marong.unified_store import UnifiedStore
from pg import TestDB
from run_app import RoomLocks


ORIGIN = "https://fixture.invalid"
INTRO = {"personality": ["활발함"], "likes": "고구마", "dislikes": "", "ownerCall": "누나"}
VOICE_RULES = {"dog": {"활발함": "Puck"}}


class PetIntroTests(unittest.IsolatedAsyncioTestCase):
    def test_voice_order_and_fallback(self):
        for traits, rules, choices, expected in (
            ([], {}, ("Sulafat",), "Sulafat"),
            (["활발함"], VOICE_RULES, ("Sulafat", "Puck"), "Puck"),
            (["먹보", "활발함"], VOICE_RULES, ("Sulafat", "Puck"), "Puck"),
            (["활발함"], {"dog": {"활발함": "Kore"}}, ("Sulafat", "Puck"), "Sulafat"),
            ([], {"dog": {"default": "Puck"}}, ("Sulafat", "Puck"), "Puck"),
        ):
            with self.subTest(traits=traits, rules=rules):
                self.assertEqual(recommended_voice("dog", traits, rules, choices), expected)

    async def test_intro_endpoints_and_voice_precedence(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        db.apply_pet_app_prerequisites()
        db.apply_pet_app()
        store = UnifiedStore(db.app_url)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22))

        async def account(name):
            invite, _ = await sessions.create_invite("join")
            auth = await sessions.join(invite, name, "웹")
            who = await sessions.find_session(auth.token)
            character = db.admin("""
                INSERT INTO marong.characters(friend_id, kind, template, name, traits, stage, status, ready_at)
                VALUES (%s,'dog','dog_small','콩이','{}','done','ready',now()) RETURNING id
            """, (who["friend_id"],))[0][0]
            return ({"Cookie": f"{COOKIE}={auth.token}", "Origin": ORIGIN},
                    who["friend_id"], f"/chat/api/characters/{character}/intro")

        first, friend, path = await account("시험친구 가")
        second, other, other_path = await account("시험친구 나")
        draft = db.admin("INSERT INTO marong.characters(friend_id,kind) VALUES (%s,'cat') RETURNING id", (friend,))[0][0]
        db.admin("UPDATE marong.friend_profiles SET voice='Sulafat', voice_source='chosen' WHERE friend_id=%s", (other,))
        chat = AppChat(store, SimpleNamespace(friend_cards=None), RoomLocks(), None, AppPush(store),
                       origin=ORIGIN, sessions=sessions, authentication="session",
                       pet_app_settings=PetAppSettings(voice_recommend=VOICE_RULES))
        chat.profile.voices = ("Sulafat", "Puck")
        async with TestClient(TestServer(chat.web_app())) as client:
            self.assertEqual((await client.get(path)).status, 401)
            self.assertEqual((await client.put(path, json=INTRO, headers={"Origin": ORIGIN})).status, 401)
            initial = await (await client.get(path, headers=first)).json()
            self.assertEqual(initial, {"intro": None, "introAt": None, "voice": None, "voiceSource": "none"})
            self.assertEqual((await client.put(path, json=INTRO, headers={**first, "Origin": "https://cross.invalid"})).status, 403)
            self.assertEqual((await client.put(path, json={**INTRO, "likes": "x" * 17000}, headers=first)).status, 413)
            for ident, status, code in (("abc", 400, "invalid_input"), (draft, 409, "not_ready"),
                                        (9999, 404, "not_found")):
                url = f"/chat/api/characters/{ident}/intro"
                for method, kwargs in ((client.get, {}), (client.put, {"json": INTRO})):
                    response = await method(url, headers=first, **kwargs)
                    self.assertEqual(response.status, status)
                    self.assertEqual((await response.json())["code"], code)
            missing = await (await client.get("/chat/api/characters/9999/intro", headers=first)).json()
            forbidden = await (await client.get(other_path, headers=first)).json()
            self.assertEqual({**forbidden, "traceId": ""}, {**missing, "traceId": ""})
            self.assertEqual((await client.put(other_path, json=INTRO, headers=first)).status, 404)
            for diff in ({"personality": ["사나움"]}, {"personality": ["활발함", "활발함"]},
                         {"personality": ["활발함", "먹보", "얌전함", "느긋함"]},
                         {"likes": "가" * 61}, {"ownerCall": "  `<> "}, {"ownerCall": ""}):
                response = await client.put(path, json={**INTRO, **diff}, headers=first)
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())["code"], "invalid_input")
            self.assertEqual(await (await client.get(path, headers=first)).json(), initial)
            saved = await client.put(path, json={**INTRO, "likes": "고\n구#`마<>"}, headers=first)
            self.assertEqual(saved.status, 200)
            self.assertEqual(saved.headers["Cache-Control"], "no-store")
            first_intro = await saved.json()
            self.assertEqual(first_intro["intro"], INTRO)
            self.assertTrue(first_intro["introAt"])
            self.assertEqual((first_intro["voice"], first_intro["voiceSource"]), ("Puck", "recommended"))
            self.assertEqual(await (await client.get(path, headers=first)).json(), first_intro)
            self.assertEqual(await (await client.put(path, json=INTRO, headers=first)).json(), first_intro)
            edited = await (await client.put(path, json={**INTRO, "personality": []}, headers=first)).json()
            self.assertEqual(edited["introAt"], first_intro["introAt"])
            self.assertEqual((edited["voice"], edited["voiceSource"]), ("Puck", "recommended"))
            profile = await client.patch("/chat/api/profile", json={"voice": "Sulafat"}, headers=first)
            self.assertEqual(profile.status, 200)
            self.assertEqual(db.admin("SELECT voice_source FROM marong.friend_profiles WHERE friend_id=%s", (friend,)),
                             [("chosen",)])
            for headers, url in ((first, path), (second, other_path)):
                intro = await (await client.put(url, json=INTRO, headers=headers)).json()
                self.assertEqual((intro["voice"], intro["voiceSource"]), ("Sulafat", "chosen"))
            self.assertEqual((await client.patch("/chat/api/profile", json={"voice": None}, headers=first)).status, 200)
            intro = await (await client.get(path, headers=first)).json()
            self.assertEqual((intro["voice"], intro["voiceSource"]), (None, "none"))


if __name__ == "__main__":
    unittest.main()
