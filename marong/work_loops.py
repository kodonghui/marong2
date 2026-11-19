"""Keep each periodic app job in one process during the transport cutover."""

import asyncio
import logging

import psycopg


log = logging.getLogger(__name__)
LOCK_NAMESPACE = 20261119
LOCKS = {"memory": 1, "cache": 2, "proactive": 3, "reminders": 4, "google": 5, "legacy_proactive": 6, "call_text": 7, "diary": 8,
         "character": 9}


def loops_home(value):
    if value not in ("bot", "app"):
        raise ValueError("MARONG_LOOPS_HOME must be bot or app")
    return value


async def run_locked(database_url, name, run, *, retry=60):
    """Use a dedicated session. The connection owns the lock until the job stops."""
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(database_url, autocommit=True, connect_timeout=5) as conn:
                cursor = await conn.execute("SELECT pg_try_advisory_lock(%s,%s)", (LOCK_NAMESPACE, LOCKS[name]))
                if (await cursor.fetchone())[0]:
                    job = asyncio.create_task(run())
                    try:
                        while True:
                            done, _ = await asyncio.wait({job}, timeout=10)
                            if done:
                                return await job
                            await conn.execute("SELECT 1")
                    finally:
                        job.cancel()
                        await asyncio.gather(job, return_exceptions=True)
                log.info("loops_skipped loop=%s", name)
        except psycopg.OperationalError as e:
            log.warning("work_loop_lock_unavailable loop=%s error=%s", name, type(e).__name__)
        await asyncio.sleep(retry)
