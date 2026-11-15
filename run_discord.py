"""Run the private Discord bot using the existing server-side Marong settings."""
import asyncio
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from marong.config import load_dotenv, load_settings
from marong.discord_dm import DiscordAgent, DiscordDM, DiscordProactive, DiscordReminders
from marong.discord_store import DiscordStore
from marong.embed import Embeddings
from marong.google_calendar import DEFAULT_PORT, GoogleCalendar, GoogleConfig, serve as serve_google
from marong.llm import LLM
from marong.memory import MemoryWorker
from marong.shopping import FETCH_DAILY, ShopFetch
from marong.store import Store
from marong.web_search import DAILY as WEB_DAILY, PER_REPLY as WEB_PER_REPLY, WebSearch


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
    store = DiscordStore(settings.database_url, call_bridge=True)
    store.discord_context_enabled = False
    llm = LLM(settings)
    emb = Embeddings(settings.embed_model, settings.embed_cache_dir)
    # During parallel operation the Kakao process already maintains these tables.
    standalone = os.getenv("MARONG_DISCORD_MEMORY_WORKER") == "1"
    worker_store = Store(settings.database_url, call_bridge=True) if standalone else None
    worker = MemoryWorker(settings, worker_store, emb, llm) if worker_store else None
    tasks = []
    google, google_web = None, None
    try:
        await store.open(wait=True)
        await store.proactive_rooms()  # Fail before login if the private binding schema is unavailable.
        await store.claim_due_reminders(0)  # Likewise for the schedules table (012_schedules.sql).
        if google_config:
            await store.google_pending(0)  # And for 013_google_calendar.sql when Google is set up.
            google = GoogleCalendar(google_config, store, ZoneInfo(settings.timezone))
        if worker_store:
            await worker_store.open(wait=True)
        emb.start()
        if worker:
            tasks.append(asyncio.create_task(worker.run()))
        agent = DiscordAgent(settings, store, emb, llm, on_saved=worker.kick if worker else None,
                             first_replies=first_replies, google=google, shop=shop, web=web)
        client = DiscordDM(agent, store, int(os.environ["MARONG_DISCORD_APP_ID"]), int(os.environ["MARONG_DISCORD_GUILD_ID"]))
        async with client:
            tasks.append(asyncio.create_task(DiscordProactive(settings, store, agent, client).run()))
            tasks.append(asyncio.create_task(DiscordReminders(settings, store, agent, client).run()))
            if google:
                google.notify = client.tell
                google_web = await serve_google(google)
                tasks.append(asyncio.create_task(google.sync_loop()))
            await client.start(token)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if google_web:
            await google_web.cleanup()
        if google:
            await google.close()
        if worker_store:
            await worker_store.close()
        await store.close()
        await llm.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for name in ("httpx", "httpcore", "psycopg.pool", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.WARNING)
    asyncio.run(main())
