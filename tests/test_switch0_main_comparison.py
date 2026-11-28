"""BUG-143: compare switch-off pet behavior with main using two isolated databases."""

import asyncio
import base64
from decimal import Decimal
from io import BytesIO
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]


async def probe():
    # The executable runs with cwd set to the version being measured.
    sys.path.insert(0, os.getcwd())
    from PIL import Image
    from pg import TestDB
    from marong.app_session import AppSessions
    from marong.decor import DecorCatalog
    from marong.decor_reactions import DecorReactions
    from marong.diary_models import ModelResult, parse_picture
    from marong.scene_picture import ScenePictures
    from marong.scene_worker import SceneWorker
    from marong.unified_store import UnifiedStore

    db = TestDB()
    store = None
    try:
        db.apply_unified_prerequisites(); db.apply_unified(); db.apply_pet_app_prerequisites(); db.apply_pet_app(); db.apply_marong_outfit()
        store = UnifiedStore(db.app_url); await store.open(wait=True)
        sessions = AppSessions(store.pool, b'x'*32, contact_schedule=(2,8,22))
        auth = await sessions.join((await sessions.create_invite('join'))[0], '시험친구', '웹')
        friend = (await sessions.find_session(auth.token))['friend_id']
        pet = db.admin("""INSERT INTO marong.characters(friend_id,kind,status,stage,ready_at,template,name,traits)
            VALUES (%s,'dog','ready','done',now(),'dog_small','시험','{}') RETURNING id""", (friend,))[0][0]
        db.admin('UPDATE marong.friend_profiles SET character_id=%s WHERE friend_id=%s', (pet, friend))
        db.admin("INSERT INTO marong.decor_items(id,kind,slot) VALUES ('berry-beanie','hat','head')")
        db.admin("INSERT INTO marong.decor_owned(friend_id,item_id) VALUES (%s,'berry-beanie')", (friend,))
        db.admin("INSERT INTO marong.outfits(character_id,head) VALUES (%s,'berry-beanie')", (pet,))
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,character_id,item_id,next_at) VALUES (%s,%s,'berry-beanie',now())", (friend,pet))
        output = BytesIO(); Image.new('RGB', (12,12), '#442233').save(output, 'WEBP')
        picture = parse_picture(base64.b64encode(output.getvalue()).decode(), square=True)
        catalog = DecorCatalog(); model = AsyncMock(return_value=ModelResult(value=picture,cost=Decimal('.02')))
        media = SimpleNamespace(read=AsyncMock(return_value=b'fixture'))
        picture_args = {'catalog':catalog}
        if 'default_wear' in inspect.signature(ScenePictures).parameters:
            picture_args['default_wear'] = False
        art = ScenePictures(store,media,SimpleNamespace(edit_picture=model),'fixture',**picture_args)
        usage = SimpleNamespace(record=AsyncMock())
        worker_args = {'default_wear':False} if 'default_wear' in inspect.signature(SceneWorker).parameters else {}
        worker = SceneWorker(store,art,usage,**worker_args)
        legacy = db.admin("""INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,topic,state,
            finished_at,format,width,height,image) VALUES (%s,%s,'topic','v1/test','done',now(),'png',1,1,'\\x01') RETURNING id""", (friend,pet))[0][0]
        old = await worker.wait_for_topic({'id':legacy,'state':'done'})
        old_ok = old == legacy
        old_calls = model.await_count

        async def unlist_during_draw(*args, **kwargs):
            db.admin("UPDATE marong.decor_items SET state='unlisted',unlisted_at=now() WHERE id='berry-beanie'")
            return ModelResult(value=picture,cost=Decimal('.02'))
        model.side_effect = unlist_during_draw
        diary = await art.diary_art({'character_id':pet,'friend_id':friend},
                                    'The little white character sits.',None,'sunny','fixture')
        diary_prompt = model.await_args.args[0]
        diary_calls = model.await_count - old_calls
        model.reset_mock(); model.side_effect = None

        reaction_args = {'default_wear':False} if 'default_wear' in inspect.signature(DecorReactions).parameters else {}
        async def draw_job(job):
            await worker.step()
            return await worker.wait_for_topic({'id':job['id'],'state':'done'})
        scenes = SimpleNamespace(wait_for_topic=draw_job)
        reactions = DecorReactions(store,media,usage,catalog,scenes,**reaction_args)
        row, = await reactions.due(friend)
        reaction = await reactions.scene(row) if row['active'] else None
        reaction_prompt = model.await_args.args[0] if model.await_count else ''
        return {'legacy_reused':old_ok, 'legacy_calls':old_calls,
                'diary_outcome':diary.outcome, 'diary_cost':str(diary.cost), 'diary_calls':diary_calls,
                'diary_has_item':catalog.items['berry-beanie'].prompt in diary_prompt,
                'reaction_active':bool(row['active']), 'reaction_picture':reaction is not None,
                'reaction_calls':model.await_count,
                'reaction_has_item':catalog.items['berry-beanie'].prompt in reaction_prompt}
    finally:
        if store is not None:
            await store.close()
        db.close()


class SwitchOffMainComparison(unittest.TestCase):
    def test_bug143_switch_off_matches_main(self):
        with tempfile.TemporaryDirectory(prefix='marong-main-') as directory:
            proc = subprocess.Popen(['git','archive','origin/main'], cwd=ROOT, stdout=subprocess.PIPE)
            with proc.stdout as stream:
                with tarfile.open(fileobj=stream, mode='r|*') as archive:
                    archive.extractall(directory, filter='data')
            self.assertEqual(proc.wait(),0)
            results = []
            for version in (directory, str(ROOT)):
                run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--probe'], cwd=version,
                                     capture_output=True, text=True, check=True)
                results.append(json.loads(run.stdout.strip().splitlines()[-1]))
            self.assertEqual(results[0],results[1])
            self.assertEqual(results[0], {'legacy_reused':True,'legacy_calls':0,'diary_outcome':'ok',
                'diary_cost':'0.02','diary_calls':1,'diary_has_item':True,'reaction_active':True,
                'reaction_picture':True,'reaction_calls':1,'reaction_has_item':True})


if __name__ == '__main__':
    if '--probe' in sys.argv:
        print(json.dumps(asyncio.run(probe()),sort_keys=True))
    else:
        unittest.main()
