"""HTTP entry point for the isolated pet service."""

import asyncio
import logging
import os
import sys

import psycopg
from aiohttp import web
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from marong.pet.settings import Settings, SettingsError

log = logging.getLogger("pet")
POOL = web.AppKey("pet_database", AsyncConnectionPool)
CONFIG = web.AppKey("pet_settings", Settings)


async def health(_request):
    return web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})


def make_app(settings: Settings) -> web.Application:
    app = web.Application()
    app[CONFIG] = settings

    async def database(app):
        pool = AsyncConnectionPool(settings.db, open=False, min_size=1, max_size=4, timeout=3,
                                   kwargs={"row_factory": dict_row})
        try:
            await pool.open(wait=True, timeout=3)
            async with pool.connection() as conn:
                cursor = await conn.execute(
                    """SELECT current_database()='marong_pet' AND current_user='marong_pet'
                    AND to_regclass('pet.jobs') IS NOT NULL AS ready"""
                )
                if not (await cursor.fetchone())["ready"]:
                    raise SettingsError("the separate pet database is not initialized")
            app[POOL] = pool
            yield
        finally:
            await pool.close()

    app.cleanup_ctx.append(database)
    app.router.add_get("/healthz", health, allow_head=False)
    return app


def main() -> int:
    # Connection/library diagnostics may include endpoints or role credentials. Log only fixed codes.
    logging.getLogger("psycopg.pool").setLevel(logging.CRITICAL)
    try:
        settings = Settings.read(os.environ)
        web.run_app(make_app(settings), host="127.0.0.1", port=settings.port, access_log=None, print=None)
    except SettingsError as error:
        log.error("pet_start_failed %s", error)
        return 2
    except (psycopg.Error, OSError, asyncio.TimeoutError):
        log.error("pet_start_failed database_or_listener")
        return 2
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    raise SystemExit(main())
