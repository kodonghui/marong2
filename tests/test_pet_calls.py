"""TC-416 API portion with the real SQL, a clock and a fake call server."""

import asyncio
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import psycopg
from aiohttp.test_utils import TestClient, TestServer

from marong.pet.calls import CallConfig
from marong.pet.quota import KST, quota_day
from marong.pet.settings import Settings
from pg import TestDB
from run_pet import make_app
from test_pet_core import fixtures
from test_pet_talk import ORIGIN, add_pet, seed


async def scenario(admin, dsn):
    at = datetime(2026, 11, 18, 14, tzinfo=KST)
    online = True
    settings = Settings.read({"PET_DATABASE_URL": dsn, "PET_ORIGIN": ORIGIN,
                              "PET_MONTHLY_BUDGET_KRW": "10000"})
    config = CallConfig("wss://pet.fixture.test/pet-call", "http://127.0.0.1:8091/healthz", "fixture-secret" * 4)
    internal = {"X-Pet-Internal": config.secret}

    async def health(candidate):
        assert candidate is config
        return online

    with psycopg.connect(admin) as conn:
        member, headers = seed(conn, 1)
        other, outsider = seed(conn, 2)
        friend, second, foreign = add_pet(conn, member), add_pet(conn, member), add_pet(conn, other)
        conn.execute("INSERT INTO pet.member_days(member_id,day,quota_limit,used_units) VALUES (%s,%s,100,71)",
                     (member, quota_day(at)))

    def set_used(amount):
        with psycopg.connect(admin) as conn:
            conn.execute("UPDATE pet.member_days SET used_units=%s WHERE member_id=%s AND day=%s",
                         (amount, member, quota_day(at)))

    def snapshot():
        with psycopg.connect(admin) as conn:
            return conn.execute("SELECT used_units FROM pet.member_days WHERE member_id=%s AND day=%s",
                                (member, quota_day(at))).fetchone()[0]

    app = make_app(settings, call_config=config, call_clock=lambda: at, call_available=health)
    async with TestClient(TestServer(app)) as client:
        async def post(path, status, headers, data=None):
            kwargs = {"json": data} if data is not None else {}
            response = await client.post(path, headers=headers, **kwargs)
            assert response.status == status, (path, response.status, await response.text())
            return await response.json() if status != 204 else None

        def start(pet=friend):
            return f"/api/pets/{pet}/calls"

        assert (await post(start(), 409, headers))["code"] == "quota_exhausted"
        assert snapshot() == 71
        await post(start(), 404, outsider)
        await post(start(foreign), 404, headers)
        set_used(70)
        online = False
        assert (await post(start(), 503, headers))["code"] == "call_unavailable"
        assert snapshot() == 70
        online = True
        session = await post(start(), 201, headers)
        assert len(session["token"]) == 43 and session["wsUrl"] == config.websocket
        assert datetime.fromisoformat(session["expiresAt"]) == at + timedelta(seconds=60)
        assert snapshot() == 100
        assert (await post(start(second), 409, headers))["code"] == "call_in_progress"
        await post("/internal/calls/verify", 401, {}, {"token": session["token"]})
        await post("/internal/calls/verify", 400, internal, {"token": "bad"})
        verified = await post("/internal/calls/verify", 200, internal, {"token": session["token"]})
        assert verified["voice"] == "dog" and verified["callId"] == session["callId"]
        assert "instructions" in verified and "instructions" not in session
        await post("/internal/calls/verify", 401, internal, {"token": session["token"]})
        root = "/internal/calls/" + session["callId"]
        await post(root + "/minute", 401, {"X-Pet-Internal": "foreign-credential"})
        await post(f"/internal/calls/{uuid4()}/minute", 404, internal)
        at += timedelta(seconds=60)
        assert (await post(root + "/minute", 200, internal))["status"] == "exhausted"
        assert (await post(root + "/minute", 200, internal))["status"] == "exhausted"
        at += timedelta(seconds=7)
        data = {"reason": "quota", "unchargedMinutes": 1,
                "transcript": [{"role": "member", "text": "합성 통화예요", "at": at.isoformat()}]}
        await post(root + "/end", 204, internal, data)
        await post(root + "/end", 204, internal, data)
        with psycopg.connect(admin) as conn:
            row = conn.execute("SELECT minutes,unbilled_minutes,end_reason FROM pet.calls WHERE id=%s",
                               (UUID(session["callId"]),)).fetchone()
            assert row == (1, 0, "quota")
            assert conn.execute("SELECT count(*) FROM pet.messages WHERE call_id=%s AND kind='call'",
                                (UUID(session["callId"]),)).fetchone() == (1,)
            assert conn.execute("SELECT count(*) FROM pet.ai_runs WHERE pet_id=%s AND entry='AI-35'",
                                (friend,)).fetchone() == (1,)
        set_used(40)
        session = await post(start(), 201, headers)
        root = "/internal/calls/" + session["callId"]
        await post("/internal/calls/verify", 200, internal, {"token": session["token"]})
        at += timedelta(seconds=60)
        assert (await post(root + "/minute", 200, internal))["status"] == "ok"
        at += timedelta(seconds=60)
        # No minute request reached the application during the second minute.
        await post(root + "/end", 204, internal, {"reason": "member", "unchargedMinutes": 1, "transcript": []})
        assert snapshot() == 100
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT minutes FROM pet.calls WHERE id=%s",
                                (UUID(session["callId"]),)).fetchone() == (2,)
        set_used(40)
        abandoned = await post(start(), 201, headers)
        at += timedelta(seconds=61)
        await post("/internal/calls/verify", 401, internal, {"token": abandoned["token"]})
        new = await post(start(), 201, headers)
        assert snapshot() == 70 and new["callId"] != abandoned["callId"]


if __name__ == "__main__":
    db = TestDB()
    try:
        asyncio.run(scenario(*fixtures(db)))
    finally:
        db.close()
    print("TC-416 API: reservation/release, secret and token replay, elapsed billing/retry, private transcript and idempotent end")
