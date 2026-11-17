"""TC-166 with synthetic diaries, Postgres and a local fake Access signer."""

import asyncio
from unittest.mock import patch

import httpx
import psycopg
from aiohttp.test_utils import TestClient, TestServer

from test_app_chat import AUD, HK_EMAIL, ORIGIN, STRANGER, TEAM, Certs, auth, prepare, problem
from marong.access import AccessConfig, AccessVerifier
from marong.app_chat import AppChat
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
    print("TC-166: five diary read routes verified")
