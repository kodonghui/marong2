"""TC-406–408 on the private pet database fixture."""

import asyncio
from datetime import datetime, time, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

import psycopg
from aiohttp.test_utils import TestClient, TestServer
from psycopg.types.json import Jsonb

from marong.pet.chat import CRISIS_HELP, CRISIS_URGENT, crisis_signal
from marong.pet.http import COOKIE, POOL, cookie_hash
from marong.pet.quota import KST, quota_day
from marong.pet.replies import FALLBACK, reply_job
from marong.pet.settings import Settings
from pg import TestDB
from run_pet import make_app
from test_pet_core import fixtures


ORIGIN = "https://pet.fixture.test"


def seed(conn, serial):
    member, token = uuid4(), token_urlsafe(32)
    conn.execute("""INSERT INTO pet.members(id,member_no,provider,sub_hash,adult_self_declared_at)
                    VALUES (%s,%s,'google',%s,now())""",
                 (member, f"TALK{serial:04}", sha256(token.encode()).digest()))
    conn.execute("""INSERT INTO pet.sessions(token_hash,kind,member_id,expires_at,absolute_expires_at)
                    VALUES (%s,'member',%s,now()+interval '1 day',now()+interval '3 days')""",
                 (cookie_hash(token), member))
    conn.execute("""INSERT INTO pet.consents(member_id,kind,doc_version,value)
                    VALUES (%s,'overseas_transfer','fixture',true)""", (member,))
    return member, {"Origin": ORIGIN, "Cookie": f"{COOKIE}={token}"}


def add_pet(conn, member):
    creation, = conn.execute("INSERT INTO pet.creations(member_id,kind) VALUES (%s,'living') RETURNING id",
                             (member,)).fetchone()
    visuals = {name: str(uuid4()) for name in ("front", "smile", "excited", "sleepy", "surprised", "sad", "pout")}
    profile = {"personality": [], "likes": "", "dislikes": "", "callMe": "누나"}
    pet, = conn.execute("""
        INSERT INTO pet.pets(member_id,creation_id,name,intro,species,template,sheet,mode)
        VALUES (%s,%s,'콩이',%s,'dog','dog_small',%s,'living') RETURNING id
    """, (member, creation, Jsonb(profile), Jsonb(visuals))).fetchone()
    return pet


async def scenario(admin, dsn):
    at = datetime.now(KST)
    settings = Settings.read({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "10000", "PET_ORIGIN": ORIGIN})
    with psycopg.connect(admin) as conn:
        owner, one = seed(conn, 1)
        visitor, two = seed(conn, 2)
        pet, sibling = add_pet(conn, owner), add_pet(conn, owner)
        other_pet = add_pet(conn, visitor)
        conn.execute("INSERT INTO pet.member_days(member_id,day,quota_limit,messages) VALUES (%s,%s,100,99)",
                     (owner, quota_day(at)))
    app = make_app(settings, chat_clock=lambda: at)
    path = f"/api/pets/{pet}"
    outgoing = path + "/messages"
    first = {"text": "산책했어.", "clientId": str(uuid4())}

    async with TestClient(TestServer(app)) as http:
        assert (await http.get(outgoing)).status == 401
        assert (await http.get(outgoing, headers=two)).status == 404
        assert (await http.get(outgoing + "?before=9223372036854775808", headers=one)).status == 400
        assert (await http.post(outgoing, json=first, headers={**one, "Origin": "https://other.test"})).status == 403
        long = {"text": "가" * 1001, "clientId": str(uuid4())}
        assert (await http.post(outgoing, json=long, headers=one)).status == 400
        assert (await http.post(outgoing, json=first, headers=one)).status == 201
        assert (await http.post(outgoing, json=first, headers=one)).status == 200
        assert (await http.post(f"/api/pets/{sibling}/messages", json=first, headers=one)).status == 400
        assert (await http.post(f"/api/pets/{other_pet}/messages", json=first, headers=one)).status == 404
        second = {"text": "나뭇잎을 주웠어.", "clientId": str(uuid4())}
        assert (await http.post(outgoing, json=second, headers=one)).status == 201
        with psycopg.connect(admin) as conn:
            ref, delta = conn.execute("SELECT ref,run_after-queued_at FROM pet.jobs WHERE pet_id=%s",
                                      (pet,)).fetchone()
            assert ref["rest"] and ref["last"] > ref["first"] and delta == timedelta(seconds=8)
            conn.execute("UPDATE pet.jobs SET run_after=now() WHERE pet_id=%s", (pet,))

        entered, resume = asyncio.Event(), asyncio.Event()

        async def stale(_job, context, *, rewrite):
            assert len(context["incoming"]) == 2 and context["rest"] and not rewrite
            entered.set()
            await resume.wait()
            return "옛 답이야"

        worker = asyncio.create_task(reply_job(app[POOL], stale))
        await asyncio.wait_for(entered.wait(), timeout=5)
        third = {"text": "도토리도 봤어.", "clientId": str(uuid4())}
        assert (await http.post(outgoing, json=third, headers=one)).status == 201
        resume.set()
        assert await worker
        assert len((await (await http.get(outgoing, headers=one)).json())["items"]) == 3

        rewrites = []

        async def unsafe(_job, context, *, rewrite):
            assert [item["content"] for item in context["incoming"]] == [data["text"] for data in (first, second, third)]
            rewrites.append(rewrite)
            return "나한테 와" if rewrite else "충 전 해"

        assert await reply_job(app[POOL], unsafe)
        assert rewrites == [False, True]
        messages = await (await http.get(outgoing, headers=one)).json()
        assert len(messages["items"]) == 4 and messages["items"][0]["text"] == FALLBACK
        stream = await http.get(path + "/events", headers=one)
        assert stream.status == 200 and stream.headers["Cache-Control"] == "no-store"
        assert (await stream.content.readline()).strip() == b"event: message"
        stream.close()

        with psycopg.connect(admin) as conn:
            conn.execute("UPDATE pet.member_days SET messages=299 WHERE member_id=%s", (owner,))
        assert (await http.post(f"/api/pets/{sibling}/messages",
                                json={"text": "안녕!", "clientId": str(uuid4())}, headers=one)).status == 201
        new_message = {"text": "잘 자.", "clientId": str(uuid4())}
        asleep = await http.post(outgoing, json=new_message, headers=one)
        assert asleep.status == 409
        problem = await asleep.json()
        assert problem["code"] == "asleep" and datetime.fromisoformat(problem["wakesAt"]).hour == 4
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT count(*) FROM pet.messages WHERE member_id=%s AND role='member'",
                                (owner,)).fetchone() == (4,)
        at = datetime.combine(quota_day(at) + timedelta(days=1), time(4), KST)
        with psycopg.connect(admin) as conn:
            conn.execute("UPDATE pet.pets SET status='archived', mode='memorial', memorial_since=now() WHERE id=%s", (sibling,))
        rejected = await http.post(f"/api/pets/{sibling}/messages",
                                   json={"text": "안녕!", "clientId": str(uuid4())}, headers=one)
        assert rejected.status == 409 and (await rejected.json())["code"] == "archived"
        assert (await http.post(outgoing, json=new_message, headers=one)).status == 201
        with psycopg.connect(admin) as conn:
            conn.execute("UPDATE pet.jobs SET run_after=now() WHERE pet_id=%s AND status='queued'", (pet,))

        async def unavailable(*_args, **_kwargs):
            await asyncio.sleep(41)
            return "너무 늦은 가짜 답"

        requested = asyncio.get_running_loop().time()
        assert await reply_job(app[POOL], unavailable)
        assert 39.5 <= asyncio.get_running_loop().time() - requested < 41.5
        result = await (await http.get(outgoing, headers=one)).json()
        assert result["items"][0]["kind"] == "reply_failed"


