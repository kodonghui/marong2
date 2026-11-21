"""TC-521: the writer is pinned while a diary is generated."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import secrets
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE
from marong.diary import KST
from marong.diary_models import ModelResult, write_prompt
from marong.diary_worker import DiaryWorker
from marong.unified_prompt import PET_LINES
from marong.unified_store import UnifiedStore
from pg import TestDB
from run_app import RoomLocks


class PetDiaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_writer_and_prompt_version(self):
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
        invite, _ = await sessions.create_invite("join")
        auth = await sessions.join(invite, "시험친구", "웹")
        who = await sessions.find_session(auth.token)
        friend = who["friend_id"]
        character = db.admin("""
            INSERT INTO marong.characters(friend_id,kind,template,name,traits,stage,status,ready_at,owner_call)
            VALUES (%s,'dog','dog_small','콩이','{}','done','ready',now(),'누나') RETURNING id
        """, (friend,))[0][0]
        db.admin("UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s", (character, friend))
        now = datetime(2026, 11, 21, 2, tzinfo=KST)
        day = now.date() - timedelta(days=1)
        lease = now + timedelta(minutes=10)
        row = await store._one("""
            INSERT INTO marong.diaries(friend_id,diary_date,state,lease_until)
            VALUES (%s,%s,'writing',%s) RETURNING *
        """, (friend, day, lease))
        draft = {"title": "콩이 일기", "body": "누나가 이야기해 준 일을 떠올리며 하루를 마무리했다. " * 3,
                 "weather": "sunny", "scene": "The little white character carries a basket."}
        fake = AsyncMock(return_value=ModelResult(value=draft))
        models = SimpleNamespace(write=fake, text_model="fixture-text", effort="medium")
        worker = DiaryWorker(store, models, None, Decimal(5), now=lambda: now, unified=True, pet_voice=True)
        with patch("marong.diary_worker.read_day_bundle", return_value=SimpleNamespace(enough=True, value="합성 기록")):
            written = await worker._write(row, lease, uuid4().hex)
        self.assertEqual(written["character_id"], character)
        writer = fake.await_args.kwargs["character"]
        instruction = write_prompt("시험친구", False, Path(__file__).with_name("unused.md"), character=writer)
        self.assertIn("콩이(강아지)이야", instruction)
        self.assertIn("콩이 1인칭(나)", instruction)
        self.assertIn("'누나'라고 불러", instruction)
        self.assertTrue(all(line in instruction for line in PET_LINES))
        self.assertEqual(db.admin("SELECT prompt_version FROM marong.diary_ai_runs WHERE diary_id=%s", (row["id"],)),
                         [("pet-diary-v1",)])
        db.admin("UPDATE marong.friend_profiles SET character_id=NULL WHERE friend_id=%s", (friend,))
        db.admin("UPDATE marong.diaries SET state='ready',ready_at=%s,lease_until=NULL WHERE id=%s", (now, row["id"]))
        chat = AppChat(store, SimpleNamespace(friend_cards=None), RoomLocks(), None, AppPush(store),
                       sessions=sessions, authentication="session")
        async with TestClient(TestServer(chat.web_app())) as client:
            path = f"/chat/diary/api/days/{day}"
            response = await client.get(path, headers={"Cookie": f"{COOKIE}={auth.token}"})
            self.assertEqual(response.status, 200)
            diary = (await response.json())["diary"]
            self.assertEqual(diary["writer"], {"id": character, "name": "콩이", "kind": "dog", "active": True,
                                              "faceUrl": f"/chat/api/characters/{character}/images/smile"})
            db.admin("UPDATE marong.characters SET status='retired', retired_at=now() WHERE id=%s", (character,))
            response = await client.get(path, headers={"Cookie": f"{COOKIE}={auth.token}"})
            self.assertIs((await response.json())["diary"]["writer"]["active"], False)


if __name__ == "__main__":
    unittest.main()
