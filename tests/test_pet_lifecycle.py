"""TC-417 and TC-419 against real isolated PostgreSQL and synthetic members."""

import asyncio
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import psycopg
from aiohttp.test_utils import TestClient, TestServer

from marong.pet.http import POOL
from marong.pet.push import notify
from marong.pet.quota import KST, quota_day, reserve
from marong.pet.settings import Settings
from pg import TestDB
from run_pet import make_app
from test_pet_core import fixtures
from test_pet_talk import ORIGIN, add_pet, seed


async def scenario(admin, dsn, root):
    now = datetime(2026, 11, 18, 9, tzinfo=KST)
    setting = Settings.read({"PET_DATABASE_URL": dsn, "PET_ORIGIN": ORIGIN, "PET_MONTHLY_BUDGET_KRW": "10000",
                             "PET_MEDIA_DIR": str(root)})
    with psycopg.connect(admin) as conn:
        member, headers = seed(conn, 1)
        other, outsider = seed(conn, 2)
        pet, sibling, foreign = add_pet(conn, member), add_pet(conn, member), add_pet(conn, other)
        creation, = conn.execute("SELECT creation_id FROM pet.pets WHERE id=%s", (pet,)).fetchone()
        order, = conn.execute("""
            INSERT INTO pet.orders(order_no, member_id, product, creation_id, amount_krw, vat_krw, withdrawal_rule,
                status,idempotency_key)
            VALUES ('synthetic-order',%s,'character_creation',%s,0,0,'fixture','fulfilled',%s) RETURNING id
        """, (member, creation, uuid4())).fetchone()
        conn.execute("INSERT INTO pet.proactive_turns(member_id,pet_id,kind,slot_at,status,draft)"
                     " VALUES (%s,%s,'light',%s,'retry','fixture')", (member, pet, now))
        conn.execute("INSERT INTO pet.jobs(kind,member_id,pet_id) VALUES ('proactive',%s,%s)", (member, pet))
        conn.execute("INSERT INTO pet.push_subscriptions(member_id,endpoint,p256dh,auth)"
                     " VALUES (%s,'https://updates.push.services.mozilla.com/test','fixture','fixture')", (member,))
        media, sibling_media = uuid4(), uuid4()
        for ident, child in ((media, pet), (sibling_media, sibling)):
            key = f"sheet/{ident}.png"
            path = root / key
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"fixture")
            conn.execute("""
                INSERT INTO pet.media(id,member_id,pet_id,kind,storage_key,content_type,bytes,sha256)
                VALUES (%s,%s,%s,'sheet_front',%s,'image/png',7,%s)
            """, (ident, member, child, key, sha256(b"fixture").digest()))
        diary, = conn.execute(
            "INSERT INTO pet.diary_entries(member_id,pet_id,day,title,status) VALUES (%s,%s,%s,'fixture','ready') RETURNING id",
            (member, pet, now.date()),
        ).fetchone()
    app = make_app(setting, lifecycle_clock=lambda: now, chat_clock=lambda: now)
    path = f"/api/pets/{pet}"

    async def fake_push(*_args):
        raise AssertionError("memorial pet sent a diary notification")

    async with TestClient(TestServer(app)) as client:
        async def request(method, endpoint, code, *, data=None, actor=headers):
            result = await client.request(method, endpoint, headers=actor, **({"json": data} if data else {}))
            assert result.status == code, (method, endpoint, result.status, await result.text())
            return await result.json() if result.status != 204 else None

        assert (await request("POST", path + "/archive", 409))["code"] == "not_memorial"
        await request("POST", path + "/mode", 404, data={"mode": "memorial"}, actor=outsider)
        await request("POST", path + "/mode", 403, data={"mode": "memorial"},
                      actor={**headers, "Origin": "https://outside.test"})
        await request("POST", path + "/mode", 400, data={"mode": "memorial", "passedOn": "2026-02-30"})
        first = await request("POST", path + "/mode", 200, data={"mode": "memorial", "passedOn": "2026-11-11"})
        assert first["mode"] == "memorial" and first["passedOn"] == "2026-11-11"
        assert not first["shopEntry"] and not first["rechargePrompt"]
        assert first == await request("POST", path + "/mode", 200, data={"mode": "memorial"})
        assert await notify(app[POOL], member, pet, "diary", send=fake_push) == 0
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT status,draft FROM pet.proactive_turns WHERE pet_id=%s", (pet,)).fetchone() == ("dropped", None)
            assert conn.execute("SELECT status,lease_until FROM pet.jobs WHERE pet_id=%s", (pet,)).fetchone() == ("canceled", None)
        now += timedelta(days=6)
        assert (await request("POST", path + "/mode", 200, data={"mode": "living"}))["passedOn"] is None
        await request("POST", path + "/mode", 200, data={"mode": "memorial"})
        now += timedelta(days=7)
        assert (await request("POST", path + "/mode", 409, data={"mode": "living"}))["code"] == "revert_window_passed"
        async with app[POOL].connection() as conn, conn.transaction():
            hold, error = await reserve(conn, member, "new_picture", at=now, diary=diary, memorial=True)
            assert hold and error is None
            await conn.execute("INSERT INTO pet.jobs(kind,member_id,pet_id) VALUES ('redraw',%s,%s)", (member, pet))
        archived = await request("POST", path + "/archive", 200)
        assert archived["status"] == "archived" and archived["revertUntil"] is None
        assert archived == await request("POST", path + "/archive", 200)
        await request("POST", path + "/mode", 409, data={"mode": "living"})
        msg = {"text": "fixture message", "clientId": str(uuid4())}
        assert (await request("POST", path + "/messages", 409, data=msg))["code"] == "archived"
        assert (await request("POST", path + "/unarchive", 200))["status"] == "active"
        await request("POST", path + "/messages", 201, data=msg)
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT status FROM pet.quota_holds WHERE id=%s", (hold,)).fetchone() == ("released",)
            assert conn.execute("SELECT used_units FROM pet.member_days WHERE member_id=%s AND day=%s",
                                (member, quota_day(now))).fetchone() == (0,)
        await request("DELETE", path, 404, data={"confirm": "콩이"}, actor=outsider)
        assert (await request("DELETE", path, 400, data={"confirm": "다른이름"}))["code"] == "confirm_required"
        await request("DELETE", path, 204, data={"confirm": "콩이"})
        await request("GET", path, 404)
        await request("GET", f"/api/media/{media}", 404)
        await request("GET", f"/api/pets/{sibling}", 200)
        deleted = root / "sheet" / f"{media}.png"
        async with asyncio.timeout(8):
            while deleted.exists():
                await asyncio.sleep(.05)
        assert (root / "sheet" / f"{sibling_media}.png").is_file()
        with psycopg.connect(admin) as conn:
            for table in ("messages", "diary_entries", "media", "proactive_turns"):
                assert conn.execute(f"SELECT count(*) FROM pet.{table} WHERE pet_id=%s", (pet,)).fetchone() == (0,)
            assert conn.execute("SELECT creation_id,member_id FROM pet.orders WHERE id=%s", (order,)).fetchone() == (None, member)
            assert conn.execute("SELECT count(*) FROM pet.pets WHERE id IN (%s,%s)", (sibling, foreign)).fetchone() == (2,)


if __name__ == "__main__":
    db = TestDB()
    try:
        with TemporaryDirectory() as media:
            asyncio.run(scenario(*fixtures(db), Path(media)))
    finally:
        db.close()
    print("TC-417/419: lifecycle, pending message gate, quota release, owner-only deletion and retained order")
