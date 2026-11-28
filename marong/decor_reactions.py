"""First-wear reactions, including a local composite if the image model fails."""

import asyncio
from io import BytesIO
import logging

from PIL import Image

from .character.records import CharacterError
from .diary_models import REFERENCES
from .room_scope import writing_room_key


log = logging.getLogger(__name__)


async def drain_default_wear(store):
    """Close queued default reactions while disabled, including when decor workers are off."""
    async with store.pool.connection() as conn, conn.transaction():
        await conn.execute("""UPDATE marong.outfit_firsts SET state='skipped',finished_at=now()
            WHERE character_id IS NULL AND state='waiting'""")
        await conn.execute("""UPDATE marong.scene_pictures SET state='failed',fail_reason='disabled',finished_at=now()
            WHERE character_id IS NULL AND purpose='reaction' AND state='queued'""")
        await conn.execute("""UPDATE marong.scene_pictures SET state='failed',fail_reason='timeout',finished_at=now(),lease_until=NULL
            WHERE character_id IS NULL AND purpose='reaction' AND state='drawing' AND lease_until<=now()""")


async def drain_default_wear_loop(store):
    while True:
        try:
            await drain_default_wear(store)
        except Exception as error:
            log.warning('default_wear_drain_error error=%s', type(error).__name__)
        await asyncio.sleep(1)


def composite(base, layers):
    with Image.open(BytesIO(base)) as image:
        canvas = image.convert("RGBA")
    if canvas.size != (1024, 1024):
        canvas = canvas.resize((1024, 1024), Image.Resampling.LANCZOS)
    for layer in layers:
        with Image.open(layer) as image:
            canvas.alpha_composite(image.convert("RGBA"))
    out = BytesIO()
    canvas.save(out, "PNG")
    return out.getvalue(), canvas.width, canvas.height


