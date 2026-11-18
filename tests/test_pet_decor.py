"""TC-421 for the separate pet database and real HTTP routes."""

import asyncio
import json
from base64 import b64decode
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import psycopg
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image, ImageDraw
from psycopg.types.json import Jsonb

from marong.pet.auth import AuthConfig
from marong.pet.decor import apply_outfit, outfit_input
from marong.pet.http import COOKIE, POOL, Problem, cookie_hash
from marong.pet.settings import Settings
from marong.pet.inventory import TEMPLATES
from pg import TestDB
from run_pet import make_app
from test_pet_core import fixtures
from tools import pet_admin

PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+Xvp4AAAAASUVORK5CYII=")
SHEET = ("front", "smile", "excited", "sleepy", "surprised", "sad", "pout")


def add_member(conn, code, mode):
    member, pet = uuid4(), uuid4()
    token = token_urlsafe(32)
    conn.execute("""
        INSERT INTO pet.members(id,member_no,provider,sub_hash,adult_self_declared_at)
        VALUES (%s,%s,'google',%s,now())
    """, (member, code, sha256(member.bytes).digest()))
    conn.execute("""
        INSERT INTO pet.sessions(token_hash,kind,member_id,expires_at,absolute_expires_at)
        VALUES (%s,'member',%s,now()+interval '1 day',now()+interval '3 days')
    """, (cookie_hash(token), member))
    (creation,) = conn.execute("""
        INSERT INTO pet.creations(member_id,kind,state,template) VALUES (%s,%s,'done','dog_small') RETURNING id
    """, (member, mode)).fetchone()
    conn.execute("""
        INSERT INTO pet.pets(id,member_id,creation_id,name,intro,species,template,sheet,mode,memorial_since)
        VALUES (%s,%s,%s,'시험용 아이','{}','dog','dog_small',%s,%s,CASE WHEN %s='memorial' THEN now() END)
    """, (pet, member, creation, Jsonb(dict.fromkeys(SHEET, str(uuid4()))), mode, mode))
    return member, pet, {"Cookie": f"{COOKIE}={token}"}


