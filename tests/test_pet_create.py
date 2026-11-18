"""Disposable PostgreSQL and synthetic fixtures for TC-394–397."""

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
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from marong.pet.creations import cleanup
from marong.pet.http import COOKIE, POOL, cookie_hash
from marong.pet.photos import MASK, load_detector, sanitize
from marong.pet.settings import Settings
from marong.pet.traits import next_traits
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
        original = Path(face_path).read_bytes()
        photo = sanitize(original, 1, detector)
        assert photo.faces == 1, "expected only the public human face to be masked"
        with Image.open(BytesIO(original)) as raw, Image.open(BytesIO(photo.png)) as clean:
            pet_area = (512, 384, 640, 512)
            assert clean.crop(pet_area).tobytes() == raw.crop(pet_area).tobytes()
    if pet_dir:
        paths = sorted(path for path in Path(pet_dir).iterdir() if path.is_file())
        assert len(paths) == 20
        masked = 0
        for path in paths:
            with Image.open(path) as raw:
                masked += bool(detector(raw.convert("RGB")))
        print(f"TC-395: false masks on {masked} of {len(paths)} public pet photos")


TRAITS = {
    "species": "dog", "breedGuess": "푸들", "coatColors": ["갈색"], "pattern": "단색",
    "patternNotes": "", "earShape": "늘어진 귀", "eyeColor": "갈색", "build": "작음",
    "furLength": "곱슬", "distinctive": "", "petVisible": True, "multiplePets": True,
    "confidence": "medium",
}


async def check_traits(admin, dsn, directory):
    with psycopg.connect(admin) as conn:
        # Only the fixtures from this case are eligible for this worker in the disposable database.
        conn.execute("DELETE FROM pet.jobs WHERE kind='traits'")
        accounts = [add_member(conn) for _ in range(5)]
        outsider_id, outsider = add_member(conn)
    settings = Settings.read({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "50000",
                              "PET_ORIGIN": ORIGIN, "PET_MEDIA_DIR": str(directory)})
    app = make_app(settings, face_detector=lambda image: [])
    raw = photo_file()
    async with TestClient(TestServer(app)) as client:
        pool = app[POOL]

        async def request(method, path, token, status, **data):
            response = await client.request(method, path, headers=headers(token), **data)
            body = await response.json()
            assert response.status == status, body
            return body

        async def extract(photos, job):
            assert job["kind"] == "traits"
            assert len(photos) == 3
            for png in photos:
                with Image.open(BytesIO(png)) as image:
                    assert image.format == "PNG" and not image.getexif() and not image.info
            return TRAITS

        member, token = accounts[0]
        result = await request("POST", "/api/creations", token, 202, data=form([raw] * 3))
        path = "/api/creations/" + result["id"]
        assert (await request("GET", path, token, 200))["state"] == "photos"
        assert (await request("PATCH", path + "/traits", token, 409, json={"build": "긴 몸"}))["code"] == "wrong_state"
        assert (await request("GET", path, outsider, 404))["code"] == "not_found"
        assert (await request("GET", "/api/creations/nope", token, 400))["code"] == "invalid_input"
        assert (await request("GET", "/api/creations", outsider, 200))["items"] == []
        assert await next_traits(pool, directory, extract)
        traits = await request("GET", path, token, 200)
        assert traits["state"] == "traits" and traits["multiplePets"]
        assert not {"confidence", "petVisible", "multiplePets"} & traits["traits"].keys()
        assert traits["traits"]["coatColors"] == ["갈색"]
        for bad in ({"build": "unknown"}, {"coatColors": ["갈색", "갈색"]}, {"breedGuess": "x" * 31},
                    {"multiplePets": False}):
            assert (await request("PATCH", path + "/traits", token, 400, json=bad))["code"] == "invalid_input"
        assert (await request("PATCH", path + "/traits", outsider, 404, json={"build": "긴 몸"}))["code"] == "not_found"
        revised = await request("PATCH", path + "/traits", token, 200, json={"build": "긴 몸"})
        assert revised["traits"]["build"] == "긴 몸" and revised["traits"]["breedGuess"] == "푸들"
        confirmed = await request("POST", path + "/confirm-traits", token, 200)
        assert confirmed["state"] == "traits_confirmed" and confirmed["template"] == "dog_long"
        assert (await request("POST", path + "/confirm-traits", token, 409))["code"] == "wrong_state"
        assert (await request("GET", "/api/creations", token, 200))["items"] == [confirmed]

        preview = uuid4()
        preview_path = directory / str(preview)
        preview_path.write_bytes(b"synthetic preview fixture")
        with psycopg.connect(admin) as conn:
            conn.execute("""INSERT INTO pet.media(id,member_id,creation_id,kind,storage_key,content_type,bytes,sha256)
                VALUES (%s,%s,%s,'preview',%s,'image/png',%s,%s)""",
                         (preview, member, result["id"], str(preview), preview_path.stat().st_size,
                          sha256(preview_path.read_bytes()).digest()))
            conn.execute("""UPDATE pet.creations SET state='previewed',preview_id=%s,expires_at=now()-interval '1 s'
                WHERE id=%s""", (preview, result["id"]))
        assert (await request("GET", path, token, 200))["preview"] == f"/api/media/{preview}"
        await cleanup(pool, directory)
        assert not preview_path.exists() and not list(directory.glob("photos/*.png"))
        expired = await request("GET", path, token, 200)
        assert (expired["state"], expired["failure"], expired["preview"]) == ("expired", "expired", None)
        assert (await request("GET", "/api/creations", token, 200))["items"] == []

        for account, changes, expected, attempts in zip(
            accounts[1:],
            [{"species": "other"}, {"petVisible": False}, {"build": "invalid"}, None],
            [("rejected", "not_dog_or_cat"), ("rejected", "pet_not_visible"),
             ("failed_traits", "traits_failed"), ("failed_traits", "traits_failed")],
            [1, 1, 2, 2],
        ):
            _, token = account
            queued = await request("POST", "/api/creations", token, 202, data=form([raw]))
            path = "/api/creations/" + queued["id"]
            calls = 0

            async def scripted(photos, _job):
                assert len(photos) == 1
                nonlocal calls
                calls += 1
                if changes is None:
                    await asyncio.sleep(1)
                return {**TRAITS, **changes}

            for _ in range(attempts):
                assert await next_traits(pool, directory, scripted, timeout=0.08)
            got = await request("GET", path, token, 200)
            assert (got["state"], got["failure"]) == expected and calls == attempts
            await cleanup(pool, directory)
            assert not list(directory.glob("photos/*.png"))
        assert not await next_traits(pool, directory, extract)
        assert (await request("GET", "/api/creations/" + str(outsider_id), outsider, 404))["code"] == "not_found"
        states = ("photos", "traits", "traits_confirmed", "previewed", "paid", "candidates", "chosen",
                  "sheet_ready", "done", "sheet_needs_operator", "rejected", "failed_traits",
                  "failed_candidates", "expired")
        with psycopg.connect(admin) as conn:
            state_ids = [
                conn.execute("""INSERT INTO pet.creations(member_id,kind,state,template)
                    VALUES (%s,'living',%s,'dog_small') RETURNING id""",
                             (outsider_id, expected)).fetchone()[0]
                for expected in states
            ]
        for expected, ident in zip(states, state_ids):
            assert (await request("GET", f"/api/creations/{ident}", outsider, 200))["state"] == expected