class DecorReactions:
    def __init__(self, store, media, usage, catalog, scenes, *, default_wear=False):
        self.store = store
        self.media = media
        self.usage = usage
        self.catalog = catalog
        self.scenes = scenes
        self.default_wear = default_wear
        self._stale_drained = False

    async def due(self, friend=None):
        if not self.default_wear:
            await self.store._one("""WITH skipped AS (UPDATE marong.outfit_firsts SET state='skipped',finished_at=now()
                WHERE character_id IS NULL AND state='waiting' RETURNING id) SELECT count(*) FROM skipped""")
        elif not self._stale_drained:
            await self.store._one("""WITH skipped AS (UPDATE marong.outfit_firsts SET state='skipped',finished_at=now()
                WHERE character_id IS NULL AND state='waiting' AND next_at < now()-interval '1 hour' RETURNING id)
                SELECT count(*) FROM skipped""")
            self._stale_drained = True
        rows = await self.store._all("""
            SELECT r.id,r.friend_id,r.character_id,r.item_id,r.attempts,coalesce(c.template,'marong') AS template,
                   coalesce(c.name,p.bot_name) AS name,
                   CASE WHEN r.character_id IS NULL THEN mo.body ELSE o.body END AS body,
                   CASE WHEN r.character_id IS NULL THEN mo.neck ELSE o.neck END AS neck,
                   CASE WHEN r.character_id IS NULL THEN mo.head ELSE o.head END AS head,
                   coalesce(CASE WHEN r.character_id IS NULL THEN p.character_id IS NULL
                       AND r.item_id IN (mo.body,mo.neck,mo.head)
                       ELSE p.character_id=c.id AND c.status='ready' AND r.item_id IN (o.body,o.neck,o.head) END, false) AS active
            FROM marong.outfit_firsts r LEFT JOIN marong.characters c ON c.id=r.character_id
            LEFT JOIN marong.friend_profiles p ON p.friend_id=r.friend_id
            LEFT JOIN marong.outfits o ON o.character_id=c.id
            LEFT JOIN marong.marong_outfits mo ON mo.friend_id=r.friend_id AND r.character_id IS NULL
            WHERE r.state='waiting' AND r.next_at<=now() AND (%s::bigint IS NULL OR r.friend_id=%s)
            ORDER BY r.next_at,r.id LIMIT 40
        """, (friend, friend))
        def validate():
            result = []
            for row in rows:
                row = dict(row)
                if row['character_id'] is None:
                    outfit = self.catalog.valid_marong_outfit(row) if self.catalog else dict.fromkeys(('body', 'neck', 'head'))
                    row.update(outfit)
                    row['active'] = row['active'] and row['item_id'] in outfit.values()
                result.append(row)
            return result
        return await asyncio.to_thread(validate)

    async def finish(self, row, state, scene=None):
        await self.store._one(f"""
            UPDATE marong.outfit_firsts SET state=%s,scene_picture_id=CASE WHEN %s='sent' THEN
                COALESCE((SELECT (m.meta->>'scene')::uuid FROM marong.messages m
                    WHERE m.room_key={writing_room_key('outfit_firsts.friend_id')} AND m.kakao_id='app-reaction:' || outfit_firsts.id::text),%s)
                ELSE %s END,finished_at=now()
            WHERE id=%s AND state='waiting' RETURNING id
        """, (state, state, scene, scene, row["id"]))

    async def defer(self, row, next_at):
        await self.store._one("""
            UPDATE marong.outfit_firsts SET state=CASE WHEN attempts=1 THEN 'blocked' ELSE 'waiting' END,
                finished_at=CASE WHEN attempts=1 THEN now() END,attempts=1,next_at=%s
            WHERE id=%s AND state='waiting' AND attempts=%s RETURNING id
        """, (next_at, row["id"], row["attempts"]))

    async def reaction_job(self, row, *, after_insert=None):
        selections = [row[slot] for slot in ('body', 'neck', 'head') if row[slot]]
        async with self.store.pool.connection() as conn, conn.transaction():
            cursor = await conn.execute('SELECT state,scene_job_id FROM marong.outfit_firsts WHERE id=%s FOR UPDATE', (row['id'],))
            first = await cursor.fetchone()
            if not first or first['state'] != 'waiting':
                return None
            if first['scene_job_id']:
                cursor = await conn.execute('SELECT id,state FROM marong.scene_pictures WHERE id=%s', (first['scene_job_id'],))
                return await cursor.fetchone()
            cursor = await conn.execute("""INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,item_id,outfit)
                VALUES (%s,%s,'reaction',%s,%s) RETURNING id,state""",
                (row['friend_id'], row['character_id'], row['item_id'], selections))
            job = await cursor.fetchone()
            if after_insert:
                after_insert()
            await conn.execute('UPDATE marong.outfit_firsts SET scene_job_id=%s WHERE id=%s', (job['id'], row['id']))
            return job

    async def scene(self, row):
        async def current_selections():
            if row['character_id'] is None:
                outfit = await asyncio.to_thread(self.catalog.valid_marong_outfit, row)
                if row['item_id'] not in outfit.values():
                    return None
                return [outfit[slot] for slot in ('body', 'neck', 'head') if outfit[slot]]
            return [row[slot] for slot in ('body', 'neck', 'head') if row[slot]]

        selections = await current_selections()
        if selections is None:
            return None
        if row['character_id'] is None:
            row = {**row, **{slot: next((ident for ident in selections if self.catalog.items[ident].slot == slot), None)
                             for slot in ('body', 'neck', 'head')}}
        if self.scenes:
            job = await self.reaction_job(row)
            if not job:
                return None
            result = await self.scenes.wait_for_topic(job)
            if result:
                if row['character_id'] is not None:
                    return result
                current = await current_selections()
                if current is None:
                    return None
                snapshot = await self.store._one('SELECT outfit FROM marong.scene_pictures WHERE id=%s', (result,))
                if snapshot and snapshot['outfit'] == current:
                    return result
        selections = await current_selections()
        if selections is None:
            return None
        try:
            if row['character_id'] is None:
                expression = (REFERENCES / '05-excited.webp').read_bytes()
            else:
                async with self.store.pool.connection() as conn:
                    expression = await self.media.read(conn, row["character_id"], "excited")
            key = row["template"] + ".png"
            paths = [self.catalog.items[ident].files[key] for ident in selections
                     if ident in self.catalog.items and key in self.catalog.items[ident].files]
            data, width, height = await asyncio.to_thread(composite, expression, paths)
        except (CharacterError, OSError, ValueError, TypeError) as error:
            log.warning("reaction_composite_error character=%s error=%s", row["character_id"], type(error).__name__)
            return None
        async with self.store.pool.connection() as conn, conn.transaction():
            cursor = await conn.execute("""
                INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,item_id,outfit,
                    state,finished_at,fallback,format,width,height,image)
                VALUES (%s,%s,'reaction',%s,%s,'done',now(),true,'png',%s,%s,%s) RETURNING id
            """, (row["friend_id"], row["character_id"], row["item_id"], selections, width, height, data))
            done = await cursor.fetchone()
            await self.usage.record(row["friend_id"], conn=conn, images=1)
        return done["id"]