async def check_inventory(admin, app_dsn, directory):
    settings = Settings.read({"PET_DATABASE_URL": app_dsn, "PET_ORIGIN": "http://127.0.0.1",
                              "PET_MONTHLY_BUDGET_KRW": "50000", "PET_MEDIA_DIR": str(directory)})
    with psycopg.connect(admin, autocommit=True) as conn:
        member, pet, own = add_member(conn, "FIXTURE1", "living")
        memorial, memorial_pet, memorial_cookie = add_member(conn, "FIXTURE2", "memorial")
        free, sale, ended, future = (uuid4() for _ in range(4))
        conn.execute("""
            INSERT INTO pet.items(id,kind,name,slot,is_default,sellable,limited,price_krw,license_key,assets,sale_starts_at,sale_ends_at)
            VALUES (%s,'wear','기본 목도리','neck',true,false,false,NULL,'fixture','{}',NULL,NULL),
                   (%s,'wear','털모자','head',false,true,true,1200,'fixture','{}',now()-interval '1 day',now()+interval '1 day'),
                   (%s,'wear','지난 털모자','head',false,true,true,1200,'fixture','{}',now()-interval '2 days',now()-interval '1 day'),
                   (%s,'wear','나중 털모자','head',false,true,true,1200,'fixture','{}',now()+interval '1 day',NULL)
        """, (free, sale, ended, future))
        conn.execute("INSERT INTO pet.inventory(member_id,item_id,source) VALUES (%s,%s,'free_default')", (member, free))
        conn.execute("INSERT INTO pet.decor(pet_id,neck_item) VALUES (%s,%s)", (pet, free))

        for item in (sale, ended):
            layers = settings.media_dir / "items" / str(item) / "layers"
            layers.mkdir(parents=True)
            (layers / "dog_small.png").write_bytes(PNG)

        async with TestClient(TestServer(make_app(settings, auth_config=AuthConfig({}, b"synthetic-signing-secret")))) as client:
            inventory = "/api/me/inventory"
            shop = "/api/shop"
            layer = lambda item, template="dog_small": f"/api/items/{item}/layer?template={template}"
            assert (await client.get(inventory)).status == 401
            assert (await client.get(shop + "?kind=font", headers=own)).status == 400
            assert (await client.get(inventory + "?kind=wear&kind=font", headers=own)).status == 400
            assert (await client.get(layer(sale, "unknown"), headers=own)).status == 400

            async def items(url, headers):
                response = await client.get(url, headers=headers)
                assert response.status == 200
                return (await response.json())["items"]

            [owned] = await items(inventory + "?kind=wear", own)
            assert owned == {"itemId": str(free), "kind": "wear", "name": "기본 목도리", "slot": "neck",
                             "source": "free_default", "wornBy": [str(pet)], "contents": [], "withdrawableUntil": None}
            assert await items(inventory, memorial_cookie) == []
            assert await items(shop, memorial_cookie) == []
            [offered] = await items(shop, own)
            assert offered["id"] == str(sale) and offered["priceKrw"] == 1200 and not offered["purchasable"]
            image = await client.get(layer(sale), headers=own)
            assert image.status == 200 and image.content_type == "image/png" and await image.read() == PNG
            assert image.headers["Cache-Control"] == "no-store"
            assert (await client.get(layer(sale), headers=memorial_cookie)).status == 404
            assert (await client.get(layer(ended), headers=own)).status == 404
            assert (await client.get(layer(sale, "cat"), headers=own)).status == 404
            assert (await client.get(layer(sale))).status == 401
            assert conn.execute("SELECT count(*) FROM pet.inventory WHERE member_id=%s", (member,)).fetchone() == (1,)

            # An ended item can still be worn by its owner. A past buyer's layer is otherwise private.
            (purchase,) = conn.execute("""
                INSERT INTO pet.orders(order_no,member_id,product,item_id,amount_krw,vat_krw,withdrawal_rule,
                                       status,idempotency_key,paid_at)
                VALUES ('fixture-owned',%s,'item',%s,1200,109,'fixture','fulfilled',%s,now()) RETURNING id
            """, (memorial, ended, uuid4())).fetchone()
            conn.execute("INSERT INTO pet.inventory(member_id,item_id,source,order_id) VALUES (%s,%s,'order',%s)",
                         (memorial, ended, purchase))
            [former_sale] = await items(inventory, memorial_cookie)
            assert former_sale["itemId"] == str(ended) and former_sale["withdrawableUntil"]
            assert (await client.get(layer(ended), headers=memorial_cookie)).status == 200
            pool = client.server.app[POOL]

            async def equip(actor, child, *, head=None, body=None, neck=None, required_error=None):
                payload = outfit_input({"head": head, "body": body, "neck": neck})
                try:
                    async with pool.connection() as session, session.transaction():
                        await apply_outfit(session, actor, child, payload)
                    assert required_error is None
                except Problem as error:
                    assert error.code == required_error

            await equip(member, pet, head=str(ended), required_error="not_found")
            await equip(member, memorial_pet, required_error="not_found")
            await equip(memorial, memorial_pet, neck=str(ended), required_error="wrong_slot")
            assert conn.execute("SELECT used_at FROM pet.orders WHERE id=%s", (purchase,)).fetchone() == (None,)
            await equip(memorial, memorial_pet, head=str(ended))
            (first_use,) = conn.execute("SELECT used_at FROM pet.orders WHERE id=%s", (purchase,)).fetchone()
            assert first_use is not None
            await equip(memorial, memorial_pet, head=str(ended))
            assert conn.execute("SELECT used_at FROM pet.orders WHERE id=%s", (purchase,)).fetchone() == (first_use,)
            [used] = await items(inventory, memorial_cookie)
            assert used["withdrawableUntil"] is None and used["wornBy"] == [str(memorial_pet)]
            await equip(memorial, memorial_pet)
            [removed] = await items(inventory, memorial_cookie)
            assert removed["wornBy"] == []
            conn.execute("UPDATE pet.pets SET status='archived' WHERE id=%s", (memorial_pet,))
            await equip(memorial, memorial_pet, head=str(ended), required_error="archived")


