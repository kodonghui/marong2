"""Lease and publish scene jobs. The app owns image generation and all picture reads."""

import asyncio
import logging
from time import monotonic

from .topics import picture_set


log = logging.getLogger(__name__)


class SceneWorker:
    def __init__(self, store, pictures, usage):
        self.store = store
        self.pictures = pictures
        self.usage = usage

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
                    WHERE state='queued' AND not_before<=now() AND attempts<3
                    ORDER BY not_before, created_at, id LIMIT 2 FOR UPDATE SKIP LOCKED
                )
                UPDATE marong.scene_pictures s SET state='drawing', lease_until=now()+interval '10 minutes',
                    started_at=now(), attempts=s.attempts+1
                FROM due WHERE s.id=due.id RETURNING s.*
            """)
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

    async def process(self, job):
        started = monotonic()
        character = await self.store._one("""
            SELECT id, kind, template, traits, name FROM marong.characters
            WHERE id=%s AND friend_id=%s AND status='ready'
        """, (job["character_id"], job["friend_id"]))
        topics = picture_set()
        topic = topics.get(job["topic"]) if topics and job["purpose"] == "topic" else None
        result = await self.pictures.draw("topic", character, (), topic.scene) if character and topic else None
        if await self.finish(job, result, fail_reason="check_failed"):
            log.info("scene_finished result=%s friend=%s character=%s scene=%s ms=%d usd=%s",
                     result.outcome if result else "check_failed", job["friend_id"], job["character_id"], job["id"],
                     round((monotonic() - started) * 1000), result.cost if result else 0)

    async def step(self):
        await self.recover()
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
