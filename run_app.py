"""Run Marong's chat and background jobs without a Discord client."""

import asyncio
from dataclasses import replace
from decimal import Decimal, InvalidOperation
import logging
import os
from pathlib import Path
import signal
from types import SimpleNamespace
from weakref import WeakValueDictionary
from zoneinfo import ZoneInfo

from aiohttp import ClientSession

from marong.access import AccessVerifier
from marong.app_chat import AppChat
from marong.app_profile import AppProfile
from marong.app_push import AppPush
from marong.app_runtime import app_settings, app_tables, google_settings, greeting_settings, model_tools, topic_tables
from marong.app_session import AppSessions, auth_mode
from marong.cache_warm import CacheWarmer
from marong.character.artwork import ImageEditor
from marong.character.graphics import ROOT, Templates
from marong.character.http import CharacterAPI
from marong.character.photos import load_detector
from marong.character.vision import VisionExtractor
from marong.character.worker import CharacterWorker, WorkerBudget
from marong.config import load_dotenv, load_settings
from marong.deepseek import from_env as deepseek_route
from marong.decor import DecorCatalog
from marong.decor_reactions import DecorReactions, drain_default_wear_loop
from marong.diary_models import DiaryModels
from marong.diary_worker import DiaryWorker
from marong.discord_dm import PrivateChatAgent
from marong.embed import Embeddings
from marong.google_calendar import GoogleCalendar, serve as serve_google
from marong.graphs.memory import run_text_memory
from marong.internal_shop import InternalShop
from marong.llm import LLM
from marong.memory import MemoryWorker
from marong.pet.settings import PriceBook
from marong.pet_app_settings import PetAppSettings
from marong.scene_picture import ScenePictures
from marong.scene_worker import SceneWorker
from marong.store import Store
from marong.topics import Topics
from marong.unified_delivery import AppProactive, AppReminders, UnifiedDelivery
from marong.unified_prompt import PET_HEALTH_REFERRAL, character_section, explicit_pet_health, marker_positions
from marong.unified_store import UnifiedStore
from marong.work_loops import loops_home, run_locked


log = logging.getLogger("marong.runtime")


