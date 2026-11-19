"""PostgreSQL connections and locks for the shared talk_graph checkpoint schema."""

from contextlib import asynccontextmanager
import asyncio

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


def checkpoint_pool(dsn):
    return AsyncConnectionPool(
        dsn, open=False, min_size=1, max_size=3, check=AsyncConnectionPool.check_connection,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row,
                "options": "-c search_path=talk_graph,public"},
    )


@asynccontextmanager
async def checkpoint_lock(pool, key):
    async with pool.connection() as conn:
        try:
            cursor = await conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked", (key,))
            locked = (await cursor.fetchone())["locked"]
        except BaseException:
            # The server may already have acquired the lock while the client was cancelled.
            await conn.close()
            raise
        try:
            yield locked
        finally:
            if locked:
                try:
                    await conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))
                except BaseException:
                    await conn.close()
                    raise


async def setup_checkpoints(pool, saver):
    # Neither the guard nor another waiting worker should hold an open transaction
    # during the saver's concurrent index build.
    while True:
        async with checkpoint_lock(pool, "talk_graph:setup") as locked:
            if locked:
                await saver.setup()
                return
        await asyncio.sleep(.25)