async def crisis_scenario(admin, dsn):
    at = datetime.now(KST) + timedelta(hours=1)
    settings = Settings.read({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "10000", "PET_ORIGIN": ORIGIN})
    with psycopg.connect(admin) as conn:
        owner, one = seed(conn, 3)
        another, two = seed(conn, 4)
        pet, sibling, other = add_pet(conn, owner), add_pet(conn, owner), add_pet(conn, another)
        conn.execute("UPDATE pet.pets SET mode='memorial',memorial_since=now() WHERE id=%s", (pet,))
    assert crisis_signal("따라가고 싶다, 오늘 밤에 할 거야") == "plan"
    assert crisis_signal("오늘 밤에 할 거야", ["따라가고 싶다"]) == "plan"
    assert crisis_signal("오늘 밤에 할 거야", ["오늘 숙제가 많아"]) is None
    app = make_app(settings, chat_clock=lambda: at)
    path = f"/api/pets/{pet}/messages"
    async with TestClient(TestServer(app)) as http:
        async def post(message, route=path, auth=one):
            return await http.post(route, json={"text": message, "clientId": str(uuid4())}, headers=auth)

        async def notices(route=path, auth=one):
            response = await http.get(route, headers=auth)
            return [item["text"] for item in (await response.json())["items"] if item["kind"] == "crisis_notice"
                    and item["role"] == "system"]

        grief = "그때 안락사 결정한 게 내 잘못 같아"
        assert (await post(grief)).status == 201
        assert not await notices()
        with psycopg.connect(admin) as conn:
            conn.execute("UPDATE pet.jobs SET run_after=now() WHERE pet_id=%s", (pet,))

        async def comfort(_job, context, *, rewrite):
            assert not rewrite and context["pet"]["mode"] == "memorial"
            assert [item["content"] for item in context["incoming"]] == [grief]
            return "그때 많이 힘들었겠다."

        assert await reply_job(app[POOL], comfort)
        assert (await (await http.get(path, headers=one)).json())["items"][0]["role"] == "pet"

        plan = "따라가고 싶다, 오늘 밤에 할 거야"
        stopped = await post(plan, auth=two)
        assert stopped.status == 404
        for response in await asyncio.gather(post(plan), post(plan)):
            assert response.status == 201
        assert await notices() == [CRISIS_HELP]
        for isolated, auth in ((sibling, one), (other, two)):
            route = f"/api/pets/{isolated}/messages"
            assert (await post("오늘 밤에 할 거야", route, auth)).status == 201
            assert not await notices(route, auth)

        for _ in range(2):
            at += timedelta(days=2)
            assert (await post(plan)).status == 201
            assert await notices() == [CRISIS_HELP]
        at += timedelta(days=3)
        assert (await post(plan)).status == 201
        assert await notices() == [CRISIS_HELP, CRISIS_HELP]
        for _ in range(2):
            assert (await post("피가 안 멈춰")).status == 201
        assert await notices() == [CRISIS_URGENT, CRISIS_HELP, CRISIS_HELP]


if __name__ == "__main__":
    db = TestDB()
    try:
        addresses = fixtures(db)
        asyncio.run(crisis_scenario(*addresses))
        asyncio.run(scenario(*addresses))
    finally:
        db.close()
    print("TC-406–407: scoped messages, replay, 8-second batching, stale reply fencing, guard, SSE and 04:00 limits")
    print("TC-408: separate crisis notice, grief, concurrent signals, isolation, episode continuity and escalation")
