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
from marong.decor import DecorCatalog, MARONG_SLOTS
from marong.decor_reactions import DecorReactions
from marong.diary import KST
from marong.unified_delivery import AppProactive, UnifiedDelivery
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
            for template in (*TEMPLATE_IDS, "marong"):
                boxes = ROOT / "design" / "pet" / "templates" / f"{template}.json"
                left, top, right, bottom = (MARONG_SLOTS if template == "marong" else
                                            json.loads(boxes.read_text(encoding="utf-8"))["slots"])[slot]
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
    async def test_tc760_missing_marong_layer_does_not_block_pet_or_listing(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup); assets(folder.name)
        catalog = DecorCatalog(folder.name)
        original = catalog.items['hat-fixture']
        catalog.items['hat-fixture'] = replace(original, files={k:v for k,v in original.files.items() if k != 'marong.png'})
        db = TestDB(); self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        store = UnifiedStore(db.app_url); await store.open(wait=True); self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool,secrets.token_bytes(32),contact_schedule=(2,8,22))
        auth = await sessions.join((await sessions.create_invite('join'))[0], '시험친구','웹')
        friend = (await sessions.find_session(auth.token))['friend_id']
        member = {'Cookie':f'{COOKIE}={auth.token}','Origin':ORIGIN}
        access = SimpleNamespace(check=AsyncMock(return_value=('ok','a'*64)))
        chat = AppChat(store,SimpleNamespace(friend_cards=None),RoomLocks(),access,AppPush(store),origin=ORIGIN,
                       sessions=sessions,authentication='session',admin_email_hash='a'*64)
        chat.decor.catalog = catalog
        chat.pet_app_settings = replace(chat.pet_app_settings,decor=True,default_wear=True)
        chat.profile.features['defaultWear'] = True
        await chat.decor.seed()
        async with TestClient(TestServer(chat.web_app())) as client:
            shop = (await (await client.get('/chat/api/shop',headers=member)).json())['items']
            self.assertFalse(next(i for i in shop if i['id']=='hat-fixture')['marongWearable'])
            self.assertTrue(next(i for i in shop if i['id']=='top-fixture')['marongWearable'])
            self.assertEqual((await client.post('/chat/admin/api/items/hat-fixture/list',headers={'Origin':ORIGIN,'Cf-Access-Jwt-Assertion':'fixture'})).status,200)
            self.assertEqual((await client.post('/chat/api/shop/hat-fixture/claim',headers=member)).status,201)
            closet = await (await client.get('/chat/api/closet',headers=member)).json()
            self.assertFalse(next(i for i in closet['items'] if i['id']=='hat-fixture')['marongWearable'])
            picks={'head':'hat-fixture','body':None,'neck':None}
            invalid = await client.put('/chat/api/marong/outfit',headers=member,json=picks)
            invalid_body = await invalid.json()
            self.assertEqual((invalid.status,invalid_body['code'],invalid_body['missing']),(409,'item_invalid',['layer:marong']))
            catalog.items['hat-fixture'] = replace(original,files={**original.files,'marong.png':Path(folder.name)/'not-on-disk.png'})
            absent = await client.put('/chat/api/marong/outfit',headers=member,json=picks)
            self.assertEqual((absent.status,(await absent.json())['missing']),(409,['layer:marong']))
            invalid_layer = Path(folder.name) / 'invalid.png'
            invalid_art = Image.new('RGBA',(1024,1024))
            ImageDraw.Draw(invalid_art).rectangle((10,10,50,50),fill='#abcdef')
            invalid_art.save(invalid_layer)
            catalog.items['hat-fixture'] = replace(original,files={**original.files,'marong.png':invalid_layer})
            invalid_box = await client.put('/chat/api/marong/outfit',headers=member,json=picks)
            self.assertEqual((invalid_box.status,(await invalid_box.json())['missing']),(409,['layer_box:marong']))
            self.assertEqual(db.admin('SELECT count(*) FROM marong.marong_outfits'),[(0,)])
            self.assertEqual(db.admin('SELECT count(*) FROM marong.outfit_firsts'),[(0,)])
            pet = db.admin("""INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
                VALUES (%s,'dog','ready','done',now(),'dog_small','시험','{}') RETURNING id""", (friend,))[0][0]
            self.assertEqual((await client.put(f'/chat/api/characters/{pet}/outfit',headers=member,json=picks)).status,200)
            catalog.items['hat-fixture'] = original
            self.assertEqual((await client.put('/chat/api/marong/outfit',headers=member,json=picks)).status,200)
            catalog.items['hat-fixture'] = replace(original,files={k:v for k,v in original.files.items() if k != 'marong.png'})
            db.admin('UPDATE marong.friend_profiles SET character_id=NULL WHERE friend_id=%s',(friend,))
            self.assertIsNone((await (await client.get('/chat/api/closet',headers=member)).json())['outfit']['head'])
            self.assertIsNone((await (await client.get('/chat/api/profile',headers=member)).json())['marongOutfit']['head'])

    async def test_bug139_switch_off_seeds_all_existing_items_and_shop(self):
        """BUG-139 / SPEC-575: an absent default layer must not hide existing pet items."""
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        store = UnifiedStore(db.app_url)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22))
        auth = await sessions.join((await sessions.create_invite('join'))[0], '시험친구', '웹')
        headers = {'Cookie': f'{COOKIE}={auth.token}', 'Origin': ORIGIN}
        chat = AppChat(store, SimpleNamespace(friend_cards=None), RoomLocks(), None, AppPush(store),
                       origin=ORIGIN, sessions=sessions, authentication='session')
        chat.decor.catalog = DecorCatalog()
        chat.pet_app_settings = replace(chat.pet_app_settings, decor=True, default_wear=False)
        hat = chat.decor.catalog.items['berry-beanie']
        missing_pet_layer = replace(hat, files={name:path for name,path in hat.files.items() if name != 'cat.png'})
        self.assertEqual(chat.decor.catalog.check(missing_pet_layer), ['layer:cat'])
        for ident in ('oat-sweater','blue-raincoat','forest-vest','apricot-apron'):
            item = chat.decor.catalog.items[ident]
            chat.decor.catalog.items[ident] = replace(item, files={name:path for name,path in item.files.items() if name != 'marong.png'})
            self.assertEqual(chat.decor.catalog.check(chat.decor.catalog.items[ident]), [])
            self.assertEqual(chat.decor.catalog.marong_layer_issue(chat.decor.catalog.items[ident]), 'layer')
        await chat.decor.seed()
        await chat.decor.seed()
        self.assertEqual(db.admin('SELECT count(*) FROM marong.decor_items'), [(48,)])
        async with TestClient(TestServer(chat.web_app())) as client:
            shop = (await (await client.get('/chat/api/shop', headers=headers)).json())['items']
            self.assertEqual(len(shop), 48)
            self.assertTrue({'oat-sweater','blue-raincoat','forest-vest','apricot-apron'} <= {item['id'] for item in shop})
            self.assertEqual((await client.post('/chat/api/shop/oat-sweater/claim', headers=headers)).status, 201)

    def test_tc763_default_wear_requires_both_flags(self):
        from marong.pet_app_settings import PetAppSettings
        for env, expected in (({},False), ({'MARONG_DEFAULT_WEAR':'1'},False),
                              ({'MARONG_DECOR':'1'},False), ({'MARONG_DECOR':'1','MARONG_DEFAULT_WEAR':'1'},True)):
            self.assertEqual(PetAppSettings.from_env(env).default_wear, expected)

    async def test_tc773_shared_reaction_job_and_atomic_crash(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        friend = db.admin("INSERT INTO marong.friends(name) VALUES ('fixture') RETURNING id")[0][0]
        pet = db.admin("INSERT INTO marong.characters(friend_id,kind) VALUES (%s,'dog') RETURNING id", (friend,))[0][0]
        db.admin("INSERT INTO marong.decor_items(id,kind,slot) VALUES ('fixture-hat','hat','head')")
        first = db.admin("INSERT INTO marong.outfit_firsts(friend_id,character_id,item_id,next_at) VALUES (%s,%s,'fixture-hat',now()) RETURNING id", (friend,pet))[0][0]
        store = UnifiedStore(db.app_url)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        scenes = SimpleNamespace(wait_for_topic=AsyncMock(return_value=None))
        reactions = DecorReactions(store, None, None, None, scenes)
        row = {'id':first, 'friend_id':friend, 'character_id':pet, 'item_id':'fixture-hat', 'head':'fixture-hat', 'neck':None, 'body':None}
        with self.assertRaises(RuntimeError):
            await reactions.reaction_job(row, after_insert=lambda: (_ for _ in ()).throw(RuntimeError('stop')))
        self.assertEqual(db.admin('SELECT count(*) FROM marong.scene_pictures'), [(0,)])
        one, two = await asyncio.gather(reactions.reaction_job(row), reactions.reaction_job(row))
        self.assertEqual(one['id'], two['id'])
        self.assertEqual(db.admin('SELECT count(*) FROM marong.scene_pictures'), [(1,)])
        self.assertEqual(db.admin('SELECT scene_job_id FROM marong.outfit_firsts WHERE id=%s', (first,))[0][0], one['id'])
        db.admin("INSERT INTO marong.rooms(room_key,owner_friend_id) VALUES ('app:fixture',%s)", (friend,))
        pictures = [db.admin("""INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,item_id,state,
            finished_at,fallback,format,width,height,image) VALUES (%s,%s,'reaction','fixture-hat','done',now(),true,
            'png',1,1,'\\x01') RETURNING id""", (friend,pet))[0][0] for _ in range(2)]
        delivery = UnifiedDelivery(store, SimpleNamespace(enabled=False), 'session', lambda: None)
        results = await asyncio.gather(*(delivery.say(friend,'fixture',kind='proactive',notify=False,
            key=f'app-reaction:{first}',meta={'scene':str(picture)}) for picture in pictures))
        self.assertEqual(results, ['later','later'])
        messages = db.admin("SELECT meta->>'scene' FROM marong.messages WHERE kakao_id=%s", (f'app-reaction:{first}',))
        self.assertEqual(len(messages), 1)
        await asyncio.gather(reactions.finish(row,'sent',pictures[1]), reactions.finish(row,'sent',pictures[0]))
        self.assertEqual(str(db.admin('SELECT scene_picture_id FROM marong.outfit_firsts WHERE id=%s', (first,))[0][0]), messages[0][0])
        default_first = db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'fixture-hat',now()) RETURNING id", (friend,))[0][0]
        default_row = {**row, 'id':default_first, 'character_id':None}
        with self.assertRaises(RuntimeError):
            await reactions.reaction_job(default_row,after_insert=lambda: (_ for _ in ()).throw(RuntimeError('stop')))
        self.assertEqual(db.admin('SELECT count(*) FROM marong.scene_pictures WHERE character_id IS NULL'), [(0,)])
        a, b = await asyncio.gather(reactions.reaction_job(default_row), reactions.reaction_job(default_row))
        self.assertEqual(a['id'],b['id'])
        self.assertEqual(db.admin('SELECT count(*) FROM marong.scene_pictures WHERE character_id IS NULL'), [(1,)])
        default_pictures = [db.admin("""INSERT INTO marong.scene_pictures(friend_id,purpose,item_id,state,
            finished_at,fallback,format,width,height,image) VALUES (%s,'reaction','fixture-hat','done',now(),true,
            'png',1,1,'\\x01') RETURNING id""", (friend,))[0][0] for _ in range(2)]
        default_key = f'app-reaction:{default_first}'
        results = await asyncio.gather(*(delivery.say(friend,'fixture',kind='proactive',notify=False,
            key=default_key,meta={'scene':str(picture)}) for picture in default_pictures))
        self.assertEqual(results, ['later','later'])
        messages = db.admin("SELECT meta->>'scene' FROM marong.messages WHERE kakao_id=%s", (default_key,))
        self.assertEqual(len(messages),1)
        await asyncio.gather(reactions.finish(default_row,'sent',default_pictures[1]),
                             reactions.finish(default_row,'sent',default_pictures[0]))
        self.assertEqual(str(db.admin('SELECT scene_picture_id FROM marong.outfit_firsts WHERE id=%s', (default_first,))[0][0]), messages[0][0])

    async def test_tc761_762_763_771_default_outfit_is_session_scoped(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        assets(folder.name)
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        db.apply_pet_app_prerequisites()
        db.apply_pet_app()
        db.apply_marong_outfit()
        store = UnifiedStore(db.app_url)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22))
        first = await sessions.join((await sessions.create_invite('join'))[0], '시험가', '웹')
        second = await sessions.join((await sessions.create_invite('join'))[0], '시험나', '웹')
        a = (await sessions.find_session(first.token))['friend_id']
        b = (await sessions.find_session(second.token))['friend_id']
        ah = {'Cookie': f'{COOKIE}={first.token}', 'Origin': ORIGIN}
        bh = {'Cookie': f'{COOKIE}={second.token}', 'Origin': ORIGIN}
        chat = AppChat(store, SimpleNamespace(friend_cards=None), RoomLocks(), None, AppPush(store),
                       origin=ORIGIN, sessions=sessions, authentication='session')
        chat.decor.catalog = DecorCatalog(folder.name)
        chat.pet_app_settings = replace(chat.pet_app_settings, decor=True, default_wear=True)
        chat.profile.features.update(decor=True, defaultWear=True)
        await chat.decor.seed()
        async with TestClient(TestServer(chat.web_app())) as client:
            await client.post('/chat/api/shop/hat-fixture/claim', headers=ah)
            await client.post('/chat/api/shop/top-fixture/claim', headers=bh)
            outfit = '/chat/api/marong/outfit'
            hat = {'head': 'hat-fixture', 'body': None, 'neck': None}
            top = {'head': None, 'body': 'top-fixture', 'neck': None}
            self.assertEqual((await client.put(outfit, headers=bh, json=top)).status, 200)
            before = db.admin('SELECT row_to_json(x) FROM (SELECT * FROM marong.marong_outfits WHERE friend_id=%s) x', (b,))
            before_profile = await (await client.get('/chat/api/profile', headers=bh)).read()
            before_closet = await (await client.get('/chat/api/closet', headers=bh)).read()
            for payload, code in (({**hat, 'friendId': b}, 400), (top, 409)):
                self.assertEqual((await client.put(outfit, headers=ah, json=payload)).status, code)
            response = await client.put(outfit, headers=ah, json=hat)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['head']['layerUrl'], '/chat/decor/v1/hat-fixture/marong.png')
            self.assertEqual(db.admin('SELECT extract(epoch FROM next_at-worn_at) FROM marong.outfit_firsts WHERE friend_id=%s', (a,)), [(180,)])
            self.assertEqual((await client.put(outfit, headers=ah, json=hat)).status, 200)
            self.assertEqual(db.admin('SELECT count(*) FROM marong.outfit_firsts WHERE friend_id=%s', (a,)), [(1,)])
            chat.authentication = 'access'
            chat.access = SimpleNamespace(check=AsyncMock(return_value=('ok', 'a'*64)))
            self.assertEqual((await client.put(outfit, headers={**ah, 'Cf-Access-Jwt-Assertion':'fixture'}, json=hat)).status, 200)
            self.assertEqual((await client.put(outfit, headers={'Origin': ORIGIN, 'Cf-Access-Jwt-Assertion':'fixture'}, json=hat)).status, 401)
            chat.authentication = 'session'
            self.assertEqual((await client.put(outfit, headers=ah, json={'head': None, 'body': None, 'neck': None})).status, 200)
            self.assertEqual((await client.put(outfit, headers=ah, json=hat)).status, 200)
            self.assertEqual(db.admin('SELECT count(*) FROM marong.outfit_firsts WHERE friend_id=%s', (a,)), [(1,)])
            wrong = await client.put(outfit, headers=ah, json={'head': None, 'body': 'hat-fixture', 'neck': None})
            self.assertEqual((wrong.status, (await wrong.json())['errors']), (400, [{'field': 'body', 'reason': 'wrong_kind'}]))
            self.assertEqual(before, db.admin('SELECT row_to_json(x) FROM (SELECT * FROM marong.marong_outfits WHERE friend_id=%s) x', (b,)))
            self.assertEqual(before_profile, await (await client.get('/chat/api/profile', headers=bh)).read())
            self.assertEqual(before_closet, await (await client.get('/chat/api/closet', headers=bh)).read())
            profile = await (await client.get('/chat/api/profile', headers=ah)).json()
            self.assertEqual(profile['marongOutfit']['head']['id'], 'hat-fixture')
            closet = await (await client.get('/chat/api/closet', headers=ah)).json()
            self.assertEqual(closet['outfit']['head']['id'], 'hat-fixture')
            self.assertEqual((await client.put(outfit, headers={'Origin': ORIGIN}, json=hat)).status, 401)
            self.assertEqual((await client.put(outfit, headers={**ah, 'Origin': 'https://other.invalid'}, json=hat)).status, 403)
            self.assertEqual((await client.put(outfit, headers=ah, json={'head': None})).status, 400)
            self.assertEqual((await client.put(outfit, headers=ah, json={**hat, 'extra': 'x'*17000})).status, 413)
            character = db.admin("""INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
                VALUES (%s,'dog','ready','done',now(),'dog_small','fixture','{}') RETURNING id""", (a,))[0][0]
            db.admin('UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s', (character, a))
            self.assertEqual((await client.put(outfit, headers=ah, json=hat)).status, 200)
            self.assertEqual(db.admin('SELECT count(*) FROM marong.outfits WHERE character_id=%s', (character,)), [(0,)])
            self.assertNotIn('marongOutfit', await (await client.get('/chat/api/profile', headers=ah)).json())
            db.admin('UPDATE marong.friend_profiles SET character_id=NULL WHERE friend_id=%s', (a,))
            chat.pet_app_settings = replace(chat.pet_app_settings, default_wear=False)
            chat.profile.features['defaultWear'] = False
            self.assertEqual((await client.put(outfit, headers=ah, json=hat)).status, 404)
            self.assertNotIn('marongOutfit', await (await client.get('/chat/api/profile', headers=ah)).json())
            self.assertIsNone((await (await client.get('/chat/api/closet', headers=ah)).json())['outfit'])
            chat.pet_app_settings = replace(chat.pet_app_settings, default_wear=True, decor=False)
            self.assertEqual((await client.put(outfit, headers=ah, json=hat)).status, 404)

    def test_tc760_default_marong_layers(self):
        catalog = DecorCatalog()
        wearable = [item for item in catalog.items.values() if item.slot]
        self.assertEqual(len(wearable), 10)
        for item in wearable:
            with self.subTest(item=item.id):
                self.assertIn("marong.png", item.files)
                with Image.open(item.files["marong.png"]) as image:
                    self.assertEqual((image.mode, image.size), ("RGBA", (1024, 1024)))
                self.assertIsNone(catalog._layer_issue(item.files["marong.png"], "marong", item.slot))
                self.assertEqual("layer", catalog.marong_layer_issue(replace(
                    item, files={k: v for k, v in item.files.items() if k != "marong.png"})))

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
                if item.kind == "font":
                    self.assertEqual(catalog.licenses[item.license_id]["license"], "OFL-1.1")
                    ofl = (catalog.root / item.id / "OFL.txt").read_text(encoding="utf-8-sig")
                    self.assertIn("SIL OPEN FONT LICENSE", ofl)
                    self.assertIn("1.1", ofl)
                if item.slot:
                    self.assertTrue(item.prompt.isascii() and item.prompt.strip())

    async def test_tc539_real_application_starts_twice_without_reseeding_duplicates(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        assets(folder.name)
        root = Path(folder.name) / "v1"
        manifest = root / "items.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        duplicate = dict(data["items"][0], id="hat-second", name="hat-second", license="hat-second")
        data["items"].append(duplicate)
        shutil.copytree(root / "hat-fixture", root / "hat-second")
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with (root / "licenses.csv").open("a", encoding="utf-8", newline="") as file:
            csv.writer(file).writerow(("hat-second", "hat-second", "*", "synthetic", "fixture", "CC0-1.0", "fixture", "2026-11-21"))
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        db.apply_pet_app_prerequisites()
        db.apply_pet_app()
        db.apply_marong_outfit()
        for attempt in range(2):
            child = await asyncio.create_subprocess_exec(
                sys.executable, str(ROOT / "tests/support/decor_start_child.py"), db.app_url, folder.name,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            output, errors = await asyncio.wait_for(child.communicate(), 60)
            self.assertEqual(child.returncode, 0, errors.decode(errors="replace")[-3000:])
            self.assertIn(b"listed=7 new=1", output)
            self.assertIn(b"decor_seed_skip", errors)
            self.assertEqual(db.admin("SELECT count(*) FROM marong.decor_items WHERE state='listed'"), [(7,)])
            self.assertEqual(db.admin("SELECT count(*) FROM marong.decor_items WHERE id='bad-fixture'"), [(0,)])

    async def test_reaction_respects_daily_cap_and_precedes_a_topic(self):
        now = datetime(2026, 11, 22, 12, tzinfo=KST)
        room = dict(friend_id=1, room_key="fixture", opted_in_at=now-timedelta(days=2),
                    last_incoming_at=None, per_day=2, start_hour=8, end_hour=22,
                    quiet_for=timedelta(hours=10), sent_ago=None, failures=0)
        row = dict(id=3, friend_id=1, active=True, item_id="hat-fixture", name="콩이", attempts=0)
        outbox = SimpleNamespace(push=None, say=AsyncMock(return_value=True))
        sent_today = {"count": 1}
        async def count_delivery(*args):
            sent_today["count"] += 1
        store = SimpleNamespace(proactive_rooms=AsyncMock(return_value=[room]), proactive_count=AsyncMock(side_effect=lambda *_: sent_today["count"]),
                                hello_count=AsyncMock(return_value=0), topic_answers=AsyncMock(return_value=[]),
                                claim_slot=AsyncMock(return_value=True), record_delivery=AsyncMock(side_effect=count_delivery))
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

        sent_today["count"] = 0
        self.assertEqual(await loop.step(now), 1)
        self.assertEqual(sent_today["count"], 1)
        self.assertEqual(outbox.say.await_args.args, (1, "나 털모자 생겼어! 어때?"))
        meta = outbox.say.await_args.kwargs["meta"]
        self.assertEqual((meta["proactive"], meta["reaction"], meta["scene"]), (True, "hat-fixture", "fixture-scene"))
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
        db.apply_marong_outfit()
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
            original_hat = catalog.items['hat-fixture']
            catalog.items['hat-fixture'] = replace(original_hat, files={key: value for key, value in original_hat.files.items() if key != 'marong.png'})
            listed_missing = await client.post('/chat/admin/api/items/hat-fixture/list', headers=admin)
            self.assertEqual(listed_missing.status, 200)
            catalog.items['hat-fixture'] = original_hat
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
            protected_tables = ("friend_profiles", "characters", "decor_items", "decor_owned", "outfits", "outfit_firsts", "diary_decor", "diary_stickers")
            def protected_snapshot():
                return tuple(db.admin("SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]'::jsonb) FROM marong." + name + " t")[0][0]
                             for name in protected_tables)
            before_cross_site = protected_snapshot()
            for method, path, session in writes:
                without_origin = {key: value for key, value in session.items() if key != "Origin"}
                for headers in (without_origin, {**session, "Origin": "https://other.invalid"}):
                    with self.subTest(path=path, origin=headers.get("Origin")):
                        error = await method(path, headers=headers, json={})
                        self.assertEqual((error.status, (await error.json())["code"]), (403, "cross_site"))
            self.assertEqual(protected_snapshot(), before_cross_site)
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
            self.assertEqual((await client.get("/chat/decor/v1/hat-fixture/../items.json", headers=member)).status, 404)
            self.assertEqual((await client.get("/chat/admin/api/items", headers=member)).status, 403)
            for action in ("list", "unlist"):
                denied = await client.post(f"/chat/admin/api/items/hat-fixture/{action}", headers=member)
                self.assertEqual((denied.status, (await denied.json())["code"]), (403, "not_allowed"))
                invalid = await client.post(f"/chat/admin/api/items/Bad_ID/{action}", headers=admin)
                self.assertEqual((invalid.status, (await invalid.json())["code"]), (400, "invalid_input"))
            absent = await client.post("/chat/admin/api/items/absent-fixture/unlist", headers=admin)
            self.assertEqual((absent.status, (await absent.json())["code"]), (404, "not_found"))
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
            admin_items = (await (await client.get("/chat/admin/api/items", headers=admin)).json())["items"]
            hat_state = next(item for item in admin_items if item["id"] == "hat-fixture")
            self.assertEqual((hat_state["state"], hat_state["owners"], hat_state["missing"]), ("listed", 1, []))
            invalid_state = next(item for item in admin_items if item["id"] == "bad-fixture")
            self.assertIn("license", invalid_state["missing"])
            unlisted = await client.post("/chat/admin/api/items/hat-fixture/unlist", headers=admin)
            self.assertEqual((unlisted.status, (await unlisted.json())["state"]), (200, "unlisted"))
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
            self.assertEqual(db.admin("SELECT extract(epoch FROM next_at-worn_at) FROM marong.outfit_firsts WHERE character_id=%s AND item_id='hat-fixture'", (character,)), [(180,)])
            self.assertEqual((await client.put(outfit, json=picks, headers={"Origin": ORIGIN})).status, 401)
            self.assertEqual((await client.put("/chat/api/characters/999999999/outfit", headers=other, json=picks)).status, 404)
            oversized = await client.put(outfit, headers=member, json={**picks, "extra": "x" * 17000})
            self.assertEqual(oversized.status, 413)
            closet = await (await client.get("/chat/api/closet", headers=member)).json()
            self.assertEqual(closet["characterId"], character)
            self.assertEqual(closet["outfit"]["head"]["id"], "hat-fixture")
            hat_only = {"head": "hat-fixture", "body": None, "neck": None}
            self.assertEqual((await client.put(outfit, headers=member, json=hat_only)).status, 200)
            hat_closet = await (await client.get("/chat/api/closet", headers=member)).json()
            self.assertEqual(hat_closet["characterId"], character)
            self.assertEqual(hat_closet["outfit"]["head"]["id"], "hat-fixture")
            self.assertIsNone(hat_closet["outfit"]["body"])
            self.assertIsNone(hat_closet["outfit"]["neck"])
            self.assertEqual((await client.put(outfit, headers=member, json=picks)).status, 200)
            profile = await (await client.get("/chat/api/profile", headers=member)).json()
            self.assertEqual(profile["character"]["outfit"]["head"]["id"], "hat-fixture")
            self.assertEqual(profile["character"]["outfit"]["head"]["layerUrl"], image)
            self.assertEqual((await client.get(image, headers=member)).status, 200)
            self.assertNotIn("hat-fixture", [item["id"] for item in (await (await client.get("/chat/api/shop", headers=member)).json())["items"]])
            self.assertIn("hat-fixture", [row["id"] for row in closet["items"]])
            starter_closet = await (await client.get("/chat/api/closet", headers=other)).json()
            self.assertIsNone(starter_closet["outfit"])
            self.assertEqual({row["kind"] for row in starter_closet["items"]}, {"background", "paper", "font"})
            self.assertTrue(all(item["owned"] and item["starter"] for item in starter_closet["items"]))
            self.assertEqual({kind: starter_closet["diaryDecor"][kind]["id"] for kind in ("background", "paper", "font")},
                             {kind: "starter-" + kind for kind in ("background", "paper", "font")})
            draft_id = db.admin("INSERT INTO marong.characters(friend_id,kind) VALUES (%s,'dog') RETURNING id", (friend,))[0][0]
            draft = await client.put(f"/chat/api/characters/{draft_id}/outfit", headers=member, json=picks)
            self.assertEqual((draft.status, (await draft.json())["code"]), (409, "not_ready"))
            misplaced = await client.put(outfit, headers=member, json={**picks, "head": "top-fixture"})
            misplaced_body = await misplaced.json()
            self.assertEqual((misplaced.status, misplaced_body["code"]), (400, "invalid_input"))
            self.assertEqual(misplaced_body["errors"], [{"field": "head", "reason": "wrong_kind"}])
            missing_outfit = await client.put(outfit, headers=member, json={"head": "hat-fixture"})
            self.assertEqual((await missing_outfit.json())["errors"], [{"field": "body", "reason": "required"}, {"field": "neck", "reason": "required"}])
            invalid_outfit = await client.put(outfit, headers=member, json={**picks, "head": "!"})
            self.assertEqual((await invalid_outfit.json())["errors"], [{"field": "head", "reason": "bad_format"}])
            extra_outfit = await client.put(outfit, headers=member, json={**picks, "extra": True})
            self.assertEqual((await extra_outfit.json())["errors"], [{"field": "request", "reason": "bad_format"}])
            two_slots = await client.put(outfit, headers=member, json={"head": "top-fixture", "body": "hat-fixture", "neck": None})
            self.assertEqual((await two_slots.json())["errors"], [{"field": "head", "reason": "wrong_kind"}, {"field": "body", "reason": "wrong_kind"}])
            invalid_character = await client.put("/chat/api/characters/nope/outfit", headers=member, json=picks)
            self.assertEqual((await invalid_character.json())["errors"], [{"field": "id", "reason": "bad_format"}])
            malformed_outfit = await client.put(outfit, headers=member, json=[])
            self.assertEqual((await malformed_outfit.json())["errors"], [{"field": "request", "reason": "bad_format"}])
            unowned = await client.put(outfit, headers=member, json={**picks, "head": "unknown-fixture"})
            self.assertEqual((unowned.status, (await unowned.json())["code"]), (409, "not_owned"))
            self.assertEqual((await client.put(outfit, headers=other, json=picks)).status, 404)
            reactions = DecorReactions(store, None, chat.usage, catalog, None)
            self.assertEqual(await reactions.due(friend), [])
            db.admin("UPDATE marong.outfit_firsts SET next_at=now() WHERE state='waiting'")
            expression = BytesIO()
            Image.new("RGBA", (1024, 1024), "#e6ac87").save(expression, "PNG")
            failed_scene = SimpleNamespace(wait_for_topic=AsyncMock(return_value=None))
            reactions = DecorReactions(store, SimpleNamespace(read=AsyncMock(return_value=expression.getvalue())),
                                       chat.usage, catalog, failed_scene)
            due, = await reactions.due(friend)
            self.assertFalse(due["active"])  # D198: an unlisted reaction item is not drawable.
            self.assertEqual((await client.post("/chat/admin/api/items/hat-fixture/list", headers=admin)).status, 200)
            due, = await reactions.due(friend)
            self.assertTrue(due["active"])
            scene = await reactions.scene(due)
            failed_scene.wait_for_topic.assert_awaited_once()
            await reactions.finish(due, "sent", scene)
            self.assertEqual(db.admin("SELECT format,width,height FROM marong.scene_pictures WHERE id=%s", (scene,)), [("png", 1024, 1024)])
            self.assertEqual(db.admin("SELECT fallback,state,cost_usd FROM marong.scene_pictures WHERE id=%s", (scene,)),
                             [(True, "done", 0)])
            delivery = UnifiedDelivery(store, AppPush(store), "session", lambda: None)
            before_count = await store.proactive_count(timedelta(days=1))
            outcome = await delivery.say(friend, "나 털모자 생겼어! 어때?", kind="proactive", notify=False,
                meta={"proactive": True, "reaction": "hat-fixture", "scene": str(scene)}, key="synthetic-reaction")
            self.assertEqual(outcome, "later")
            self.assertEqual(await store.proactive_count(timedelta(days=1)), before_count + 1)
            delivered = db.admin("SELECT content,meta FROM marong.messages WHERE kakao_id='synthetic-reaction'")
            self.assertEqual(len(delivered), 1)
            self.assertEqual(delivered[0][0], "나 털모자 생겼어! 어때?")
            self.assertEqual({key: delivered[0][1][key] for key in ("proactive", "reaction", "scene")},
                             {"proactive": True, "reaction": "hat-fixture", "scene": str(scene)})
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
            self.assertEqual((await client.get("/chat/diary/api/decor")).status, 401)
            self.assertEqual((await client.put("/chat/diary/api/decor", headers={"Origin": ORIGIN}, json=style)).status, 401)
            oversized_style = await client.put("/chat/diary/api/decor", headers=member, json={**style, "extra": "x" * 17000})
            self.assertEqual(oversized_style.status, 413)
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
            missing_style = await client.put("/chat/diary/api/decor", headers=member, json={"fontId": "starter-font"})
            self.assertEqual(missing_style.status, 400)
            self.assertEqual((await missing_style.json())["errors"], [{"field": "backgroundId", "reason": "required"}, {"field": "paperId", "reason": "required"}])
            self.assertEqual(db.admin("SELECT count(*) FROM marong.diary_decor WHERE friend_id=%s", (friend,)), [(1,)])
            style_path = "/chat/diary/api/decor"
            no_ownership = await client.put(style_path, headers=other, json={**style, "fontId": "unknown-fixture"})
            self.assertEqual((no_ownership.status, (await no_ownership.json())["code"]), (409, "not_owned"))
            wrong_kind = await client.put(style_path, headers=other, json={**style, "fontId": "starter-background"})
            self.assertEqual(wrong_kind.status, 400)
            wrong_body = await wrong_kind.json()
            self.assertEqual(wrong_body["code"], "invalid_input")
            self.assertEqual(wrong_body["errors"], [{"field": "fontId", "reason": "wrong_kind"}])
            bad_style = await client.put(style_path, headers=other, json={**style, "backgroundId": "!"})
            self.assertEqual(bad_style.status, 400)
            self.assertEqual((await bad_style.json())["errors"], [{"field": "backgroundId", "reason": "bad_format"}])
            self.assertEqual((await client.post("/chat/api/shop/sticker-fixture/claim", headers=member)).status, 201)
            sticker_ids = ["sticker-fixture"]
            for index in range(1, 12):
                ident = f"sticker-extra-{index:02}"
                catalog.items[ident] = replace(catalog.items["sticker-fixture"], id=ident, starter=False)
                db.admin("INSERT INTO marong.decor_items(id,item_set,kind,slot,starter) VALUES (%s,'v1','sticker',NULL,false)", (ident,))
                self.assertEqual((await client.post(f"/chat/api/shop/{ident}/claim", headers=member)).status, 201)
                sticker_ids.append(ident)
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
            invalid_date = await client.put(invalid, headers=member, json={"stickers": []})
            self.assertEqual((await invalid_date.json())["errors"], [{"field": "date", "reason": "bad_format"}])
            self.assertEqual((await client.get(path)).status, 401)
            self.assertEqual((await client.put(path, headers={"Origin": ORIGIN}, json={"stickers": []})).status, 401)
            oversized_stickers = await client.put(path, headers=member, json={"stickers": [], "extra": "x" * 17000})
            self.assertEqual(oversized_stickers.status, 413)
            for method, params in ((client.get, {}), (client.put, {"json": {"stickers": [sticker]}})):
                self.assertEqual((await method(missing, headers=member, **params)).status, 404)
                error = await method(invalid, headers=member, **params)
                self.assertEqual((error.status, (await error.json())["code"]), (400, "invalid_input"))
            # Give both synthetic accounts distinct characters, outfits, diary days, stickers and scenes.
            other_friend = (await sessions.find_session(joined.token))["friend_id"]
            other_character = db.admin("""
                INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
                VALUES (%s,'dog','ready','done',now(),'dog_small','시험아이둘','{}') RETURNING id
            """, (other_friend,))[0][0]
            db.admin("UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s", (other_character, other_friend))
            self.assertEqual((await client.post("/chat/admin/api/items/hat-fixture/list", headers=admin)).status, 200)
            self.assertEqual((await client.post("/chat/api/shop/hat-fixture/claim", headers=other)).status, 201)
            self.assertEqual((await client.post("/chat/api/shop/sticker-fixture/claim", headers=other)).status, 201)
            other_outfit = f"/chat/api/characters/{other_character}/outfit"
            self.assertEqual((await client.put(other_outfit, headers=other, json={"head":"hat-fixture", "body":None, "neck":None})).status, 200)
            other_day = day - timedelta(days=2)
            other_diary = db.admin("INSERT INTO marong.diaries(friend_id,diary_date) VALUES (%s,%s) RETURNING id", (other_friend, other_day))[0][0]
            db.admin("INSERT INTO marong.diary_revisions(diary_id,revision,source,title,weather,body) VALUES (%s,1,'weather','합성 일기','sunny',repeat('나',60))", (other_diary,))
            db.admin("UPDATE marong.diaries SET state='ready',ready_at=now(),revision=1 WHERE id=%s", (other_diary,))
            other_stickers = f"/chat/diary/api/days/{other_day}/stickers"
            self.assertEqual((await client.put(path, headers=member, json={"stickers":[sticker]})).status, 200)
            self.assertEqual((await client.put(other_stickers, headers=other, json={"stickers":[sticker]})).status, 200)
            other_scene = db.admin("""
                INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,topic,state,finished_at,format,width,height,image)
                SELECT %s,%s,'topic','v1/fixture','done',now(),format,width,height,image
                FROM marong.scene_pictures WHERE id=%s RETURNING id
            """, (other_friend, other_character, scene))[0][0]
            # TC-554: compare every cross-account response with the same absent-resource path.
            intro = {"personality": ["활발함"], "likes": "시험사생활가", "dislikes": "시험사생활나", "ownerCall": "시험호칭"}
            intro_path = f"/chat/api/characters/{character}/intro"
            self.assertEqual((await client.put(intro_path, headers=member, json=intro)).status, 200)
            self.assertEqual((await client.put(f"/chat/api/characters/{other_character}/intro", headers=other, json=intro)).status, 200)
            absent_id = 999999999
            absent_intro = f"/chat/api/characters/{absent_id}/intro"
            absent_outfit = f"/chat/api/characters/{absent_id}/outfit"
            scene_path = f"/chat/api/scenes/{scene}"
            absent_scene = f"/chat/api/scenes/{uuid4()}"
            snapshots = lambda: tuple(db.admin("SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]'::jsonb) FROM marong." + name + " t")[0][0]
                                      for name in ("characters", "friend_profiles", "decor_owned", "outfits", "outfit_firsts", "diaries", "diary_revisions", "diary_decor", "diary_stickers", "scene_pictures"))
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
                self.assertEqual((await client.put(f"/chat/api/characters/{other_character}/intro", headers=other, json=intro)).status, 200)
                self.assertEqual((await client.get(f"/chat/api/characters/{other_character}/intro", headers=other)).status, 200)
                self.assertEqual((await client.get(f"/chat/api/scenes/{other_scene}", headers=other)).status, 200)
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
                reverse_cases = (
                    (client.get, f"/chat/api/characters/{other_character}/intro", absent_intro, {}),
                    (client.put, f"/chat/api/characters/{other_character}/intro", absent_intro, {"json": intro}),
                    (client.put, other_outfit, absent_outfit, {"json": picks}),
                    (client.get, other_stickers, missing, {}),
                    (client.put, other_stickers, missing, {"json": {"stickers": [sticker]}}),
                    (client.get, f"/chat/api/scenes/{other_scene}", absent_scene, {}),
                )
                for method, foreign, absent, params in reverse_cases:
                    actual = await method(foreign, headers=member, **params)
                    nonexistent = await method(absent, headers=member, **params)
                    self.assertEqual((actual.status, nonexistent.status), (404, 404))
                    self.assertEqual(without_trace(await actual.json()), without_trace(await nonexistent.json()))
                self.assertEqual(snapshots(), before)
            finally:
                root_logger.removeHandler(handler)
                root_logger.setLevel(old_level)
            self.assertFalse(any(marker in line for line in captured for marker in
                                 ("콩이", "시험아이둘", "시험사생활가", "시험사생활나", "시험호칭", "Main character:")))
            origin_mismatch = {**member, "Origin": "https://other.invalid"}
            self.assertEqual((await client.put(path, headers=origin_mismatch, json={"stickers": [sticker]})).status, 403)
            eleven = [{**sticker, "itemId": ident} for ident in sticker_ids[:11]]
            too_many = await client.put(path, headers=member, json={"stickers": eleven})
            self.assertEqual((too_many.status, (await too_many.json())["code"]), (409, "too_many_stickers"))
            unowned_sticker = await client.put(path, headers=member, json={"stickers": [{**sticker, "itemId": "bad-fixture"}]})
            self.assertEqual((unowned_sticker.status, (await unowned_sticker.json())["code"]), (409, "not_owned"))
            trio = [{**sticker, "itemId": ident, "x": value} for ident, value in zip(sticker_ids[:3], (100, 200, 300))]
            self.assertEqual((await client.put(path, headers=member, json={"stickers": trio})).status, 200)
            read_back = await (await client.get(path, headers=member)).json()
            self.assertEqual([{key: item[key] for key in sticker} for item in read_back["stickers"]], trio)
            self.assertEqual((await client.get(path, headers=other)).status, 404)
            self.assertEqual((await client.put(path, headers=other, json={"stickers": [sticker]})).status, 404)
            for key, value in (("x", 1001), ("y", -1), ("scale", 49), ("rotation", 181)):
                with self.subTest(key=key):
                    response = await client.put(path, headers=member, json={"stickers": [{**sticker, key: value}]})
                    self.assertEqual(response.status, 400)
                    self.assertEqual((await response.json())["errors"], [{"field": key, "index": 0, "reason": "out_of_range"}])
            multiple = await client.put(path, headers=member, json={"stickers": [{**sticker, "x": 1001}, {**sticker, "scale": 49}]})
            self.assertEqual((await multiple.json())["errors"], [{"field": "x", "index": 0, "reason": "out_of_range"}, {"field": "scale", "index": 1, "reason": "out_of_range"}])
            wrong_sticker = await client.put(path, headers=member, json={"stickers": [{**sticker, "itemId": "hat-fixture"}]})
            self.assertEqual((await wrong_sticker.json())["errors"], [{"field": "itemId", "index": 0, "reason": "wrong_kind"}])
            bad_id = await client.put(path, headers=member, json={"stickers": [{**sticker, "itemId": "!"}]})
            self.assertEqual((await bad_id.json())["errors"], [{"field": "itemId", "index": 0, "reason": "bad_format"}])
            missing_scale = {key: value for key, value in sticker.items() if key != "scale"}
            missing_entry = await client.put(path, headers=member, json={"stickers": [sticker, missing_scale]})
            self.assertEqual((await missing_entry.json())["errors"], [{"field": "scale", "index": 1, "reason": "required"}])
            malformed_list = await client.put(path, headers=member, json={"stickers": {}})
            self.assertEqual((await malformed_list.json())["errors"], [{"field": "stickers", "reason": "bad_format"}])
            missing_list = await client.put(path, headers=member, json={})
            self.assertEqual((await missing_list.json())["errors"], [{"field": "stickers", "reason": "required"}])
            malformed_entry = await client.put(path, headers=member, json={"stickers": [sticker, None]})
            self.assertEqual((await malformed_entry.json())["errors"], [{"field": "stickers", "index": 1, "reason": "bad_format"}])
            wrong_type = await client.put(path, headers=member, json={"stickers": [{**sticker, "x": True}]})
            self.assertEqual((await wrong_type.json())["errors"], [{"field": "x", "index": 0, "reason": "bad_format"}])
            many_errors = await client.put(path, headers=member, json={"stickers": [{} for _ in range(10)]})
            self.assertEqual(len((await many_errors.json())["errors"]), 10)
            self.assertEqual([{key: item[key] for key in sticker} for item in (await (await client.get(path, headers=member)).json())["stickers"]], trio)
            db.admin("UPDATE marong.diaries SET hidden=true WHERE id=%s", (diary,))
            self.assertEqual((await client.put(path, headers=member, json={"stickers": trio[:2]})).status, 200)
            hidden_items = (await (await client.get(path, headers=member)).json())["stickers"]
            self.assertEqual([{key: item[key] for key in sticker} for item in hidden_items], trio[:2])
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
            # TC-544: same-kind listing order and concurrent claim of a different item.
            catalog.items["hat-second"] = replace(catalog.items["hat-fixture"], id="hat-second", starter=False)
            db.admin("INSERT INTO marong.decor_items(id,item_set,kind,slot,starter,listed_at) VALUES ('hat-second','v1','hat','head',false,now() + interval '1 minute')")
            await client.post("/chat/admin/api/items/hat-fixture/list", headers=admin)
            hats = [item["id"] for item in (await (await client.get("/chat/api/shop", headers=member)).json())["items"] if item["kind"] == "hat"]
            self.assertEqual(hats, ["hat-fixture", "hat-second"])
            second_claims = await asyncio.gather(*(client.post("/chat/api/shop/hat-second/claim", headers=member) for _ in range(2)))
            self.assertEqual(sorted(response.status for response in second_claims), [200, 201])
            self.assertEqual(db.admin("SELECT count(*) FROM marong.decor_owned WHERE friend_id=%s AND item_id='hat-second'", (friend,)), [(1,)])
            self.assertEqual((await client.get("/chat/api/shop")).status, 401)
            self.assertEqual((await client.get("/chat/api/closet")).status, 401)
            self.assertEqual((await client.post("/chat/api/shop/hat-second/claim", headers={"Origin": ORIGIN})).status, 401)
            self.assertEqual(db.admin("""
                SELECT table_name, column_name FROM information_schema.columns
                WHERE table_schema IN ('marong','call')
                  AND (table_name ~* '(^|_)(payments?|orders?|gacha)(_|$)'
                    OR column_name ~* '(^|_)(payments?|orders?|gacha)(_|$)')
            """), [])
            # TC-555: repeat cross-site writes with populated target rows and compare every domain value.
            writes_with_rows = (
                (client.put, intro_path, member, intro),
                (client.post, "/chat/api/shop/hat-fixture/claim", member, {}),
                (client.put, outfit, member, picks),
                (client.put, "/chat/diary/api/decor", member, style),
                (client.put, path, member, {"stickers": [sticker]}),
                (client.post, "/chat/admin/api/items/hat-fixture/list", admin, {}),
                (client.post, "/chat/admin/api/items/hat-fixture/unlist", admin, {}),
            )
            full_before = protected_snapshot()
            for method, endpoint, session, payload in writes_with_rows:
                for origin in (None, "https://other.invalid"):
                    headers = {key: value for key, value in session.items() if key != "Origin"}
                    if origin is not None:
                        headers["Origin"] = origin
                    response = await method(endpoint, headers=headers, json=payload)
                    self.assertEqual((response.status, (await response.json())["code"]), (403, "cross_site"))
            self.assertEqual(protected_snapshot(), full_before)
            chat.decor.catalog = None
            disabled_profile = await (await client.get("/chat/api/profile", headers=member)).json()
            self.assertEqual(disabled_profile["character"]["outfit"], {"head": None, "body": None, "neck": None})
            for endpoint in (image, "/chat/api/shop", "/chat/api/closet", "/chat/diary/api/decor", path):
                self.assertEqual((await client.get(endpoint, headers=member)).status, 404)
            self.assertEqual((await client.get("/chat/admin/api/items", headers=admin)).status, 404)
            self.assertEqual((await client.post("/chat/admin/api/items/hat-fixture/list", headers=admin)).status, 404)


class StickerValidationTests(unittest.TestCase):
    def test_d190_sticker_validation_identifies_fields(self):
        from marong.diary_decor import DiaryDecor
        from marong.app_decor import AppDecor
        from marong.app_chat import Problem

        service = DiaryDecor.__new__(DiaryDecor)
        service.decor = SimpleNamespace(item_key=AppDecor.item_key)
        with self.assertRaises(Problem) as error:
            service.input_sticker({"itemId": "sticker-fixture", "x": 1001, "y": 300, "scale": 49, "rotation": 0})
        self.assertEqual(error.exception.errors, [{"field": "x", "index": 0, "reason": "out_of_range"},
                                                   {"field": "scale", "index": 0, "reason": "out_of_range"}])


if __name__ == "__main__":
    unittest.main()
