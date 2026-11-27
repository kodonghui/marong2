"""Synthetic decor assets, admin moderation, account wardrobe and diary edits."""

import asyncio
import csv
from dataclasses import replace
import json
import logging
from uuid import uuid4
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE
from marong.character.graphics import TEMPLATE_IDS
from marong.decor import DecorCatalog
from marong.decor_reactions import DecorReactions
from marong.diary import KST
from marong.unified_delivery import AppProactive
from marong.unified_store import UnifiedStore
from pg import TestDB
from run_app import RoomLocks


ORIGIN = "https://fixture.invalid"


def assets(root):
    folder = Path(root) / "v1"
    folder.mkdir()
    items = []
    for ident, kind, slot, starter in (("hat-fixture", "hat", "head", False), ("top-fixture", "top", "body", False),
                                        ("starter-background", "background", None, True),
                                        ("starter-paper", "paper", None, True), ("starter-font", "font", None, True),
                                        ("sticker-fixture", "sticker", None, False), ("bad-fixture", "sticker", None, False)):
        output = folder / ident
        output.mkdir()
        thumb = Image.new("RGB", (24, 24), "#ddcab2")
        files = {}
        if kind != "sticker":
            thumb.save(output / "thumb.webp", "WEBP")
            files["thumb.webp"] = "thumb.webp"
        if slot:
            for template in TEMPLATE_IDS:
                boxes = ROOT / "design" / "pet" / "templates" / f"{template}.json"
                left, top, right, bottom = json.loads(boxes.read_text(encoding="utf-8"))["slots"][slot]
                layer = Image.new("RGBA", (1024, 1024))
                ImageDraw.Draw(layer).rectangle((left * 1024 + 4, top * 1024 + 4, right * 1024 - 4, bottom * 1024 - 4),
                                                fill="#654321")
                name = template + ".png"
                layer.save(output / name)
                files[name] = name
        if kind == "background":
            thumb.save(output / "bg.webp", "WEBP")
            files["bg.webp"] = "bg.webp"
        if kind == "paper":
            files["paperCss"] = "manuscript"
        if kind == "font":
            font = ROOT / "marong" / "app_chat_static" / "diary" / "Gaegu-Regular.woff2"
            shutil.copyfile(font, output / "font.woff2")
            files["font.woff2"] = "font.woff2"
        if ident == "sticker-fixture":
            art = Image.new("RGBA", (512, 512))
            ImageDraw.Draw(art).ellipse((80, 80, 432, 432), fill="#654321")
            art.save(output / "sticker.webp", "WEBP")
            files["sticker.webp"] = "sticker.webp"
        items.append({"id": ident, "kind": kind, "slot": slot, "name": ident,
                      "prompt": "a soft hat" if slot else None, "starter": starter, "files": files,
                      "priceKrw": 100 if ident == "bad-fixture" else 0, "license": ident})
    (folder / "items.json").write_text(json.dumps({"set": "v1", "items": items}), encoding="utf-8")
    with (folder / "licenses.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(("id", "item_id", "file", "source", "author", "license", "terms", "checked_at"))
        for item in items:
            if item["id"] != "bad-fixture":
                writer.writerow((item["id"], item["id"], "*", "synthetic", "fixture",
                                "OFL-1.1" if item["kind"] == "font" else "CC0-1.0", "fixture", "2026-11-21"))


class DecorTests(unittest.IsolatedAsyncioTestCase):
    def test_all_shipped_items_pass_the_same_catalog_validation(self):
        catalog = DecorCatalog()
        self.assertEqual(len(catalog.items), 48)
        self.assertEqual(sum(item.starter for item in catalog.items.values()), 3)
        self.assertEqual({kind: sum(item.kind == kind for item in catalog.items.values()) for kind in
                          ("hat", "top", "scarf", "background", "paper", "font", "sticker")},
                         {"hat": 4, "top": 4, "scarf": 2, "background": 7, "paper": 5, "font": 6, "sticker": 20})
        for item in catalog.items.values():
            with self.subTest(item=item.id):
                self.assertEqual(catalog.check(item), [])

    async def test_reaction_respects_daily_cap_and_precedes_a_topic(self):
        now = datetime(2026, 11, 22, 12, tzinfo=KST)
        room = dict(friend_id=1, room_key="fixture", opted_in_at=now-timedelta(days=2),
                    last_incoming_at=None, per_day=2, start_hour=8, end_hour=22,
                    quiet_for=timedelta(hours=10), sent_ago=None, failures=0)
        row = dict(id=3, friend_id=1, active=True, item_id="hat-fixture", name="콩이", attempts=0)
        outbox = SimpleNamespace(push=None, say=AsyncMock(return_value=True))
        store = SimpleNamespace(proactive_rooms=AsyncMock(return_value=[room]), proactive_count=AsyncMock(return_value=1),
                                hello_count=AsyncMock(return_value=0), topic_answers=AsyncMock(return_value=[]),
                                claim_slot=AsyncMock(return_value=True), record_delivery=AsyncMock())
        agent = SimpleNamespace(proactive_allowed=AsyncMock(return_value=True), proactive_message=AsyncMock(return_value=None))
        topics = SimpleNamespace(today=AsyncMock(return_value=SimpleNamespace(at=now)), choose=AsyncMock())
        settings = SimpleNamespace(proactive_hours=(8,22), proactive_per_day=2, proactive_daily_max=1)
        due = [row]
        async def change_state(*args):
            due.clear()
        reactions = SimpleNamespace(due=AsyncMock(side_effect=lambda *args: list(due)),
             catalog=SimpleNamespace(items={"hat-fixture": SimpleNamespace(name="털모자")}),
             scene=AsyncMock(return_value="fixture-scene"), finish=AsyncMock(side_effect=change_state), defer=AsyncMock())
        loop = AppProactive(settings, store, agent, RoomLocks(), outbox, reactions=reactions, topics=topics,
                            clock=lambda: now, rng=lambda: 0)
        self.assertEqual(await loop.step(now), 0)
        reactions.defer.assert_awaited_once_with(row, now.replace(hour=15))
        outbox.say.assert_not_awaited()

        store.proactive_count.return_value = 0
        self.assertEqual(await loop.step(now), 1)
        self.assertEqual(outbox.say.await_args.args, (1, "나 털모자 생겼어! 어때?"))
        self.assertEqual(outbox.say.await_args.kwargs["meta"]["scene"], "fixture-scene")
        reactions.finish.assert_awaited_once_with(row, "sent", "fixture-scene")
        store.record_delivery.assert_awaited_once()
        topics.choose.assert_not_awaited()

        due.append(row)
        async def remove_item(*args, **kwargs):
            row["active"] = False
            return "나 털모자 새로 입었어", {}
        agent.proactive_message.side_effect = remove_item
        loop.reaction_friends = {1}
        self.assertIsNone(await loop.priority(room, loop._slot(room, now)[0]))
        reactions.finish.assert_awaited_with(row, "skipped")
        self.assertEqual(outbox.say.await_count, 1)

    def test_layer_bounds_and_font_license_explain_why_assets_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            assets(root)
            manifest = Path(root) / "v1" / "items.json"
            inventory = json.loads(manifest.read_text(encoding="utf-8"))
            inventory["items"].append({"id": "Bad_ID", "kind": "hat"})
            manifest.write_text(json.dumps(inventory), encoding="utf-8")
            with self.assertLogs("marong.decor", "WARNING") as log:
                catalog = DecorCatalog(root)
            self.assertIn("missing=id", log.output[0])
            self.assertNotIn("Bad_ID", catalog.items)
            item = catalog.items["hat-fixture"]
            self.assertEqual(catalog.check(replace(item, kind="gacha")), ["kind"])
            self.assertEqual(catalog.check(replace(item, files={key: value for key, value in item.files.items()
                                                               if key != "dog_long.png"})), ["layer:dog_long"])
            canvas = Image.new("RGBA", (1024, 1024))
            ImageDraw.Draw(canvas).rectangle((6, 950, 94, 1000), fill="#654321")
            canvas.save(item.files["cat.png"], "PNG")
            self.assertEqual(catalog.check(item), ["layer_box:cat"])
            font = catalog.items["starter-font"]
            catalog.licenses[font.license_id]["license"] = "Proprietary"
            self.assertEqual(catalog.check(font), ["font_license"])

    async def test_catalog_and_account_scoped_actions(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        assets(folder.name)
        catalog = DecorCatalog(folder.name)
        self.assertEqual(catalog.check(catalog.items["hat-fixture"]), [])
        self.assertEqual(catalog.check(catalog.items["bad-fixture"]), ["price", "license", "file:sticker.webp"])
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        db.apply_pet_app_prerequisites()
        db.apply_pet_app()
        store = UnifiedStore(db.app_url)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22))
        auth = await sessions.join((await sessions.create_invite("join"))[0], "시험친구", "웹")
        friend = (await sessions.find_session(auth.token))["friend_id"]
        member = {"Cookie": f"{COOKIE}={auth.token}", "Origin": ORIGIN}
        joined = await sessions.join((await sessions.create_invite("join"))[0], "다른시험친구", "웹")
        other = {"Cookie": f"{COOKIE}={joined.token}", "Origin": ORIGIN}
        admin = {"Cf-Access-Jwt-Assertion": "fixture", "Origin": ORIGIN}
        access = SimpleNamespace(check=AsyncMock(return_value=("ok", "a" * 64)))
        chat = AppChat(store, SimpleNamespace(friend_cards=None), RoomLocks(), access, AppPush(store),
                       origin=ORIGIN, sessions=sessions, authentication="session", admin_email_hash="a" * 64)
        async with TestClient(TestServer(chat.web_app())) as client:
            self.assertEqual((await client.get("/chat/api/shop", headers=member)).status, 404)
            self.assertEqual((await client.get("/chat/diary/api/decor", headers=member)).status, 404)
            image = "/chat/decor/v1/hat-fixture/dog_small.png"
            self.assertEqual((await client.get(image, headers=member)).status, 404)
            thumb = "/chat/admin/api/items/hat-fixture/thumbnail"
            self.assertEqual((await client.get(thumb, headers=admin)).status, 404)
            chat.decor.catalog = catalog
            self.assertEqual((await client.get(thumb, headers=member)).status, 403)
            self.assertEqual((await client.get(thumb)).status, 403)
            access.check.return_value = ("ok", "b" * 64)
            self.assertEqual((await client.get(thumb, headers=admin)).status, 403)
            access.check.return_value = ("ok", "a" * 64)
            response = await client.get(thumb, headers=admin)
            self.assertEqual((response.status, response.content_type), (200, "image/webp"))
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(await response.read(), catalog.items["hat-fixture"].files["thumb.webp"].read_bytes())
            sticker = await client.get(thumb.replace("hat-fixture", "sticker-fixture"), headers=admin)
            self.assertEqual((sticker.status, sticker.content_type), (200, "image/webp"))
            self.assertEqual(await sticker.read(), catalog.items["sticker-fixture"].files["sticker.webp"].read_bytes())
            self.assertEqual((await client.get(thumb.replace("hat-fixture", "missing"), headers=admin)).status, 404)
            self.assertEqual((await client.get(thumb.replace("hat-fixture", "bad-fixture"), headers=admin)).status, 404)
            self.assertEqual((await client.get(thumb.replace("thumbnail", "font.woff2"), headers=admin)).status, 404)
            with self.assertLogs("marong.app_decor", level="INFO") as seed_logs:
                await chat.decor.seed()
                await chat.decor.seed()
            self.assertEqual(sum("decor_seed_skip" in line for line in seed_logs.output), 2)
            self.assertEqual(db.admin("SELECT count(*) FROM marong.decor_items WHERE state='listed'"), [(6,)])
            admin_items = (await (await client.get("/chat/admin/api/items", headers=admin)).json())["items"]
            self.assertEqual(next(item for item in admin_items if item["id"] == "bad-fixture")["state"], "new")
            writes = (
                (client.put, "/chat/api/characters/1/intro", member),
                (client.post, "/chat/api/shop/hat-fixture/claim", member),
                (client.put, "/chat/api/characters/1/outfit", member),
                (client.put, "/chat/diary/api/decor", member),
                (client.put, "/chat/diary/api/days/2026-11-20/stickers", member),
                (client.post, "/chat/admin/api/items/hat-fixture/list", admin),
                (client.post, "/chat/admin/api/items/hat-fixture/unlist", admin),
            )
            before_cross_site = tuple(db.admin("SELECT count(*) FROM marong." + name)[0][0] for name in
                                      ("decor_owned", "outfits", "outfit_firsts", "diary_decor", "diary_stickers"))
            for method, path, session in writes:
                without_origin = {key: value for key, value in session.items() if key != "Origin"}
                for headers in (without_origin, {**session, "Origin": "https://other.invalid"}):
                    with self.subTest(path=path, origin=headers.get("Origin")):
                        error = await method(path, headers=headers, json={})
                        self.assertEqual((error.status, (await error.json())["code"]), (403, "cross_site"))
            self.assertEqual(tuple(db.admin("SELECT count(*) FROM marong." + name)[0][0] for name in
                                   ("decor_owned", "outfits", "outfit_firsts", "diary_decor", "diary_stickers")), before_cross_site)
            self.assertEqual((await client.get(image)).status, 401)
            response = await client.get(image, headers=member)
            self.assertEqual((response.status, response.content_type), (200, "image/png"))
            self.assertEqual(response.headers["Cache-Control"], "public, max-age=31536000, immutable")
            font = await client.get("/chat/decor/v1/starter-font/font.woff2", headers=member)
            self.assertEqual((font.status, font.content_type), (200, "font/woff2"))
            self.assertEqual(font.headers["Cache-Control"], "public, max-age=31536000, immutable")
            self.assertEqual((await client.get("/chat/decor/v1/hat-fixture/items.json", headers=member)).status, 404)
            self.assertEqual((await client.get(image.replace("/v1/", "/v2/"), headers=member)).status, 404)
            self.assertEqual((await client.get("/chat/decor/v1/hat-fixture/%2e%2e%2fitems.json",
                                               headers=member)).status, 404)
            self.assertEqual((await client.get("/chat/admin/api/items", headers=member)).status, 403)
            rejected = await client.post("/chat/admin/api/items/bad-fixture/list", headers=admin)
            self.assertEqual((rejected.status, (await rejected.json())["missing"]),
                             (409, ["price", "license", "file:sticker.webp"]))
            self.assertEqual((await client.post("/chat/admin/api/items/starter-font/unlist", headers=admin)).status, 400)
            self.assertEqual((await client.post("/chat/admin/api/items/Bad_ID/list", headers=admin)).status, 400)
            shop = (await (await client.get("/chat/api/shop", headers=member)).json())["items"]
            self.assertEqual([item["kind"] for item in shop], ["hat", "top", "background", "paper", "font", "sticker"])
            self.assertTrue(all(item["priceKrw"] == 0 for item in shop))
            self.assertTrue(all(item["owned"] for item in shop if item["starter"]))
            self.assertEqual((await client.post("/chat/api/shop/Bad_ID/claim", headers=member)).status, 400)
            path = "/chat/api/shop/hat-fixture/claim"
            claims = await asyncio.gather(*(client.post(path, headers=member) for _ in range(2)))
            self.assertEqual(sorted(response.status for response in claims), [200, 201])
            self.assertEqual(db.admin("SELECT count(*) FROM marong.decor_owned WHERE friend_id=%s AND item_id='hat-fixture'", (friend,)), [(1,)])
            self.assertEqual((await client.post(path, headers=member)).status, 200)
            self.assertEqual((await client.post("/chat/admin/api/items/hat-fixture/unlist", headers=admin)).status, 200)
            self.assertEqual((await client.post(path, headers=member)).status, 404)
            listed = await client.post("/chat/admin/api/items/hat-fixture/list", headers=admin)
            self.assertEqual((listed.status, (await listed.json())["state"]), (200, "listed"))
            missing_item = await client.post("/chat/admin/api/items/absent-fixture/list", headers=admin)
            self.assertEqual(missing_item.status, 404)
            self.assertEqual((await client.post("/chat/admin/api/items/hat-fixture/unlist", headers=admin)).status, 200)
            self.assertEqual((await client.post("/chat/api/shop/top-fixture/claim", headers=member)).status, 201)
            character = db.admin("""
                INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
                VALUES (%s,'dog','ready','done',now(),'dog_small','콩이','{}') RETURNING id
            """, (friend,))[0][0]
            db.admin("UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s", (character, friend))
            outfit = "/chat/api/characters/" + str(character) + "/outfit"
            picks = {"head": "hat-fixture", "body": "top-fixture", "neck": None}
            response = await client.put(outfit, headers=member, json=picks)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["head"]["layerUrl"], image)
            await client.put(outfit, headers=member, json=picks)
            self.assertEqual(db.admin("SELECT item_id,state FROM marong.outfit_firsts ORDER BY id"),
                             [("hat-fixture", "waiting"), ("top-fixture", "skipped")])
            closet = await (await client.get("/chat/api/closet", headers=member)).json()
            self.assertEqual(closet["characterId"], character)
            self.assertEqual(closet["outfit"]["head"]["id"], "hat-fixture")
            profile = await (await client.get("/chat/api/profile", headers=member)).json()
            self.assertEqual(profile["character"]["outfit"]["head"]["id"], "hat-fixture")
            self.assertNotIn("hat-fixture", [item["id"] for item in (await (await client.get("/chat/api/shop", headers=member)).json())["items"]])
            self.assertIn("hat-fixture", [row["id"] for row in closet["items"]])
            starter_closet = await (await client.get("/chat/api/closet", headers=other)).json()
            self.assertIsNone(starter_closet["outfit"])
            self.assertEqual({row["kind"] for row in starter_closet["items"]}, {"background", "paper", "font"})
            self.assertEqual({kind: starter_closet["diaryDecor"][kind]["id"] for kind in ("background", "paper", "font")},
                             {kind: "starter-" + kind for kind in ("background", "paper", "font")})
            draft_id = db.admin("INSERT INTO marong.characters(friend_id,kind) VALUES (%s,'dog') RETURNING id", (friend,))[0][0]
            draft = await client.put(f"/chat/api/characters/{draft_id}/outfit", headers=member, json=picks)
            self.assertEqual((draft.status, (await draft.json())["code"]), (409, "not_ready"))
            misplaced = await client.put(outfit, headers=member, json={**picks, "head": "top-fixture"})
            self.assertEqual((misplaced.status, (await misplaced.json())["code"]), (400, "invalid_input"))
            unowned = await client.put(outfit, headers=member, json={**picks, "head": "unknown-fixture"})
            self.assertEqual((unowned.status, (await unowned.json())["code"]), (409, "not_owned"))
            self.assertEqual((await client.put(outfit, headers=other, json=picks)).status, 404)
            db.admin("UPDATE marong.outfit_firsts SET next_at=now() WHERE state='waiting'")
            expression = BytesIO()
            Image.new("RGBA", (1024, 1024), "#e6ac87").save(expression, "PNG")
            reactions = DecorReactions(store, SimpleNamespace(read=AsyncMock(return_value=expression.getvalue())),
                                       chat.usage, catalog, None)
            due, = await reactions.due(friend)
            self.assertTrue(due["active"])
            scene = await reactions.scene(due)
            await reactions.finish(due, "sent", scene)
            self.assertEqual(db.admin("SELECT fallback,state,cost_usd FROM marong.scene_pictures WHERE id=%s", (scene,)),
                             [(True, "done", 0)])
            db.admin("UPDATE marong.outfit_firsts SET state='waiting', finished_at=NULL, next_at=now() WHERE item_id='top-fixture'")
            delayed, = await reactions.due(friend)
            await reactions.defer(delayed, sessions.now() - timedelta(seconds=1))
            delayed, = await reactions.due(friend)
            self.assertEqual(delayed["attempts"], 1)
            await reactions.defer(delayed, sessions.now() + timedelta(hours=1))
            self.assertEqual(db.admin("SELECT state, attempts FROM marong.outfit_firsts WHERE item_id='top-fixture'"),
                             [("blocked", 1)])
            catalog.items["scarf-fixture"] = replace(catalog.items["hat-fixture"], id="scarf-fixture", kind="scarf", slot="neck")
            db.admin("INSERT INTO marong.decor_items(id,item_set,kind,slot,starter) VALUES ('scarf-fixture','v1','scarf','neck',false)")
            self.assertEqual((await client.post("/chat/api/shop/scarf-fixture/claim", headers=member)).status, 201)
            fresh_character = db.admin("""
                INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
                VALUES (%s,'dog','ready','done',now(),'dog_small','시험아이','{}') RETURNING id
            """, (friend,))[0][0]
            full_outfit = {"head": "hat-fixture", "body": "top-fixture", "neck": "scarf-fixture"}
            fresh_path = f"/chat/api/characters/{fresh_character}/outfit"
            self.assertEqual((await client.put(fresh_path, headers=member, json=full_outfit)).status, 200)
            self.assertEqual(db.admin("SELECT item_id,state FROM marong.outfit_firsts WHERE character_id=%s ORDER BY id", (fresh_character,)),
                             [("hat-fixture", "waiting"), ("top-fixture", "skipped"), ("scarf-fixture", "skipped")])
            self.assertEqual((await client.put(fresh_path, headers=member, json={"head": None, "body": None, "neck": None})).status, 200)
            self.assertEqual((await client.put(fresh_path, headers=member, json=full_outfit)).status, 200)
            self.assertEqual(db.admin("SELECT count(*) FROM marong.outfit_firsts WHERE character_id=%s", (fresh_character,)), [(3,)])
            style = {"backgroundId": "starter-background", "paperId": "starter-paper", "fontId": "starter-font"}
            for kind in ("background", "font"):
                original = catalog.items["starter-" + kind]
                ident = "extra-" + kind
                catalog.items[ident] = replace(original, id=ident, starter=False, name=ident)
                db.admin("INSERT INTO marong.decor_items(id,item_set,kind,slot,starter) VALUES (%s,'v1',%s,NULL,false)", (ident, kind))
                self.assertEqual((await client.post(f"/chat/api/shop/{ident}/claim", headers=other)).status, 201)
            initial_style = await (await client.get("/chat/diary/api/decor", headers=other)).json()
            self.assertEqual({kind: initial_style[kind]["id"] for kind in ("background", "paper", "font")},
                             {kind: "starter-" + kind for kind in ("background", "paper", "font")})
            custom_style = {**style, "backgroundId": "extra-background", "fontId": "extra-font"}
            saved_style = await client.put("/chat/diary/api/decor", headers=other, json=custom_style)
            self.assertEqual(saved_style.status, 200)
            read_style = await (await client.get("/chat/diary/api/decor", headers=other)).json()
            self.assertEqual((read_style["background"]["id"], read_style["font"]["id"]), ("extra-background", "extra-font"))
            self.assertEqual(db.admin("SELECT count(*) FROM marong.diary_decor WHERE friend_id=%s", ((await sessions.find_session(joined.token))["friend_id"],)), [(1,)])
            self.assertEqual((await client.put("/chat/diary/api/decor", headers=member, json=style)).status, 200)
            self.assertEqual((await client.put("/chat/diary/api/decor", headers=member, json={"fontId": "starter-font"})).status, 400)
            self.assertEqual(db.admin("SELECT count(*) FROM marong.diary_decor WHERE friend_id=%s", (friend,)), [(1,)])
            style_path = "/chat/diary/api/decor"
            no_ownership = await client.put(style_path, headers=other, json={**style, "fontId": "unknown-fixture"})
            self.assertEqual((no_ownership.status, (await no_ownership.json())["code"]), (409, "not_owned"))
            wrong_kind = await client.put(style_path, headers=other, json={**style, "fontId": "starter-background"})
            self.assertEqual((wrong_kind.status, (await wrong_kind.json())["code"]), (400, "invalid_input"))
            self.assertEqual((await client.post("/chat/api/shop/sticker-fixture/claim", headers=member)).status, 201)
            day = sessions.now().astimezone(KST).date() - timedelta(days=1)
            diary = db.admin("""
                INSERT INTO marong.diaries(friend_id,diary_date) VALUES (%s,%s) RETURNING id
            """, (friend, day))[0][0]
            db.admin("""
                INSERT INTO marong.diary_revisions(diary_id,revision,source,title,weather,body)
                VALUES (%s,1,'weather','시험 일기','sunny',repeat('가', 60))
            """, (diary,))
            db.admin("UPDATE marong.diaries SET state='ready',ready_at=now(),revision=1 WHERE id=%s", (diary,))
            path = f"/chat/diary/api/days/{day}/stickers"
            sticker = {"itemId": "sticker-fixture", "x": 100, "y": 300, "scale": 85, "rotation": -10}
            missing = f"/chat/diary/api/days/{day - timedelta(days=1)}/stickers"
            invalid = "/chat/diary/api/days/2026-13-01/stickers"
            for method, params in ((client.get, {}), (client.put, {"json": {"stickers": [sticker]}})):
                self.assertEqual((await method(missing, headers=member, **params)).status, 404)
                error = await method(invalid, headers=member, **params)
                self.assertEqual((error.status, (await error.json())["code"]), (400, "invalid_input"))
            # TC-554: compare every cross-account response with the same absent-resource path.
            intro = {"personality": ["활발함"], "likes": "시험사생활가", "dislikes": "시험사생활나", "ownerCall": "시험호칭"}
            intro_path = f"/chat/api/characters/{character}/intro"
            self.assertEqual((await client.put(intro_path, headers=member, json=intro)).status, 200)
            absent_id = 999999999
            absent_intro = f"/chat/api/characters/{absent_id}/intro"
            absent_outfit = f"/chat/api/characters/{absent_id}/outfit"
            scene_path = f"/chat/api/scenes/{scene}"
            absent_scene = f"/chat/api/scenes/{uuid4()}"
            snapshots = lambda: (
                db.admin("SELECT personality,likes,dislikes,owner_call,intro_at FROM marong.characters WHERE id=%s", (character,)),
                db.admin("SELECT * FROM marong.outfits WHERE character_id=%s", (character,)),
                db.admin("SELECT * FROM marong.diary_stickers WHERE diary_id=%s ORDER BY id", (diary,)),
                db.admin("SELECT state,image FROM marong.scene_pictures WHERE id=%s", (scene,)),
            )
            before = snapshots()
            captured = []
            class Capture(logging.Handler):
                def emit(self, record): captured.append(record.getMessage())
            handler = Capture()
            root_logger = logging.getLogger()
            old_level = root_logger.level
            root_logger.addHandler(handler)
            root_logger.setLevel(logging.INFO)
            try:
                self.assertEqual((await client.put(intro_path, headers=member, json=intro)).status, 200)
                self.assertEqual((await client.get(intro_path, headers=member)).status, 200)
                self.assertEqual((await client.get(scene_path, headers=member)).status, 200)
                cases = (
                    (client.get, intro_path, absent_intro, {}),
                    (client.put, intro_path, absent_intro, {"json": intro}),
                    (client.put, outfit, absent_outfit, {"json": picks}),
                    (client.get, path, missing, {}),
                    (client.put, path, missing, {"json": {"stickers": [sticker]}}),
                    (client.get, scene_path, absent_scene, {}),
                )
                for method, foreign, absent, params in cases:
                    with self.subTest(foreign=foreign):
                        actual = await method(foreign, headers=other, **params)
                        nonexistent = await method(absent, headers=other, **params)
                        self.assertEqual((actual.status, nonexistent.status), (404, 404))
                        def without_trace(body): return {key: value for key, value in body.items() if key != "traceId"}
                        self.assertEqual(without_trace(await actual.json()), without_trace(await nonexistent.json()))
                self.assertEqual(snapshots(), before)
            finally:
                root_logger.removeHandler(handler)
                root_logger.setLevel(old_level)
            self.assertFalse(any(marker in line for line in captured for marker in
                                 ("콩이", "시험사생활가", "시험사생활나", "시험호칭", "Main character:")))
            origin_mismatch = {**member, "Origin": "https://other.invalid"}
            self.assertEqual((await client.put(path, headers=origin_mismatch, json={"stickers": [sticker]})).status, 403)
            self.assertEqual((await client.put(path, headers=member, json={"stickers": [sticker] * 11})).status, 409)
            unowned_sticker = await client.put(path, headers=member, json={"stickers": [{**sticker, "itemId": "bad-fixture"}]})
            self.assertEqual((unowned_sticker.status, (await unowned_sticker.json())["code"]), (409, "not_owned"))
            trio = [{**sticker, "x": value} for value in (100, 200, 300)]
            self.assertEqual((await client.put(path, headers=member, json={"stickers": trio})).status, 200)
            read_back = await (await client.get(path, headers=member)).json()
            self.assertEqual([{key: item[key] for key in sticker} for item in read_back["stickers"]], trio)
            self.assertEqual((await client.get(path, headers=other)).status, 404)
            self.assertEqual((await client.put(path, headers=other, json={"stickers": [sticker]})).status, 404)
            for key, value in (("x", 1001), ("y", -1), ("scale", 49), ("rotation", 181)):
                with self.subTest(key=key):
                    response = await client.put(path, headers=member, json={"stickers": [{**sticker, key: value}]})
                    self.assertEqual(response.status, 400)
            db.admin("UPDATE marong.diaries SET hidden=true WHERE id=%s", (diary,))
            self.assertEqual((await client.put(path, headers=member, json={"stickers": [sticker]})).status, 200)
            self.assertEqual((await (await client.get(path, headers=member)).json())["stickers"][0]["x"], 100)
            await client.put(path, headers=member, json={"stickers": []})
            self.assertEqual(db.admin("SELECT count(*) FROM marong.diary_stickers WHERE diary_id=%s AND removed_at IS NULL",
                                      (diary,)), [(0,)])
            self.assertGreater(len(db.admin("SELECT id FROM marong.diary_stickers WHERE diary_id=%s AND removed_at IS NOT NULL", (diary,))), 0)
            positions = [[{**sticker, "x": x} for x in range(start, start + 10)] for start in (10, 20)]
            saved = await asyncio.gather(*(client.put(path, headers=member, json={"stickers": batch})
                                           for batch in positions))
            self.assertEqual([response.status for response in saved], [200, 200])
            result = await (await client.get(path, headers=member)).json()
            self.assertIn([row["x"] for row in result["stickers"]], [list(range(10, 20)), list(range(20, 30))])
            chat.decor.catalog = None
            for endpoint in (image, "/chat/api/shop", "/chat/api/closet", "/chat/diary/api/decor", path):
                self.assertEqual((await client.get(endpoint, headers=member)).status, 404)
            self.assertEqual((await client.get("/chat/admin/api/items", headers=admin)).status, 404)
            self.assertEqual((await client.post("/chat/admin/api/items/hat-fixture/list", headers=admin)).status, 404)


if __name__ == "__main__":
    unittest.main()
