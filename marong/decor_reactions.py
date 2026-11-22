"""First-wear reactions, including a local composite if the image model fails."""

import asyncio
from io import BytesIO
import logging

from PIL import Image

from .character.records import CharacterError


log = logging.getLogger(__name__)


def composite(base, layers):
    with Image.open(BytesIO(base)) as image:
        canvas = image.convert("RGBA")
    for layer in layers:
        with Image.open(layer) as image:
            canvas.alpha_composite(image.convert("RGBA"))
    out = BytesIO()
    canvas.save(out, "PNG")
    return out.getvalue(), canvas.width, canvas.height


class DecorReactions:
    def __init__(self, store, media, usage, catalog, scenes):
        self.store = store
        self.media = media
        self.usage = usage
        self.catalog = catalog
        self.scenes = scenes

    async def due(self, friend=None):
        return await self.store._all("""
            SELECT r.id,r.friend_id,r.character_id,r.item_id,r.attempts,c.template,c.name,
                   o.body,o.neck,o.head,coalesce(p.character_id=c.id AND c.status='ready'
                       AND r.item_id IN (o.body,o.neck,o.head), false) AS active
            FROM marong.outfit_firsts r JOIN marong.characters c ON c.id=r.character_id
            LEFT JOIN marong.friend_profiles p ON p.friend_id=r.friend_id
            LEFT JOIN marong.outfits o ON o.character_id=c.id
            WHERE r.state='waiting' AND r.next_at<=now() AND (%s::bigint IS NULL OR r.friend_id=%s)
            ORDER BY r.next_at,r.id LIMIT 40
        """, (friend, friend))

    async def finish(self, row, state, scene=None):
        await self.store._one("""
            UPDATE marong.outfit_firsts SET state=%s,scene_picture_id=%s,finished_at=now()
            WHERE id=%s AND state='waiting' RETURNING id
        """, (state, scene, row["id"]))

    async def defer(self, row, next_at):
        await self.store._one("""
            UPDATE marong.outfit_firsts SET state=CASE WHEN attempts=1 THEN 'blocked' ELSE 'waiting' END,
                finished_at=CASE WHEN attempts=1 THEN now() END,attempts=1,next_at=%s
            WHERE id=%s AND state='waiting' AND attempts=%s RETURNING id
        """, (next_at, row["id"], row["attempts"]))

    async def scene(self, row):
        selections = [row[slot] for slot in ("body", "neck", "head") if row[slot]]
        if self.scenes:
            job = await self.store._one("""
                INSERT INTO marong.scene_pictures(friend_id,character_id,purpose,item_id,outfit)
                VALUES (%s,%s,'reaction',%s,%s) RETURNING id,state
            """, (row["friend_id"], row["character_id"], row["item_id"], selections))
            result = await self.scenes.wait_for_topic(job)
            if result:
                return result
        try:
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
