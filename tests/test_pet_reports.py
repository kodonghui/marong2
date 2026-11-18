"""TC-410 across the reporting HTTP endpoint, digest and operator CLI."""

import asyncio
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer
import psycopg

from marong.pet.cost import KST
from marong.pet.http import POOL
from marong.pet.reports import report_digest
from marong.pet.settings import Settings
from pg import TestDB
from run_pet import make_app
from test_pet_core import fixtures
from test_pet_talk import ORIGIN, add_pet, seed


def admin_cmd(env, *args):
    script = Path(__file__).resolve().parents[1] / "tools/pet_admin.py"
    output = subprocess.run([sys.executable, str(script), "report", *args],
                            env={**os.environ, **env, "PYTHONIOENCODING": "utf-8"},
                            check=True, capture_output=True, encoding="utf-8")
    return output.stdout


async def scenario(admin, dsn):
    env = {"PET_DATABASE_URL": dsn, "PET_ORIGIN": ORIGIN, "PET_MONTHLY_BUDGET_KRW": "10000"}
    at = datetime(2026, 11, 18, 10, tzinfo=KST)
    with psycopg.connect(admin) as conn:
        owner, headers = seed(conn, 1)
        visitor, _ = seed(conn, 2)
        pet, other_pet = add_pet(conn, owner), add_pet(conn, visitor)
        ids = [uuid4() for _ in range(21)]
        for message in ids:
            conn.execute(
                "INSERT INTO pet.messages(id,member_id,pet_id,role,kind,content) VALUES (%s,%s,%s,'pet','chat','fixture')",
                (message, owner, pet),
            )
        foreign, = conn.execute(
            "INSERT INTO pet.messages(member_id,pet_id,role,kind,content) VALUES (%s,%s,'pet','chat','fixture') RETURNING id",
            (visitor, other_pet),
        ).fetchone()
    app = make_app(Settings.read(env), report_clock=lambda: at)
    route = "/api/reports"

    def body(message, reason="hurtful"):
        return {"targetId": str(message), "targetType": "message", "reason": reason, "note": "fixture"}

    async with TestClient(TestServer(app)) as http:
        assert (await http.post(route, json=body(ids[0]), headers={"Origin": ORIGIN})).status == 401
        made, duplicate = await asyncio.gather(*(http.post(route, json=body(ids[0]), headers=headers) for _ in range(2)))
        assert {made.status, duplicate.status} == {200, 201}
        first = (await made.json())["jobId"]
        assert (await duplicate.json())["jobId"] == first
        assert (await http.post(route, json=body(foreign), headers=headers)).status == 404
        assert (await http.post(route, json=body(ids[0], "unknown"), headers=headers)).status == 400
        await asyncio.sleep(0)
        assert await report_digest(app[POOL], at.replace(hour=8, minute=59)) == 0
        tomorrow = at.replace(day=19, hour=9)
        first_digest = await asyncio.gather(report_digest(app[POOL], tomorrow), report_digest(app[POOL], tomorrow))
        assert sorted(first_digest) == [0, 1]
        assert first in admin_cmd(env, "list")
        assert '"text": "fixture"' in admin_cmd(env, "show", first)
        assert first in admin_cmd(env, "resolve", first)
        assert first not in admin_cmd(env, "list")
        assert await report_digest(app[POOL], tomorrow.replace(day=20)) == 0
        for message in ids[1:20]:
            assert (await http.post(route, json=body(message), headers=headers)).status == 201
        limited = await http.post(route, json=body(ids[20]), headers=headers)
        assert limited.status == 429 and (await limited.json())["code"] == "rate_limited"
        at = tomorrow
        assert (await http.post(route, json=body(ids[20]), headers=headers)).status == 201


if __name__ == "__main__":
    db = TestDB()
    try:
        asyncio.run(scenario(*fixtures(db)))
    finally:
        db.close()
    print("TC-410: owner validation, concurrent retry, daily cap, digest and operator commands")
