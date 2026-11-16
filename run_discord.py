"""Run the private Discord bot using the existing server-side Marong settings."""
import asyncio
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import psycopg

from marong.access import AccessConfig, AccessVerifier
from marong.app_chat import DEFAULT_PORT as APP_PORT, AppChat
from marong.app_push import AppPush
from marong.cache_warm import CacheWarmer
from marong.config import load_dotenv, load_settings
from marong.deepseek import from_env as deepseek_route
from marong.discord_dm import DEFAULT_ORIGIN, DiscordAgent, DiscordDM, DiscordProactive, DiscordReminders
from marong.discord_store import DiscordStore
from marong.embed import Embeddings
from marong.fcm import FCM
from marong.google_calendar import DEFAULT_PORT, GoogleCalendar, GoogleConfig, serve as serve_google
from marong.llm import LLM
from marong.memory import MemoryWorker
from marong.shopping import FETCH_DAILY, ShopFetch
from marong.store import Store
from marong.web_search import DAILY as WEB_DAILY, PER_REPLY as WEB_PER_REPLY, WebSearch


ORIGIN = re.compile(r"https://[a-z0-9-]+(\.[a-z0-9-]+)+(:[0-9]{1,5})?\Z")
app_log = logging.getLogger("marong.app")


def app_settings(credentials: Path) -> dict | None:
    """The Marong app (docs/app-chat.md, docs/app-ring.md): None unless MARONG_APP_CHAT=1. Then the in-app chat with
    the Access check, app notifications when the FCM key is loaded, and Marong's own calls with MARONG_APP_RING=1."""
    if os.environ.get("MARONG_APP_CHAT", "0").strip() != "1":
        app_log.info("app off")
        return None
    origin = os.environ.get("MARONG_APP_ORIGIN", DEFAULT_ORIGIN).strip().rstrip("/")
    port = os.environ.get("MARONG_APP_PORT", str(APP_PORT)).strip()
    if not ORIGIN.fullmatch(origin) or not port.isdecimal() or not 1024 <= int(port) <= 65535:
        raise SystemExit("Invalid MARONG_APP_ORIGIN or MARONG_APP_PORT")
    access = AccessConfig.from_env()
    if access is None:  # TC-119: without the Access values the chat server never starts
        app_log.warning("app off: Cloudflare Access settings missing")
        return None
    try:
        sender = FCM.from_credentials(str(credentials))  # LoadCredential=fcm-service-account.json (SPEC-127)
    except (ValueError, OSError, KeyError, TypeError) as e:
        app_log.warning("fcm off: unreadable key %s", type(e).__name__)
        sender = None
    ring = os.environ.get("MARONG_APP_RING", "0").strip() == "1"
    app_log.info("app on fcm=%s ring=%s", "on" if sender else "off", "on" if ring else "off")
    return {"origin": origin, "port": int(port), "access": access, "fcm": sender, "ring": ring}


async def app_tables(store) -> bool:
    """014_app_chat.sql and 015_app_ring.sql with their grants. Without them the bot runs as before."""
    try:
        await store.app_login("0" * 64)
        await store.app_devices(0)
        await store.recent_ring(0)
        return True
    except psycopg.Error as e:
        app_log.warning("app off: tables unavailable %s", type(e).__name__)
        return False


