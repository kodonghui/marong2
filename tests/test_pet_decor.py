"""TC-421 for the separate pet database and real HTTP routes."""

import asyncio
from base64 import b64decode
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from uuid import uuid4

import psycopg
from aiohttp.test_utils import TestClient, TestServer
from psycopg.types.json import Jsonb

from marong.pet.auth import AuthConfig
from marong.pet.http import COOKIE, cookie_hash
from marong.pet.settings import Settings
from pg import TestDB
from run_pet import make_app
from test_pet_core import fixtures

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
        memorial, _, memorial_cookie = add_member(conn, "FIXTURE2", "memorial")
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
            assert image.headers["Cache-Control"] == "private, no-store"
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
            conn.execute("UPDATE pet.orders SET used_at=now() WHERE id=%s", (purchase,))
            [used] = await items(inventory, memorial_cookie)
            assert used["withdrawableUntil"] is None


if __name__ == "__main__":
    db = TestDB()
    try:
        with TemporaryDirectory() as directory:
            asyncio.run(check_inventory(*fixtures(db), Path(directory)))
    finally:
        db.close()
    print("TC-421: inventory scope, current sales, read-only previews, and owned ended layers passed")
