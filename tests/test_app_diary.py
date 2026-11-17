"""Diary API cases with synthetic diaries, Postgres and a local fake Access signer."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import psycopg
from aiohttp.test_utils import TestClient, TestServer

from test_app_chat import AUD, HK_EMAIL, ORIGIN, STRANGER, TEAM, Certs, auth, prepare, problem
from marong.access import AccessConfig, AccessVerifier
from marong.agent import Agent, Incoming
from marong.app_chat import AppChat
from marong.diary import KST, diary_day
from marong.discord_store import DiscordStore
from pg import TestDB

PREFIX = "/chat/diary/api"
DRAWING = "10000000-0000-0000-0000-000000000003"
OTHER_DRAWING = "10000000-0000-0000-0000-000000000004"


def fixtures(db):
    db.admin("""
        INSERT INTO marong.diary_settings(friend_id,enabled,from_date) VALUES (2,true,'2026-11-17');
        INSERT INTO marong.diaries(friend_id,diary_date) VALUES
            (2,'2026-11-14'),(2,'2026-11-15'),(2,'2026-11-17'),(1,'2026-11-13');
        INSERT INTO marong.diary_revisions(diary_id,revision,source,title,weather,body,scene)
            SELECT id,1,'weather',CASE WHEN friend_id=2 THEN '시험 일기' ELSE '비공개 일기' END,
                   'sunny',repeat('밤',60),'hidden-scene-marker' FROM marong.diaries;
        INSERT INTO marong.diary_ai_runs(diary_id,kind,origin,trace_id,model,prompt_version,sent_at,outcome)
            SELECT id,'draw','night','fixture-trace','fixture','fixture',now(),'ok'
            FROM marong.diaries WHERE diary_date IN ('2026-11-15','2026-11-13');
        INSERT INTO marong.diary_drawings(id,diary_id,revision,origin,ai_run_id,format,width,height,image)
            SELECT CASE WHEN d.friend_id=2 THEN '10000000-0000-0000-0000-000000000003'::uuid
                        ELSE '10000000-0000-0000-0000-000000000004'::uuid END,
                   d.id,1,'night',r.id,'webp',1024,768,decode('52494646','hex')
            FROM marong.diaries d JOIN marong.diary_ai_runs r ON r.diary_id=d.id;
        UPDATE marong.diaries d SET state='ready',revision=1,ready_at=now(),
            hidden=(d.diary_date='2026-11-15'),
            drawing_id=(SELECT id FROM marong.diary_drawings g WHERE g.diary_id=d.id);
    """, None)


async def check_look(http, db, store):
    card = {"hair": "long", "glasses": "round", "top": "navy"}
    path = PREFIX + "/look"
    h = auth(write=True)

    async def request(method, headers):
        return await http.request(method, path, headers=headers, **({"json": card} if method == "PUT" else {}))

    db.admin("INSERT INTO marong.diary_looks(friend_id,hair,glasses,top) VALUES (1,'short','square','black')")
    empty = await request("GET", h)
    assert empty.status == 200 and empty.headers["Cache-Control"] == "no-store"
    assert await empty.json() == {"look": None}
    for method in ("GET", "PUT", "DELETE"):
        await problem(await request(method, {"Origin": ORIGIN}), 401, "unauthenticated")
        await problem(await request(method, auth(STRANGER, write=True)), 403, "not_allowed")
    db.admin("UPDATE marong.discord_dm_links SET channel_id=NULL,last_incoming_at=NULL WHERE friend_id=2")
    for method in ("GET", "PUT", "DELETE"):
        await problem(await request(method, h), 403, "no_dm")
    db.admin("UPDATE marong.discord_dm_links SET channel_id='200000000000000010',last_incoming_at=now() WHERE friend_id=2")
    for method in ("PUT", "DELETE"):
        await problem(await request(method, auth(write=True, origin="https://other.test")), 403, "cross_site")
    for invalid in ({**card, "hair": "arbitrary"}, {"hair": "long"}, {**card, "top": ["navy"]},
                    {**card, "friend_id": 1}):
        await problem(await http.put(path, headers=h, json=invalid), 400, "invalid_request")
    assert await (await request("GET", h)).json() == {"look": None}
    saved = await request("PUT", h)
    assert saved.status == 200 and await saved.json() == {"look": card}
    assert await (await request("GET", h)).json() == {"look": card}
    other, = db.admin("SELECT hair,glasses,top FROM marong.diary_looks WHERE friend_id=1")
    assert other == ("short", "square", "black")
    for _ in range(2):
        cleared = await request("DELETE", h)
        assert cleared.status == 204 and not await cleared.read()
    assert await (await request("GET", h)).json() == {"look": None}
    assert db.admin("SELECT hair,glasses,top FROM marong.diary_looks WHERE friend_id=2") == [(None, None, None)]
    for error, status, code in ((psycopg.OperationalError("synthetic"), 503, "db_unavailable"),
                                (RuntimeError("synthetic"), 500, "internal")):
        with patch.object(store, "app_login", side_effect=error):
            for method in ("GET", "PUT", "DELETE"):
                await problem(await request(method, h), status, code)


async def check_diary_updates(http, db, store):
    path = PREFIX + "/days/2026-11-17"
    h = auth(write=True)

    async def update(action, data, headers=h, url=path):
        return await http.put(f"{url}/{action}", headers=headers, json=data)

    actions = {"weather": {"weather": "rain", "revision": 1}, "hidden": {"hidden": True},
               "stamp": {"stamped": True}}
    unseen = PREFIX + "/days/2026-11-13"
    for action, data in actions.items():
        await problem(await update(action, data, {"Origin": ORIGIN}), 401, "unauthenticated")
        await problem(await update(action, data, auth(STRANGER, write=True)), 403, "not_allowed")
        await problem(await update(action, data, auth(write=True, origin="https://other.test")), 403, "cross_site")
        await problem(await update(action, data, url=unseen), 409, "not_ready")
        await problem(await update(action, data, url=PREFIX + "/days/2026-02-30"), 400, "invalid_request")
        await problem(await update(action, {**data, "friend_id": 1}), 400, "invalid_request")
        with patch.object(store, "app_login", side_effect=psycopg.OperationalError("synthetic")):
            await problem(await update(action, data), 503, "db_unavailable")
        with patch.object(store, "app_login", side_effect=RuntimeError("synthetic")):
            await problem(await update(action, data), 500, "internal")

    for weather in ([], "wind"):
        await problem(await update("weather", {"weather": weather, "revision": 1}), 400, "invalid_request")
    for action, field in (("hidden", "hidden"), ("stamp", "stamped")):
        await problem(await update(action, {field: 1}), 400, "invalid_request")
    await problem(await update("weather", {"weather": "rain", "revision": True}), 400, "invalid_request")
    db.admin("UPDATE marong.diaries SET busy='fix',busy_until=now()+interval '5 minutes' "
             "WHERE friend_id=2 AND diary_date='2026-11-17'")
    await problem(await update("weather", actions["weather"]), 409, "busy")
    db.admin("UPDATE marong.diaries SET busy_until=now()-interval '1 second',fixes_used=1,notice_state='waiting',"
             "notice_next_at=now() WHERE friend_id=2 AND diary_date='2026-11-17'")
    same = await update("weather", {"weather": "sunny", "revision": 1})
    assert same.status == 200 and (await same.json())["diary"]["revision"] == 1
    results = await asyncio.gather(update("weather", actions["weather"]), update("weather", actions["weather"]))
    accepted, stale = sorted(results, key=lambda result: result.status)
    assert accepted.status == 200
    body = (await accepted.json())["diary"]
    assert body["revision"] == 2 and body["weather"] == "rain" and body["fix"]["left"] == 4
    await problem(stale, 409, "stale_revision")
    assert db.admin("SELECT r.source,r.weather,r.scene FROM marong.diary_revisions r JOIN marong.diaries d "
                    "ON d.id=r.diary_id WHERE d.friend_id=2 AND d.diary_date='2026-11-17' ORDER BY r.revision") == [
        ("weather", "sunny", "hidden-scene-marker"), ("weather", "rain", "hidden-scene-marker")]
    repeated = await update("weather", {"weather": "rain", "revision": 2})
    assert repeated.status == 200 and (await repeated.json())["diary"] == body

    first = (await (await update("stamp", actions["stamp"])).json())["diary"]["stampedAt"]
    second = (await (await update("stamp", actions["stamp"])).json())["diary"]["stampedAt"]
    assert first and first == second
    month = await (await http.get(PREFIX + "/days?month=2026-11", headers=h)).json()
    assert month["days"][-1] == {"date": "2026-11-17", "weather": "rain", "stamped": True}
    for _ in range(2):
        hidden = await update("hidden", actions["hidden"])
        assert hidden.status == 200 and (await hidden.json())["diary"]["hidden"]
    day = await (await http.get(PREFIX + "/days/2026-11-14", headers=h)).json()
    assert day["next"] is None
    month = await (await http.get(PREFIX + "/days?month=2026-11", headers=h)).json()
    assert [day["date"] for day in month["days"]] == ["2026-11-14"]
    assert db.admin("SELECT notice_state,notice_next_at FROM marong.diaries "
                    "WHERE friend_id=2 AND diary_date='2026-11-17'") == [("cancelled", None)]
    shown = await update("hidden", {"hidden": False})
    assert shown.status == 200 and not (await shown.json())["diary"]["hidden"]
    assert (await (await update("stamp", {"stamped": False})).json())["diary"]["stampedAt"] is None


async def check_stamp_context(db, store):
    user = {"friend_id": 2, "name": "시험친구"}
    room, kakao, user_key = db.admin("SELECT room_key,kakao_room_key,user_key FROM marong.discord_dm_links "
                                    "WHERE friend_id=2")[0]
    assert room and kakao
    agent = SimpleNamespace(store=store)
    now = datetime.now(KST)
    expected = "- 시험친구가 11월 17일 마롱이 일기에 도장을 찍어 줬어(일기 내용은 여기 없어. 자연스러울 때만 고마워해도 돼)"
    for age, hidden, wanted in ((23, False, expected), (25, False, ""), (1, True, ""), (None, False, "")):
        db.admin("UPDATE marong.diaries SET stamped_at=%s,hidden=%s WHERE friend_id=2 AND diary_date='2026-11-17'",
                 (now - timedelta(hours=age) if age is not None else None, hidden))
        for key in (room, kakao):
            msg = Incoming(room_key=key, user_key=user_key, text="안녕")
            assert await Agent._diary_stamp(agent, msg, user) == wanted
    db.admin("UPDATE marong.diaries SET stamped_at=now() WHERE friend_id=2 AND diary_date='2026-11-17'")
    no_stamp = (
        (Incoming(room_key=room, user_key=user_key, text="안녕", is_channel=False), user),
        (Incoming(room_key="fixture-other", user_key=user_key, text="안녕"), user),
        (Incoming(room_key=room, user_key=user_key, text="안녕"), {"friend_id": 1, "name": "다른친구"}),
    )
    for msg, person in no_stamp:
        assert await Agent._diary_stamp(agent, msg, person) == ""

    msg = Incoming(room_key=room, user_key=user_key, text="안녕")

    async def slow_read(*args):
        await asyncio.sleep(10)

    with patch("marong.agent.recent_stamp", side_effect=slow_read):
        assert await asyncio.wait_for(Agent._diary_stamp(agent, msg, user), 0.8) == ""
    with patch("marong.agent.recent_stamp", side_effect=psycopg.OperationalError("synthetic")):
        assert await Agent._diary_stamp(agent, msg, user) == ""
    db.admin("INSERT INTO marong.diary_settings(friend_id,enabled,from_date) VALUES (2,false,%s)", (diary_day(now),))
    assert await Agent._diary_stamp(agent, msg, user) == ""


async def run(db):
    certs = Certs()
    client = httpx.AsyncClient(transport=httpx.MockTransport(certs))
    config = AccessConfig(TEAM, AUD, frozenset({HK_EMAIL}))
    store = DiscordStore(db.app_url, call_bridge=True)
    await store.open(wait=True)
    chat = AppChat(store, None, None, AccessVerifier(config, client), None, origin=ORIGIN)
    paths = ("/latest", "/days?month=2026-11", "/days/2026-11-15", "/hidden", f"/drawings/{DRAWING}")
    try:
        async with TestClient(TestServer(chat.web_app())) as http:
            home = await http.get("/chat/diary/")
            dated = await http.get("/chat/diary/2026-11-17")
            assert home.status == dated.status == 200
            assert (await home.read()) == (await dated.read())
            for file, content_type in (("diary.js", "text/javascript"), ("sheets.js", "text/javascript"),
                                       ("diary.css", "text/css"), ("tokens.css", "text/css"),
                                       ("Gaegu-Regular.woff2", "font/woff2")):
                asset = await http.get("/chat/diary/" + file)
                assert asset.status == 200 and asset.content_type == content_type and await asset.read()

            async def get(path, headers=None):
                return await http.get(PREFIX + path, headers=headers or {})

            h = auth()
            for path in paths:
                await problem(await get(path), 401, "unauthenticated")
                await problem(await get(path, auth(STRANGER)), 403, "not_allowed")
            db.admin("UPDATE marong.discord_dm_links SET channel_id=NULL,last_incoming_at=NULL WHERE friend_id=2")
            for path in paths:
                await problem(await get(path, h), 403, "no_dm")
            db.admin("UPDATE marong.discord_dm_links SET channel_id='200000000000000010',last_incoming_at=now() WHERE friend_id=2")

            for path in paths[:-1]:
                r = await get(path, h)
                assert r.status == 200 and r.headers["Cache-Control"] == "no-store"
                assert "hidden-scene-marker" not in await r.text()
            assert await (await get("/latest", h)).json() == {"date": "2026-11-17", "enabled": True}
            month = await (await get("/days?month=2026-11", h)).json()
            assert month == {"month": "2026-11", "days": [
                {"date": "2026-11-14", "weather": "sunny", "stamped": False},
                {"date": "2026-11-17", "weather": "sunny", "stamped": False},
            ]}
            hidden = await (await get("/hidden", h)).json()
            assert hidden == {"items": [{"date": "2026-11-15", "title": "시험 일기"}], "nextBefore": None}
            assert await (await get("/hidden?before=2026-11-15", h)).json() == {"items": [], "nextBefore": None}
            day = await (await get("/days/2026-11-15", h)).json()
            assert day["state"] == "ready" and day["diary"]["hidden"]
            assert (day["prev"], day["next"]) == ("2026-11-14", "2026-11-17")
            assert day["diary"]["drawing"] == {"id": DRAWING, "kind": "ai"}
            for missing in ("/days/2026-11-13", "/days/2031-11-12"):
                item = await (await get(missing, h)).json()
                assert item["state"] == "none" and item["diary"] is None

            r = await get(f"/drawings/{DRAWING}", h)
            assert r.status == 200 and r.headers["Content-Type"] == "image/webp" and await r.read() == b"RIFF"
            assert r.headers["Cache-Control"] == "private, max-age=31536000, immutable"
            for nosuch in (OTHER_DRAWING, "40000000-0000-0000-0000-000000000000", "invalid"):
                await problem(await get(f"/drawings/{nosuch}", h), 404, "not_found")
            for path in ("/days?month=2026-13", "/days/2026-02-30", "/hidden?before=wrong"):
                await problem(await get(path, h), 400, "invalid_request")
            for error, status, code in ((psycopg.OperationalError("synthetic"), 503, "db_unavailable"),
                                        (RuntimeError("synthetic"), 500, "internal")):
                with patch.object(store, "app_login", side_effect=error):
                    for path in paths:
                        await problem(await get(path, h), status, code)
            await check_look(http, db, store)
            await check_diary_updates(http, db, store)
            await check_stamp_context(db, store)
    finally:
        await client.aclose()
        await store.close()


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        fixtures(db)
        asyncio.run(run(db))
    finally:
        db.close()
    print("TC-166, TC-169, TC-170 API and TC-171 stamp context verified")
