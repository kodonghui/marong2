"""Disposable PostgreSQL and synthetic fixtures for TC-394–397."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from secrets import token_urlsafe
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import psycopg
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image, ImageDraw
from psycopg.types.json import Jsonb

from marong.pet.creations import cleanup
from marong.pet.billing import deliver, fulfil
from marong.pet.delete import erase_next
from marong.pet.http import COOKIE, POOL, Problem, cookie_hash
from marong.pet.identity import IdentityResult
from marong.pet.photos import MASK, load_detector, sanitize
from marong.pet.pg_fake import FakeGateway
from marong.pet.quota import quota_day
from marong.pet.settings import Settings
from marong.pet.traits import next_traits
from pg import ROOT, TestDB
from run_pet import BUDGET, make_app
from test_pet_core import fixtures
from tools.pet_admin import BUSINESS_FIELDS

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


def preview_fixture(*, opaque=False):
    image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 255 if opaque else 0))
    ImageDraw.Draw(image).ellipse((32, 32, 300, 300), fill=(80, 120, 160, 255))
    data = BytesIO()
    image.save(data, "PNG")
    return data.getvalue()


async def check_preview(admin, dsn, directory):
    with psycopg.connect(admin) as conn:
        member, token = add_member(conn)
        _, stranger = add_member(conn)
        creations = [conn.execute("""
            INSERT INTO pet.creations(member_id,kind,state,template,traits)
            VALUES (%s,'living','traits_confirmed','dog_small',%s) RETURNING id
        """, (member, Jsonb(TRAITS))).fetchone()[0] for _ in range(4)]
    settings = replace(Settings.read({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "50000",
                                      "PET_ORIGIN": ORIGIN, "PET_MEDIA_DIR": str(directory)}),
                       image_model="fixture-primary", image_fallback_model="fixture-secondary")
    mode = "fail"
    received = []
    release_failure = asyncio.Event()

    async def renderer(*, model, template, traits):
        assert template == "dog_small" and traits["coatColors"] == ["갈색"]
        assert "petVisible" not in traits and "multiplePets" not in traits and "confidence" not in traits
        received.append(model)
        if mode == "fail":
            await release_failure.wait()
            return preview_fixture(opaque=True)
        if mode == "fallback" and model == "fixture-primary":
            raise ValueError("fixture provider failure")
        return preview_fixture()

    app = make_app(settings, preview_renderer=renderer)
    async with TestClient(TestServer(app)) as client:
        async def request(ident, status, token=token, *, origin=ORIGIN):
            result = await client.post(f"/api/creations/{ident}/preview", headers=headers(token, origin=origin))
            data = await result.json()
            assert result.status == status, data
            return data

        async def wait_status(ident, *, ok):
            for _ in range(100):
                reply = await client.get(f"/api/creations/{ident}", headers=headers(token))
                data = await reply.json()
                if ok and data["state"] == "previewed" or not ok and data["failure"] == "preview_failed":
                    return data
                await asyncio.sleep(0.05)
            raise AssertionError("preview did not settle")

        first = creations[0]
        assert (await request(first, 401, None))["code"] == "unauthenticated"
        assert (await request(first, 403, origin="https://else.test"))["code"] == "cross_site"
        assert (await request(first, 404, stranger))["code"] == "not_found"
        assert (await request("bad", 400))["code"] == "invalid_input"
        allow = AsyncMock(side_effect=Problem("budget_paused"))
        with patch.object(app[BUDGET], "allow", allow):
            assert (await request(first, 409))["code"] == "budget_paused"

        assert (await request(first, 202))["state"] == "traits_confirmed"
        assert (await request(first, 409))["code"] == "busy"
        release_failure.set()
        assert (await wait_status(first, ok=False))["state"] == "traits_confirmed"
        assert received == ["fixture-primary", "fixture-secondary"]
        day = quota_day(datetime.now(timezone.utc))
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT previews FROM pet.member_days WHERE member_id=%s AND day=%s",
                                (member, day)).fetchone() == (0,)
        assert not list(directory.glob("previews/*.png"))

        mode = "fallback"
        received.clear()
        await request(first, 202)
        art = await wait_status(first, ok=True)
        assert received == ["fixture-primary", "fixture-secondary"] and art["preview"]
        saved = await client.get(art["preview"], headers=headers(token))
        assert saved.status == 200 and saved.headers["Cache-Control"] == "no-store"
        assert (await request(first, 409))["code"] == "wrong_state"
        mode = "success"
        for ident in creations[1:3]:
            await request(ident, 202)
            await wait_status(ident, ok=True)
        limited = await request(creations[3], 429)
        assert limited["code"] == "preview_limit"
        assert datetime.fromisoformat(limited["resetsAt"]).hour == 4


async def check_orders(admin, dsn, directory):
    with psycopg.connect(admin) as conn:
        member, token = add_member(conn)
        _, other = add_member(conn)
        items = [conn.execute("""
            INSERT INTO pet.items(kind,slot,name,price_krw,sellable,license_key,assets)
            VALUES ('wear','head',%s,1200,true,'fixture','{}') RETURNING id
        """, (f"fixture-{n}",)).fetchone()[0] for n in range(3)]
    settings = Settings.read({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "50000",
                              "PET_ORIGIN": ORIGIN, "PET_MEDIA_DIR": str(directory)})
    gateway = FakeGateway(b"synthetic-webhook-secret")
    fail = False

    async def deliver_order(conn, row, at):
        await deliver(conn, row, at)
        if fail:
            raise RuntimeError("fixture post-delivery rollback")

    app = make_app(settings, gateway=gateway, deliver_order=deliver_order)
    async with TestClient(TestServer(app)) as client:
        path = "/api/orders"
        order_body = {"product": "item", "itemId": str(items[0]), "idempotencyKey": str(uuid4())}

        async def post(url, body, status, token=token):
            reply = await client.post(url, headers=headers(token), json=body)
            data = await reply.json()
            assert reply.status == status, data
            return data

        assert (await post(path, order_body, 409))["code"] == "payments_off"
        with psycopg.connect(admin) as conn:
            conn.execute("INSERT INTO pet.settings(key,value) VALUES ('payments_enabled','true')")
        assert (await post(path, order_body, 409))["code"] == "identity_required"
        with psycopg.connect(admin) as conn:
            conn.execute("UPDATE pet.members SET identity_verified_at=now(),identity_ci_hash=%s WHERE id=%s",
                         (sha256(b"synthetic").digest(), member))

        missing = {**order_body, "itemId": str(uuid4())}
        assert (await post(path, missing, 404))["code"] == "not_found"
        replies = await asyncio.gather(post(path, order_body, 201), post(path, order_body, 201))
        assert replies[0] == replies[1]
        first = replies[0]["order"]
        assert replies[0]["pg"]["clientKey"] == gateway.client_key
        assert (first["status"], first["amountKrw"], first["vatKrw"]) == ("created", 1200, 109)
        listing = await client.get(path, headers=headers(other))
        assert (await listing.json())["items"] == []
        confirm_url = f"{path}/{first['id']}/confirm"
        confirmation = {"paymentKey": "fixture-paid-order", "amount": 1200}
        assert (await post(confirm_url, confirmation, 404, other))["code"] == "not_found"
        gateway.add("fixture-paid-order", first["orderNo"], 1200)
        webhook = json.dumps({"eventType": "PAYMENT_STATUS_CHANGED",
                              "data": {"orderNo": first["orderNo"], **confirmation}}).encode()
        hook = "/api/pg/webhook"
        unsigned = await client.post(hook, data=webhook, headers={"Content-Type": "application/json"})
        assert unsigned.status == 401 and (await unsigned.json())["code"] == "bad_signature"
        via_browser, via_hook = await asyncio.gather(post(confirm_url, confirmation, 200),
            client.post(hook, data=webhook, headers={"Content-Type": "application/json",
                                                   "X-PG-Signature": gateway.sign(webhook)}))
        assert via_browser["status"] == "fulfilled" and via_hook.status == 200
        assert len(gateway.calls) == 1
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT count(*) FROM pet.inventory WHERE order_id=%s", (first["id"],)).fetchone() == (1,)
            assert conn.execute("SELECT status FROM pet.jobs WHERE kind='fulfil' AND ref->>'order'=%s",
                                (first["id"],)).fetchall() == [("done",)]
        assert (await post(path, {**order_body, "idempotencyKey": str(uuid4())}, 409))["code"] == "already_owned"

        second = (await post(path, {**order_body, "itemId": str(items[1]), "idempotencyKey": str(uuid4())}, 201))["order"]
        mismatch = await post(f"{path}/{second['id']}/confirm", {"paymentKey": "fixture-mismatch", "amount": 1199}, 200)
        assert mismatch["status"] == "failed" and len(gateway.calls) == 1
        third = (await post(path, {**order_body, "itemId": str(items[2]), "idempotencyKey": str(uuid4())}, 201))["order"]
        gateway.add("fixture-retry", third["orderNo"], 1200)
        fail = True
        retry_body = {"paymentKey": "fixture-retry", "amount": 1200}
        assert (await post(f"{path}/{third['id']}/confirm", retry_body, 200))["status"] == "paid"
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT count(*) FROM pet.inventory WHERE order_id=%s", (third["id"],)).fetchone() == (0,)
            result = conn.execute("""UPDATE pet.jobs SET run_after=now() WHERE ref->>'order'=%s AND status='queued'
              AND run_after>=now()+interval '59 seconds' RETURNING attempts""", (third["id"],))
            assert result.fetchone() == (1,)
        fail = False
        assert (await fulfil(app[POOL], member, third["id"], override=deliver_order))["status"] == "fulfilled"
        assert len(gateway.calls) == 2
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT count(*) FROM pet.inventory WHERE order_id=%s", (third["id"],)).fetchone() == (1,)
            conn.execute("INSERT INTO pet.member_days(member_id,day,quota_limit,used_units) VALUES (%s,%s,100,80)",
                         (member, quota_day(datetime.now(timezone.utc))))
        recharge = {"product": "recharge_half", "idempotencyKey": str(uuid4())}
        refill = (await post(path, recharge, 201))["order"]
        gateway.add("fixture-recharge", refill["orderNo"], 1500)
        assert (await post(f"{path}/{refill['id']}/confirm", {"paymentKey": "fixture-recharge", "amount": 1500},
                           200))["status"] == "fulfilled"
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT used_units,refilled_units,recharges FROM pet.member_days WHERE member_id=%s",
                                (member,)).fetchone() == (30, 50, 1)


async def check_identity(admin, dsn, directory):
    with psycopg.connect(admin) as conn:
        adult, adult_token = add_member(conn)
        minor, minor_token = add_member(conn)
    settings = Settings.read({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "50000",
                              "PET_ORIGIN": ORIGIN, "PET_MEDIA_DIR": str(directory)})
    fake = {
        "adult-fixture": IdentityResult(date(2007, 11, 18), "synthetic-adult-ci"),
        "minor-fixture": IdentityResult(date(2007, 11, 19), "synthetic-minor-ci"),
    }
    calls = []

    async def verify(token, member):
        calls.append(member)
        return fake[token]

    key = b"isolated synthetic identity key 0"
    app = make_app(settings, identity_verify=verify, identity_digest_key=key)
    with patch("marong.pet.identity.korea_today", return_value=date(2026, 11, 18)):
        async with TestClient(TestServer(app)) as client:
            async def identify(token, provider_value, expected):
                response = await client.post("/api/me/identity", headers=headers(token), json={"token": provider_value})
                body = await response.json()
                assert response.status == expected, body
                return body

            assert (await identify(adult_token, "", 400))["code"] == "invalid_input"
            assert (await identify(adult_token, "provider-error", 502))["code"] == "identity_provider"
            assert (await identify(adult_token, "adult-fixture", 200))["identityVerified"]
            assert (await identify(adult_token, "unused-after-success", 200))["identityVerified"]
            assert (await identify(minor_token, "minor-fixture", 403))["code"] == "underage"
            assert (await identify(minor_token, "minor-fixture", 401))["code"] == "unauthenticated"
            assert calls == [adult, adult, minor]

            with psycopg.connect(admin) as conn:
                digest, = conn.execute("SELECT identity_ci_hash FROM pet.members WHERE id=%s", (adult,)).fetchone()
                assert len(digest) == 32 and digest != b"synthetic-adult-ci"
                assert conn.execute("SELECT status,identity_ci_hash FROM pet.members WHERE id=%s",
                                    (minor,)).fetchone() == ("minor_locked", None)
                assert conn.execute("SELECT count(*) FROM pet.sessions WHERE member_id=%s", (minor,)).fetchone() == (0,)
                assert conn.execute("""SELECT count(*) FROM pet.jobs WHERE kind='account_delete' AND member_id=%s
                    AND run_after>=now()+interval '6 days 23 hours'""", (minor,)).fetchone() == (1,)
                conn.execute("UPDATE pet.members SET minor_locked_at=now()-interval '7 days' WHERE id=%s", (minor,))
                conn.execute("UPDATE pet.jobs SET run_after=now() WHERE kind='account_delete' AND member_id=%s", (minor,))
            assert await erase_next(app[POOL], directory)
            with psycopg.connect(admin) as conn:
                assert conn.execute("SELECT count(*) FROM pet.members WHERE id=%s", (minor,)).fetchone() == (0,)


async def check_admin(admin, dsn, directory):
    env = {**os.environ, "PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "50000",
           "PET_ORIGIN": ORIGIN, "PET_MEDIA_DIR": str(directory)}
    with psycopg.connect(admin) as conn:
        member, token = add_member(conn)
        number, = conn.execute("SELECT member_no FROM pet.members WHERE id=%s", (member,)).fetchone()
        conn.execute("UPDATE pet.members SET identity_verified_at=now(),identity_ci_hash=%s WHERE id=%s",
                     (sha256(b"synthetic admin identity").digest(), member))
        conn.execute("DELETE FROM pet.settings WHERE key IN ('business_info','payments_enabled')")
        item, = conn.execute("""
            INSERT INTO pet.items(kind,slot,name,price_krw,sellable,license_key,assets)
            VALUES ('wear','body','synthetic item',1200,true,'fixture','{}') RETURNING id
        """).fetchone()
    settings = Settings.read(env)
    gateway = FakeGateway(b"synthetic admin webhook key")
    info = {name: f"synthetic-field-{i}" for i, name in enumerate(BUSINESS_FIELDS)}

    async def command(*parts, stdin=""):
        result = await asyncio.to_thread(subprocess.run, [sys.executable, str(ROOT / "tools/pet_admin.py"), *parts],
                                        env=env, input=stdin, text=True, capture_output=True, timeout=20)
        assert all(value not in result.stdout and value not in result.stderr for value in info.values())
        return result

    bad = await command("payments", "on", stdin="\n".join(["", *list(info.values())[1:]]) + "\n")
    assert bad.returncode == 2
    with psycopg.connect(admin) as conn:
        assert conn.execute("SELECT 1 FROM pet.settings WHERE key='payments_enabled'").fetchone() is None
    enabled = await command("payments", "on", stdin="\n".join(info.values()) + "\n")
    assert enabled.returncode == 0
    assert (await command("ticket", "grant", number, "--count", "2", "--reason", "test")).stdout.strip() == "2"
    assert (await command("ticket", "grant", "ZZZZZZZZ", "--reason", "test")).returncode == 2
    created = await command("invite", "create", "--uses", "2")
    assert created.returncode == 0
    invite = created.stdout.strip()
    new_tokens = [token_urlsafe(32) for _ in range(3)]
    with psycopg.connect(admin) as conn:
        for user in new_tokens:
            conn.execute("""
                INSERT INTO pet.sessions(token_hash,kind,provider,sub_hash,expires_at,absolute_expires_at)
                VALUES (%s,'pending','google',%s,now()+interval '1 hour',now()+interval '1 hour')
            """, (cookie_hash(user), sha256(user.encode()).digest()))
        assert conn.execute("SELECT uses_left FROM pet.invites WHERE code_hash=%s",
                            (sha256(invite.encode()).digest(),)).fetchone() == (2,)
    async with TestClient(TestServer(make_app(settings, gateway=gateway))) as client:
        reply = await client.get("/api/me", headers=headers(token))
        profile = await reply.json()
        assert profile["paymentsEnabled"] and profile["business"] == info and profile["freeTickets"] == 2
        order = {"product": "item", "itemId": str(item), "idempotencyKey": str(uuid4())}
        opened = await client.post("/api/orders", headers=headers(token), json=order)
        assert opened.status == 201
        order = (await opened.json())["order"]
        assert (await command("payments", "off")).returncode == 0
        restricted = await client.post("/api/orders", headers=headers(token),
                            json={"product": "item", "itemId": str(item), "idempotencyKey": str(uuid4())})
        assert restricted.status == 409 and (await restricted.json())["code"] == "payments_off"
        gateway.add("fixture-continue", order["orderNo"], 1200)
        confirmed = await client.post(f"/api/orders/{order['id']}/confirm", headers=headers(token),
                                     json={"paymentKey": "fixture-continue", "amount": 1200})
        assert confirmed.status == 200 and (await confirmed.json())["status"] == "fulfilled"

        signup = {"birthDate": "2000-01-01", "agreeTerms": True, "agreePrivacy": True,
                  "aiNoticeConfirmed": True, "overseasTransfer": True, "inviteCode": invite}
        for pending, expected in zip(new_tokens, (201, 201, 403)):
            result = await client.post("/api/signup", headers=headers(pending), json=signup)
            assert result.status == expected


async def check_checkout(admin, dsn, directory):
    with psycopg.connect(admin) as conn:
        member, token = add_member(conn)
        _, other = add_member(conn)
        blocked, no_consent = add_member(conn, consent=False)
        conn.execute("UPDATE pet.members SET free_tickets=1 WHERE id=%s", (member,))
        free, paid = [conn.execute("""
            INSERT INTO pet.creations(member_id,kind,state,template) VALUES (%s,'living','previewed','dog_small')
            RETURNING id
        """, (member,)).fetchone()[0] for _ in range(2)]
        denied, = conn.execute("""
            INSERT INTO pet.creations(member_id,kind,state,template) VALUES (%s,'living','previewed','dog_small')
            RETURNING id
        """, (blocked,)).fetchone()
    settings = Settings.read({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "50000",
                              "PET_ORIGIN": ORIGIN, "PET_MEDIA_DIR": str(directory)})
    gateway = FakeGateway(b"synthetic checkout gateway key")
    async with TestClient(TestServer(make_app(settings, gateway=gateway))) as client:
        async def checkout(ident, use_ticket, expected, token=token, key=None):
            reply = await client.post(f"/api/creations/{ident}/checkout", headers=headers(token),
                                      json={"useFreeTicket": use_ticket, "idempotencyKey": str(key or uuid4())})
            data = await reply.json()
            assert reply.status == expected, data
            return data

        assert (await checkout(free, True, 404, other))["code"] == "not_found"
        assert (await checkout(denied, True, 409, no_consent))["code"] == "consent_required"
        key = uuid4()
        results = await asyncio.gather(checkout(free, True, 200, key=key), checkout(free, True, 200, key=key))
        assert results[0] == results[1]
        assert results[0]["pg"] is None
        assert results[0]["order"]["status"] == "fulfilled" and results[0]["order"]["amountKrw"] == 0
        assert (await checkout(paid, True, 409))["code"] == "payments_off"
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT free_tickets FROM pet.members WHERE id=%s", (member,)).fetchone() == (0,)
            assert conn.execute("SELECT count(*) FROM pet.jobs WHERE kind='candidates' AND creation_id=%s",
                                (free,)).fetchone() == (1,)
            assert conn.execute("SELECT state FROM pet.creations WHERE id=%s", (free,)).fetchone() == ("paid",)
            conn.execute("UPDATE pet.settings SET value='true' WHERE key='payments_enabled'")
        assert (await checkout(paid, False, 409))["code"] == "identity_required"
        with psycopg.connect(admin) as conn:
            conn.execute("UPDATE pet.members SET identity_verified_at=now(),identity_ci_hash=%s WHERE id=%s",
                         (sha256(b"synthetic checkout identity").digest(), member))
        order = (await checkout(paid, False, 200))["order"]
        assert order["status"] == "created" and order["amountKrw"] == 5900
        gateway.add("fixture-completed-creation", order["orderNo"], 5900)
        response = await client.post(f"/api/orders/{order['id']}/confirm", headers=headers(token),
                                     json={"paymentKey": "fixture-completed-creation", "amount": 5900})
        assert response.status == 200 and (await response.json())["status"] == "fulfilled"
        assert (await checkout(paid, False, 200))["order"]["id"] == order["id"]
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT state FROM pet.creations WHERE id=%s", (paid,)).fetchone() == ("paid",)
            assert conn.execute("SELECT count(*) FROM pet.jobs WHERE kind='candidates' AND creation_id=%s", (paid,)
                                ).fetchone() == (1,)


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
        with tempfile.TemporaryDirectory() as path:
            asyncio.run(check_preview(admin, dsn, Path(path)))
        with tempfile.TemporaryDirectory() as path:
            asyncio.run(check_orders(admin, dsn, Path(path)))
        with tempfile.TemporaryDirectory() as path:
            asyncio.run(check_identity(admin, dsn, Path(path)))
        with tempfile.TemporaryDirectory() as path:
            asyncio.run(check_admin(admin, dsn, Path(path)))
        with tempfile.TemporaryDirectory() as path:
            asyncio.run(check_checkout(admin, dsn, Path(path)))
    finally:
        db.close()
    print("TC-394–395: upload contract, metadata removal, local masking, limits, transaction and member isolation verified")
    print("TC-396–397: traits, correction, confirmation, retries, owner-only status and preview expiry verified")
    print("TC-398: opaque-output rejection, fallback, success-only quota and budget gate verified")
    print("TC-399: scoped orders, authenticated duplicate confirmation, rollback, retry and recharge verified")
    print("TC-400: provider error, age boundary, identity HMAC and delayed account erasure verified")
    print("TC-401: operator settings, ticket grant and two-use invite verified")
    print("TC-402: free and paid creation checkout, idempotency and candidate queue verified")
