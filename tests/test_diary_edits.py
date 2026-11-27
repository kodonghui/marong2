"""TC-167/168 with a signed fake Access request and a disposable PostgreSQL."""

import asyncio
from collections import deque
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import psycopg
from aiohttp.test_utils import TestClient, TestServer

from test_app_chat import AUD, HK_EMAIL, ORIGIN, STRANGER, TEAM, Certs, auth, prepare, problem
from test_app_diary import PREFIX, fixtures
from test_diary_worker import DRAFT, picture
from marong.access import AccessConfig, AccessVerifier
from marong.app_chat import AppChat
from marong.diary_models import ModelResult, parse_picture
from marong.decor import DecorCatalog
from marong.app_diary import AppDiary
from marong.diary_decor import DiaryDecor
from marong.discord_store import DiscordStore
from pg import TestDB

DAY = "/days/2026-11-17"
DAY_2 = "/days/2026-11-14"


class Models:
    text_model = "fixture-text"
    image_model = "fixture-image"
    image_key = "fixture"

    def __init__(self):
        self.calls = []
        self.fix_results = deque()
        self.scenes = deque()
        self.draws = deque()
        self.fix_started = asyncio.Event()
        self.fix_continue = asyncio.Event()

    async def fix(self, name, look, draft, bundle, note):
        self.calls.append(("fix", draft, bundle, note))
        self.fix_started.set()
        await self.fix_continue.wait()
        return self.fix_results.popleft()

    async def scene(self, look, body, scene, note):
        self.calls.append(("scene", body, scene, note))
        return self.scenes.popleft()

    async def draw(self, scene, look):
        self.calls.append(("draw", scene))
        return self.draws.popleft()


def clear_rate(db):
    db.admin("UPDATE marong.diary_requests SET created_at=created_at-interval '2 minutes'")