class AppAgent(PrivateChatAgent):
    schedule_source = "app"
    pet_voice = False
    direct_system = (
        "지금은 앱과 웹에서 마롱이와 하는 개인 대화야. 다른 친구의 기록을 찾아 주겠다고 말하지 마. "
        "친구처럼 바로 이야기하고, 사용법이나 먼저 연락하는 설정을 먼저 설명하지 마. "
        "먼저 거는 말은 잠금 화면에도 보일 수 있어. 몸·연애·성·돈·비밀처럼 남이 보면 곤란한 얘기는 먼저 꺼내지 마."
    )
    app_line = "- 이번 말은 앱이나 웹에서 왔어. 같은 사람과 앞서 나눈 이야기를 이어 가."
    app_calendar_text = "내 마롱이에서 ‘구글 캘린더’를 열면 연결 상태를 보고 연결하거나 끊을 수 있어."

    @staticmethod
    def _dm_lines(link, private=False):
        lines = PrivateChatAgent._dm_lines(link, private=private)
        return [line.replace("이 DM으로", "앱 글 대화로").replace("이 DM에서는", "이 대화에서는")
                for line in lines]
    friend_context_limit = 20

    async def _reply(self, msg, person, user_id, text, timeout, use_memory=True, held=None):
        if msg.friend_id and not getattr(msg, "safety_decision", None) and explicit_pet_health(text):
            try:
                profile = await asyncio.wait_for(self.store.character_prompt(msg.friend_id, False), .5)
            except Exception as exc:
                log.warning("pet_referral_profile_error %s", type(exc).__name__)
            else:
                if profile and profile["kind"] in ("dog", "cat"):
                    msg.pet_health_referral = True
                    return PET_HEALTH_REFERRAL, {"pet_health_referral": True}
        return await super()._reply(msg, person, user_id, text, timeout, use_memory=use_memory, held=held)

    async def _review_reply(self, msg, person, reply, text, deadline, *, proactive=False, recent=()):
        if getattr(msg, "pet_health_referral", False):
            return PET_HEALTH_REFERRAL, {}
        return await super()._review_reply(msg, person, reply, text, deadline, proactive=proactive, recent=recent)

    async def _with_question(self, msg, reply, text):
        if getattr(msg, "pet_health_referral", False):
            return PET_HEALTH_REFERRAL
        return await super()._with_question(msg, reply, text)

    async def _friend_system(self, system, friend, room, *, private):
        if private and friend:
            profile = await asyncio.wait_for(self.store.character_prompt(
                friend, os.getenv("MARONG_FRIENDS") == "1", pet_voice=self.pet_voice), .5)
            if profile:
                if profile["kind"]:
                    pet_prompt = await asyncio.to_thread(self.persona, pet=True)
                    if system and system[0].get("cache_control"):
                        system = [{**system[0], "text": pet_prompt}, *system[1:]]
                section = character_section(profile, pet_voice=self.pet_voice)
                system = [*system[:-1], {"type": "text", "text": section}, system[-1]]
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
    pet_settings = PetAppSettings.from_env(os.environ)
    server_config = google_settings(credentials)
    web, shop, warm = model_tools(settings)
    try:
        fixed_proactive_friends = tuple(int(friend) for friend in os.getenv("MARONG_PROACTIVE_FIXED_FRIENDS", "").split())
    except ValueError:
        raise SystemExit("Invalid MARONG_PROACTIVE_FIXED_FRIENDS") from None
    store = UnifiedStore(settings.database_url, call_bridge=True, fixed_proactive_friends=fixed_proactive_friends)
    store.discord_context_enabled = False
    llm = LLM(settings)
    route = deepseek_route(os.environ, credentials, llm, settings.anthropic_model)
    emb = Embeddings(settings.embed_model, settings.embed_cache_dir)
    memory_enabled = home == "app" and os.getenv("MARONG_DISCORD_MEMORY_WORKER") == "1"
    memory_store = Store(settings.database_url, call_bridge=True) if memory_enabled else None
    tasks = []
    google = google_web = chat = diary_models = character_http = None
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
        agent.pet_voice = pet_settings.pet_voice
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
        diary_enabled = os.getenv("MARONG_DIARY") == "1"
        if diary_enabled or pet_settings.scene_pictures:
            diary_models = DiaryModels(settings, os.environ)
        chat = AppChat(store, agent, locks, AccessVerifier(options["access"]), push,
                       origin=options["origin"], port=options["port"], timezone=settings.timezone,
                       sessions=sessions, authentication=authentication,
                       admin_email_hash=os.getenv("MARONG_ADMIN_EMAIL_SHA256"), diary_models=diary_models,
                       pet_app_settings=pet_settings)
        chat.profile = AppProfile(chat, character=os.getenv("MARONG_CHARACTER") == "1",
                                  friends=os.getenv("MARONG_FRIENDS") == "1", google=google is not None,
                                  voice_samples=os.getenv("MARONG_VOICE_SAMPLES_DIR"))
        if pet_settings.decor:
            chat.decor.catalog = await asyncio.to_thread(DecorCatalog)
            await chat.decor.seed()
        saved = agent.on_saved

        def on_saved():
            saved()
            chat.pulse()

        agent.on_saved = on_saved
        delivery = UnifiedDelivery(store, push, authentication, on_saved, origin=options["origin"])
        chat.delivery = delivery
        if os.getenv("MARONG_CALL_SHOP") == "1":
            chat.internal_shop = InternalShop(llm, web, shop, settings.anthropic_model,
                                              os.getenv("MARONG_INTERNAL_SECRET", ""))
        if os.getenv("MARONG_CHARACTER_DIR"):
            try:
                budget = Decimal(os.getenv("MARONG_IMAGE_MONTHLY_USD", "20"))
                if not budget.is_finite() or budget < 0:
                    raise InvalidOperation()
            except InvalidOperation:
                raise SystemExit("Invalid MARONG_IMAGE_MONTHLY_USD") from None
            detector = (await asyncio.to_thread(load_detector, os.getenv("MARONG_FACE_DETECTOR"))
                        if chat.profile.features["character"] else None)
            chat.characters = CharacterAPI(chat, os.getenv("MARONG_CHARACTER_DIR"), detector, budget,
                                           enabled=chat.profile.features["character"])
        jobs = {}
        if chat.profile.features["character"]:
            character_http = ClientSession()
            templates = await asyncio.to_thread(Templates)
            prices = await asyncio.to_thread(PriceBook.read, ROOT / "marong" / "pet" / "prices.json")
            metering = WorkerBudget(store, prices)
            model_settings = SimpleNamespace(vision_model=os.getenv("MARONG_CHARACTER_VISION", "claude-sonnet-5-5"),
                                             image_model=os.getenv("MARONG_CHARACTER_IMAGE", "gpt-image-2.5-flare"))
            vision = VisionExtractor(character_http, settings.anthropic_api_key, model_settings, metering)
            editor = ImageEditor(character_http, os.getenv("OPENAI_API_KEY", ""), templates, metering)

            async def notify_character(friend, step, ident):
                if await delivery.notifications_allowed(friend):
                    notice = ("그림 후보가 나왔어" if step == "candidates" else "표정 그림이 준비됐어")
                    page = "candidates" if step == "candidates" else "name"
                    await push.notify(friend, "character", notice, open_path=f"/chat/character/{ident}/{page}")

            character_worker = CharacterWorker(chat.characters, templates, vision, editor, model_settings, prices,
                                               on_complete=notify_character)
            jobs["character"] = character_worker.run
        scenes = None
        if home == "app" and pet_settings.scene_pictures and chat.characters.media is not None:
            pictures = ScenePictures(store, chat.characters.media, diary_models, pet_settings.scene_model,
                                     catalog=chat.decor.catalog)
            chat.diary_scenes = pictures
            scenes = SceneWorker(store, pictures, chat.usage, default_wear=pet_settings.default_wear and pet_settings.decor)
            jobs["scenes"] = scenes.run
        topics = None
        if os.getenv("MARONG_TOPICS") == "1" and await topic_tables(store):
            candidate = Topics(settings, store, push, scenes=scenes)
            agent.topics = candidate.on
            topics = candidate if candidate.on else None
        await chat.serve()
        if home == "app":
            if not pet_settings.default_wear or not pet_settings.decor:
                jobs['default_wear_drain'] = lambda: drain_default_wear_loop(store)
            reactions = (DecorReactions(store, chat.characters.media, chat.usage, chat.decor.catalog, scenes,
                                        default_wear=pet_settings.default_wear and pet_settings.decor)
                         if chat.decor.catalog and chat.characters.media else None)
            proactive = AppProactive(settings, store, agent, locks, delivery, topics=topics, scenes=scenes,
                                     reactions=reactions)
            reminders = AppReminders(settings, store, agent, delivery, origin=options["origin"],
                                     scenes=bool(scenes))
            jobs.update(proactive=proactive.run, reminders=reminders.run)
            if diary_enabled:
                diary = DiaryWorker(store, diary_models, delivery, pet_settings.diary_image_budget,
                                    unified=True, pet_voice=pet_settings.pet_voice, scenes=chat.diary_scenes,
                                    wear_catalog=chat.decor.catalog if pet_settings.default_wear and pet_settings.decor else None)
                jobs["diary"] = diary.run
            call_texts = await store._one("SELECT to_regclass('marong.call_texts') IS NOT NULL AS ready")
            if call_texts["ready"]:
                async def call_text():
                    await delivery.call_texts(chat._spawn)

                jobs["call_text"] = call_text
            if worker:
                jobs["memory"] = worker.run
            if store.friend_memory_enabled:
                async def text_memory():
                    await run_text_memory(store, settings.database_url, llm, settings.anthropic_model)
                jobs["friend_memory"] = text_memory
            if agent.warmer:
                jobs["cache"] = agent.warmer.run
            if google:
                google.notify = delivery.tell
                google_web = await serve_google(google, sessions=sessions, authentication=authentication,
                                                origin=options["origin"])
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
        if diary_models:
            await diary_models.close()
        if character_http:
            await character_http.close()
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
