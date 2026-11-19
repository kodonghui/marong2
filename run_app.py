"""Run Marong's chat and background jobs without a Discord client."""

import asyncio
from dataclasses import replace
import logging
import os
from pathlib import Path
import signal
from weakref import WeakValueDictionary
from zoneinfo import ZoneInfo

from marong.access import AccessVerifier
from marong.app_chat import AppChat
from marong.app_profile import AppProfile
from marong.app_push import AppPush
from marong.app_runtime import app_settings, app_tables, google_settings, greeting_settings, model_tools, topic_tables
from marong.app_session import AppSessions, auth_mode
from marong.cache_warm import CacheWarmer
from marong.config import load_dotenv, load_settings
from marong.deepseek import from_env as deepseek_route
from marong.discord_dm import PrivateChatAgent
from marong.embed import Embeddings
from marong.google_calendar import GoogleCalendar, serve as serve_google
from marong.llm import LLM
from marong.memory import MemoryWorker
from marong.store import Store
from marong.topics import Topics
from marong.unified_delivery import AppProactive, AppReminders, UnifiedDelivery
from marong.unified_prompt import character_section, marker_positions
from marong.unified_store import UnifiedStore
from marong.work_loops import loops_home, run_locked


log = logging.getLogger("marong.runtime")


class AppAgent(PrivateChatAgent):
    schedule_source = "app"

    async def _friend_system(self, system, friend, room, *, private):
        if private and friend:
            profile = await asyncio.wait_for(self.store.character_prompt(friend, os.getenv("MARONG_FRIENDS") == "1"), .5)
            if profile:
                if profile["kind"]:
                    pet_prompt = await asyncio.to_thread(self.persona, pet=True)
                    if system and system[0].get("cache_control"):
                        system = [{**system[0], "text": pet_prompt}, *system[1:]]
                system = [*system[:-1], {"type": "text", "text": character_section(profile)}, system[-1]]
        return await super()._friend_system(system, friend, room, private=private)


class RoomLocks:
    def __init__(self):
        self.locks = WeakValueDictionary()

    def room_lock(self, room_key):
        return self.locks.setdefault(room_key, asyncio.Lock())