async def check(http, chat, db, models):
    async def send(action, data, *, key=None, day=DAY, headers=None):
        headers = dict(auth(write=True) if headers is None else headers)
        headers["Idempotency-Key"] = key or str(uuid4())
        return await http.post(PREFIX + day + "/" + action, headers=headers, json=data)

    async def sticker_values():
        # The edit API above uses synthetic Access; ownership routing was tested separately with sessions.
        with patch.object(chat.profile, "who", new=AsyncMock(return_value={"friend_id": 2})):
            response = await http.get(PREFIX + DAY + "/stickers")
            assert response.status == 200, (response.status, await response.text())
            return [{key: item[key] for key in ("itemId", "x", "y", "scale", "rotation")}
                    for item in (await response.json())["stickers"]]

    stickers_before = await sticker_values()
    assert len(stickers_before) == 3
    good = {"revision": 1, "text": "군밤을 먹었어"}
    draw = {"revision": 1}
    for action, data in (("fixes", good), ("drawings", draw)):
        await problem(await send(action, data), 403, "no_dm")
    db.admin("UPDATE marong.discord_dm_links SET channel_id='200000000000000010',last_incoming_at=now() "
             "WHERE friend_id=2")
    for action, data in (("fixes", good), ("drawings", draw)):
        await problem(await send(action, data, headers={"Origin": ORIGIN}), 401, "unauthenticated")
        await problem(await send(action, data, headers=auth(STRANGER, write=True)), 403, "not_allowed")
        await problem(await send(action, data, headers=auth(write=True, origin="https://else.test")), 403, "cross_site")
        await problem(await send(action, data, key="invalid"), 400, "invalid_request")
        await problem(await send(action, {**data, "revision": True}), 400, "invalid_request")
        await problem(await send(action, data, day="/days/2026-11-13"), 409, "not_ready")
        for error, status, code in ((psycopg.OperationalError("synthetic"), 503, "db_unavailable"),
                                    (RuntimeError("synthetic"), 500, "internal")):
            with patch.object(chat.store, "app_login", side_effect=error):
                await problem(await send(action, data), status, code)
    for note in ("", "  ", "가" * 201):
        await problem(await send("fixes", {**good, "text": note}), 400, "invalid_request")
    await problem(await send("drawings", {**draw, "change": " " * 201}), 400, "invalid_request")

    key = str(uuid4())
    fresh_scene = DRAFT["scene"]
    models.fix_results.append(ModelResult(value={**DRAFT, "sceneChanged": False}))
    pending = asyncio.create_task(send("fixes", good, key=key))
    await asyncio.wait_for(models.fix_started.wait(), 2)
    try:
        await problem(await send("fixes", good, key=key), 409, "busy")
        await problem(await send("fixes", good), 409, "busy")
        await problem(await send("drawings", draw, key=key), 400, "invalid_request")
        await problem(await send("fixes", good, key=key, day=DAY_2), 400, "invalid_request")
    finally:
        models.fix_continue.set()
    success = await pending
    assert success.status == 200
    reply = await success.json()
    panel = reply["day"]["diary"]
    assert panel["revision"] == 2 and panel["fix"]["left"] == 4 and reply["sceneChanged"]
    assert await sticker_values() == stickers_before
    assert "scene" not in panel and "hidden-scene-marker" not in str(reply)
    assert db.admin("SELECT source,scene FROM marong.diary_revisions r JOIN marong.diaries d "
                    "ON d.id=r.diary_id WHERE d.friend_id=2 AND d.diary_date='2026-11-17' ORDER BY r.revision") == [
        ("weather", "hidden-scene-marker"), ("fix", fresh_scene)]
    repeated = await send("fixes", good, key=key)
    assert repeated.status == 200 and await repeated.json() == reply
    assert len(models.calls) == 1 and "하루 모음 데이터 시작" in models.calls[0][2]
    await problem(await send("fixes", good), 409, "stale_revision")

    failure_key = str(uuid4())
    models.fix_results.append(ModelResult(outcome="timeout"))
    for _ in range(2):
        await problem(await send("fixes", {**good, "revision": 2}, key=failure_key), 503, "fix_failed")
    models.fix_results.append(ModelResult(value={**DRAFT, "sceneChanged": True, "scene": "The friend is here."}))
    corrected = await send("fixes", {**good, "revision": 2})
    assert corrected.status == 200 and (await corrected.json())["sceneChanged"] is False
    assert db.admin("SELECT revision,fixes_used,redraws_used FROM marong.diaries WHERE friend_id=2 "
                    "AND diary_date='2026-11-17'") == [(3, 2, 0)]
    limited = await send("drawings", {"revision": 3})
    await problem(limited, 429, "too_many_requests")
    assert 0 < int(limited.headers["Retry-After"]) <= 60
    assert len(models.calls) == 3
    clear_rate(db)

    currently = {"revision": 3}
    redraw_key = str(uuid4())
    image = parse_picture(picture("WEBP"))
    models.draws.append(ModelResult(value=image, cost=Decimal("0.025"), estimated=True))
    accepted = await send("drawings", currently, key=redraw_key)
    assert accepted.status == 202 and (await accepted.json())["day"]["diary"]["busy"] == "redraw"
    await asyncio.gather(*list(chat.tasks))
    calls = len(models.calls)
    after = await send("drawings", currently, key=redraw_key)
    assert after.status == 202 and len(models.calls) == calls
    first = (await after.json())["day"]["diary"]
    assert first["revision"] == 3 and first["redraw"]["last"]["result"] == "done"
    first_drawing = first["drawing"]["id"]
    assert first_drawing and first["redraw"]["left"] == 1
    assert await sticker_values() == stickers_before

    models.scenes.append(ModelResult(value={"scene": "A woman holds a basket."}))
    bad_scene = await send("drawings", {**currently, "change": "배경을 바꿔 줘"})
    assert bad_scene.status == 202
    await asyncio.gather(*list(chat.tasks))
    month = await http.get(PREFIX + DAY, headers=auth())
    value = (await month.json())["diary"]
    assert value["drawing"]["id"] == first_drawing and value["redraw"]["last"]["result"] == "scene_rejected"
    assert value["redraw"]["left"] == 1 and models.calls[-1][0] == "scene"
    models.draws.append(ModelResult(outcome="error", error="http_500"))
    first_failure = await send("drawings", currently)
    assert first_failure.status == 202
    await asyncio.gather(*list(chat.tasks))
    day = await http.get(PREFIX + DAY, headers=auth())
    value = (await day.json())["diary"]
    assert value["drawing"]["id"] == first_drawing and value["redraw"]["last"]["result"] == "draw_failed"
    assert value["redraw"]["left"] == 1

    models.scenes.append(ModelResult(value={"scene": "A white basket sits beside a curtain."}))
    models.draws.append(ModelResult(value=image))
    accepted = await send("drawings", {**currently, "change": "바구니를 크게 그려 줘"})
    assert accepted.status == 202
    await asyncio.gather(*list(chat.tasks))
    newly_drawn = await http.get(PREFIX + DAY, headers=auth())
    value = (await newly_drawn.json())["diary"]
    assert value["revision"] == 4 and value["drawing"]["id"] != first_drawing
    assert value["redraw"]["left"] == 0 and value["redraw"]["last"]["result"] == "done"
    assert db.admin("SELECT count(*) FROM marong.diary_drawings WHERE id=%s", (first_drawing,)) == [(1,)]
    await problem(await send("drawings", {"revision": 4}), 409, "redraw_limit")
    clear_rate(db)
    db.admin("UPDATE marong.diaries SET fixes_used=5 WHERE friend_id=2 AND diary_date='2026-11-17'")
    await problem(await send("fixes", {**good, "revision": 4}), 409, "fix_limit")
    db.admin("UPDATE marong.diary_ai_runs SET cost_usd=5,sent_at=now() WHERE kind='draw' AND origin='redraw'")
    await problem(await send("drawings", draw, day=DAY_2), 429, "drawing_budget")