async def check_vision_adapter():
    from base64 import b64decode
    import json
    from types import SimpleNamespace
    from marong.pet.vision import VisionExtractor

    hits = []
    recorded = []

    async def endpoint(req):
        assert req.headers["x-api-key"] == "fixture-only"
        body = await req.json()
        hits.append(body)
        assert body.keys() == {"model", "max_tokens", "messages", "output_config"}
        assert body["output_config"]["effort"] == "medium"
        assert body["output_config"]["format"]["type"] == "json_schema"
        source = body["messages"][0]["content"][0]["source"]
        assert source["media_type"] == "image/png"
        with Image.open(BytesIO(b64decode(source["data"]))) as image:
            assert not image.getexif() and not image.info
        return web.json_response({"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(TRAITS)}],
                                  "usage": {"input_tokens": 42, "output_tokens": 13}})

    async def record(run):
        recorded.append(run)

    fake = web.Application()
    fake.router.add_post("/v1/messages", endpoint)
    async with TestClient(TestServer(fake)) as client:
        with patch("marong.pet.vision.ENDPOINT", str(client.make_url("/v1/messages"))):
            extract = VisionExtractor(client.session, "fixture-only", SimpleNamespace(vision_model="fixture"),
                                      SimpleNamespace(record=record))
            assert await extract([photo_file("PNG")], {"id": uuid4(), "member_id": uuid4()}) == TRAITS
    assert len(hits) == 1 and len(recorded) == 1
    assert (recorded[0].entry, recorded[0].result, recorded[0].input_tokens) == ("AI-30", "ok", 42)


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
        with tempfile.TemporaryDirectory() as path:
            asyncio.run(check_traits(admin, dsn, Path(path)))
        asyncio.run(check_vision_adapter())
    finally:
        db.close()
    print("TC-394–395: upload contract, metadata removal, local masking, limits, transaction and member isolation verified")
    print("TC-396–397: traits, correction, confirmation, retries, owner-only status and preview expiry verified")
