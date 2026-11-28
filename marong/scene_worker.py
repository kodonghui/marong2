"""Lease and publish scene jobs. The app owns image generation and all picture reads."""

import asyncio
from datetime import timedelta
import logging
from time import monotonic

from psycopg.types.json import Jsonb

from .topics import picture_set
from .decor import available_outfit_snapshot, valid_fixed_outfit_snapshot


log = logging.getLogger(__name__)


class SceneWorker:
    def __init__(self, store, pictures, usage, *, default_wear=False):
        self.store = store
        self.pictures = pictures
        self.usage = usage
        self.default_wear = default_wear

    async def topic_job(self, friend, key, at, *, queue=True):
        """Keep one job per planned topic and selected character, including prefetch retries."""
        due = at - timedelta(minutes=30)
        async with self.store.pool.connection() as conn, conn.transaction():
            profile = await (await conn.execute("""
                SELECT c.id,o.body,o.neck,o.head FROM marong.friend_profiles p
                JOIN marong.characters c ON c.id=p.character_id AND c.friend_id=p.friend_id AND c.status='ready'
                LEFT JOIN marong.outfits o ON o.character_id=c.id
                WHERE p.friend_id=%s FOR UPDATE OF p
            """, (friend,))).fetchone()
            if profile is None:
                return None
            params = (friend, profile["id"], key, due)
            job = await (await conn.execute("""
                SELECT id,state FROM marong.scene_pictures
                WHERE friend_id=%s AND character_id=%s AND topic=%s AND not_before=%s AND purpose='topic'
                ORDER BY created_at LIMIT 1
            """, params)).fetchone()
            if job or not queue:
                return job
            return await (await conn.execute("""
                INSERT INTO marong.scene_pictures(friend_id,character_id,topic,not_before,purpose,outfit,drawn_outfit)
                VALUES (%s,%s,%s,%s,'topic',%s,%s) RETURNING id,state
            """, (*params, [profile[key] for key in ("body", "neck", "head") if profile[key]],
                  Jsonb({'version': 1}) if self.default_wear else None))).fetchone()

    async def wait_for_topic(self, job):
        if not job:
            return None
        deadline = monotonic() + 185
        while job["state"] in {"queued", "drawing"} and monotonic() < deadline:
            await asyncio.sleep(.5)
            job = await self.store._one("SELECT id,state FROM marong.scene_pictures WHERE id=%s", (job["id"],))
            if job is None:
                return None
        return await self.confirm_topic(job)

    async def confirm_topic(self, job):
        """Validate a completed scene without waiting for queued work."""
        if not job or job['state'] != 'done':
            return None
        active = await self.store._one("""
            SELECT s.id,s.friend_id,s.character_id,s.drawn_outfit,c.template FROM marong.scene_pictures s
            JOIN marong.friend_profiles p ON p.friend_id=s.friend_id AND p.character_id IS NOT DISTINCT FROM s.character_id
            LEFT JOIN marong.characters c ON c.id=s.character_id
            WHERE s.id=%s
        """, (job["id"],))
        if not active:
            return None
        if active['drawn_outfit'] is None and active['character_id'] is not None:
            return active['id']
        catalog = self.pictures.catalog if self.pictures else None
        template = active['template'] if active['character_id'] is not None else 'marong'
        if not await valid_fixed_outfit_snapshot(self.store, catalog, active['friend_id'], active['drawn_outfit'], template):
            return None
        return active['id']

    async def recover(self):
        async with self.store.pool.connection() as conn, conn.transaction():
            await conn.execute("""
                UPDATE marong.scene_pictures SET
                    state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,
                    fail_reason=CASE WHEN attempts>=3 THEN 'timeout' END,
                    finished_at=CASE WHEN attempts>=3 THEN now() END,
                    lease_until=NULL
                WHERE state='drawing' AND lease_until<=now()
            """)

    async def claim(self):
        async with self.store.pool.connection() as conn, conn.transaction():
            cur = await conn.execute("""
                WITH due AS (
                    SELECT id FROM marong.scene_pictures
                    WHERE state='queued' AND not_before<=now() AND attempts<3 AND (%s OR character_id IS NOT NULL)
                    ORDER BY not_before, created_at, id LIMIT 2 FOR UPDATE SKIP LOCKED
                )
                UPDATE marong.scene_pictures s SET state='drawing', lease_until=now()+interval '10 minutes',
                    started_at=now(), attempts=s.attempts+1
                FROM due WHERE s.id=due.id RETURNING s.*
            """, (self.default_wear,))
            return await cur.fetchall()

    async def finish(self, job, result, *, fail_reason=None):
        picture = result.picture if result else None
        reason = result.reason if result else fail_reason
        async with self.store.pool.connection() as conn, conn.transaction():
            cursor = await conn.execute("""
                UPDATE marong.scene_pictures SET state=%s, fail_reason=%s, lease_until=NULL, finished_at=now(),
                    model=%s, prompt_version=%s, cost_usd=%s, cost_estimated=%s,
                    format=%s, width=%s, height=%s, image=%s
                WHERE id=%s AND state='drawing' AND lease_until=%s AND attempts=%s RETURNING friend_id
            """, ("done" if picture else "failed", reason, result.model if result else None,
                  result.prompt_version if result else None, result.cost if result else 0,
                  result.estimated if result else False, picture.format if picture else None,
                  picture.width if picture else None, picture.height if picture else None,
                  picture.data if picture else None, job["id"], job["lease_until"], job["attempts"]))
            updated = await cursor.fetchone()
            if updated and picture:
                await self.usage.record(updated["friend_id"], conn=conn, images=1)
        return updated is not None

    async def record_drawn_outfit(self, job, snapshot):
        async with self.store.pool.connection() as conn, conn.transaction():
            cursor = await conn.execute("""UPDATE marong.scene_pictures SET drawn_outfit=%s
                WHERE id=%s AND state='drawing' AND lease_until=%s AND attempts=%s RETURNING id""",
                (Jsonb(snapshot), job['id'], job['lease_until'], job['attempts']))
            return await cursor.fetchone() is not None

    async def process(self, job):
        started = monotonic()
        character = await self.store._one("""
            SELECT c.id,c.kind,c.template,c.traits,c.name,o.body,o.neck,o.head FROM marong.characters c
            LEFT JOIN marong.outfits o ON o.character_id=c.id
            WHERE c.id=%s AND c.friend_id=%s AND c.status='ready'
        """, (job["character_id"], job["friend_id"]))
        topics = picture_set()
        topic = topics.get(job["topic"]) if topics and job["purpose"] == "topic" else None
        result = None
        drawn_outfit = None
        if character and job['drawn_outfit'] is None:
            outfit = self.pictures.outfit_prompts(job['outfit'])
            if topic:
                result = await self.pictures.draw('topic', character, outfit, topic.scene)
            elif job['purpose'] == 'reaction':
                item = self.pictures.catalog.items.get(job['item_id']) if self.pictures.catalog else None
                if item and item.prompt:
                    scene = f"The pet character proudly shows off the new {item.prompt}, looking at the viewer."
                    result = await self.pictures.draw('reaction', character, outfit, scene)
        elif character or (job['character_id'] is None and self.default_wear and job['purpose'] == 'reaction'):
            catalog = self.pictures.catalog
            template = character['template'] if character is not None else 'marong'
            by_slot = character if character is not None else await self.store._one(
                'SELECT body,neck,head FROM marong.marong_outfits WHERE friend_id=%s', (job['friend_id'],))
            drawn_outfit = await available_outfit_snapshot(self.store, catalog, job['friend_id'], by_slot, template)
            selections = [layer['id'] for layer in drawn_outfit]
            outfit = self.pictures.outfit_prompts(selections)
            if topic:
                if not await self.record_drawn_outfit(job, drawn_outfit):
                    return
                result = await self.pictures.draw("topic", character, outfit, topic.scene)
            elif job["purpose"] == "reaction":
                item = catalog.items.get(job["item_id"]) if catalog else None
                if item and item.prompt and job['item_id'] in selections:
                    if not await self.record_drawn_outfit(job, drawn_outfit):
                        return
                    subject = 'little white character' if character is None else 'pet character'
                    scene = f"The {subject} proudly shows off the new {item.prompt}, looking at the viewer."
                    result = await self.pictures.draw("reaction", character, outfit, scene)
        if await self.finish(job, result, fail_reason="check_failed"):
            log.info("scene_finished result=%s friend=%s character=%s scene=%s ms=%d usd=%s",
                     result.outcome if result else "check_failed", job["friend_id"], job["character_id"], job["id"],
                     round((monotonic() - started) * 1000), result.cost if result else 0)

    async def step(self):
        await self.recover()
        if not self.default_wear:
            await self.store._one("""WITH disabled AS (
                UPDATE marong.scene_pictures SET state='failed',fail_reason='disabled',finished_at=now()
                WHERE character_id IS NULL AND purpose='reaction' AND state='queued' RETURNING id
            ) SELECT count(*) FROM disabled""")
        jobs = await self.claim()
        results = await asyncio.gather(*(self.process(job) for job in jobs), return_exceptions=True)
        for job, result in zip(jobs, results):
            if isinstance(result, Exception):
                log.warning("scene_job_error scene=%s error=%s", job["id"], type(result).__name__)
        return len(jobs)

    async def run(self):
        while True:
            try:
                if await self.step():
                    continue
            except Exception as error:
                log.warning("scene_loop_error error=%s", type(error).__name__)
            await asyncio.sleep(1)
