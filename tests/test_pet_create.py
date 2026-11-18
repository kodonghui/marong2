"""Disposable PostgreSQL and in-memory photo fixtures for TC-394 and TC-395."""

import argparse
import asyncio
import tempfile
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from secrets import token_urlsafe
from unittest.mock import patch
from uuid import uuid4

import psycopg
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from marong.pet.http import COOKIE, cookie_hash
from marong.pet.photos import MASK, MAX_PHOTO, load_detector
from marong.pet.settings import Settings
from pg import TestDB
from run_pet import make_app
from test_pet_core import fixtures

ORIGIN = "https://pet.example.test"


def photo_file(image_format="JPEG", size=(161, 120)):
    output = BytesIO()
    image = Image.new("RGB", size, color=(25, 95, 155))
    options = {}
    if image_format == "JPEG":
        exif = Image.Exif()
        exif[274] = 6
        exif[270] = "synthetic metadata marker"
        exif[34853] = {1: "N", 2: (37.0, 0.0, 0.0)}
        options["exif"] = exif
    image.save(output, format=image_format, **options)
    return output.getvalue()


def add_member(conn, *, consent=True, creations=0, pets=0):
    token = token_urlsafe(32)
    member = uuid4()
    conn.execute("""INSERT INTO pet.members(id,member_no,provider,sub_hash,adult_self_declared_at)
        VALUES (%s,%s,'google',%s,now())""",
                 (member, member.hex[:8].upper(), sha256(token.encode()).digest()))
    conn.execute("""INSERT INTO pet.sessions(token_hash,kind,member_id,expires_at,absolute_expires_at)
        VALUES (%s,'member',%s,now()+interval '1 day',now()+interval '3 days')""",
                 (cookie_hash(token), member))
    if consent:
        conn.execute("""INSERT INTO pet.consents(member_id,kind,doc_version,value)
            VALUES (%s,'overseas_transfer','fixture',true)""", (member,))
    for _ in range(creations):
        conn.execute("INSERT INTO pet.creations(member_id,kind) VALUES (%s,'living')", (member,))
    for _ in range(pets):
        created = conn.execute("""INSERT INTO pet.creations(member_id,kind,state,template)
            VALUES (%s,'living','done','dog_small') RETURNING id""", (member,)).fetchone()[0]
        conn.execute("""INSERT INTO pet.pets(member_id,creation_id,name,intro,species,template,sheet,mode)
            VALUES (%s,%s,'fixture','{}','dog','dog_small',
            '{"front":null,"smile":null,"excited":null,"sleepy":null,
              "surprised":null,"sad":null,"pout":null}','living')""", (member, created))
    return member, token


def form(photos, kind="living"):
    payload = FormData(default_to_multipart=True)
    payload.add_field("kind", kind)
    for raw in photos:
        payload.add_field("photos", raw, filename="fixture.jpg", content_type="image/jpeg")
    return payload


def headers(token=None, *, origin=ORIGIN):
    result = {"Origin": origin}
    if token:
        result["Cookie"] = f"{COOKIE}={token}"
    return result