def character_settings(settings):
    if os.getenv("MARONG_CHARACTER") != "1":
        return
    folder = os.getenv("MARONG_CHARACTER_DIR")
    if not folder or not Path(folder).is_dir():
        raise SystemExit("MARONG_CHARACTER_DIR is required when characters are enabled")
    path = Path(settings.prompt_path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise SystemExit("Cannot read prompt for character mode") from e
    if marker_positions(lines) is None:
        raise SystemExit("Prompt needs one ordered pair of adult section markers")


async def serve(settings, credentials, options, secret, authentication, home, stop):
    server_config = google_settings(credentials)
    web, shop, warm = model_tools(settings)
    store = UnifiedStore(settings.database_url, call_bridge=True)
    store.discord_context_enabled = False
    llm = LLM(settings)
    route = deepseek_route(os.environ, credentials, llm, settings.anthropic_model)
    emb = Embeddings(settings.embed_model, settings.embed_cache_dir)
    memory_enabled = home == "app" and os.getenv("MARONG_DISCORD_MEMORY_WORKER") == "1"
    memory_store = Store(settings.database_url, call_bridge=True) if memory_enabled else None
    tasks = []
    google = google_web = chat = None
    fcm = options["fcm"]
    try:
        await store.open(wait=True)
        await store.contact(0)
        if not await app_tables(store):
            raise RuntimeError("App tables are unavailable")
        await store.claim_due_reminders(0)
        if server_config:
            await store.google_pending(0)
            google = GoogleCalendar(server_config, store, ZoneInfo(settings.timezone))
        emb.start()
        worker = None
        if memory_store:
            await memory_store.open(wait=True)
            worker = MemoryWorker(settings, memory_store, emb, llm)
        agent = AppAgent(settings, store, emb, llm, on_saved=worker.kick if worker else None,
                         first_replies=greeting_settings(), google=google, shop=shop, web=web)
        agent.route = route
        agent.ring = options["ring"]
        if warm:
            agent.warmer = CacheWarmer(llm, settings.timezone)
        locks = RoomLocks()
        push = AppPush(store, fcm, ring_enabled=agent.ring, title_for=store.app_bot_name)
        sessions = AppSessions(store.pool, secret,
                               contact_schedule=(settings.proactive_per_day, *settings.proactive_hours),
                               invite_days=int(os.getenv("MARONG_INVITE_DAYS", "7")),
                               session_days=int(os.getenv("MARONG_SESSION_DAYS", "90")))
        chat = AppChat(store, agent, locks, AccessVerifier(options["access"]), push,
                       origin=options["origin"], port=options["port"], timezone=settings.timezone,
                       sessions=sessions, authentication=authentication,
                       admin_email_hash=os.getenv("MARONG_ADMIN_EMAIL_SHA256"))
        chat.profile = AppProfile(chat, character=os.getenv("MARONG_CHARACTER") == "1",
                                  friends=os.getenv("MARONG_FRIENDS") == "1", google=google is not None,
                                  daily_limit=int(os.environ["MARONG_DAILY_UNITS"]) if os.getenv("MARONG_DAILY_UNITS") else None)
        saved = agent.on_saved

        def on_saved():
            saved()
            chat.pulse()

        agent.on_saved = on_saved
        delivery = UnifiedDelivery(store, push, authentication, on_saved)
        chat.delivery = delivery
        topics = None
        if os.getenv("MARONG_TOPICS") == "1" and await topic_tables(store):
            candidate = Topics(settings, store, push)
            agent.topics = candidate.on
            topics = candidate if candidate.on else None
        await chat.serve()
        if home == "app":
            proactive = AppProactive(settings, store, agent, locks, delivery, topics=topics)
            reminders = AppReminders(settings, store, agent, delivery, origin=options["origin"])
            jobs = {"proactive": proactive.run, "reminders": reminders.run}
            call_texts = await store._one("SELECT to_regclass('marong.call_texts') IS NOT NULL AS ready")
            if call_texts["ready"]:
                async def call_text():
                    await delivery.call_texts(chat._spawn)

                jobs["call_text"] = call_text
            if worker:
                jobs["memory"] = worker.run
            if agent.warmer:
                jobs["cache"] = agent.warmer.run
            if google:
                google.notify = delivery.tell
                google_web = await serve_google(google)
                jobs["google"] = google.sync_loop
            tasks = [asyncio.create_task(run_locked(settings.database_url, name, job)) for name, job in jobs.items()]
        log.info("app_runtime_on loops_home=%s authentication=%s", home, authentication)
        await stop.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if chat:
            await chat.close()
        if google_web:
            await google_web.cleanup()
        if google:
            await google.close()
        if fcm:
            await fcm.close()
        if memory_store:
            await memory_store.close()
        await store.close()
        await llm.close()
        if route:
            await route.llm.close()


async def main():
    load_dotenv()
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul")
    if any("BOT_TOKEN" not in item for item in settings.problems()):
        raise SystemExit("Invalid Marong model or database settings")
    secret = os.getenv("MARONG_SESSION_SECRET", "").encode()
    if len(secret) < 32:
        raise SystemExit("MARONG_SESSION_SECRET must contain at least 32 bytes")
    character_settings(settings)
    authentication = auth_mode(os.getenv("MARONG_AUTH", "access"))
    home = loops_home(os.getenv("MARONG_LOOPS_HOME", "bot"))
    credentials = Path(os.getenv("CREDENTIALS_DIRECTORY", "/run/credentials/marong-app.service"))
    options = app_settings(credentials, standalone=True)
    if options is None:
        raise SystemExit("Missing Cloudflare Access verification settings")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    if os.name != "nt":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
    await serve(settings, credentials, options, secret, authentication, home, stop)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for name in ("httpx", "httpcore", "psycopg.pool", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.WARNING)
    asyncio.run(main())
