"""TC-526–531, with synthetic scenes, models and a temporary database."""

import asyncio
import base64
import logging
from datetime import timedelta
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import secrets
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE
from marong.diary import drawing_allowed_in, image_budget
from marong.decor import DecorCatalog
from marong.diary_models import ModelResult, parse_picture
from marong.pet_app_settings import PetAppSettings
from marong.scene_picture import ScenePictures, SceneResult, subject
from marong.scene_worker import SceneWorker
from marong.unified_store import UnifiedStore
from pg import TestDB
from run_app import RoomLocks


PET = {"id": 1, "kind": "dog", "template": "dog_small", "name": "콩이",
       "traits": {"coatColors": ["갈색"], "build": "작음", "breedGuess": "푸들"}}


def picture():
    stream = BytesIO()
    Image.new("RGB", (12, 12), "#442233").save(stream, "WEBP")
    return parse_picture(base64.b64encode(stream.getvalue()).decode(), square=True)


class ScenesTests(unittest.IsolatedAsyncioTestCase):
    async def test_scene_prompts_references_retries_and_cost(self):
        self.assertEqual(subject({"kind": "dog"}), "a small dog")
        self.assertEqual(subject(PET), "a small brown poodle")
        output = picture()
        with self.assertRaisesRegex(ValueError, "image_shape"):
            parse_picture(base64.b64encode(output.data).decode())
        model = AsyncMock(return_value=ModelResult(value=output, cost=Decimal(".025"), estimated=True))
        store = SimpleNamespace(pool=SimpleNamespace(connection=patch_connection()))
        media = SimpleNamespace(read=AsyncMock(return_value=b"reference"))
        art = ScenePictures(store, media, SimpleNamespace(edit_picture=model), "fixture")
        for purpose, expression, size in (("topic", "smile", "1024x1024"), ("reaction", "excited", "1024x1024"),
                                           ("diary", "sad", "1536x1024"), ("topic", "smile", "1024x1024")):
            result = await art.draw(purpose, PET, ["a red beanie"], "Marong sits with 가나 and 콩이.",
                                    weather="rain", friend_name="가나")
            self.assertEqual((result.outcome, result.cost, result.estimated), ("ok", Decimal(".025"), True))
            prompt, refs = model.await_args.args
            self.assertEqual([item[1][0] for item in refs], ["front.png", expression + ".png"])
            self.assertIn("Main character: a small brown poodle", prompt)
            self.assertIn("Wearing: a red beanie.", prompt)
            self.assertIn("No text, letters or numbers", prompt)
            for private in ("Marong", "콩이", "가나"):
                self.assertNotIn(private, prompt)
            self.assertEqual(model.await_args.kwargs, {
                "model": "fixture", "size": size, "output_format": "webp", "deadline": 90, "estimate_errors": True,
            })
        self.assertEqual(model.await_count, 4)
        # TC-554: include a synthetic scene description while capturing every application logger.
        records = []
        class Capture(logging.Handler):
            def emit(self, record): records.append(record.getMessage())
        handler = Capture()
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        try:
            await art.draw("topic", PET, (), "시험장면지시 가나다 콩이", friend_name="가나다")
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)
        self.assertFalse(any(marker in line for line in records for marker in ("시험장면지시", "가나다", "콩이", "Main character:")))

        for outcomes, expected, reason, cost in (
            (["refused"], "refused", "refused", ".025"),
            (["error", "error"], "failed", "model_error", ".05"),
            (["timeout", "ok"], "ok", None, ".05"),
            (["invalid"], "failed", "check_failed", ".025"),
        ):
            model.reset_mock()
            model.side_effect = [ModelResult(value=output if status == "ok" else None, outcome=status,
                                             cost=Decimal(".025"), estimated=True) for status in outcomes]
            result = await art.draw("topic", PET, (), "A basket sits in the snow.")
            self.assertEqual((result.outcome, result.reason, result.cost), (expected, reason, Decimal(cost)))
            self.assertEqual(model.await_count, len(outcomes))

    async def test_tc554_scene_worker_logs_omit_prompt_and_names(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app()
        store = UnifiedStore(db.app_url)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22))
        auth = await sessions.join((await sessions.create_invite("join"))[0], "합성친구이름", "웹")
        friend = (await sessions.find_session(auth.token))["friend_id"]
        character = db.admin("""
            INSERT INTO marong.characters(friend_id,kind,template,name,traits,stage,status,ready_at)
            VALUES (%s,'dog','dog_small','시험아이이름','{}','done','ready',now()) RETURNING id
        """, (friend,))[0][0]
        db.admin("UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s", (character, friend))
        catalog = DecorCatalog()
        item = catalog.items["berry-beanie"]
        catalog.items[item.id] = replace(item, prompt="시험장면지시")
        db.admin("INSERT INTO marong.decor_items(id,item_set,kind,slot,starter) VALUES (%s,'v1','hat','head',false)", (item.id,))
        db.admin("""INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,item_id,outfit)
                    VALUES (%s,%s,'reaction',%s,ARRAY[%s])""", (friend, character, item.id, item.id))
        model = AsyncMock(return_value=ModelResult(value=picture(), cost=Decimal("0")))
        media = SimpleNamespace(read=AsyncMock(return_value=b"synthetic"))
        art = ScenePictures(store, media, SimpleNamespace(edit_picture=model), "fixture", catalog=catalog)
        worker = SceneWorker(store, art, SimpleNamespace(record=AsyncMock()))
        job, = await worker.claim()
        records = []
        class Capture(logging.Handler):
            def emit(self, record): records.append(record.getMessage())
        handler = Capture(); root = logging.getLogger(); old = root.level
        root.addHandler(handler); root.setLevel(logging.INFO)
        try:
            await worker.process(job)
        finally:
            root.removeHandler(handler); root.setLevel(old)
        self.assertEqual(model.await_count, 1)
        self.assertTrue(any("scene_finished" in line for line in records))
        self.assertFalse(any(marker in line for line in records for marker in
                             ("합성친구이름", "시험아이이름", "시험장면지시", "Main character:")))

    async def test_leases_usage_and_owner_only_picture_endpoint(self):
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

        async def account():
            invite, _ = await sessions.create_invite("join")
            auth = await sessions.join(invite, "합성 친구", "웹")
            friend = (await sessions.find_session(auth.token))["friend_id"]
            ident = db.admin("""
                INSERT INTO marong.characters(friend_id,kind,template,name,traits,stage,status,ready_at)
                VALUES (%s,'dog','dog_small','콩이','{}','done','ready',now()) RETURNING id
            """, (friend,))[0][0]
            return {"Cookie": f"{COOKIE}={auth.token}"}, friend, ident

        owner, friend, ident = await account()
        outsider, other, other_ident = await account()
        chat = AppChat(store, SimpleNamespace(friend_cards=None), RoomLocks(), None, AppPush(store),
                       sessions=sessions, authentication="session", admin_email_hash="a" * 64,
                       pet_app_settings=PetAppSettings(diary_image_budget=None))
        chat.access = SimpleNamespace(check=AsyncMock(return_value=("ok", "a" * 64)))
        worker = SceneWorker(store, None, chat.usage)

        def queue(who, character, count):
            return [row[0] for row in db.admin("""
                INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,topic,not_before)
                SELECT %s,%s,'topic','v1/snow',now()-make_interval(mins=>6-n)
                FROM generate_series(1,%s) n RETURNING id
            """, (who, character, count))]

        ids = queue(friend, ident, 4)
        other_id = queue(other, other_ident, 1)[0]
        first = await worker.claim()
        self.assertEqual({row["id"] for row in first}, {ids[0], other_id})
        db.admin("UPDATE marong.scene_pictures SET lease_until=now()-interval '1 second' WHERE state='drawing'")
        await worker.recover()
        self.assertEqual(db.admin("SELECT count(*) FROM marong.scene_pictures WHERE state='queued'"), [(5,)])
        self.assertEqual(len(await worker.claim()), 2)
        db.admin("UPDATE marong.scene_pictures SET lease_until=now()-interval '1 second',attempts=3 WHERE id=%s", (other_id,))
        await worker.recover()
        self.assertEqual(db.admin("SELECT state,fail_reason FROM marong.scene_pictures WHERE id=%s", (other_id,)),
                         [("failed", "timeout")])
        output = picture()
        success = SceneResult("ok", None, output, Decimal(".01"), False, "fixture")
        failure = SceneResult("refused", "refused", None, Decimal(".025"), True, "fixture")
        self.assertFalse(await worker.finish(first[0], success))
        jobs = await worker.claim()
        self.assertEqual(len(jobs), 2)
        await asyncio.gather(*(worker.finish(job, result) for job, result in zip(jobs, (success, failure))))
        self.assertFalse(await worker.finish(jobs[0], success))
        self.assertEqual((await chat.usage.get(friend))["images"], 1)
        db.admin("UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s", (ident, friend))
        future = sessions.now() + timedelta(hours=1)
        prefetch = await worker.topic_job(friend, "v1/snow", future)
        self.assertEqual(await worker.topic_job(friend, "v1/snow", future), prefetch)
        self.assertEqual(db.admin("SELECT not_before FROM marong.scene_pictures WHERE id=%s", (prefetch["id"],))[0][0],
                         future - timedelta(minutes=30))
        db.admin("UPDATE marong.scene_pictures SET cost_usd=.25 WHERE id=%s", (jobs[0]["id"],))
        db.admin("UPDATE marong.scene_pictures SET cost_usd=.25 WHERE id=%s", (jobs[1]["id"],))
        diary_id = db.admin("INSERT INTO marong.diaries(friend_id,diary_date) VALUES (%s,current_date) RETURNING id",
                            (friend,))[0][0]
        db.admin("""
            INSERT INTO marong.diary_ai_runs(diary_id,kind,origin,trace_id,model,prompt_version,sent_at,cost_usd,outcome)
            VALUES (%s,'draw','night','fixture','fixture','diary-v1',now(),2,'ok')
        """, (diary_id,))
        db.admin("""
            INSERT INTO marong.character_jobs(character_id,step,state,finished_at,cost_usd)
            VALUES (%s,'sheet','done',now(),3)
        """, (ident,))

        async with TestClient(TestServer(chat.web_app())) as client:
            api = "/chat/api/scenes/"
            response = await client.get(api + str(jobs[0]["id"]), headers=owner)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, "image/webp")
            self.assertEqual(response.headers["Cache-Control"], "private, max-age=31536000")
            self.assertEqual(await response.read(), output.data)
            self.assertEqual((await client.get(api + "abc", headers=owner)).status, 400)
            self.assertEqual((await client.get(api + str(jobs[0]["id"]))).status, 401)
            attempts = [(jobs[0]["id"], outsider), (jobs[1]["id"], owner), (uuid4(), owner)]
            for key, headers in attempts:
                found = await client.get(api + str(key), headers=headers)
                self.assertEqual((found.status, (await found.json())["code"]), (404, "not_found"))
            costs = "/chat/admin/api/image-costs"
            self.assertEqual((await client.get(costs, headers=owner)).status, 403)
            response = await client.get(costs, headers={"Cf-Access-Jwt-Assertion": "fixture"})
            self.assertEqual(response.status, 200)
            costs = await response.json()
            self.assertEqual(costs["byKind"], {"diary": 2, "topic": .5, "reaction": 0, "character": 3})
            self.assertIsNone(costs["budgets"]["diary"])
            self.assertEqual(costs["budgets"]["character"]["ratio"], .15)
        conn = SimpleNamespace(execute=AsyncMock())
        self.assertTrue(await drawing_allowed_in(conn, image_budget(" UNLIMITED "), sessions.now()))
        conn.execute.assert_not_called()


def patch_connection():
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def connection():
        yield object()

    return connection


if __name__ == "__main__":
    unittest.main()