async def run(db):
    store = DiscordStore(db.app_url, call_bridge=True)
    models = Models()
    async with httpx.AsyncClient(transport=httpx.MockTransport(Certs())) as client:
        access = AccessVerifier(AccessConfig(TEAM, AUD, frozenset({HK_EMAIL})), client)
        await store.open(wait=True)
        chat = AppChat(store, None, None, access, None, origin=ORIGIN, diary_models=models)
        chat.decor.catalog = DecorCatalog()
        try:
            app = chat.web_app()
            DiaryDecor(AppDiary(chat)).register(app.router)
            async with TestClient(TestServer(app)) as http:
                await check(http, chat, db, models)
        finally:
            await chat.close()
            await store.close()


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        root = Path(__file__).resolve().parents[1]
        db.apply_sql(root / "marong/call/migrations/007_call_cost.sql", root / "marong/migrations/019_persona.sql", root / "marong/migrations/020_unified.sql",
                     root / "marong/call/migrations/008_unified.sql")
        db.apply_pet_app_prerequisites()
        db.apply_pet_app()
        fixtures(db)
        catalog = DecorCatalog()
        sticker = next(item.id for item in catalog.items.values() if item.kind == "sticker")
        db.admin("INSERT INTO marong.decor_items(id,item_set,kind,slot,starter) VALUES (%s,'v1','sticker',NULL,false)", (sticker,))
        db.admin("INSERT INTO marong.decor_owned(friend_id,item_id) VALUES (2,%s)", (sticker,))
        db.admin("""INSERT INTO marong.diary_stickers(diary_id,friend_id,item_id,x,y,scale,rotation,z)
            SELECT id,2,%s,100*z,250,100,0,z FROM marong.diaries CROSS JOIN generate_series(0,2) z
            WHERE friend_id=2 AND diary_date='2026-11-17'""", (sticker,))
        asyncio.run(run(db))
    finally:
        db.close()
    print("TC-167 and TC-168: fixes, concurrent replay, limits, and redraw history verified")
