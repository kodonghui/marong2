"""Lease-backed work queue for the separate pet database (TBL-160)."""

from datetime import timedelta
from uuid import UUID


class JobQueue:
    def __init__(self, pool):
        self.pool = pool

    async def claim(self, kinds, *, lease: timedelta, attempts: int):
        """Return one work row. The returned lease is required to publish its result."""
        if lease <= timedelta() or attempts < 1:
            raise ValueError("invalid job policy")
        kinds = list(kinds)
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute(
                """UPDATE pet.jobs SET status='failed', error_code='deadline', finished_at=now(), lease_until=NULL
                WHERE kind=ANY(%s::text[]) AND status IN ('running','queued') AND attempts >= %s
                  AND COALESCE(lease_until,run_after)<=now()""",
                (kinds, attempts),
            )
            cur = await conn.execute(
                """WITH ready AS (
                    SELECT id FROM pet.jobs WHERE kind=ANY(%s::text[]) AND attempts < %s AND
                     ((status='queued' AND run_after<=now()) OR (status='running' AND lease_until<=now()))
                    ORDER BY run_after,queued_at,id LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE pet.jobs AS job SET status='running', attempts=job.attempts+1, lease_until=now()+%s,
                    started_at=now(), running_at_start=1+(SELECT count(*) FROM pet.jobs WHERE status='running'
                                                         AND lease_until>now()),
                    finished_at=NULL,error_code=NULL
                FROM ready WHERE job.id=ready.id RETURNING job.*""",
                (kinds, attempts, lease),
            )
            return await cur.fetchone()

    async def complete(self, job, *, media_id: UUID | None = None) -> bool:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                """UPDATE pet.jobs SET status='done', result_media_id=%s, finished_at=now(), lease_until=NULL
                WHERE id=%s AND status='running' AND lease_until=%s AND lease_until>now()""",
                (media_id, job["id"], job["lease_until"]),
            )
            return result.rowcount == 1

    async def fail(self, job, code: str, *, retry_after: timedelta | None = None, attempts: int = 1) -> bool:
        if not code.isascii() or not code.replace("_", "").isalnum() or len(code) > 40:
            raise ValueError("invalid job error code")
        retry = retry_after is not None and job["attempts"] < attempts
        if retry and retry_after < timedelta():
            raise ValueError("invalid retry delay")
        async with self.pool.connection() as conn:
            result = await conn.execute(
                """UPDATE pet.jobs SET status=%s, error_code=%s, run_after=now()+%s,
                    finished_at=CASE WHEN %s THEN NULL ELSE now() END, lease_until=NULL
                WHERE id=%s AND status='running' AND lease_until=%s AND lease_until>now()""",
                ("queued" if retry else "failed", code, retry_after if retry else timedelta(),
                 retry, job["id"], job["lease_until"]),
            )
            return result.rowcount == 1
