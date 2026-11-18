"""HTTP entry point for the isolated pet service."""

import asyncio
import logging
import os
import sys

import psycopg
from aiohttp import ClientSession, web
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from marong.pet.account import register as register_account
from marong.pet.auth import AuthConfig, register as register_auth
from marong.pet.chat import register as register_chat
from marong.pet.cost import Budget
from marong.pet.delete import register as register_delete
from marong.pet.http import CONFIG, POOL, guard, read_media
from marong.pet.quota import register as register_quota
from marong.pet.push import VapidSender, register as register_push
from marong.pet.replies import ChatModel, register as register_replies
from marong.pet.reports import register as register_reports
from marong.pet.settings import Settings, SettingsError

log = logging.getLogger("pet")
BUDGET = web.AppKey("pet_budget", Budget)
CHAT = web.AppKey("pet_chat", ChatModel)


async def health(_request):
    return web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})


def make_app(settings: Settings, *, auth_config=None, revoke_billing_key=None, push_sender=None,
             chat_api_key=None, reply_model=None, chat_clock=None, report_clock=None) -> web.Application:
    app = web.Application(middlewares=[guard])
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
            app[BUDGET] = Budget(pool, settings)
            if chat_api_key:
                async with ClientSession() as session:
                    app[CHAT] = ChatModel(session, chat_api_key, settings, app[BUDGET])
                    yield
            else:
                yield
        finally:
            await pool.close()

    app.cleanup_ctx.append(database)
    app.router.add_get("/healthz", health, allow_head=False)
    app.router.add_get("/api/media/{id}", read_media, allow_head=False)
    register_auth(app, auth_config if auth_config is not None else AuthConfig.read(os.environ))
    register_account(app)
    register_quota(app)
    register_push(app, sender=push_sender)
    register_delete(app, revoke=revoke_billing_key)
    register_reports(app, clock=report_clock)
    register_chat(app, **({"clock": chat_clock} if chat_clock else {}))
    if reply_model or chat_api_key:
        register_replies(app, reply_model or (lambda *args, **kwargs: app[CHAT](*args, **kwargs)))
    return app


def main() -> int:
    # Connection/library diagnostics may include endpoints or role credentials. Log only fixed codes.
    logging.getLogger("psycopg.pool").setLevel(logging.CRITICAL)
    try:
        settings = Settings.read(os.environ)
        key, subject = os.environ.get("PET_VAPID_PRIVATE_KEY"), os.environ.get("PET_VAPID_SUBJECT")
        if bool(key) != bool(subject):
            raise SettingsError("pet push key and contact must be configured together")
        sender = VapidSender(key, subject) if key else None
        web.run_app(make_app(settings, push_sender=sender, chat_api_key=os.environ.get("PET_ANTHROPIC_API_KEY")),
                   host="127.0.0.1", port=settings.port,
                   access_log=None, print=None)
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
