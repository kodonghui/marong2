"""Settings shared by the private bot and the standalone app server."""
import json
import logging
import os
from pathlib import Path
import re

import psycopg

from .access import AccessConfig
from .app_chat import DEFAULT_PORT as APP_PORT
from .fcm import FCM
from .google_calendar import DEFAULT_PORT, GoogleConfig
from .discord_dm import DEFAULT_ORIGIN
from .shopping import FETCH_DAILY, ShopFetch
from .web_search import DAILY as WEB_DAILY, PER_REPLY as WEB_PER_REPLY, WebSearch

ORIGIN = re.compile(r"https://[a-z0-9-]+(\.[a-z0-9-]+)+(:[0-9]{1,5})?\Z")
app_log = logging.getLogger("marong.app")


def app_settings(credentials: Path, *, standalone=False) -> dict | None:
    """The Marong app (docs/app-chat.md, docs/app-ring.md): None unless MARONG_APP_CHAT=1. Then the in-app chat with
    the Access check, app notifications when the FCM key is loaded, and Marong's own calls with MARONG_APP_RING=1."""
    if not standalone and os.environ.get("MARONG_APP_CHAT", "0").strip() != "1":
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


async def topic_tables(store) -> bool:
    """018_call_first.sql with its grants (picture topics and hello calls). Without them topics stay off."""
    try:
        await store.topic_prefs(0)
        await store.hello_last(0)
        return True
    except psycopg.Error as e:
        logging.getLogger("marong.topics").warning("topics off: tables unavailable %s", type(e).__name__)
        return False

def google_settings(credentials: Path):
    google_file = credentials / "google-client.json"
    try:
        if google_file.exists():
            return GoogleConfig.load(google_file, int(os.environ.get("MARONG_GOOGLE_PORT", DEFAULT_PORT)))
    except (ValueError, OSError) as e:
        raise SystemExit("Invalid Google client configuration") from e


def greeting_settings():
    first_replies = json.loads(os.environ.get("MARONG_DISCORD_FIRST_REPLIES", "{}"))
    if not isinstance(first_replies, dict):
        raise SystemExit("Invalid Discord first-reply configuration")
    for friend_id, reply in first_replies.items():
        greeting = reply.get("once") if isinstance(reply, dict) else reply
        if not friend_id.isdecimal() or not isinstance(greeting, str) or not greeting.strip():
            raise SystemExit("Invalid Discord first-reply configuration")
    return first_replies


def model_tools(settings):
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
    return web, shop, warm
