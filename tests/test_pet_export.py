"""TC-420: a real ZIP, guarded download and the daily/expiry gates in a temporary database."""

import asyncio
from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZipFile

import psycopg
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from psycopg.types.json import Jsonb

from marong.pet.artwork import Templates
from marong.pet.quota import KST
from marong.pet.settings import Settings
from pg import TestDB
from run_pet import make_app
from test_pet_core import fixtures
from test_pet_talk import ORIGIN, add_pet, seed


def media_file(conn, root, member, pet, content, kind):
    ident = uuid4()
    path = root / f"{ident}.png"
    conn.execute("""
       INSERT INTO pet.media(id,member_id,pet_id,kind,storage_key,content_type,bytes,sha256)
       VALUES (%s,%s,%s,%s,%s,'image/png',%s,%s)
    """, (ident, member, pet, kind, path.name, len(content), sha256(content).digest()))
    return ident, path


async def scenario(admin, dsn, base):
    at = datetime(2026, 11, 18, 5, tzinfo=KST)
    assets, root = base / "art", base / "media"
    (assets / "backgrounds").mkdir(parents=True)
    root.mkdir()
    Image.new("RGB", (1536, 1024), "#f1e6d6").save(assets / "backgrounds/home_livingroom.webp")
    preview = BytesIO()
    Image.new("RGB", (64, 48), "#fbf6ee").save(preview, "PNG")
    original = Templates().front("dog_small")
    with psycopg.connect(admin) as conn:
        member, headers = seed(conn, 1)
        other, stranger = seed(conn, 2)
        pet, foreign = add_pet(conn, member), add_pet(conn, other)
        front, front_path = media_file(conn, root, member, pet, original, "sheet_front")
        image, image_path = media_file(conn, root, member, pet, preview.getvalue(), "scene")
        image_path.write_bytes(preview.getvalue())
        front_path.write_bytes(original)
        conn.execute("UPDATE pet.pets SET mode='memorial',status='archived',memorial_since=%s,sheet=%s WHERE id=%s",
                     (at, Jsonb({name: str(front) for name in ("front", "smile", "excited", "sleepy",
                                                              "surprised", "sad", "pout")}), pet))
        for index in range(30):
            day = at.date() - timedelta(days=index)
            conn.execute("""
                INSERT INTO pet.diary_entries(member_id,pet_id,day,status,title,body,picture_id,composite)
                VALUES (%s,%s,%s,'ready','fixture','<script>fixture</script>',%s,%s)
            """, (member, pet, day, image if index else None,
                  None if index else Jsonb({"backgroundId": "missing", "expression": "front", "outfit": {}})))
        conn.execute("INSERT INTO pet.messages(member_id,pet_id,role,kind,content,created_at)"
                     " VALUES (%s,%s,'member','chat','우리 집은 시험용이야',%s)", (member, pet, at))
        conn.execute("INSERT INTO pet.messages(member_id,pet_id,role,kind,content,created_at)"
                     " VALUES (%s,%s,'pet','chat','시험이야',%s)", (member, pet, at))
        conn.execute("INSERT INTO pet.messages(member_id,pet_id,role,kind,content)"
                     " VALUES (%s,%s,'member','chat','다른 계정의 시험',now())", (other, foreign))
        conn.execute("INSERT INTO pet.push_subscriptions(member_id,endpoint,p256dh,auth)"
                     " VALUES (%s,'https://updates.push.services.mozilla.com/test','fixture','fixture')", (member,))
    pushes = []

    async def sender(row, payload):
        assert row["member_id"] == member
        pushes.append(payload)
        return 200

    setting = Settings.read({"PET_DATABASE_URL": dsn, "PET_ORIGIN": ORIGIN, "PET_MONTHLY_BUDGET_KRW": "10000",
                             "PET_MEDIA_DIR": str(root)})
    app = make_app(setting, push_sender=sender, export_clock=lambda: at, export_assets=assets)
    async with TestClient(TestServer(app)) as client:
        start = f"/api/pets/{pet}/export"
        assert (await client.post(start, headers=stranger)).status == 404
        opened = await asyncio.gather(*(client.post(start, headers=headers) for _ in range(2)))
        assert sorted(row.status for row in opened) == [202, 429]
        ticket = await next(row for row in opened if row.status == 202).json()
        assert (await next(row for row in opened if row.status == 429).json())["code"] == "export_limit"
        status = f"/api/exports/{ticket['id']}"
        assert (await client.get(status, headers=stranger)).status == 404
        assert (await client.get(status + "/download", headers=stranger)).status == 404
        assert (await client.get(status + "/download")).status == 401
        async with asyncio.timeout(25):
            while True:
                data = await (await client.get(status, headers=headers)).json()
                assert data["status"] != "failed"
                if data["status"] == "done" and pushes:
                    break
                await asyncio.sleep(.15)
        assert len(pushes) == 1 and "내보내기가 끝났어요." in pushes[0]["body"]
        assert datetime.fromisoformat(data["readyUntil"]) == at + timedelta(hours=24)
        download = await client.get(status + "/download", headers=headers)
        assert download.status == 200 and download.headers["Cache-Control"] == "no-store"
        assert download.headers["Content-Disposition"].startswith("attachment;")
        with ZipFile(BytesIO(await download.read())) as bundle:
            assert bundle.testzip() is None
            assert {"pictures/", "diary.html", "chat.txt", "README.txt"} <= set(bundle.namelist())
            diary = bundle.read("diary.html").decode()
            assert diary.count("<article>") == 30 and "<script>" not in diary
            assert "&lt;script&gt;" in diary and 'src="pictures/day-' in diary
            log = bundle.read("chat.txt").decode()
            assert "05:00:00+09:00] 나:" in log and "05:00:00+09:00] 콩이:" in log and "다른 계정" not in log
            images = [name for name in bundle.namelist() if name.endswith(".png")]
            assert len(images) == 37
            for name in images:
                with Image.open(BytesIO(bundle.read(name))) as raster:
                    assert raster.info["AI-Generated"] == "true"
                    assert "trainedAlgorithmicMedia" in raster.info["XML:com.adobe.xmp"]
            with Image.open(BytesIO(bundle.read("pictures/front.png"))) as front_exported:
                assert front_exported.getpixel((973, 995))[3] <= 179
                assert front_exported.crop((800, 935, 1024, 1024)).getbbox() is not None
        assert (await client.post(start, headers=headers)).status == 429
        at += timedelta(hours=25)
        assert (await client.get(status + "/download", headers=headers)).status == 404
        assert (await client.get(status, headers=headers)).status == 404
        assert (await client.post(start, headers=headers)).status == 202


if __name__ == "__main__":
    db = TestDB()
    try:
        with TemporaryDirectory() as folder:
            asyncio.run(scenario(*fixtures(db), Path(folder)))
    finally:
        db.close()
    print("TC-420: 30 diary pages, 37 marked PNGs, archived export, one per day, tenant isolation and 24-hour expiry")