async def main():
    load_dotenv()
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul")
    if any("BOT_TOKEN" not in item for item in settings.problems()):
        raise SystemExit("Invalid Marong model or database settings")
    credentials = Path(os.environ["CREDENTIALS_DIRECTORY"])
    token = (credentials / "discord-token").read_text(encoding="ascii").strip()
    # Google Calendar is on only when the OAuth client file is loaded (deploy/marong-discord-google.conf).
    google_file = credentials / "google-client.json"
    try:
        google_config = (GoogleConfig.load(google_file, int(os.environ.get("MARONG_GOOGLE_PORT", DEFAULT_PORT)))
                         if google_file.exists() else None)
    except (ValueError, OSError) as e:
        raise SystemExit("Invalid Google client configuration") from e
    app_config = app_settings(credentials)
    fcm_client = app_config["fcm"] if app_config else None
    first_replies = json.loads(os.environ.get("MARONG_DISCORD_FIRST_REPLIES", "{}"))
    if not isinstance(first_replies, dict):
        raise SystemExit("Invalid Discord first-reply configuration")
    for friend_id, reply in first_replies.items():
        greeting = reply.get("once") if isinstance(reply, dict) else reply
        if not friend_id.isdecimal() or not isinstance(greeting, str) or not greeting.strip():
            raise SystemExit("Invalid Discord first-reply configuration")
    # Internet search (Claude's web_search server tool). MARONG_WEB_SEARCH_DAILY=0 turns it off.
    try:
        web_daily = int(os.environ.get("MARONG_WEB_SEARCH_DAILY", WEB_DAILY))
        web_per_reply = int(os.environ.get("MARONG_WEB_SEARCH_PER_REPLY", WEB_PER_REPLY))
    except ValueError as e:
        raise SystemExit("Invalid web search limits") from e
    if web_daily < 0 or not 1 <= web_per_reply <= 10:
        raise SystemExit("Invalid web search limits")
    web = WebSearch(web_per_reply, web_daily, settings.timezone) if web_daily else None
    logging.getLogger("marong.web").info(
        "web_search %s", f"on daily={web_daily} per_reply={web_per_reply}" if web else "off")
    # Shopping-mall product page reads (Claude web_fetch, mall domains only): a daily cap, 0 turns them off.
    shop_daily = os.environ.get("MARONG_SHOP_FETCH_PER_DAY", str(FETCH_DAILY)).strip()
    if not shop_daily.isdecimal():
        raise SystemExit("Invalid MARONG_SHOP_FETCH_PER_DAY")
    shop = ShopFetch(int(shop_daily), timezone=settings.timezone) if int(shop_daily) else None
    logging.getLogger("marong.shop").info("web_fetch %s", f"on, {shop_daily} a day" if shop else "off")
    # Keep the cached tools+persona front warm between messages (1-hour cache only). MARONG_CACHE_WARM=off turns it off.
    warm = os.environ.get("MARONG_CACHE_WARM", "on").strip().lower()
    if warm not in ("on", "off"):
        raise SystemExit("Invalid MARONG_CACHE_WARM")
    warm = warm == "on" and settings.cache_ttl == "1h"
    logging.getLogger("marong.cache").info("prompt_cache ttl=%s warm=%s", settings.cache_ttl, "on" if warm else "off")
    store = DiscordStore(settings.database_url, call_bridge=True)
    store.discord_context_enabled = False
    llm = LLM(settings)
    # Text replies via DeepSeek in the rooms MARONG_DEEPSEEK_ROOMS lists ("*" = all; empty = Claude only). Web search and
    # shop page reads are delegated to Claude. A bad setting or a missing key logs an error and keeps Claude.
    route = deepseek_route(os.environ, credentials, llm, settings.anthropic_model)
    emb = Embeddings(settings.embed_model, settings.embed_cache_dir)
    # During parallel operation the Kakao process already maintains these tables.
    standalone = os.getenv("MARONG_DISCORD_MEMORY_WORKER") == "1"
    worker_store = Store(settings.database_url, call_bridge=True) if standalone else None
    worker = MemoryWorker(settings, worker_store, emb, llm) if worker_store else None
    tasks = []
    google, google_web = None, None
    push, chat = None, None
    try:
        await store.open(wait=True)
        await store.proactive_rooms()  # Fail before login if the private binding schema is unavailable.
        await store.claim_due_reminders(0)  # Likewise for the schedules table (012_schedules.sql).
        if google_config:
            await store.google_pending(0)  # And for 013_google_calendar.sql when Google is set up.
            google = GoogleCalendar(google_config, store, ZoneInfo(settings.timezone))
        if app_config and not await app_tables(store):
            app_config = None
        if worker_store:
            await worker_store.open(wait=True)
        emb.start()
        if worker:
            tasks.append(asyncio.create_task(worker.run()))
        agent = DiscordAgent(settings, store, emb, llm, on_saved=worker.kick if worker else None,
                             first_replies=first_replies, google=google, shop=shop, web=web)
        agent.route = route
        if warm:
            agent.warmer = CacheWarmer(llm, settings.timezone)
            tasks.append(asyncio.create_task(agent.warmer.run()))
        client = DiscordDM(agent, store, int(os.environ["MARONG_DISCORD_APP_ID"]), int(os.environ["MARONG_DISCORD_GUILD_ID"]))
        origin = DEFAULT_ORIGIN
        if app_config:
            origin = app_config["origin"]
            push = AppPush(store, app_config["fcm"], ring_enabled=app_config["ring"])
            agent.ring = app_config["ring"]
            chat = AppChat(store, agent, client, AccessVerifier(app_config["access"]), push, origin=origin,
                           port=app_config["port"], timezone=settings.timezone)
            saved = agent.on_saved

            def on_saved():  # every saved message also wakes the chat screens' waits (SPEC-114)
                saved()
                chat.pulse()

            agent.on_saved = on_saved
            await chat.serve()
        async with client:
            tasks.append(asyncio.create_task(DiscordProactive(settings, store, agent, client, app=push).run()))
            tasks.append(asyncio.create_task(
                DiscordReminders(settings, store, agent, client, app=push, origin=origin).run()))
            if google:
                google.notify = client.tell
                google_web = await serve_google(google)
                tasks.append(asyncio.create_task(google.sync_loop()))
            await client.start(token)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if chat:
            await chat.close()
        if fcm_client:
            await fcm_client.close()
        if google_web:
            await google_web.cleanup()
        if google:
            await google.close()
        if worker_store:
            await worker_store.close()
        await store.close()
        await llm.close()
        if route:
            await route.llm.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for name in ("httpx", "httpcore", "psycopg.pool", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.WARNING)
    asyncio.run(main())
