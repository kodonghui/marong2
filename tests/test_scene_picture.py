"""TC-526–531, with synthetic scenes, models and a temporary database."""

import asyncio
import base64
import logging
from datetime import timedelta
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import secrets
import shutil
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE
from marong.diary import drawing_allowed_in, image_budget
from marong.decor import DecorCatalog
from marong.diary_models import ModelResult, parse_picture
from marong.pet_app_settings import PetAppSettings
from marong.scene_picture import ScenePictures, SceneResult, subject
from marong.scene_worker import SceneWorker
from marong.unified_store import UnifiedStore
from pg import TestDB
from run_app import RoomLocks


PET = {"id": 1, "kind": "dog", "template": "dog_small", "name": "콩이",
       "traits": {"coatColors": ["갈색"], "build": "작음", "breedGuess": "푸들"}}


def picture():
    stream = BytesIO()
    Image.new("RGB", (12, 12), "#442233").save(stream, "WEBP")
    return parse_picture(base64.b64encode(stream.getvalue()).decode(), square=True)


class ScenesTests(unittest.IsolatedAsyncioTestCase):
    async def bug140_setup(self):
        from marong.app_decor import AppDecor
        from marong.decor_reactions import DecorReactions
        db = TestDB(); self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        store = UnifiedStore(db.app_url); await store.open(wait=True); self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool,secrets.token_bytes(32),contact_schedule=(2,8,22))
        auth = await sessions.join((await sessions.create_invite('join'))[0],'시험친구','웹')
        friend = (await sessions.find_session(auth.token))['friend_id']
        db.admin("INSERT INTO marong.decor_items(id,kind,slot) VALUES ('berry-beanie','hat','head'),('oat-sweater','top','body')")
        db.admin("INSERT INTO marong.decor_owned(friend_id,item_id) VALUES (%s,'berry-beanie'),(%s,'oat-sweater')", (friend,friend))
        db.admin("INSERT INTO marong.marong_outfits(friend_id,head,body) VALUES (%s,'berry-beanie','oat-sweater')", (friend,))
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'berry-beanie',now())", (friend,))
        catalog = DecorCatalog()
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        original = catalog.items['berry-beanie']; path = Path(tmp.name) / 'hat.png'
        shutil.copyfile(original.files['marong.png'], path)
        catalog.items[original.id] = replace(original, files={**original.files, 'marong.png': path})
        decor = AppDecor(SimpleNamespace(store=store)); decor.catalog = catalog
        model = AsyncMock(return_value=ModelResult(value=picture(), cost=Decimal('.02')))
        usage = SimpleNamespace(record=AsyncMock())
        art = ScenePictures(store,None,SimpleNamespace(edit_picture=model),'fixture',catalog=catalog)
        worker = SceneWorker(store,art,usage,default_wear=True)
        reactions = DecorReactions(store,None,usage,catalog,worker,default_wear=True)
        return db, store, friend, catalog, path, decor, model, worker, reactions

    async def test_bug140_profile_and_diary_agree_after_layer_removed_or_invalid(self):
        from marong.diary_models import marong_outfit_prompts
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        self.assertEqual((await decor.equipped(friend,'marong'))['head']['id'], 'berry-beanie')
        self.assertIn(catalog.items['berry-beanie'].prompt, await marong_outfit_prompts(store,catalog,friend))
        for invalid in ('missing', 'outside'):
            if invalid == 'missing':
                path.unlink()
            else:
                image = Image.new('RGBA',(1024,1024)); image.putpixel((0,0),(255,0,0,255)); image.save(path)
            with self.subTest(invalid=invalid):
                self.assertIsNone((await decor.equipped(friend,'marong'))['head'])
                self.assertNotIn(catalog.items['berry-beanie'].prompt, await marong_outfit_prompts(store,catalog,friend))
                self.assertIn(catalog.items['oat-sweater'].prompt, await marong_outfit_prompts(store,catalog,friend))

    async def test_bug140_waiting_reaction_inactive_when_layer_removed(self):
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        self.assertTrue((await reactions.due(friend))[0]['active'])
        path.unlink()
        row, = await reactions.due(friend)
        self.assertFalse(row['active'])
        self.assertIsNone(row['head'])

    async def test_bug140_queued_reaction_rechecks_invalid_target_and_other_layers(self):
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'oat-sweater',now())", (friend,))
        rows = {row['item_id']: row for row in await reactions.due(friend)}
        jobs = {ident: await reactions.reaction_job(row) for ident, row in rows.items()}
        path.unlink()
        self.assertEqual(await worker.step(), 2)
        self.assertEqual(model.await_count, 1)
        self.assertEqual(db.admin('SELECT state FROM marong.scene_pictures WHERE id=%s',(jobs['berry-beanie']['id'],)), [('failed',)])
        self.assertEqual(db.admin('SELECT state FROM marong.scene_pictures WHERE id=%s',(jobs['oat-sweater']['id'],)), [('done',)])
        prompt = model.await_args.args[0]
        self.assertNotIn(catalog.items['berry-beanie'].prompt, prompt)
        self.assertIn(catalog.items['oat-sweater'].prompt, prompt)

    async def test_bug140_stale_reaction_fallback_rechecks_layer(self):
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'oat-sweater',now())", (friend,))
        rows = {row['item_id']: row for row in await reactions.due(friend)}
        reactions.scenes = None
        path.unlink()
        self.assertIsNone(await reactions.scene(rows['berry-beanie']))
        image_id = await reactions.scene(rows['oat-sweater'])
        self.assertIsNotNone(image_id)
        self.assertEqual(db.admin('SELECT outfit FROM marong.scene_pictures WHERE id=%s',(image_id,)), [(['oat-sweater'],)])

    async def test_bug140_completed_snapshot_rechecked_before_fallback(self):
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'oat-sweater',now())", (friend,))
        row = next(row for row in await reactions.due(friend) if row['item_id'] == 'oat-sweater')
        async def completed_after_loss(job):
            path.unlink()
            return job['id']
        reactions.scenes = SimpleNamespace(wait_for_topic=completed_after_loss)
        image_id = await reactions.scene(row)
        self.assertEqual(db.admin('SELECT outfit,fallback FROM marong.scene_pictures WHERE id=%s',(image_id,)), [(['oat-sweater'],True)])
        self.assertEqual(db.admin('SELECT count(*) FROM marong.scene_pictures'), [(2,)])

    async def test_bug141_restored_layer_did_not_change_fixed_draw(self):
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'oat-sweater',now())", (friend,))
        row = next(row for row in await reactions.due(friend) if row['item_id'] == 'oat-sweater')
        job = await reactions.reaction_job(row)
        original = path.read_bytes(); path.unlink()
        async def restore_during_draw(*args, **kwargs):
            saved = db.admin('SELECT state,drawn_outfit FROM marong.scene_pictures WHERE id=%s',(job['id'],))[0]
            self.assertEqual(saved[0], 'drawing')
            self.assertEqual([layer['id'] for layer in saved[1]], ['oat-sweater'])
            self.assertEqual(len(saved[1][0]['sha256']), 64)
            path.write_bytes(original)
            return ModelResult(value=picture(), cost=Decimal('.02'))
        model.side_effect = restore_during_draw
        self.assertEqual(await worker.step(), 1)
        self.assertNotIn(catalog.items['berry-beanie'].prompt, model.await_args.args[0])
        result = await reactions.scene(row)
        self.assertEqual(result,job['id'])
        self.assertEqual(db.admin('SELECT fallback FROM marong.scene_pictures WHERE id=%s',(result,)), [(False,)])

    async def test_bug141_changed_layer_hash_invalidates_completed_draw(self):
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'oat-sweater',now())", (friend,))
        row = next(row for row in await reactions.due(friend) if row['item_id'] == 'oat-sweater')
        job = await reactions.reaction_job(row)
        async def change_during_draw(*args, **kwargs):
            image = Image.open(path).convert('RGBA')
            point = image.getchannel('A').getbbox()[:2]
            image.putpixel(point,(123,45,67,255)); image.save(path)
            return ModelResult(value=picture(), cost=Decimal('.02'))
        model.side_effect = change_during_draw
        self.assertEqual(await worker.step(), 1)
        self.assertIsNone(catalog.marong_layer_issue(catalog.items['berry-beanie']))
        result = await reactions.scene(row)
        self.assertNotEqual(result,job['id'])
        self.assertEqual(db.admin('SELECT fallback FROM marong.scene_pictures WHERE id=%s',(result,)), [(True,)])

    async def test_bug142_reaction_keeps_valid_draw_after_changing_other_slot(self):
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'oat-sweater',now())",(friend,))
        row = next(row for row in await reactions.due(friend) if row['item_id'] == 'oat-sweater')
        job = await reactions.reaction_job(row)
        async def draw(*args, **kwargs):
            db.admin('UPDATE marong.marong_outfits SET head=NULL WHERE friend_id=%s',(friend,))
            return ModelResult(value=picture(),cost=Decimal('.02'))
        model.side_effect=draw
        self.assertEqual(await worker.step(),1)
        self.assertEqual(await reactions.scene(row),job['id'])
        self.assertEqual(db.admin('SELECT count(*) FROM marong.scene_pictures'),[(1,)])

    async def test_bug142_reaction_rejects_unlisted_or_unowned_fixed_layer(self):
        for change in ('unlisted','unowned'):
            with self.subTest(change=change):
                db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
                db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'oat-sweater',now())",(friend,))
                row=next(row for row in await reactions.due(friend) if row['item_id']=='oat-sweater')
                job=await reactions.reaction_job(row)
                async def draw(*args, **kwargs):
                    if change=='unlisted':
                        db.admin("UPDATE marong.decor_items SET state='unlisted',unlisted_at=now() WHERE id='berry-beanie'")
                    else:
                        db.admin("DELETE FROM marong.decor_owned WHERE friend_id=%s AND item_id='berry-beanie'",(friend,))
                    return ModelResult(value=picture(),cost=Decimal('.02'))
                model.side_effect=draw
                self.assertEqual(await worker.step(),1)
                result=await reactions.scene(row)
                self.assertNotEqual(result,job['id'])
                self.assertEqual(db.admin('SELECT fallback FROM marong.scene_pictures WHERE id=%s',(result,)),[(True,)])
                self.assertEqual(db.admin('SELECT outfit FROM marong.scene_pictures WHERE id=%s',(result,)),[(['oat-sweater'],)])

    async def test_bug142_pet_scene_rejects_unlisted_fixed_layer(self):
        from marong.topics import picture_set
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        pet=db.admin("""INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
            VALUES (%s,'dog','ready','done',now(),'dog_small','시험','{}') RETURNING id""",(friend,))[0][0]
        db.admin('UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s',(pet,friend))
        db.admin("INSERT INTO marong.outfits(character_id,head) VALUES (%s,'berry-beanie')",(pet,))
        topics=picture_set(); key=f"{topics.set}/{next(iter(topics.by_name))}"
        job=db.admin("INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,topic,outfit) VALUES (%s,%s,'topic',%s,%s) RETURNING id",(friend,pet,key,['berry-beanie']))[0][0]
        worker.default_wear=False
        worker.pictures.media=SimpleNamespace(read=AsyncMock(return_value=b'fixture'))
        async def draw(*args, **kwargs):
            db.admin("UPDATE marong.decor_items SET state='unlisted',unlisted_at=now() WHERE id='berry-beanie'")
            return ModelResult(value=picture(),cost=Decimal('.02'))
        model.side_effect=draw
        self.assertEqual(await worker.step(),1)
        self.assertIsNone(await worker.wait_for_topic({'id':job,'state':'done'}))
        self.assertEqual(model.await_count,1)
        db.admin("UPDATE marong.decor_items SET state='listed',unlisted_at=NULL WHERE id='berry-beanie'")
        legacy=db.admin("""INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,topic,state,
            finished_at,format,width,height,image) VALUES (%s,%s,'topic',%s,'done',now(),'png',1,1,'\\x01') RETURNING id""",(friend,pet,key))[0][0]
        self.assertIsNone(await worker.wait_for_topic({'id':legacy,'state':'done'}))

    async def test_bug142_fixed_snapshot_checks_ownership_per_friend(self):
        from marong.decor import valid_fixed_outfit_snapshot
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        other=db.admin("INSERT INTO marong.friends(name) VALUES ('fixture') RETURNING id")[0][0]
        snapshot=catalog.outfit_snapshot({'head':'berry-beanie','body':None,'neck':None},'marong')
        self.assertTrue(await valid_fixed_outfit_snapshot(store,catalog,friend,snapshot,'marong'))
        self.assertFalse(await valid_fixed_outfit_snapshot(store,catalog,other,snapshot,'marong'))
        db.admin("INSERT INTO marong.decor_owned(friend_id,item_id) VALUES (%s,'berry-beanie')",(other,))
        self.assertTrue(await valid_fixed_outfit_snapshot(store,catalog,other,snapshot,'marong'))

    async def test_bug142_pet_reaction_keeps_valid_snapshot_or_falls_back(self):
        from marong.decor_reactions import DecorReactions
        for action in ('change_selection','unlist'):
            with self.subTest(action=action):
                db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
                pet=db.admin("""INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
                    VALUES (%s,'dog','ready','done',now(),'dog_small','시험','{}') RETURNING id""",(friend,))[0][0]
                db.admin('UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s',(pet,friend))
                db.admin("INSERT INTO marong.outfits(character_id,head,body) VALUES (%s,'berry-beanie','oat-sweater')",(pet,))
                db.admin("INSERT INTO marong.outfit_firsts(friend_id,character_id,item_id,next_at) VALUES (%s,%s,'oat-sweater',now())",(friend,pet))
                expression=(Path(__file__).resolve().parents[1]/'marong/call/static/face/v1/05-excited.webp').read_bytes()
                media=SimpleNamespace(read=AsyncMock(return_value=expression))
                worker.pictures.media=media; reactions=DecorReactions(store,media,SimpleNamespace(record=AsyncMock()),catalog,worker)
                row,=await reactions.due(friend); job=await reactions.reaction_job(row)
                async def draw(*args, **kwargs):
                    if action=='change_selection':
                        db.admin('UPDATE marong.outfits SET head=NULL WHERE character_id=%s',(pet,))
                    else:
                        db.admin("UPDATE marong.decor_items SET state='unlisted',unlisted_at=now() WHERE id='berry-beanie'")
                    return ModelResult(value=picture(),cost=Decimal('.02'))
                model.side_effect=draw
                self.assertEqual(await worker.step(),1)
                result=await reactions.scene(row)
                if action=='change_selection':
                    self.assertEqual(result,job['id'])
                else:
                    self.assertNotEqual(result,job['id'])
                    self.assertEqual(db.admin('SELECT outfit,fallback FROM marong.scene_pictures WHERE id=%s',(result,)),[(['oat-sweater'],True)])
                self.assertEqual(model.await_count,1)

    async def test_bug142_pet_diary_keeps_changed_selection_but_rejects_unlisted_item(self):
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        pet=db.admin("""INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
            VALUES (%s,'dog','ready','done',now(),'dog_small','시험','{}') RETURNING id""",(friend,))[0][0]
        db.admin("INSERT INTO marong.outfits(character_id,head) VALUES (%s,'berry-beanie')",(pet,))
        worker.pictures.media=SimpleNamespace(read=AsyncMock(return_value=b'fixture'))
        async def change_selection(*args, **kwargs):
            db.admin('UPDATE marong.outfits SET head=NULL WHERE character_id=%s',(pet,))
            return ModelResult(value=picture(),cost=Decimal('.02'))
        model.side_effect=change_selection
        row={'character_id':pet,'friend_id':friend}
        result=await worker.pictures.diary_art(row,'The little white character sits.',None,'sunny','fixture')
        self.assertEqual(result.outcome,'ok')
        db.admin("UPDATE marong.outfits SET head='berry-beanie' WHERE character_id=%s",(pet,))
        async def unlist(*args, **kwargs):
            db.admin("UPDATE marong.decor_items SET state='unlisted',unlisted_at=now() WHERE id='berry-beanie'")
            return ModelResult(value=picture(),cost=Decimal('.02'))
        model.side_effect=unlist
        result=await worker.pictures.diary_art(row,'The little white character sits.',None,'sunny','fixture')
        self.assertNotEqual(result.outcome,'ok')
        self.assertEqual(result.cost,Decimal('.02'))

    async def test_bug142_reaction_snapshots_current_outfit_at_worker_start(self):
        for pet_mode in (False,True):
            with self.subTest(pet=pet_mode):
                db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
                if pet_mode:
                    pet=db.admin("""INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
                        VALUES (%s,'dog','ready','done',now(),'dog_small','시험','{}') RETURNING id""",(friend,))[0][0]
                    db.admin('UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s',(pet,friend))
                    db.admin("INSERT INTO marong.outfits(character_id,head,body) VALUES (%s,'berry-beanie','oat-sweater')",(pet,))
                    db.admin("INSERT INTO marong.outfit_firsts(friend_id,character_id,item_id,next_at) VALUES (%s,%s,'oat-sweater',now())",(friend,pet))
                    worker.default_wear=False; reactions.default_wear=False
                    worker.pictures.media=SimpleNamespace(read=AsyncMock(return_value=b'fixture'))
                else:
                    db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'oat-sweater',now())",(friend,))
                row=next(row for row in await reactions.due(friend) if row['item_id']=='oat-sweater')
                job=await reactions.reaction_job(row)
                if pet_mode:
                    db.admin('UPDATE marong.outfits SET head=NULL WHERE character_id=%s',(pet,))
                else:
                    db.admin('UPDATE marong.marong_outfits SET head=NULL WHERE friend_id=%s',(friend,))
                self.assertEqual(await worker.step(),1)
                self.assertNotIn(catalog.items['berry-beanie'].prompt,model.await_args.args[0])
                saved=db.admin('SELECT drawn_outfit FROM marong.scene_pictures WHERE id=%s',(job['id'],))[0][0]
                self.assertEqual([layer['id'] for layer in saved],['oat-sweater'])
                self.assertEqual(await reactions.scene(row),job['id'])

    async def test_tc767_773_gate_then_failed_send_reuses_one_job(self):
        from marong.unified_delivery import AppProactive, UnifiedDelivery
        for pet_mode in (False, True):
            with self.subTest(pet=pet_mode):
                db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
                if pet_mode:
                    pet=db.admin("""INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
                        VALUES (%s,'dog','ready','done',now(),'dog_small','시험','{}') RETURNING id""", (friend,))[0][0]
                    db.admin('UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s',(pet,friend))
                    db.admin("INSERT INTO marong.outfits(character_id,head) VALUES (%s,'berry-beanie')",(pet,))
                    db.admin("INSERT INTO marong.outfit_firsts(friend_id,character_id,item_id,next_at) VALUES (%s,%s,'berry-beanie',now())",(friend,pet))
                    worker.default_wear = False; reactions.default_wear = False
                    worker.pictures.media = SimpleNamespace(read=AsyncMock(return_value=b'fixture'))
                row = next(r for r in await reactions.due(friend) if r['character_id'] == (pet if pet_mode else None))
                job = await reactions.reaction_job(row)
                self.assertEqual(await worker.step(),1)
                await reactions.defer(row,db.admin('SELECT now()')[0][0])
                row = next(r for r in await reactions.due(friend) if r['id'] == row['id'])
                self.assertEqual(row['attempts'],1)
                self.assertEqual((await reactions.reaction_job(row))['id'],job['id'])
                actual = UnifiedDelivery(store,SimpleNamespace(enabled=False),'session',lambda:None)
                calls = []
                async def fail_once(*args, **kwargs):
                    calls.append(kwargs['key'])
                    return None if len(calls)==1 else await actual.say(*args,**kwargs)
                delivery = SimpleNamespace(say=fail_once, push=actual.push)
                loop=AppProactive(SimpleNamespace(),store,SimpleNamespace(proactive_message=AsyncMock(return_value=None)),RoomLocks(),delivery,reactions=reactions)
                loop.reaction_friends={friend}; loop.still_current=AsyncMock(return_value=True)
                store.record_delivery=AsyncMock()
                self.assertIsNone(await loop.priority({'friend_id':friend},None))
                self.assertTrue((await loop.priority({'friend_id':friend},None))['ok'])
                self.assertEqual(calls,[f"app-reaction:{row['id']}"]*2)
                self.assertEqual(db.admin('SELECT scene_job_id,state FROM marong.outfit_firsts WHERE id=%s',(row['id'],)),[(job['id'],'sent')])
                self.assertEqual(db.admin('SELECT count(*) FROM marong.scene_pictures WHERE id=%s',(job['id'],)),[(1,)])
                self.assertEqual(db.admin('SELECT count(*) FROM marong.messages WHERE kakao_id=%s',(calls[0],)),[(1,)])
                self.assertEqual(model.await_count,1)

    async def test_tc767_773_concurrent_priority_shares_job_and_delivery(self):
        from marong.unified_delivery import AppProactive, UnifiedDelivery
        for pet_mode in (False, True):
            with self.subTest(pet=pet_mode):
                db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
                if pet_mode:
                    pet=db.admin("""INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
                        VALUES (%s,'dog','ready','done',now(),'dog_small','시험','{}') RETURNING id""",(friend,))[0][0]
                    db.admin('UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s',(pet,friend))
                    db.admin("INSERT INTO marong.outfits(character_id,head) VALUES (%s,'berry-beanie')",(pet,))
                    db.admin("INSERT INTO marong.outfit_firsts(friend_id,character_id,item_id,next_at) VALUES (%s,%s,'berry-beanie',now())",(friend,pet))
                    worker.default_wear=False; reactions.default_wear=False
                    worker.pictures.media=SimpleNamespace(read=AsyncMock(return_value=b'fixture'))
                entered=0; both=asyncio.Event(); finished=asyncio.Event(); lock=asyncio.Lock()
                async def draw_once(job):
                    nonlocal entered
                    entered += 1
                    if entered==2: both.set()
                    await asyncio.wait_for(both.wait(),timeout=5)
                    async with lock:
                        if not finished.is_set():
                            await worker.step(); finished.set()
                    return await worker.wait_for_topic({'id':job['id'],'state':'done'})
                reactions.scenes=SimpleNamespace(wait_for_topic=draw_once)
                delivery=UnifiedDelivery(store,SimpleNamespace(enabled=False),'session',lambda:None)
                loop=AppProactive(SimpleNamespace(),store,SimpleNamespace(proactive_message=AsyncMock(return_value=None)),RoomLocks(),delivery,reactions=reactions)
                loop.reaction_friends={friend}; loop.still_current=AsyncMock(return_value=True)
                store.record_delivery=AsyncMock()
                results=await asyncio.gather(*(loop.priority({'friend_id':friend},None) for _ in range(2)))
                self.assertTrue(any(result and result['ok'] for result in results))
                condition = 'IS NOT NULL' if pet_mode else 'IS NULL'
                self.assertEqual(db.admin(f"SELECT count(*) FROM marong.scene_pictures WHERE character_id {condition}"),[(1,)])
                first=db.admin(f"SELECT id,state,scene_job_id,scene_picture_id FROM marong.outfit_firsts WHERE character_id {condition}")[0]
                messages=db.admin("SELECT meta->>'scene' FROM marong.messages WHERE kakao_id=%s",(f'app-reaction:{first[0]}',))
                self.assertEqual((first[1],len(messages)),('sent',1))
                self.assertEqual(str(first[2]),messages[0][0]); self.assertEqual(str(first[3]),messages[0][0])
                self.assertEqual(model.await_count,1)

    async def test_tc773_pet_timeout_reuses_job_with_zero_cost_fallback(self):
        from marong.decor_reactions import DecorReactions
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        pet=db.admin("""INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
            VALUES (%s,'dog','ready','done',now(),'dog_small','시험','{}') RETURNING id""", (friend,))[0][0]
        db.admin('UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s',(pet,friend))
        db.admin("INSERT INTO marong.outfits(character_id,head) VALUES (%s,'berry-beanie')",(pet,))
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,character_id,item_id,next_at) VALUES (%s,%s,'berry-beanie',now())",(friend,pet))
        worker.default_wear=False
        expression=(Path(__file__).resolve().parents[1]/'marong/call/static/face/v1/05-excited.webp').read_bytes()
        media=SimpleNamespace(read=AsyncMock(return_value=expression))
        reactions=DecorReactions(store,media,SimpleNamespace(record=AsyncMock()),catalog,worker,default_wear=False)
        row,=await reactions.due(friend)
        with patch('marong.scene_worker.monotonic',side_effect=[0,186,0,186]):
            first=await reactions.scene(row); second=await reactions.scene(row)
        jobs=db.admin("SELECT state,fallback,cost_usd FROM marong.scene_pictures ORDER BY created_at")
        self.assertEqual(jobs,[('queued',False,Decimal(0)),('done',True,Decimal(0)),('done',True,Decimal(0))])
        self.assertNotEqual(first,second)
        self.assertEqual(db.admin('SELECT count(*) FROM marong.scene_pictures WHERE state=%s',('queued',)),[(1,)])
        model.assert_not_awaited()

    async def test_tc767_default_model_failure_cost_and_fallback(self):
        db, store, friend, catalog, path, decor, model, worker, reactions = await self.bug140_setup()
        model.return_value = ModelResult(outcome='error',cost=Decimal('.025'))
        row, = await reactions.due(friend)
        job = await reactions.reaction_job(row)
        self.assertEqual(await worker.step(),1)
        sent = await reactions.scene(row)
        self.assertNotEqual(job['id'],sent)
        self.assertEqual(db.admin('SELECT state,cost_usd,fallback FROM marong.scene_pictures WHERE id=%s',(job['id'],)), [('failed',Decimal('.05'),False)])
        self.assertEqual(db.admin('SELECT state,cost_usd,fallback FROM marong.scene_pictures WHERE id=%s',(sent,)), [('done',Decimal(0),True)])
        self.assertEqual(model.await_count,2)

    async def test_tc773_failure_cost_is_not_lost_in_fallback(self):
        from marong.decor_reactions import DecorReactions
        db=TestDB(); self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        store=UnifiedStore(db.app_url); await store.open(wait=True); self.addAsyncCleanup(store.close)
        sessions=AppSessions(store.pool,secrets.token_bytes(32),contact_schedule=(2,8,22))
        auth=await sessions.join((await sessions.create_invite('join'))[0],'시험친구','웹')
        friend=(await sessions.find_session(auth.token))['friend_id']
        pet=db.admin("""INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
            VALUES (%s,'dog','ready','done',now(),'dog_small','시험','{}') RETURNING id""",(friend,))[0][0]
        db.admin("UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s",(pet,friend))
        db.admin("INSERT INTO marong.decor_items(id,kind,slot) VALUES ('berry-beanie','hat','head')")
        db.admin("INSERT INTO marong.decor_owned(friend_id,item_id) VALUES (%s,'berry-beanie')",(friend,))
        db.admin("INSERT INTO marong.outfits(character_id,head) VALUES (%s,'berry-beanie')",(pet,))
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,character_id,item_id,next_at) VALUES (%s,%s,'berry-beanie',now())",(friend,pet))
        model=AsyncMock(return_value=ModelResult(outcome='error',cost=Decimal('.025')))
        media=SimpleNamespace(read=AsyncMock(return_value=(Path(__file__).resolve().parents[1]/'marong/call/static/face/v1/05-excited.webp').read_bytes()))
        catalog=DecorCatalog()
        art=ScenePictures(store,media,SimpleNamespace(edit_picture=model),'fixture',catalog=catalog)
        worker=SceneWorker(store,art,SimpleNamespace(record=AsyncMock()))
        reactions=DecorReactions(store,media,SimpleNamespace(record=AsyncMock()),catalog,worker)
        row,=await reactions.due(friend)
        job=await reactions.reaction_job(row)
        self.assertEqual(await worker.step(),1)
        sent=await reactions.scene(row)
        self.assertNotEqual(job['id'],sent)
        self.assertEqual(db.admin('SELECT state,cost_usd,fallback FROM marong.scene_pictures WHERE id=%s',(job['id'],)), [('failed',Decimal('.05'),False)])
        self.assertEqual(db.admin('SELECT state,cost_usd,fallback FROM marong.scene_pictures WHERE id=%s',(sent,)), [('done',Decimal(0),True)])
        self.assertEqual(await worker.wait_for_topic({'id':sent,'state':'done'}),sent)
        db.admin('UPDATE marong.friend_profiles SET character_id=NULL WHERE friend_id=%s',(friend,))
        self.assertIsNone(await worker.wait_for_topic({'id':sent,'state':'done'}))

    async def test_tc767_default_fallback_and_reuse(self):
        from marong.decor_reactions import DecorReactions
        db=TestDB(); self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        store=UnifiedStore(db.app_url); await store.open(wait=True); self.addAsyncCleanup(store.close)
        sessions=AppSessions(store.pool,secrets.token_bytes(32),contact_schedule=(2,8,22))
        auth=await sessions.join((await sessions.create_invite('join'))[0],'시험친구','웹')
        friend=(await sessions.find_session(auth.token))['friend_id']
        db.admin("INSERT INTO marong.decor_items(id,kind,slot) VALUES ('berry-beanie','hat','head')")
        db.admin("INSERT INTO marong.decor_owned(friend_id,item_id) VALUES (%s,'berry-beanie')",(friend,))
        db.admin("INSERT INTO marong.marong_outfits(friend_id,head) VALUES (%s,'berry-beanie')", (friend,))
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'berry-beanie',now())", (friend,))
        scenes=SceneWorker(store,None,None,default_wear=True)
        reactions=DecorReactions(store,None,SimpleNamespace(record=AsyncMock()),DecorCatalog(),scenes,default_wear=True)
        row,=await reactions.due(friend)
        self.assertTrue(row['active'])
        with patch('marong.scene_worker.monotonic', side_effect=[0,186,0,186]):
            sent=await reactions.scene(row)
            again=await reactions.scene(row)
        self.assertNotEqual(sent,again)
        jobs=db.admin("SELECT id,state,fallback,cost_usd FROM marong.scene_pictures ORDER BY created_at")
        self.assertEqual(len(jobs),3)
        self.assertEqual([j[1:3] for j in jobs], [('queued',False),('done',True),('done',True)])
        self.assertTrue(all(j[3]==0 for j in jobs))
        self.assertEqual(db.admin('SELECT scene_job_id FROM marong.outfit_firsts WHERE id=%s',(row['id'],)),[(jobs[0][0],)])
        await reactions.finish(row, 'sent', sent)
        db.admin("""UPDATE marong.scene_pictures SET state='done',finished_at=now(),format='png',width=1,height=1,
            image='\\x01',cost_usd=0.02 WHERE id=%s""", (jobs[0][0],))
        self.assertEqual(db.admin('SELECT scene_job_id,scene_picture_id,state FROM marong.outfit_firsts WHERE id=%s', (row['id'],)),
                         [(jobs[0][0],sent,'sent')])

    async def test_tc767_default_reaction_references_and_prompt(self):
        model = AsyncMock(return_value=ModelResult(value=picture(), cost=Decimal('.02')))
        art = ScenePictures(None, None, SimpleNamespace(edit_picture=model), 'fixture')
        result = await art.draw('reaction', None, ['a red hat'], 'The little white character shows the hat.')
        self.assertEqual((result.outcome, result.prompt_version), ('ok', 'scene-marong-v1'))
        prompt, refs = model.await_args.args
        self.assertEqual([ref[1][0] for ref in refs], ['01-neutral.webp', '02-big-laugh.webp'])
        self.assertIn('Wearing: a red hat.', prompt)
        self.assertIn('The little white character is the one in the reference images', prompt)

    async def test_tc767_default_job_uses_worker_and_active_profile(self):
        from marong.decor_reactions import DecorReactions
        db=TestDB(); self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        store=UnifiedStore(db.app_url); await store.open(wait=True); self.addAsyncCleanup(store.close)
        sessions=AppSessions(store.pool,secrets.token_bytes(32),contact_schedule=(2,8,22))
        auth=await sessions.join((await sessions.create_invite('join'))[0],'시험친구','웹')
        friend=(await sessions.find_session(auth.token))['friend_id']
        db.admin("INSERT INTO marong.decor_items(id,kind,slot) VALUES ('berry-beanie','hat','head')")
        db.admin("INSERT INTO marong.decor_owned(friend_id,item_id) VALUES (%s,'berry-beanie')",(friend,))
        db.admin("INSERT INTO marong.marong_outfits(friend_id,head) VALUES (%s,'berry-beanie')",(friend,))
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'berry-beanie',now())",(friend,))
        model=AsyncMock(return_value=ModelResult(value=picture(),cost=Decimal('.02')))
        catalog=DecorCatalog(); usage=SimpleNamespace(record=AsyncMock())
        art=ScenePictures(store,None,SimpleNamespace(edit_picture=model),'fixture',catalog=catalog)
        worker=SceneWorker(store,art,usage,default_wear=True)
        reactions=DecorReactions(store,None,usage,catalog,worker,default_wear=True)
        row,=await reactions.due(friend)
        job=await reactions.reaction_job(row)
        self.assertEqual(await worker.step(),1)
        self.assertEqual(await reactions.scene(row),job['id'])
        self.assertEqual(db.admin('SELECT state,prompt_version,cost_usd,character_id FROM marong.scene_pictures WHERE id=%s',(job['id'],)), [('done','scene-marong-v1',Decimal('.02'),None)])
        self.assertEqual(model.await_count,1)
        pet=db.admin("INSERT INTO marong.characters(friend_id,kind) VALUES (%s,'dog') RETURNING id",(friend,))[0][0]
        db.admin('UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s',(pet,friend))
        self.assertFalse((await reactions.due(friend))[0]['active'])
        self.assertIsNone(await worker.wait_for_topic({'id':job['id'],'state':'done'}))

    async def test_tc767_reaction_sent_through_proactive_with_one_message(self):
        from marong.decor_reactions import DecorReactions
        from marong.unified_delivery import AppProactive, UnifiedDelivery
        db=TestDB(); self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        store=UnifiedStore(db.app_url); await store.open(wait=True); self.addAsyncCleanup(store.close)
        sessions=AppSessions(store.pool,secrets.token_bytes(32),contact_schedule=(2,8,22))
        auth=await sessions.join((await sessions.create_invite('join'))[0],'시험친구','웹')
        friend=(await sessions.find_session(auth.token))['friend_id']
        db.admin("INSERT INTO marong.decor_items(id,kind,slot) VALUES ('berry-beanie','hat','head')")
        db.admin("INSERT INTO marong.decor_owned(friend_id,item_id) VALUES (%s,'berry-beanie')",(friend,))
        db.admin("INSERT INTO marong.marong_outfits(friend_id,head) VALUES (%s,'berry-beanie')",(friend,))
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'berry-beanie',now())",(friend,))
        catalog=DecorCatalog(); usage=SimpleNamespace(record=AsyncMock())
        scenes=SimpleNamespace(wait_for_topic=AsyncMock(return_value=None))
        reactions=DecorReactions(store,None,usage,catalog,scenes,default_wear=True)
        delivery=UnifiedDelivery(store,SimpleNamespace(enabled=False),'session',lambda:None)
        loop=AppProactive(SimpleNamespace(),store,SimpleNamespace(proactive_message=AsyncMock(return_value=None)),RoomLocks(),delivery,reactions=reactions)
        loop.reaction_friends={friend}; loop.still_current=AsyncMock(return_value=True)
        store.record_delivery=AsyncMock()
        result=await loop.priority({'friend_id':friend},None)
        self.assertTrue(result['ok'])
        message=db.admin("SELECT meta->>'reaction',meta->>'scene' FROM marong.messages WHERE kakao_id LIKE %s", ('app-reaction:%',))
        first=db.admin('SELECT state,scene_picture_id FROM marong.outfit_firsts')
        self.assertEqual(len(message),1)
        self.assertEqual((message[0][0],first[0][0],message[0][1]),('berry-beanie','sent',str(first[0][1])))
        self.assertEqual(await loop.priority({'friend_id':friend},None),None)
        self.assertEqual(db.admin("SELECT count(*) FROM marong.messages WHERE kakao_id LIKE %s", ('app-reaction:%',)),[(1,)])

    async def test_tc772_disabled_drains_default_reactions(self):
        from marong.decor_reactions import DecorReactions, drain_default_wear
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        friend = db.admin("INSERT INTO marong.friends(name) VALUES ('fixture') RETURNING id")[0][0]
        db.admin("INSERT INTO marong.decor_items(id,kind,slot) VALUES ('fixture-hat','hat','head')")
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'fixture-hat',now())", (friend,))
        job = db.admin("INSERT INTO marong.scene_pictures(friend_id,purpose,item_id) VALUES (%s,'reaction','fixture-hat') RETURNING id", (friend,))[0][0]
        db.admin("UPDATE marong.outfit_firsts SET scene_job_id=%s", (job,))
        drawing = db.admin("INSERT INTO marong.scene_pictures(friend_id,purpose,item_id,state,lease_until) VALUES (%s,'reaction','fixture-hat','drawing',now()+interval '10 minutes') RETURNING id", (friend,))[0][0]
        store = UnifiedStore(db.app_url)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        reactions = DecorReactions(store, None, None, None, None, default_wear=False)
        self.assertEqual(await reactions.due(), [])
        worker = SceneWorker(store, None, None, default_wear=False)
        self.assertEqual(await worker.step(), 0)
        self.assertEqual(db.admin('SELECT state FROM marong.outfit_firsts'), [('skipped',)])
        self.assertEqual(db.admin('SELECT state,fail_reason,cost_usd FROM marong.scene_pictures WHERE id=%s', (job,)), [('failed','disabled',0)])
        self.assertEqual(db.admin('SELECT state FROM marong.scene_pictures WHERE id=%s', (drawing,)), [('drawing',)])
        db.admin("INSERT INTO marong.decor_items(id,kind,slot) VALUES ('second-hat','hat','head')")
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'second-hat',now()-interval '2 hours')", (friend,))
        reactions.default_wear = True
        self.assertEqual(await reactions.due(), [])
        self.assertEqual(db.admin("SELECT state FROM marong.outfit_firsts WHERE item_id='second-hat'"), [('skipped',)])
        db.admin("UPDATE marong.scene_pictures SET lease_until=now()-interval '1 second' WHERE id=%s", (drawing,))
        await drain_default_wear(store)
        self.assertEqual(db.admin('SELECT state,fail_reason FROM marong.scene_pictures WHERE id=%s', (drawing,)), [('failed','timeout')])

    async def test_tc767_gate_twice_blocks_without_drawing(self):
        from marong.decor_reactions import DecorReactions
        db=TestDB(); self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        store=UnifiedStore(db.app_url); await store.open(wait=True); self.addAsyncCleanup(store.close)
        sessions=AppSessions(store.pool,secrets.token_bytes(32),contact_schedule=(2,8,22))
        auth=await sessions.join((await sessions.create_invite('join'))[0],'시험친구','웹')
        friend=(await sessions.find_session(auth.token))['friend_id']
        db.admin("INSERT INTO marong.decor_items(id,kind,slot) VALUES ('berry-beanie','hat','head')")
        db.admin("INSERT INTO marong.decor_owned(friend_id,item_id) VALUES (%s,'berry-beanie')",(friend,))
        db.admin("INSERT INTO marong.marong_outfits(friend_id,head) VALUES (%s,'berry-beanie')",(friend,))
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'berry-beanie',now())",(friend,))
        scenes=SimpleNamespace(wait_for_topic=AsyncMock())
        reactions=DecorReactions(store,None,None,DecorCatalog(),scenes,default_wear=True)
        row,=await reactions.due(friend)
        await reactions.defer(row,db.admin("SELECT now()")[0][0])
        row,=await reactions.due(friend)
        self.assertEqual(row['attempts'],1)
        await reactions.defer(row,db.admin("SELECT now()")[0][0])
        self.assertEqual(db.admin('SELECT state,attempts FROM marong.outfit_firsts'), [('blocked',1)])
        self.assertEqual(db.admin('SELECT count(*) FROM marong.scene_pictures'), [(0,)])
        scenes.wait_for_topic.assert_not_awaited()

    async def test_scene_prompts_references_retries_and_cost(self):
        self.assertEqual(subject({"kind": "dog"}), "a small dog")
        self.assertEqual(subject(PET), "a small brown poodle")
        output = picture()
        with self.assertRaisesRegex(ValueError, "image_shape"):
            parse_picture(base64.b64encode(output.data).decode())
        model = AsyncMock(return_value=ModelResult(value=output, cost=Decimal(".025"), estimated=True))
        store = SimpleNamespace(pool=SimpleNamespace(connection=patch_connection()))
        media = SimpleNamespace(read=AsyncMock(return_value=b"reference"))
        art = ScenePictures(store, media, SimpleNamespace(edit_picture=model), "fixture")
        for purpose, expression, size in (("topic", "smile", "1024x1024"), ("reaction", "excited", "1024x1024"),
                                           ("diary", "sad", "1536x1024"), ("topic", "smile", "1024x1024")):
            result = await art.draw(purpose, PET, ["a red beanie"], "Marong sits with 가나 and 콩이.",
                                    weather="rain", friend_name="가나")
            self.assertEqual((result.outcome, result.cost, result.estimated), ("ok", Decimal(".025"), True))
            prompt, refs = model.await_args.args
            self.assertEqual([item[1][0] for item in refs], ["front.png", expression + ".png"])
            self.assertIn("Main character: a small brown poodle", prompt)
            self.assertIn("Wearing: a red beanie.", prompt)
            self.assertIn("No text, letters or numbers", prompt)
            for private in ("Marong", "콩이", "가나"):
                self.assertNotIn(private, prompt)
            self.assertEqual(model.await_args.kwargs, {
                "model": "fixture", "size": size, "output_format": "webp", "deadline": 90, "estimate_errors": True,
            })
        self.assertEqual(model.await_count, 4)
        # TC-554: include a synthetic scene description while capturing every application logger.
        records = []
        class Capture(logging.Handler):
            def emit(self, record): records.append(record.getMessage())
        handler = Capture()
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        try:
            await art.draw("topic", PET, (), "시험장면지시 가나다 콩이", friend_name="가나다")
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)
        self.assertFalse(any(marker in line for line in records for marker in ("시험장면지시", "가나다", "콩이", "Main character:")))

        for outcomes, expected, reason, cost in (
            (["refused"], "refused", "refused", ".025"),
            (["error", "error"], "failed", "model_error", ".05"),
            (["timeout", "ok"], "ok", None, ".05"),
            (["invalid"], "failed", "check_failed", ".025"),
        ):
            model.reset_mock()
            model.side_effect = [ModelResult(value=output if status == "ok" else None, outcome=status,
                                             cost=Decimal(".025"), estimated=True) for status in outcomes]
            result = await art.draw("topic", PET, (), "A basket sits in the snow.")
            self.assertEqual((result.outcome, result.reason, result.cost), (expected, reason, Decimal(cost)))
            self.assertEqual(model.await_count, len(outcomes))

    async def test_tc554_scene_worker_logs_omit_prompt_and_names(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        store = UnifiedStore(db.app_url)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22))
        auth = await sessions.join((await sessions.create_invite("join"))[0], "합성친구이름", "웹")
        friend = (await sessions.find_session(auth.token))["friend_id"]
        character = db.admin("""
            INSERT INTO marong.characters(friend_id,kind,template,name,traits,stage,status,ready_at)
            VALUES (%s,'dog','dog_small','시험아이이름','{}','done','ready',now()) RETURNING id
        """, (friend,))[0][0]
        db.admin("UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s", (character, friend))
        catalog = DecorCatalog()
        item = catalog.items["berry-beanie"]
        catalog.items[item.id] = replace(item, prompt="시험장면지시")
        db.admin("INSERT INTO marong.decor_items(id,item_set,kind,slot,starter) VALUES (%s,'v1','hat','head',false)", (item.id,))
        db.admin("INSERT INTO marong.decor_owned(friend_id,item_id) VALUES (%s,%s)", (friend,item.id))
        db.admin("INSERT INTO marong.outfits(character_id,head) VALUES (%s,%s)", (character,item.id))
        db.admin("""INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,item_id,outfit)
                    VALUES (%s,%s,'reaction',%s,ARRAY[%s])""", (friend, character, item.id, item.id))
        model = AsyncMock(return_value=ModelResult(value=picture(), cost=Decimal("0")))
        media = SimpleNamespace(read=AsyncMock(return_value=b"synthetic"))
        art = ScenePictures(store, media, SimpleNamespace(edit_picture=model), "fixture", catalog=catalog)
        worker = SceneWorker(store, art, SimpleNamespace(record=AsyncMock()))
        job, = await worker.claim()
        records = []
        class Capture(logging.Handler):
            def emit(self, record): records.append(record.getMessage())
        handler = Capture(); root = logging.getLogger(); old = root.level
        root.addHandler(handler); root.setLevel(logging.INFO)
        try:
            await worker.process(job)
        finally:
            root.removeHandler(handler); root.setLevel(old)
        self.assertEqual(model.await_count, 1)
        self.assertTrue(any("scene_finished" in line for line in records))
        self.assertFalse(any(marker in line for line in records for marker in
                             ("합성친구이름", "시험아이이름", "시험장면지시", "Main character:")))

    async def test_leases_usage_and_owner_only_picture_endpoint(self):
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

        async def account():
            invite, _ = await sessions.create_invite("join")
            auth = await sessions.join(invite, "합성 친구", "웹")
            friend = (await sessions.find_session(auth.token))["friend_id"]
            ident = db.admin("""
                INSERT INTO marong.characters(friend_id,kind,template,name,traits,stage,status,ready_at)
                VALUES (%s,'dog','dog_small','콩이','{}','done','ready',now()) RETURNING id
            """, (friend,))[0][0]
            return {"Cookie": f"{COOKIE}={auth.token}"}, friend, ident

        owner, friend, ident = await account()
        outsider, other, other_ident = await account()
        chat = AppChat(store, SimpleNamespace(friend_cards=None), RoomLocks(), None, AppPush(store),
                       sessions=sessions, authentication="session", admin_email_hash="a" * 64,
                       pet_app_settings=PetAppSettings(diary_image_budget=None))
        chat.access = SimpleNamespace(check=AsyncMock(return_value=("ok", "a" * 64)))
        worker = SceneWorker(store, None, chat.usage)

        def queue(who, character, count):
            return [row[0] for row in db.admin("""
                INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,topic,not_before)
                SELECT %s,%s,'topic','v1/snow',now()-make_interval(mins=>6-n)
                FROM generate_series(1,%s) n RETURNING id
            """, (who, character, count))]

        ids = queue(friend, ident, 4)
        other_id = queue(other, other_ident, 1)[0]
        first = await worker.claim()
        self.assertEqual({row["id"] for row in first}, {ids[0], other_id})
        db.admin("UPDATE marong.scene_pictures SET lease_until=now()-interval '1 second' WHERE state='drawing'")
        await worker.recover()
        self.assertEqual(db.admin("SELECT count(*) FROM marong.scene_pictures WHERE state='queued'"), [(5,)])
        self.assertEqual(len(await worker.claim()), 2)
        db.admin("UPDATE marong.scene_pictures SET lease_until=now()-interval '1 second',attempts=3 WHERE id=%s", (other_id,))
        await worker.recover()
        self.assertEqual(db.admin("SELECT state,fail_reason FROM marong.scene_pictures WHERE id=%s", (other_id,)),
                         [("failed", "timeout")])
        output = picture()
        success = SceneResult("ok", None, output, Decimal(".01"), False, "fixture")
        failure = SceneResult("refused", "refused", None, Decimal(".025"), True, "fixture")
        self.assertFalse(await worker.finish(first[0], success))
        jobs = await worker.claim()
        self.assertEqual(len(jobs), 2)
        await asyncio.gather(*(worker.finish(job, result) for job, result in zip(jobs, (success, failure))))
        self.assertFalse(await worker.finish(jobs[0], success))
        self.assertEqual((await chat.usage.get(friend))["images"], 1)
        db.admin("UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s", (ident, friend))
        future = sessions.now() + timedelta(hours=1)
        prefetch = await worker.topic_job(friend, "v1/snow", future)
        self.assertEqual(await worker.topic_job(friend, "v1/snow", future), prefetch)
        self.assertEqual(db.admin("SELECT not_before FROM marong.scene_pictures WHERE id=%s", (prefetch["id"],))[0][0],
                         future - timedelta(minutes=30))
        db.admin("UPDATE marong.scene_pictures SET cost_usd=.25 WHERE id=%s", (jobs[0]["id"],))
        db.admin("UPDATE marong.scene_pictures SET cost_usd=.25 WHERE id=%s", (jobs[1]["id"],))
        diary_id = db.admin("INSERT INTO marong.diaries(friend_id,diary_date) VALUES (%s,current_date) RETURNING id",
                            (friend,))[0][0]
        db.admin("""
            INSERT INTO marong.diary_ai_runs(diary_id,kind,origin,trace_id,model,prompt_version,sent_at,cost_usd,outcome)
            VALUES (%s,'draw','night','fixture','fixture','diary-v1',now(),2,'ok')
        """, (diary_id,))
        db.admin("""
            INSERT INTO marong.character_jobs(character_id,step,state,finished_at,cost_usd)
            VALUES (%s,'sheet','done',now(),3)
        """, (ident,))

        async with TestClient(TestServer(chat.web_app())) as client:
            api = "/chat/api/scenes/"
            response = await client.get(api + str(jobs[0]["id"]), headers=owner)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, "image/webp")
            self.assertEqual(response.headers["Cache-Control"], "private, max-age=31536000")
            self.assertEqual(await response.read(), output.data)
            self.assertEqual((await client.get(api + "abc", headers=owner)).status, 400)
            self.assertEqual((await client.get(api + str(jobs[0]["id"]))).status, 401)
            attempts = [(jobs[0]["id"], outsider), (jobs[1]["id"], owner), (uuid4(), owner)]
            for key, headers in attempts:
                found = await client.get(api + str(key), headers=headers)
                self.assertEqual((found.status, (await found.json())["code"]), (404, "not_found"))
            costs = "/chat/admin/api/image-costs"
            self.assertEqual((await client.get(costs, headers=owner)).status, 403)
            response = await client.get(costs, headers={"Cf-Access-Jwt-Assertion": "fixture"})
            self.assertEqual(response.status, 200)
            costs = await response.json()
            self.assertEqual(costs["byKind"], {"diary": 2, "topic": .5, "reaction": 0, "character": 3})
            self.assertIsNone(costs["budgets"]["diary"])
            self.assertEqual(costs["budgets"]["character"]["ratio"], .15)
        conn = SimpleNamespace(execute=AsyncMock())
        self.assertTrue(await drawing_allowed_in(conn, image_budget(" UNLIMITED "), sessions.now()))
        conn.execute.assert_not_called()


def patch_connection():
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def connection():
        yield object()

    return connection


if __name__ == "__main__":
    unittest.main()
