"""Run the private Discord bot using the existing server-side Marong settings."""
import asyncio
from dataclasses import replace
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from marong.access import AccessVerifier
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_runtime import app_settings, app_tables, google_settings, greeting_settings, model_tools, topic_tables
from marong.cache_warm import CacheWarmer
from marong.config import load_dotenv, load_settings
from marong.deepseek import from_env as deepseek_route
from marong.discord_dm import DEFAULT_ORIGIN, DiscordAgent, DiscordDM, DiscordProactive, DiscordReminders
from marong.discord_store import DiscordStore
from marong.embed import Embeddings
from marong.google_calendar import GoogleCalendar, serve as serve_google
from marong.llm import LLM
from marong.memory import MemoryWorker
from marong.store import Store
from marong.topics import Topics
from marong.work_loops import loops_home, run_locked



async def main():
    load_dotenv()
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul")
    is_loop_home = loops_home(os.environ.get("MARONG_LOOPS_HOME", "bot")) == "bot"
    if any("BOT_TOKEN" not in item for item in settings.problems()):
        raise SystemExit("Invalid Marong model or database settings")
    credentials = Path(os.environ["CREDENTIALS_DIRECTORY"])
    token = (credentials / "discord-token").read_text(encoding="ascii").strip()
    google_config = google_settings(credentials)
    app_config = app_settings(credentials)
    fcm_client = app_config["fcm"] if app_config else None
    first_replies = greeting_settings()
    web, shop, warm = model_tools(settings)
    store = DiscordStore(settings.database_url, call_bridge=True)
    store.discord_context_enabled = False
    llm = LLM(settings)
    # Text replies via DeepSeek in the rooms MARONG_DEEPSEEK_ROOMS lists ("*" = all; empty = Claude only). Web search and
    # shop page reads are delegated to Claude. A bad setting or a missing key logs an error and keeps Claude.
    route = deepseek_route(os.environ, credentials, llm, settings.anthropic_model)
    emb = Embeddings(settings.embed_model, settings.embed_cache_dir)
    # During parallel operation the Kakao process already maintains these tables.
    standalone = is_loop_home and os.getenv("MARONG_DISCORD_MEMORY_WORKER") == "1"
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
            tasks.append(asyncio.create_task(run_locked(settings.database_url, "memory", worker.run)))
        agent = DiscordAgent(settings, store, emb, llm, on_saved=worker.kick if worker else None,
                             first_replies=first_replies, google=google, shop=shop, web=web)
        agent.route = route
        if warm:
            agent.warmer = CacheWarmer(llm, settings.timezone)
            if is_loop_home:
                tasks.append(asyncio.create_task(run_locked(settings.database_url, "cache", agent.warmer.run)))
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
        # Picture topics and hello calls (docs/04-functional-spec/call-first.md): MARONG_TOPICS=1 and table 018.
        topics = None
        if os.environ.get("MARONG_TOPICS", "0").strip() == "1" and await topic_tables(store):
            topics = Topics(settings, store, push)
            agent.topics = topics.on
            if not topics.on:
                topics = None
        logging.getLogger("marong.topics").info("topics %s", "on" if topics else "off")
        async with client:
            if is_loop_home:
                proactive = DiscordProactive(settings, store, agent, client, app=push, topics=topics)
                reminders = DiscordReminders(settings, store, agent, client, app=push, origin=origin)
                tasks.append(asyncio.create_task(run_locked(settings.database_url, "proactive", proactive.run)))
                tasks.append(asyncio.create_task(run_locked(settings.database_url, "reminders", reminders.run)))
            if google and is_loop_home:
                google.notify = client.tell
                google_web = await serve_google(google)
                tasks.append(asyncio.create_task(run_locked(settings.database_url, "google", google.sync_loop)))
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