def check_item_cli(admin, app_dsn, directory):
    media = directory / "store"
    templates = directory / "templates"
    templates.mkdir()
    license_file = directory / "licenses.csv"
    license_file.write_text("key,app_sale\napproved,yes\n", encoding="utf-8")
    for template in TEMPLATES:
        (templates / f"{template}.json").write_text(json.dumps({"slots": {"head": [.3, .3, .7, .7]}}), encoding="utf-8")
    source = directory / "hat"
    folder = source / "layers"
    folder.mkdir(parents=True)
    data = {"kind": "wear", "name": "시험 모자", "slot": "head", "priceKrw": 1200, "sellable": True,
            "limited": True, "saleStartsAt": "2026-01-01T00:00:00Z", "saleEndsAt": "2099-01-01T00:00:00Z",
            "licenseKey": "approved"}
    config = source / "item.json"
    config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    Image.new("RGB", (60, 60), "#b7a48d").save(source / "thumb.webp")
    layer = Image.new("RGBA", (1024, 1024))
    ImageDraw.Draw(layer).rectangle((400, 400, 409, 409), fill="#b7a48d")
    for template in sorted(TEMPLATES)[1:]:
        layer.save(folder / f"{template}.png")
    env = {"PET_DATABASE_URL": app_dsn, "PET_ORIGIN": "http://127.0.0.1",
           "PET_MONTHLY_BUDGET_KRW": "50000", "PET_MEDIA_DIR": str(media)}
    media.mkdir()
    with psycopg.connect(admin, autocommit=True) as conn, patch.object(pet_admin, "ASSETS", directory), patch.dict("os.environ", env):
        count = conn.execute("SELECT count(*) FROM pet.items").fetchone()[0]
        add = ["item", "add", str(source)]
        assert pet_admin.main(add) == 2
        first = folder / f"{sorted(TEMPLATES)[0]}.png"
        layer.save(first)
        config.write_text(json.dumps({**data, "licenseKey": "missing"}), encoding="utf-8")
        assert pet_admin.main(add) == 2
        config.write_text(json.dumps(data), encoding="utf-8")
        outside = layer.copy()
        ImageDraw.Draw(outside).rectangle((0, 0, 3, 0), fill="#b7a48d")
        outside.save(first)
        assert pet_admin.main(add) == 2
        layer.save(first)
        theme = directory / "theme"
        theme.mkdir()
        Image.new("RGB", (60, 60), "#b7a48d").save(theme / "thumb.webp")
        Image.new("RGB", (1000, 1800), "#b7a48d").save(theme / "background.webp")
        (theme / "item.json").write_text(json.dumps({"kind": "theme", "name": "시험 종이", "licenseKey": "approved"}),
                                         encoding="utf-8")
        assert pet_admin.main(["item", "add", str(theme)]) == 2
        assert conn.execute("SELECT count(*) FROM pet.items").fetchone()[0] == count
        assert not (media / "items").exists()
        assert pet_admin.main(add) == 0
        (ident,) = conn.execute("SELECT id FROM pet.items WHERE name='시험 모자'").fetchone()
        assert len(list((media / "items" / str(ident) / "layers").glob("*.png"))) == 5
        assert pet_admin.main(["item", "list"]) == 0
        assert pet_admin.main(["item", "end", str(ident)]) == 0
        assert pet_admin.main(["item", "reopen", str(ident)]) == 2
        assert conn.execute("SELECT sellable FROM pet.items WHERE id=%s", (ident,)).fetchone() == (False,)


if __name__ == "__main__":
    db = TestDB()
    try:
        with TemporaryDirectory() as directory:
            dsn = fixtures(db)
            asyncio.run(check_inventory(*dsn, Path(directory)))
            check_item_cli(*dsn, Path(directory))
    finally:
        db.close()
    print("TC-421: inventory scope, current sales, read-only previews, and owned ended layers passed")
    print("TC-422: missing layer, license, dimensions and pixel limits, atomic upload, and limited sale ending passed")
    print("TC-423 outfit transaction: ownership, slot mismatch, wear, remove, archive and first use passed")