async def check_upload(admin, dsn, directory):
    with psycopg.connect(admin) as conn:
        owner, permitted = add_member(conn)
        _, no_consent = add_member(conn, consent=False)
        _, limit_pets = add_member(conn, pets=5)
        _, limit_open = add_member(conn, creations=3)
        _, limit_combined = add_member(conn, pets=3, creations=2)
        racer, concurrent = add_member(conn, creations=2)
    settings = Settings.read({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "50000",
                              "PET_ORIGIN": ORIGIN, "PET_MEDIA_DIR": str(directory)})

    raw = photo_file()
    calls = 0

    def face_boxes(image):
        nonlocal calls
        calls += 1
        assert not image.getexif()
        assert not image.info
        return [(20.0, 30.0, 20.0, 30.0)]

    async with TestClient(TestServer(make_app(settings, face_detector=face_boxes))) as client:
        async def expect(status, code, photos, token=permitted, *, origin=ORIGIN, kind="living", number=None):
            response = await client.post("/api/creations", headers=headers(token, origin=origin),
                                         data=form(photos, kind))
            body = await response.json()
            assert (response.status, body.get("code")) == (status, code), body
            if number is not None:
                assert body["photo"] == number and f"{number}번째" in body["detail"]
            return body

        await expect(401, "unauthenticated", [raw], None)
        await expect(403, "cross_site", [raw], origin="https://example.test")
        await expect(409, "consent_required", [raw], no_consent)
        await expect(409, "pet_limit", [raw], limit_pets)
        await expect(409, "pet_limit", [raw], limit_combined)
        await expect(409, "too_many_creations", [raw], limit_open)
        await expect(400, "invalid_input", [])
        await expect(400, "invalid_input", [raw], kind="bad")
        await expect(400, "invalid_input", [raw] * 4)
        await expect(400, "invalid_photo", [raw, photo_file("GIF")], number=2)
        await expect(400, "invalid_photo", [b"x" * (9 * 1024 * 1024)], number=1)
        await expect(400, "invalid_photo", [photo_file("PNG", (5000, 1))], number=1)
        await expect(413, "too_large", [b"x" * (26 * 1024 * 1024)])
        assert list(directory.iterdir()) == []

        with patch("marong.pet.photos.os.open", side_effect=OSError("fixture disk error")):
            await expect(500, "server_error", [raw])
        assert list(directory.glob("**/*.png")) == []
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT count(*) FROM pet.creations WHERE member_id=%s", (owner,)).fetchone() == (0,)

        result = await expect(202, None, [raw] * 3, kind="memorial")
        assert result.keys() == {
            "id", "kind", "state", "traits", "multiplePets", "template", "preview", "candidates",
            "chosenId", "regenerationsLeft", "failure", "priceKrw", "petId", "createdAt", "expiresAt",
        }
        assert result["state"] == "photos" and result["kind"] == "memorial"
        assert result["priceKrw"] == 5900 and result["regenerationsLeft"] == 2
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT faces_masked FROM pet.creations WHERE id=%s",
                                (result["id"],)).fetchone() == (3,)
            assert conn.execute("SELECT kind,status FROM pet.jobs WHERE creation_id=%s",
                                (result["id"],)).fetchall() == [("traits", "queued")]
            rows = conn.execute("""SELECT id,storage_key,sha256,width,height,meta FROM pet.media
                WHERE creation_id=%s ORDER BY (meta->>'photo')::int""", (result["id"],)).fetchall()
        assert len(rows) == 3
        allowed_paths = set()
        for number, (ident, key, digest, width, height, meta) in enumerate(rows, 1):
            allowed_paths.add(directory / key)
            png = (directory / key).read_bytes()
            assert digest == sha256(png).digest() and meta == {"faces_masked": 1, "photo": number}
            assert (width, height) == (120, 161)
            with Image.open(BytesIO(png)) as clean:
                assert clean.format == "PNG" and not clean.getexif() and not clean.info
                for point in ((16, 24), (43, 65), (20, 30)):
                    assert clean.getpixel(point) == MASK
                for point in ((15, 24), (44, 65), (70, 70)):
                    assert clean.getpixel(point) != MASK
            owner_response = await client.get(f"/api/media/{ident}", headers=headers(permitted))
            stranger_response = await client.get(f"/api/media/{ident}", headers=headers(no_consent))
            assert owner_response.status == 200 and await owner_response.read() == png
            assert stranger_response.status == 404
        assert {path for path in directory.rglob("*") if path.is_file()} == allowed_paths

        replies = await asyncio.gather(*(
            client.post("/api/creations", headers=headers(concurrent), data=form([photo_file("WEBP")]))
            for _ in range(2)
        ))
        assert sorted(response.status for response in replies) == [202, 409]
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT count(*) FROM pet.creations WHERE member_id=%s", (racer,)).fetchone() == (3,)
            assert conn.execute("SELECT count(*) FROM pet.media WHERE member_id=%s", (racer,)).fetchone() == (1,)

    before = calls
    async with TestClient(TestServer(make_app(settings, face_detector=load_detector(str(directory / "absent.onnx"))))) as client:
        failure = await client.post("/api/creations", headers=headers(permitted), data=form([raw]))
        assert failure.status == 503 and (await failure.json())["code"] == "photo_check_unavailable"
    assert calls == before


def check_model(model_path, face_path, pet_dir):
    detector = load_detector(model_path)
    assert detector is not None
    if face_path:
        with Image.open(face_path) as raw:
            image = raw.convert("RGB")
        assert detector(image), "the configured detector missed the public human face fixture"
    if pet_dir:
        paths = sorted(path for path in Path(pet_dir).iterdir() if path.is_file())
        assert len(paths) == 20
        masked = 0
        for path in paths:
            with Image.open(path) as raw:
                masked += bool(detector(raw.convert("RGB")))
        print(f"TC-395: false masks on {masked} of {len(paths)} public pet photos")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--public-face")
    parser.add_argument("--public-pet-dir")
    args = parser.parse_args()
    assert args.model or not (args.public_face or args.public_pet_dir)
    if args.model:
        check_model(args.model, args.public_face, args.public_pet_dir)
    db = TestDB()
    try:
        admin, dsn = fixtures(db)
        with tempfile.TemporaryDirectory() as path:
            asyncio.run(check_upload(admin, dsn, Path(path)))
    finally:
        db.close()
    print("TC-394–395: upload contract, metadata removal, local masking, limits, transaction and member isolation verified")
