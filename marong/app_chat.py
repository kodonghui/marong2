"""In-app chat for the Marong app and browsers (docs/app-chat.md SPEC-110~124, SPEC-148~149,
api/app-chat.openapi.yaml API-101~106).

A small aiohttp server inside the Discord DM bot, on 127.0.0.1 only. The tunnel sends `/chat/` of the call address
here; Cloudflare Access stands in front and every API request's Access token is checked again (access.py). A friend
writes into their own Discord DM room, so Marong answers with the same memory, lock and tools in both places.
Logs carry result names and counts only: no text, FID, install id, email or token (SPEC-126).
"""
import asyncio
import os
from collections import OrderedDict, defaultdict, deque
from contextlib import AsyncExitStack
import hmac
import json
import logging
import math
from pathlib import Path
from urllib.parse import parse_qsl
import re
import secrets
import time
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientSession, ClientTimeout, web
import psycopg

from tools.vertex_live.tool_trace import app_delivery, app_step, step as trace_step

from .app_release import AppReleases, VERSION_CODE_MAX
from .app_session import COOKIE, SessionError, auth_mode, device_label, identify_request
from .character.records import CharacterError
from .app_store import APP_KEY, AppDeviceLimit
from .discord_dm import DEFAULT_ORIGIN, DiscordIncoming, proactive_preference
from .google_calendar import LINK_MARK, command as google_command
from .topics import KEY as TOPIC_KEY, NAME as PICTURE_NAME, SET_NAME, phrase as topic_phrase, picture_set
from .web_push_subscriptions import CHOICE_HEADER, INSTALLATION_HEADER, PATH as WEB_NOTICE_PATH, installation_id, lock_installation
from .web_push_targets import resolve_target, visible_message
from .web_notice_call_protocol import (BRIDGE_HEADER, CALL_BRIDGE, CONSENT_HEADER, ENDED_BRIDGE, INSTALLATION_CHECK_PATH,
    ORDINARY_CHOICE_HEADER, READ_BRIDGE_HEADER, RECEIPT_EXPIRES_HEADER, RECEIPT_HEADER, REDIAL_HEADER, client_uuid)

log = logging.getLogger("marong.app")
DEFAULT_PORT = 8796
TEXT_MAX = 2000
NAME_MAX = 40
WAIT_S = 25              # a wait with nothing new ends empty after this (SPEC-114)
WAIT_POLL_S = 5          # and looks at the DB this often for messages saved by another process
WAITERS_MAX = 4          # waits per friend; a fifth ends the oldest
RATE, RATE_WINDOW_S = 20, 60   # messages a friend may send per minute (REQ-121)
PAGE_DEFAULT, PAGE_MAX = 30, 50
BODY_MAX = 16 * 1024
REPLY_TTL_S = 3600
READ_ROOMS_MAX = 256     # rooms whose '읽음' this process keeps (one per call friend)
STATIC = Path(__file__).with_name("app_chat_static")
WEB_NOTICE_SCRIPT = b'<script defer src="/chat/web-notifications.js"></script>\n'
NOTICE_CALL_PAGE = "/chat/notice-call"
NOTICE_CALL_FAILURES = {
    "denied": ("이 알림을 열 수 없어", "글 대화로 돌아가 다시 확인할 수 있어."),
    "answered": ("이미 받은 전화야", "이 약속 전화는 이미 처리됐어. 글 대화로 돌아갈 수 있어."),
    "expired": ("약속 전화 시간이 지났어", "더 이상 이 약속 전화를 받을 수 없어."),
    "unavailable": ("지금은 이 전화를 받을 수 없어", "현재 확인한 상태로는 이 약속 전화를 연결할 수 없어."),
    "login": ("로그인한 뒤 알림을 확인할게", "기존 기기 코드로 로그인해 줘. 여기에서는 알림 내용을 먼저 보여 주지 않아."),
    "offline": ("지금 전화 상태를 확인할 수 없어", "연결을 확인한 뒤 이 전화의 상태를 다시 확인해 줘."),
    "limited": ("잠시 뒤 다시 확인해 줘", "안내된 시간이 지나면 전화 상태를 다시 확인할 수 있어."),
}
FILES = {"": ("index.html", "text/html"), "chat.js": ("chat.js", "text/javascript"),
         "chat.css": ("chat.css", "text/css"), "update-banner.js": ("update-banner.js", "text/javascript")}
UNIFIED_FILES = {"account.html": "text/html", "admin.html": "text/html", "unified.css": "text/css",
                 "unified.js": "text/javascript", "account.js": "text/javascript", "admin.js": "text/javascript",
                 "profile.html": "text/html", "profile.js": "text/javascript",
                 "voice.html": "text/html", "voice.js": "text/javascript", "friends.html": "text/html",
                 "friends.js": "text/javascript",
                 "character.html": "text/html", "character.js": "text/javascript",
                 "decor.html": "text/html", "decor.js": "text/javascript",
                 "admin-items.html": "text/html", "admin-items.js": "text/javascript",
                 "notice-call.html": "text/html"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
FID = re.compile(r"[A-Za-z0-9_-]{16,200}\Z")
VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z")
RELEASE_CHECK_PATH = "/chat/api/app/release"
NUMBER = re.compile(r"[0-9]{1,19}\Z")
PROBLEMS = {
    "invalid_input": (400, "요청 모양이 틀림"),
    "voice_unknown": (400, "고를 수 있는 목소리가 아님"),
    "self_request": (400, "내 친구 코드임"),
    "code_not_found": (404, "친구 코드를 찾지 못함"),
    "already_friends": (409, "이미 친구 관계임"),
    "request_exists": (409, "기다리는 친구 요청이 있음"),
    "request_limit": (429, "오늘 친구 요청 수를 다 씀"),
    "photo_invalid": (400, "사진 형식이나 크기가 맞지 않음"),
    "too_large": (413, "사진 요청 크기 초과"),
    "check_unavailable": (503, "사진 검사 준비 중"),
    "too_many_characters": (409, "캐릭터를 이미 세 개 보관함"),
    "image_budget": (409, "이번 달 그림 예산에 도달함"),
    "job_running": (409, "그 캐릭터의 작업이 진행 중"),
    "wrong_stage": (409, "현재 만들기 단계에서 할 수 없음"),
    "no_regen_left": (409, "후보 다시 만들기를 다 씀"),
    "login_required": (401, "로그인이 필요함"),
    "code_wrong": (401, "코드가 맞지 않음"),
    "invite_not_found": (404, "없는 초대 링크"),
    "invite_used": (410, "이미 쓴 초대 링크"),
    "invite_expired": (410, "기한이 지난 초대 링크"),
    "too_many_tries": (429, "틀린 코드를 너무 많이 넣음"),
    "too_many_codes": (429, "기기 추가 코드를 너무 많이 만듦"),
    "invalid_request": (400, "요청 모양이 틀림(빠진 칸, 길이·형식·범위 밖)"),
    "unauthenticated": (401, "Access 로그인 증명이 없거나 맞지 않음"),
    "not_allowed": (403, "허용 목록에 없는 계정이거나 통화하는 친구가 꺼짐"),
    "cross_site": (403, "다른 사이트에서 온 쓰기 요청"),
    "no_dm": (403, "이 친구의 디스코드 DM 연결이 없거나 아직 DM을 한 번도 보내지 않음"),
    "daily_limit": (429, "오늘 쓸 수 있는 양을 다 씀"),
    "too_many_messages": (429, "1분에 20번 넘게 보냄"),
    "no_picture": (404, "그 이름의 그림이 없음"),
    "not_ready": (409, "아직 준비되지 않음"),
    "not_owned": (409, "보관함에 없는 아이템"),
    "item_invalid": (409, "아이템 파일이나 설정을 확인해야 함"),
    "too_many_stickers": (409, "한 페이지에는 스티커를 10개까지 붙일 수 있음"),
    "stale_revision": (409, "보낸 판 번호가 지금 판과 다름"),
    "busy": (409, "이 일기를 고치거나 다시 그리는 중"),
    "fix_limit": (409, "고치기 다섯 번을 다 씀"),
    "redraw_limit": (409, "다시 그리기 두 번을 다 씀"),
    "drawing_budget": (429, "이번 달 그림 월 예산을 다 씀"),
    "fix_failed": (503, "고치기 모델이 실패함"),
    "stale_test": (409, "화면이 연 시험과 지금 시험 묶음이 다름"),
    "no_release": (404, "지금 받을 수 있는 앱 파일이 아님"),
    "too_many_devices": (409, "이 친구의 30일 안 폰이 이미 20대"),
    "feature_off": (403, "이 기능이 꺼져 있음"),
    "needs_owner": (403, "선톡을 늘리는 요청은 동희님이 정함"),
    "not_found": (404, "이 계정으로 찾을 수 없음"),
    "invite_closed": (409, "거둘 수 없는 링크"),
    "rule_limit": (409, "그 종류의 친구 규칙이 이미 20개"),
    "card_closed": (409, "카드가 닫혔거나 다른 값으로 답함"),
    "too_many_requests": (429, "맞춤형 지침 요청이 너무 자주 도착함"),
    "ai_unavailable": (503, "맞춤형 지침을 읽지 못함"),
    "db_unavailable": (503, "DB에 닿지 않음"),
    "internal": (500, "예상하지 못한 서버 오류"),
    "state_changed": (409, "알림 상태가 바뀌었어요"),
    "subscription_conflict": (409, "이 설치의 알림 등록을 확인할 수 없어요"),
}
WEB_NOTICE_TITLES = {
    "invalid_input": "입력을 확인해 주세요",
    "login_required": "로그인이 필요해요",
    "cross_site": "이 출처에서 요청할 수 없어요",
    "not_allowed": "이 설치에서 요청할 수 없어요",
    "not_found": "알림 대상을 열 수 없어요",
    "request_limit": "잠시 뒤 다시 시도해 주세요",
    "db_unavailable": "지금 상태를 확인할 수 없어요",
    "internal": "요청을 처리할 수 없어요",
}
WEB_CALL_ERRORS = {
    (400, "invalid_input"), (401, "login_required"), (403, "not_allowed"), (404, "not_found"),
    (409, "call_busy"), (409, "calls_full"), (409, "budget_exhausted"), (429, "daily_limit"),
    (429, "request_limit"), (503, "db_unavailable"), (500, "internal"),
}
PROBLEMS.update({
    "call_busy": (409, "다른 기기에서 통화 중이야"),
    "calls_full": (409, "지금은 전화가 꽉 찼어"),
    "budget_exhausted": (409, "통화 사용 한도에 도달했어요"),
})
HEADERS = {
    "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY", "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
                               "form-action 'none'",
}


class Problem(Exception):
    def __init__(self, code: str, errors: list | None = None, headers: dict | None = None, *, title=None, missing=None):
        super().__init__(code)
        self.code, self.errors, self.headers = code, errors or [], headers or {}
        self.title = title
        self.missing = missing


def bad(*errors) -> Problem:
    return Problem("invalid_request", [{"field": f, "reason": r} for f, r in errors][:10])


class AppChat:
    def __init__(self, store, agent, client, access, push, *, origin: str = DEFAULT_ORIGIN, port: int = DEFAULT_PORT,
                 timezone: str = "Asia/Seoul", clock=time.monotonic, releases: AppReleases | None = None,
                 sessions=None, authentication="access", admin_email_hash=None, diary_models=None, pet_app_settings=None,
                 web_push_subscriptions=None, web_push_references=None):
        self.store = store
        self.agent = agent      # DiscordAgent: the same one that answers the Discord DM
        self.client = client    # DiscordDM: its room locks keep one answer at a time per room
        self.access = access    # access.AccessVerifier
        self.push = push        # app_push.AppPush
        self.origin = origin
        self.port = port
        self.tz = ZoneInfo(timezone)
        self.clock = clock
        self.releases = releases if releases is not None else AppReleases()
        self.sessions = sessions
        self.authentication = auth_mode(authentication)
        self.web_push_subscriptions = web_push_subscriptions if sessions and authentication != "access" else None
        self.web_push_references = web_push_references
        self.web_push_delivery = None
        self.web_push_call = None
        if self.web_push_subscriptions is not None:
            sessions.web_push_subscriptions = self.web_push_subscriptions
        self.delivery = None
        self.internal_shop = None
        from .usage import Usage, configured_call_limit, configured_limit
        self.usage = Usage(store.pool, configured_limit(), sessions.now,
                           call_limit=configured_call_limit()) if sessions else None
        if self.usage is not None and hasattr(agent, "usage"):
            agent.usage = self.usage
        self.tick = asyncio.Event()          # set and replaced whenever a message is saved in this process
        self.reply_traces = OrderedDict()
        self.waiters = defaultdict(list)     # friend id -> events of their waits, oldest first
        self.sent = defaultdict(deque)       # friend id -> when their last messages came (rate limit)
        self.read = {}                       # DM room -> the friend's newest message an answer here took up (SPEC-148)
        self.tasks = set()
        self.files = {k: ((STATIC / name).read_bytes(), kind) for k, (name, kind) in FILES.items()}
        if getattr(agent, "friend_cards", None):
            self.files[""] = (self.files[""][0].replace(b"<!-- persona-link -->",
                '<a class="icon-button" href="/chat/persona/" aria-label="친구 약속">나</a>'.encode("utf-8")), "text/html")
        self.runner = None
        self.diary_models = diary_models
        self.diary_scenes = None
        from .pet_app_settings import PetAppSettings
        self.pet_app_settings = pet_app_settings if pet_app_settings is not None else PetAppSettings.from_env(os.environ)
        from .app_persona import AppPersona
        self.persona = AppPersona(self)
        from .app_admin import AppAdmin
        from .app_profile import AppProfile
        from .app_decor import AppDecor
        self.admin = AppAdmin(self, admin_email_hash)
        self.profile = AppProfile(self)
        self.decor = AppDecor(self)
        self.characters = None
        if sessions is not None:
            from .character.http import CharacterAPI
            self.characters = CharacterAPI(self)
        if sessions is not None:
            from .app_friends import AppFriends
            self.friends = AppFriends(self)
        if sessions is not None:
            self.files.update({name: ((STATIC / name).read_bytes(), mime) for name, mime in UNIFIED_FILES.items()})

    # ── plumbing ───────────────────────────────────────────────

    def pulse(self) -> None:
        """A message was saved (or Marong started or stopped writing): every wait looks again."""
        self.tick.set()
        self.tick = asyncio.Event()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _problem(self, p: Problem, trace: str) -> web.Response:
        status, title = PROBLEMS[p.code]
        body = {"type": f"{self.origin}/problems/{p.code.replace('_', '-')}", "title": p.title or title, "status": status,
                "code": p.code, "traceId": trace}
        if p.errors:
            body["errors"] = p.errors
        if p.missing is not None:
            body["missing"] = p.missing
        return web.Response(status=status, text=json.dumps(body, ensure_ascii=False),
                            content_type="application/problem+json", charset="utf-8", headers=p.headers)

    @staticmethod
    def _json(status: int, body: dict) -> web.Response:
        return web.Response(status=status, text=json.dumps(body, ensure_ascii=False), content_type="application/json",
                            charset="utf-8")

    @web.middleware
    async def guard(self, req, handler):
        trace = secrets.token_hex(8)
        req["trace_id"] = trace
        try:
            res = await handler(req)
        except Problem as p:
            res = self._problem(p, trace)
        except SessionError as p:
            headers = {"Retry-After": str(p.retry_after)} if p.retry_after is not None else None
            title = WEB_NOTICE_TITLES.get(p.code) if req.path.startswith(WEB_NOTICE_PATH + "/") else None
            res = self._problem(Problem(p.code, headers=headers, title=title), trace)
        except CharacterError as p:
            res = self._problem(Problem(p.code, p.errors), trace)
        except web.HTTPException as e:
            res = e
        except (psycopg.OperationalError, TimeoutError) as e:  # includes the pool timeout
            log.warning("app_chat_db_unavailable %s trace=%s", type(e).__name__, trace)
            title = WEB_NOTICE_TITLES["db_unavailable"] if req.path.startswith(WEB_NOTICE_PATH + "/") else None
            res = self._problem(Problem("db_unavailable", title=title), trace)
        except Exception as e:
            log.error("app_chat_error %s trace=%s", type(e).__name__, trace)
            title = WEB_NOTICE_TITLES["internal"] if req.path.startswith(WEB_NOTICE_PATH + "/") else None
            res = self._problem(Problem("internal", title=title), trace)
        if req.method == "GET" and req.path == RELEASE_CHECK_PATH:
            prefix, _, version = req.headers.get("User-Agent", "").partition("/")
            if prefix == "MarongApp" and VERSION.fullmatch(version):
                log.info("app_release check version=%s status=%d", version, res.status)
        if req.get("session_refresh") and res.status < 400:
            self._set_session_cookie(res, req["session_refresh"])
        res.headers.update(HEADERS)
        if req.get("notice_call_document") and res.status == 200:
            res.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
        if req.path == "/chat/" and res.status == 200 and self.notice_call_enabled:
            res.headers["Referrer-Policy"] = "same-origin"
            res.headers["Content-Security-Policy"] = HEADERS["Content-Security-Policy"].replace(
                "form-action 'none'", f"form-action {self.origin}{NOTICE_CALL_PAGE}")
        if req.get("cache") and res.status == 200:  # a picture of a picture set never changes (API-140)
            res.headers["Cache-Control"] = req["cache"]
        return res

    def _require_app_origin(self, req):
        if req.headers.get("Origin") != self.origin:
            raise Problem("cross_site")

    @property
    def notice_call_enabled(self):
        return all(item is not None for item in (self.web_push_subscriptions, self.web_push_references,
                                                self.web_push_call))

    @staticmethod
    async def _notice_call_form(req):
        limit = 2048
        if (req.content_type != "application/x-www-form-urlencoded"
                or req.content_length is None or not 0 < req.content_length <= limit):
            raise SessionError("invalid_input")
        try:
            pairs = parse_qsl((await req.read()).decode("ascii"), strict_parsing=True, errors="strict",
                              max_num_fields=4)
        except ValueError:
            raise SessionError("invalid_input") from None
        values = dict(pairs)
        required = {"targetRef", "installationProof", "navigation"}
        if (len(pairs) != len(values) or set(values) not in (required, required | {"ordinaryChoice"},
                                                            required | {"redialChoice"})
                or not re.fullmatch(r"[A-Za-z0-9_-]{48,768}", values["targetRef"])
                or not re.fullmatch(r"[0-9a-f]{32}", values["navigation"])
                or ("ordinaryChoice" in values and not re.fullmatch(r"[A-Za-z0-9_-]{43}", values["ordinaryChoice"]))
                or ("redialChoice" in values and not re.fullmatch(r"[A-Za-z0-9_-]{102}", values["redialChoice"]))):
            raise SessionError("invalid_input")
        return values

    @staticmethod
    def _notice_call_failure(state, status, *, retry=None):
        title, detail = NOTICE_CALL_FAILURES[state]
        action = '<a id="notice-login" href="/chat/login?expired=1">들어가기</a>' if state == "login" else ""
        if state in {"expired", "unavailable", "offline", "limited"}:
            action = '<button type="button" id="notice-retry">상태 다시 확인</button>'
        delay = str(retry or 0)
        body = f'''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<link rel="stylesheet" href="/chat/notice-call.css">
<script defer src="/chat/web-notifications.js"></script><script defer src="/chat/notice-call.js"></script>
<main class="notice-phone" data-failure="{state}" data-wait="{delay}"><section class="notice-card">
<h1 id="notice-title" tabindex="-1">{title}</h1><p>{detail}</p><div class="notice-actions">
{action}<a id="notice-back" href="/chat/">글 대화로</a></div></section></main></html>'''
        headers = {"Retry-After": delay} if retry else None
        return web.Response(status=status, text=body, content_type="text/html", headers=headers)

    async def notice_call_page(self, req):
        if not self.notice_call_enabled or req.method != "POST" or req.query_string:
            return self._notice_call_failure("denied", 404)
        if (req.headers.getall("Origin", []) != [self.origin]
                or req.headers.get("Sec-Fetch-Site") not in (None, "same-origin")
                or req.headers.get("Sec-Fetch-Mode") not in (None, "navigate")
                or req.headers.get("Sec-Fetch-Dest") not in (None, "document")):
            return self._notice_call_failure("denied", 403)
        try:
            form = await self._notice_call_form(req)
            try:
                ident = installation_id(form["installationProof"])
            except SessionError:
                raise SessionError("not_allowed") from None
            subscriptions = self.web_push_subscriptions
            protocol = self.web_push_call
            reference = form["targetRef"]
            choice = form.get("ordinaryChoice")
            redial = form.get("redialChoice")
            token = req.cookies.get(COOKIE)
            if redial:
                async with subscriptions.authenticated(token, ident) as (conn, session, now):
                    scope, consent = await self._redial_scope(conn, session, ident, reference, now)
                    protocol.check_redial(scope, redial, now, choice=True)
                if not await self._notice_ended(form["installationProof"], session, reference, consent, redial,
                                                choice=True):
                    raise SessionError("not_allowed")
            async with subscriptions.authenticated(token, ident, write=True, count_request=not redial) as (conn, session, _):
                await lock_installation(conn, ident)
                now = subscriptions.now()
                if session["expires_at"] <= now:
                    raise SessionError("login_required")
                sid = session["id"]
                if redial:
                    scope, _ = await self._redial_scope(conn, session, ident, reference, now)
                    protocol.check_redial(scope, redial, now, choice=True)
                elif choice:
                    if not hmac.compare_digest(choice, protocol.ordinary_choice(sid, ident, reference)):
                        raise SessionError("not_allowed")
                    consent = None
                else:
                    try:
                        consent, _ = await subscriptions.active_consent(conn, ident, sid, now)
                    except SessionError as error:
                        if error.code != "not_allowed":
                            raise
                        try:
                            result = await resolve_target(conn, self.store, self.web_push_references, session,
                                                          reference, now)
                        except SessionError:
                            raise error from None
                        if result["state"] == "ring_expired":
                            return self._notice_call_failure("expired", 403)
                        raise
                result = await resolve_target(conn, self.store, self.web_push_references, session, reference, now,
                                              require_enabled_caller=bool(choice or redial))
                if choice and result["state"] != "ring_expired":
                    return self._notice_call_failure("unavailable", 403)
                if redial and result["state"] != "ring_answered":
                    raise SessionError("not_allowed")
                call_client = (protocol.redial_document(redial) if redial
                               else protocol.document_client(sid, ident, reference, consent))
        except SessionError as error:
            state, status = {
                "login_required": ("login", 401), "not_allowed": ("denied", 403),
                "not_found": ("denied", 404), "invalid_input": ("denied", 400),
                "request_limit": ("limited", 429),
            }.get(error.code, ("offline", 503))
            return self._notice_call_failure(state, status, retry=error.retry_after)
        except (psycopg.OperationalError, TimeoutError):
            return self._notice_call_failure("offline", 503)
        except Exception as error:
            log.error("notice_call_page_error %s trace=%s", type(error).__name__, req["trace_id"])
            return self._notice_call_failure("offline", 500)
        state = result["state"]
        if state == "ring_answered" and not redial:
            return self._notice_call_failure("answered", 200)
        if state == "ring_unavailable":
            return self._notice_call_failure("unavailable", 200)
        if state == "ring_expired" and not choice:
            return self._notice_call_failure("expired", 200)
        if state not in {"ring_ready", "ring_expired", "ring_answered"}:
            return self._notice_call_failure("denied", 404)
        # Opaque document identifiers only. Do not echo the reference or installation proof.
        data = self.files["notice-call.html"][0].replace(b"@NAVIGATION@", form["navigation"].encode("ascii"))
        data = data.replace(b"@CALL_CLIENT@", str(call_client).encode("ascii"))
        purpose = b"redial" if redial else b"ordinary" if choice else b"answer"
        data = data.replace(b"@PURPOSE@", purpose)
        req["notice_call_document"] = True
        return web.Response(body=data, content_type="text/html", charset="utf-8")

    def _web_notice_request(self, req):
        origin = req.headers.get("Origin")
        site = req.headers.get("Sec-Fetch-Site")
        if ((req.method != "GET" or origin is not None) and origin != self.origin
                or site not in (None, "same-origin", "none")):
            raise SessionError("cross_site")
        return req.cookies.get(COOKIE), installation_id(req.headers.get(INSTALLATION_HEADER))

    @staticmethod
    async def _web_notice_body(req, limit):
        if req.content_type != "application/json" or (req.content_length is not None and req.content_length > limit):
            raise SessionError("invalid_input")
        raw = bytearray()
        async for chunk in req.content.iter_chunked(limit):
            raw.extend(chunk)
            if len(raw) > limit:
                raise SessionError("invalid_input")
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            raise SessionError("invalid_input") from None
        if not isinstance(body, dict):
            raise SessionError("invalid_input")
        return body

    async def web_notice_status(self, req):
        token, ident = self._web_notice_request(req)
        return self._json(200, await self.web_push_subscriptions.status(token, ident))

    async def web_notice_choice(self, req):
        token, ident = self._web_notice_request(req)
        body = await self._web_notice_body(req, 2048)
        return self._json(200, await self.web_push_subscriptions.choice(token, ident, body))

    async def web_notice_register(self, req):
        token, ident = self._web_notice_request(req)
        body = await self._web_notice_body(req, 4096)
        result = await self.web_push_subscriptions.register(token, ident, req.headers.get(CHOICE_HEADER), body)
        return self._json(200, result)

    async def web_notice_revoke(self, req):
        token, ident = self._web_notice_request(req)
        result = await self.web_push_subscriptions.revoke(token, ident, req.headers.get(CHOICE_HEADER))
        return self._json(200, result)

    async def web_notice_resolve(self, req):
        token, ident = self._web_notice_request(req)
        body = await self._web_notice_body(req, 2048)
        if set(body) != {"targetRef"}:
            raise SessionError("invalid_input")
        reference = body["targetRef"]
        if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z0-9_-]{48,768}", reference):
            raise SessionError("invalid_input")
        receipt = req.headers.get(RECEIPT_HEADER)
        redial = req.headers.get(REDIAL_HEADER)
        claim = None
        async with self.web_push_subscriptions.authenticated(token, ident) as (conn, session, now):
            protocol = self.web_push_call
            sid = session["id"]
            document = req.headers.get("X-Marong-Notice-Document")
            ordinary = False
            if document is not None:
                if protocol is None:
                    raise SessionError("not_allowed")
                client = client_uuid(document)
                ordinary = protocol.matches_document(sid, ident, reference, None, client)
            result = await resolve_target(conn, self.store, self.web_push_references, session, reference, now,
                                          require_enabled_caller=ordinary)
            if redial is not None:
                if (document is None or not re.fullmatch(r"[A-Za-z0-9_-]{102}", redial)
                        or client != protocol.redial_document(redial) or result["state"] != "ring_answered"):
                    raise SessionError("not_allowed")
                scope, consent = await self._redial_scope(conn, session, ident, reference, now)
                protocol.check_redial(scope, redial, now, choice=True)
            elif document is not None and not ordinary:
                await self._check_notice_consent(conn, ident, sid, now, client, reference)
            if protocol is not None and document is None and receipt and result["state"] == "ring_answered":
                try:
                    scope, consent = await self._redial_scope(conn, session, ident, reference, now)
                    claim = protocol.check_redial(scope, receipt, now)
                except SessionError:
                    pass  # The original read response remains available without a receipt.
            response = self._json(200, result)
            if protocol is not None and document is None and result["state"] == "ring_expired":
                response.headers[ORDINARY_CHOICE_HEADER] = protocol.ordinary_choice(sid, ident, reference)
        if redial is not None:
            if not await self._notice_ended(req.headers[INSTALLATION_HEADER], session, reference, consent, redial,
                                            choice=True):
                raise SessionError("not_allowed")
        elif claim is not None and await self._notice_ended(req.headers[INSTALLATION_HEADER], session, reference,
                                                           consent, receipt):
            # Recheck consent after loopback without counting a second request or holding an app lock over the read.
            try:
                async with self.web_push_subscriptions.authenticated(token, ident, count_request=False) as (
                        conn, current_session, now):
                    scope, _ = await self._redial_scope(conn, current_session, ident, reference, now)
                    claim = protocol.check_redial(scope, receipt, now)
                    response.headers[REDIAL_HEADER] = protocol.redial_choice(scope, claim, now)
            except (SessionError, psycopg.OperationalError, TimeoutError):
                pass
        return response

    async def _redial_scope(self, conn, session, ident, reference, now):
        consent, _ = await self.web_push_subscriptions.active_consent(conn, ident, session["id"], now)
        scope = self.web_push_call.receipt_scope(session["friend_id"], session["id"], ident, reference, consent)
        return scope, consent

    async def _notice_ended(self, proof, session, reference, consent, receipt, *, choice=False):
        # No app transaction is held across this read-only call.
        headers = {READ_BRIDGE_HEADER: self.web_push_call.read_secret, INSTALLATION_HEADER: proof}
        body = {"friend": session["friend_id"], "session": session["id"], "targetRef": reference,
                "consent": consent, "receipt": receipt, "choice": choice}
        try:
            async with ClientSession(timeout=ClientTimeout(total=2)) as bridge:
                async with bridge.post(ENDED_BRIDGE, headers=headers, json=body, allow_redirects=False) as response:
                    return response.status == 204
        except (ClientError, TimeoutError):
            return False

    async def _check_notice_consent(self, conn, ident, sid, now, client, reference, *, redial=None):
        consent, expires = await self.web_push_subscriptions.active_consent(conn, ident, sid, now)
        matches = (client == self.web_push_call.redial_document(redial) if redial is not None
                   else self.web_push_call.matches_document(sid, ident, reference, consent, client))
        if not matches:
            raise SessionError("not_allowed")
        return consent, expires

    async def notice_installation_check(self, req):
        # Only the loopback call server asks while it holds the session and installation locks.
        if (not self.notice_call_enabled or req.remote not in {"127.0.0.1", "::1"}
                or not hmac.compare_digest(req.headers.get(BRIDGE_HEADER, ""), self.web_push_call.bridge_secret)):
            raise web.HTTPNotFound()
        body = await self._web_notice_body(req, 2048)
        fields = {"session", "targetRef", "clientId"}
        redial = body.get("redialChoice")
        if (set(body) not in (fields, fields | {"redialChoice"}) or type(body["session"]) is not int
                or not 0 < body["session"] < 2**63
                or ("redialChoice" in body and (not isinstance(redial, str)
                                               or not re.fullmatch(r"[A-Za-z0-9_-]{102}", redial)))
                or not isinstance(body["targetRef"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{48,768}", body["targetRef"])):
            raise SessionError("invalid_input")
        ident = installation_id(req.headers.get(INSTALLATION_HEADER))
        client = client_uuid(body["clientId"])
        subscriptions = self.web_push_subscriptions
        async with asyncio.timeout(2), subscriptions.pool.connection() as conn:
            consent, expires = await self._check_notice_consent(conn, ident, body["session"], subscriptions.now(), client,
                                                                body["targetRef"], redial=redial)
        headers = {CONSENT_HEADER: consent, "Cache-Control": "no-store"}
        if expires is not None:
            headers["X-Marong-Subscription-Expires"] = str(expires)
        return web.Response(status=204, headers=headers)

    async def web_notice_reply_view(self, req):
        token, ident = self._web_notice_request(req)
        arrival = self.web_push_delivery.reply_arrival()
        body = await self._web_notice_body(req, 1024)
        if set(body) != {"messageId", "view"} or body["view"] not in ("visible", "hidden"):
            raise SessionError("invalid_input")
        ident_text = body["messageId"]
        if (not isinstance(ident_text, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", ident_text)
                or int(ident_text) > 2**63 - 1):
            raise SessionError("invalid_input")
        message = int(ident_text)
        async with self.web_push_subscriptions.authenticated(token, ident, limit=120) as (conn, session, now):
            row = await self.web_push_subscriptions._row(conn, ident)
            sid = session["id"]
            if (row is None or row["session_id"] != sid
                    or self.web_push_subscriptions._state(row, ident, sid, now) != "active"):
                raise SessionError("not_allowed")
            if not await visible_message(conn, self.store, session["friend_id"], message, reply_only=True):
                raise SessionError("not_found")
        self.web_push_delivery.report_reply_view(sid, ident, message, body["view"], arrival)
        return self._json(200, {"state": "recorded" if body["view"] == "visible" else "cleared"})

    async def web_notice_accept(self, req):
        token, ident = self._web_notice_request(req)
        body = await self._web_notice_body(req, 2048)
        if set(body) != {"targetRef", "clientId"}:
            raise SessionError("invalid_input")
        client = client_uuid(body["clientId"])
        reference = body["targetRef"]
        if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z0-9_-]{48,768}", reference):
            raise SessionError("invalid_input")
        async with self.web_push_subscriptions.authenticated(token, ident) as (conn, session, now):
            await self._check_notice_consent(conn, ident, session["id"], now, client, reference)
            kind, _ = self.web_push_references.open(reference, session["friend_id"], now)
            if kind != "call":
                raise SessionError("not_found")
        headers = {BRIDGE_HEADER: self.web_push_call.bridge_secret, INSTALLATION_HEADER: req.headers[INSTALLATION_HEADER]}
        try:
            async with ClientSession(timeout=ClientTimeout(total=5)) as bridge:
                async with bridge.post(CALL_BRIDGE, json=body, headers=headers, cookies={COOKIE: token},
                                       allow_redirects=False) as response:
                    status, result = response.status, await response.json()
                    retry_after = response.headers.get("Retry-After")
                    receipt = {name: response.headers[name] for name in (RECEIPT_HEADER, RECEIPT_EXPIRES_HEADER)
                               if name in response.headers}
        except (ClientError, TimeoutError, ValueError):
            raise SessionError("db_unavailable") from None
        if status == 200 and isinstance(result, dict):
            result_response = self._json(200, result)
            if result.get("state") == "accepted" and len(receipt) == 2:
                result_response.headers.update(receipt)
            return result_response
        code = result.get("code") if isinstance(result, dict) else None
        if (status, code) not in WEB_CALL_ERRORS:
            raise SessionError("db_unavailable")
        retry = int(retry_after) if retry_after and re.fullmatch(r"[1-9][0-9]{0,3}", retry_after) else None
        raise SessionError(code, retry_after=retry)

    def _optional_installation(self, req):
        if self.web_push_subscriptions is None:
            return None
        try:
            return installation_id(req.headers.get(INSTALLATION_HEADER))
        except SessionError:
            return None

    async def _session_body(self, req, required, optional=()):
        try:
            body = await self._body(req)
        except Problem as e:
            raise Problem("invalid_input", e.errors) from None
        if required not in body or set(body) - {required, *optional}:
            raise Problem("invalid_input")
        return body

    def _set_session_cookie(self, response, token, *, clear=False):
        age = 0 if clear else int(self.sessions.session_age.total_seconds())
        response.set_cookie(COOKIE, token, max_age=age, path="/", httponly=True, secure=True, samesite="Lax")
        return response

    async def check_invite(self, req):
        kind = await self.sessions.check_invite(req.match_info["token"])
        return self._json(200, {"kind": kind, "state": "open"})

    async def join_with_invite(self, req):
        self._require_app_origin(req)
        body = await self._session_body(req, "token", ("name",))
        session = await self.sessions.join(body["token"], body.get("name"), device_label(req.headers.get("User-Agent", "")),
                                           installation=self._optional_installation(req))
        return self._set_session_cookie(self._json(201, session.public()), session.token)

    async def login_with_device_code(self, req):
        self._require_app_origin(req)
        body = await self._session_body(req, "code")
        address = req.headers.get("CF-Connecting-IP") or req.remote or "unknown"
        session = await self.sessions.redeem_device_code(
            body["code"], address, device_label(req.headers.get("User-Agent", "")),
            installation=self._optional_installation(req))
        return self._set_session_cookie(self._json(200, session.public()), session.token)

    async def create_device_code(self, req):
        who = await self._who(req, write=True)
        if who["profile_id"] is None:
            await self.sessions.ensure_profile(who["friend_id"])
        code, expiry = await self.sessions.create_device_code(who["friend_id"])
        return self._json(201, {"code": code, "expiresAt": expiry.isoformat()})

    async def logout(self, req):
        self._require_app_origin(req)
        await self.sessions.logout(req.cookies.get(COOKIE))
        return self._set_session_cookie(web.Response(status=204), "", clear=True)

    async def _who(self, req, write: bool = False, *, require_dm: bool = True) -> dict:
        """The signed-in call friend and their DM room (SPEC-111). Writes must come from the call address."""
        if write:
            self._require_app_origin(req)
        if self.sessions is not None:
            return await self._unified_who(req)
        status, email_hash = await self.access.check(req.headers.get("Cf-Access-Jwt-Assertion", ""))
        if status == "unavailable":
            raise Problem("db_unavailable")
        if status != "ok":
            raise Problem(status)
        who = await self.store.app_login(email_hash)
        if not who or not who["enabled"]:
            raise Problem("not_allowed")
        if require_dm and (not who["room_key"] or not who["channel_id"]):
            raise Problem("no_dm")
        return who

    async def _unified_who(self, req):
        async def from_access():
            token = req.headers.get("Cf-Access-Jwt-Assertion", "")
            if not token:
                raise Problem("login_required")
            status, email_hash = await self.access.check(token)
            if status == "unavailable":
                raise Problem("db_unavailable")
            if status != "ok":
                raise Problem(status)
            return await self.sessions.find_access_member(email_hash)

        token = req.cookies.get(COOKIE)
        who = await identify_request(self.authentication, token, self.sessions.find_session, from_access)
        if not who or not who["room_key"]:
            raise Problem("login_required")
        if who.get("renewed"):
            req["session_refresh"] = token
        return who

    async def app_release(self, req):
        await self._who(req, require_dm=False)
        release = await asyncio.to_thread(self.releases.latest)
        return self._json(200, release.public()) if release else web.Response(status=204)

    async def app_apk(self, req):
        who = await self._who(req, require_dm=False)
        opened = await asyncio.to_thread(self.releases.open, req.match_info["file"])
        if opened is None:
            raise Problem("no_release")
        release, file = opened
        with file:
            res = web.StreamResponse(headers={**HEADERS, "Content-Length": str(release.size),
                                              "Content-Type": "application/vnd.android.package-archive"})
            try:
                await res.prepare(req)
                while chunk := await asyncio.to_thread(file.read, 65536):
                    await res.write(chunk)
                await res.write_eof()
            except ConnectionError:
                return res  # the phone disconnected, so no complete download was served
        log.info("app_release apk sent code=%d", release.code)
        try:
            await self.store.app_update_fetched(who["friend_id"], release.code)
        except (psycopg.Error, TimeoutError):
            log.warning("app_update record failed kind=fetched")
        return res

    @staticmethod
    async def _body(req) -> dict:
        try:
            body = await req.json()
        except (ValueError, UnicodeDecodeError):
            raise bad(("body", "bad_format"))
        if not isinstance(body, dict):
            raise bad(("body", "bad_format"))
        return body

    @staticmethod
    def _number(raw, field: str, *, minimum: int, maximum: int = 2**63 - 1, required: bool = False) -> int | None:
        if raw is None or raw == "":
            if required:
                raise bad((field, "required"))
            return None
        if not NUMBER.fullmatch(raw):
            raise bad((field, "bad_format"))
        value = int(raw)
        if not minimum <= value <= maximum:
            raise bad((field, "bad_format"))
        return value

    def _limit(self, friend_id: int) -> None:
        now = self.clock()
        sent = self.sent[friend_id]
        while sent and now - sent[0] >= RATE_WINDOW_S:
            sent.popleft()
        if len(sent) >= RATE:
            wait = max(1, math.ceil(RATE_WINDOW_S - (now - sent[0])))
            raise Problem("too_many_messages", headers={"Retry-After": str(wait)})
        sent.append(now)

    def _took_up(self, room: str, message_id: int) -> None:
        """An answer in this process took up the friend's message: it and everything before it are read."""
        if message_id > self.read.get(room, 0):
            self.read.pop(room, None)
            self.read[room] = message_id
            while len(self.read) > READ_ROOMS_MAX:
                self.read.pop(next(iter(self.read)))

    async def _marks(self, room: str) -> dict:
        """What the screen shows under the list (SPEC-114, SPEC-148, SPEC-149). answeredUpTo: the newest of the
        friend's messages Marong answered. readUpTo: the newest one she read, that is answered or taken up by an
        answer here. typing: an answer holds the room and some message of the friend's is not answered yet."""
        state = await self.store.app_answered(room)
        answered = state["answered"]
        read = max(answered, min(self.read.get(room, 0), state["newest"]))
        typing = self.client.room_lock(room).locked() and state["newest"] > answered
        return {"typing": typing, "readUpTo": read, "answeredUpTo": answered}

    def message(self, row: dict) -> dict:
        """A messages row as the API's Message (SPEC-113)."""
        meta = row["meta"] or {}
        if row["role"] == "user":
            via, kind = self._via(row["kakao_id"]), "chat"
        else:
            via = meta.get("transport") if meta.get("transport") in ("app", "discord") else self._via(row["reply_key"])
            kind = ("hello" if meta.get("hello") else "ring" if meta.get("ring") else "proactive"
                    if meta.get("proactive") else "reminder" if meta.get("reminder")
                    else "note" if row["reply_to"] is None else "chat")
        out = {"id": row["id"], "from": "me" if row["role"] == "user" else "marong",
               "text": (row["content"] or "").replace(LINK_MARK, "(일회용 링크)")[:20_000],
               "at": row["created_at"].astimezone(self.tz).isoformat(timespec="seconds"), "via": via, "kind": kind}
        picture = None
        if row["role"] == "assistant":
            scene = meta.get("scene")
            if isinstance(scene, str) and UUID.fullmatch(scene):
                alt = meta.get("sceneAlt")
                picture = {"src": f"/chat/api/scenes/{scene}",
                           "alt": alt[:60] if isinstance(alt, str) and alt else "반려동물 캐릭터의 그림"}
                name = meta.get("reactionName")
                if isinstance(name, str) and 1 <= len(name) <= 20:
                    picture["reaction"] = name
            else:
                picture = self._picture(meta.get("topic"))
        if picture:
            out["picture"] = picture
        return out

    @staticmethod
    def _picture(key) -> dict | None:
        """A picture topic's picture (SPEC-274): only one the picture list knows, removed ones too."""
        found = picture_set() if isinstance(key, str) and TOPIC_KEY.fullmatch(key) else None
        picture = found.get(key) if found else None
        return {"src": picture.src, "alt": picture.alt} if picture else None

    @staticmethod
    def _via(key: str | None) -> str | None:
        if not key:
            return None
        return "app" if key.startswith(APP_KEY) else "discord" if key.startswith("discord:") else None

    # ── pages ──────────────────────────────────────────────────

    async def health(self, req):
        return web.Response(text="ok", content_type="text/plain")

    async def home(self, req):
        raise web.HTTPFound("/chat/")

    def unified_page(self, name, *, signed_cookie=False):
        data, kind = self.files[name + ".html"]
        if signed_cookie:
            data = data.replace(b'<body>', b'<body data-session-cookie="yes">', 1)
        if self.web_push_subscriptions is not None and name in {"account", "profile"}:
            data = data.replace(b'<script ', WEB_NOTICE_SCRIPT + b'<script ', 1)
        return web.Response(body=data, content_type=kind, charset="utf-8")

    async def account_page(self, req):
        return self.unified_page("account", signed_cookie=bool(req.cookies.get(COOKIE)))

    async def picture(self, req):
        """API-140: a picture topic's picture (SPEC-274, SPEC-269), for the chat page and the call page. Only names in
        the picture list, removed ones too; anything else is no_picture. Not checked against Access again: the same
        rule as chat.js (Access stands in front), and every friend sees the same pictures of Marong."""
        set_name, file = req.match_info["set"], req.match_info["file"]
        name = file[:-len(".webp")] if file.endswith(".webp") else ""
        found = picture_set() if SET_NAME.fullmatch(set_name) and PICTURE_NAME.fullmatch(name) else None
        picture = found.get(f"{set_name}/{name}") if found else None
        if picture is None:
            raise Problem("no_picture")
        body = await asyncio.to_thread(picture.path.read_bytes)
        req["cache"] = "public, max-age=31536000, immutable"
        return web.Response(body=body, content_type="image/webp")

    async def web_asset(self, req):
        name = req.match_info["asset"]
        mime = "application/manifest+json" if name == "manifest.webmanifest" else "image/png"
        return web.FileResponse(STATIC / name, headers={"Content-Type": mime})

    async def page(self, req):
        if self.sessions is not None and self.authentication != "access" and not req.match_info.get("name"):
            try:
                await self._unified_who(req)
            except (Problem, SessionError) as error:
                if error.code not in {"login_required", "unauthenticated"}:
                    raise
                raise web.HTTPFound("/chat/login") from None
        found = self.files.get(req.match_info.get("name", ""))
        if not found:
            raise web.HTTPNotFound()
        data, kind = found
        if self.web_push_subscriptions is not None and kind == "text/html":
            data = data.replace(b'<script ', WEB_NOTICE_SCRIPT + b'<script ', 1)
        if req.path == "/chat/" and self.notice_call_enabled:
            data = data.replace(b'<body', b'<body data-notice-call-enabled="true"', 1)
        return web.Response(body=data, content_type=kind, charset="utf-8")

    async def web_notice_asset(self, req):
        asset = req.match_info["asset"]
        return web.FileResponse(STATIC / asset, headers={"Content-Type": "text/css" if asset.endswith(".css") else "text/javascript"})

    # ── API ────────────────────────────────────────────────────

    async def me(self, req):
        """API-101."""
        who = await self._who(req)
        devices = await self.store.app_devices(who["friend_id"])
        name = (who["name"] or "").strip()[:NAME_MAX] or "친구"
        return self._json(200, {"name": name, "delivery": self.push.delivery(devices),
                                "ring": self.push.ring_route(devices), "textMax": TEXT_MAX})

    async def messages(self, req):
        """API-102."""
        who = await self._who(req)
        before = self._number(req.query.get("before"), "before", minimum=1)
        limit = self._number(req.query.get("limit"), "limit", minimum=1, maximum=PAGE_MAX) or PAGE_DEFAULT
        rows = await self.store.app_messages(who["room_key"], before, limit)
        marks = await self._marks(who["room_key"])
        response = self._json(200, {"messages": await self.persona.messages(who, rows[:limit][::-1]),
                                "hasMore": len(rows) > limit, "readUpTo": marks["readUpTo"],
                                "answeredUpTo": marks["answeredUpTo"]})
        self._note_http_delivery(rows[:limit], "history")
        return response

    async def send(self, req):
        """API-103: store at once (202), answer in the background under the room lock (SPEC-112)."""
        who = await self._who(req, write=True)
        body = await self._body(req)
        errors = [("body", "bad_format")] if set(body) - {"clientId", "text"} else []
        client_id, text = body.get("clientId"), body.get("text")
        if client_id is None:
            errors.append(("clientId", "required"))
        elif not isinstance(client_id, str) or not UUID.fullmatch(client_id):
            errors.append(("clientId", "bad_format"))
        if text is None:
            errors.append(("text", "required"))
        elif not isinstance(text, str):
            errors.append(("text", "bad_format"))
        elif len(text) > TEXT_MAX:
            errors.append(("text", "too_long"))
        else:
            text = text.strip()
            if not text:
                errors.append(("text", "too_short"))
        if errors:
            raise bad(*errors)
        self._limit(who["friend_id"])
        room, key = who["room_key"], APP_KEY + client_id
        old = await self.store.app_message(room, key)
        if old:
            return self._json(200, {"message": self.message(old)})
        if self.usage is not None and await self.usage.blocked(who["friend_id"]):
            raise Problem("daily_limit")
        preference = proactive_preference(text)
        if self.sessions is None:
            await self.store.incoming(who["discord_user_id"], who["channel_id"], key, preference)
            saved = await self.store.add_message(room, "user", text, user_key=who["user_key"], kakao_id=key,
                                                meta={"transport": "app"})
        else:
            saved = await self.store.app_incoming(who, key, text, preference)
        row = await self.store.app_message(room, key)
        if saved is None:  # the same message arrived twice at once: the other request answers it
            return self._json(200, {"message": self.message(row)})
        self._spawn(self._answer(who, saved, text, key, preference))
        self.pulse()
        log.info("app_chat_sent")
        return self._json(202, {"message": self.message(row)})

    async def _delivered(self, text: str) -> bool:
        with app_step("reply_prepare", result="queued") as prepared:
            if prepared:
                prepared.io(inputs={"reply": text})
            return True  # the wait endpoint or a push handles delivery

    async def _answer(self, who: dict, saved_id: int, text: str, key: str, preference) -> None:
        with trace_step("app_turn", surface="app_chat") as trace:
            if trace:
                trace.app_message(who["friend_id"], text, room_key=who["room_key"], user_key=who["user_key"])
                self.reply_traces[saved_id] = (time.monotonic(), trace)
                if len(self.reply_traces) > 256:
                    self.reply_traces.popitem(last=False)
            room = who["room_key"]
            reply = None
            try:
                with app_step("account_lookup", storage=True):
                    link = (await self.store.link(who["discord_user_id"]) if self.sessions is None
                            else await self.store.contact(who["friend_id"]))
                msg = DiscordIncoming(room, who["user_key"], text, kakao_id=key, proactive_preference=preference,
                                      google_command=google_command(text), topic_command=topic_phrase(text),
                                      friend_id=who["friend_id"], dm_link=link, via="app", presaved_id=saved_id)
                async with AsyncExitStack() as resources:
                    with app_step("room_queue"):
                        await resources.enter_async_context(self.client.room_lock(room))
                    self._took_up(room, saved_id)
                    self.pulse()  # '읽음' and '대답 중' once this answer holds the room (SPEC-148, SPEC-149)
                    reply = await self.agent.handle(msg, self._delivered)
            except Exception as e:
                if trace:
                    trace.capture(e)
                log.error("app_chat_reply_failed %s", type(e).__name__)
            finally:
                with app_step("reply_publish", result="queued" if reply is not None else "skipped"):
                    self.pulse()
            if reply is None:
                if trace:
                    self.reply_traces.pop(saved_id, None)
                    trace.record(result="no_reply")
                return
            if trace:
                trace.record(result="ok")
                trace.app_reply(reply)
            log.info("app_chat_replied")
            if self.web_push_delivery is not None and (reply_id := getattr(msg, "saved_app_reply", None)) is not None:
                self._spawn(self.web_push_delivery.publish(who["friend_id"], "reply", reply_id, REPLY_TTL_S))
            # The friend closed the chat before the answer came: tell their phone (SPEC-120). Never Discord.
            if not self.waiters.get(who["friend_id"]) and self.push.enabled:
                try:
                    with app_step("reply_push", delivery="push") as push:
                        if push:
                            push.io(inputs={"message": {"role": "assistant", "content": reply}})
                        if self.delivery and not await self.delivery.notifications_allowed(who["friend_id"]):
                            if push:
                                push.record(result="skipped", reason="no_session")
                            return
                        outcome = await self.push.notify(who["friend_id"], "reply", reply, ttl_s=REPLY_TTL_S)
                        if push and isinstance(outcome, tuple) and len(outcome) == 2:
                            accepted, available = outcome
                            push.record(result="ok" if accepted else "rejected" if available else "no_device",
                                        reason="no_ack" if available and not accepted else None,
                                        count=accepted, available=available)
                except Exception as e:
                    log.warning("app_reply_notify_failed %s", type(e).__name__)
            else:
                with app_step("reply_push", result="skipped",
                              reason="waiter_active" if self.waiters.get(who["friend_id"]) else "disabled"):
                    pass

    def _note_http_delivery(self, rows, transport):
        for row in rows:
            if row.get("role") == "assistant":
                pending = self.reply_traces.pop(row.get("reply_to"), None)
                if pending and time.monotonic() - pending[0] <= 600:
                    app_delivery(pending[1], transport, row.get("content"))

    async def wait(self, req):
        """API-104: new messages at once, else after up to 25 s an empty list (SPEC-114). `typing` and `read` are what
        the screen shows now: the wait also ends when Marong starts or stops writing or reads a message (SPEC-148).
        A screen from before '읽음' sends no `read` and gets no early end for it."""
        who = await self._who(req)
        after = self._number(req.query.get("after"), "after", minimum=0, required=True)
        shown = req.query.get("typing", "0")
        if shown not in ("0", "1"):
            raise bad(("typing", "bad_format"))
        shown_read = self._number(req.query.get("read"), "read", minimum=0)
        friend, room = who["friend_id"], who["room_key"]
        mine = asyncio.Event()
        queue = self.waiters[friend]
        queue.append(mine)
        if len(queue) > WAITERS_MAX:
            queue.pop(0).set()  # the oldest wait ends empty
        loop = asyncio.get_running_loop()
        end = loop.time() + WAIT_S
        rows, fresh, marks = [], False, None
        try:
            while True:
                tick = self.tick
                rows = await self.store.app_messages_after(room, after)
                fresh = any(r["id"] > after for r in rows)
                marks = await self._marks(room)
                read_moved = shown_read is not None and marks["readUpTo"] != shown_read
                if (fresh or marks["typing"] != (shown == "1") or read_moved or mine.is_set()
                        or loop.time() >= end):
                    break
                woke = [asyncio.ensure_future(tick.wait()), asyncio.ensure_future(mine.wait())]
                try:
                    await asyncio.wait(woke, timeout=min(WAIT_POLL_S, end - loop.time()),
                                       return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for w in woke:
                        w.cancel()
        finally:
            if mine in queue:
                queue.remove(mine)
            if not queue:
                self.waiters.pop(friend, None)
        if mine.is_set() and not fresh:
            rows = []
        response = self._json(200, {"messages": await self.persona.messages(who, rows), **marks})
        self._note_http_delivery(rows, "poll")
        return response

    @staticmethod
    def _valid_device_update(update) -> bool:
        if not isinstance(update, dict) or set(update) - {"versionCode", "state", "status"}:
            return False
        code, state = update.get("versionCode"), update.get("state")
        if type(code) is not int or not 1 <= code <= VERSION_CODE_MAX:
            return False
        if state == "failed":
            status = update.get("status")
            return type(status) is int and 1 <= status <= 999
        return state in ("downloaded", "waiting_quiet", "needs_confirm", "installed") and "status" not in update

    async def device(self, req):
        """API-105: this phone's notification state (SPEC-115, SPEC-139)."""
        who = await self._who(req, write=True)
        install_id = req.match_info["installId"]
        if not UUID.fullmatch(install_id):
            raise bad(("installId", "bad_format"))
        body = await self._body(req)
        errors = [("body", "bad_format")] if set(body) - {"fid", "notifications", "appVersion", "ring", "update"} else []
        fid = body.get("fid")
        if "fid" not in body:
            errors.append(("fid", "required"))
        elif fid is not None and (not isinstance(fid, str) or not FID.fullmatch(fid)):
            errors.append(("fid", "bad_format"))
        notifications = body.get("notifications")
        if notifications is None:
            errors.append(("notifications", "required"))
        elif notifications not in ("granted", "denied"):
            errors.append(("notifications", "bad_format"))
        version = body.get("appVersion")
        if version is None:
            errors.append(("appVersion", "required"))
        elif not isinstance(version, str) or not VERSION.fullmatch(version):
            errors.append(("appVersion", "bad_format"))
        ring = body.get("ring")
        if ring is not None and not (isinstance(ring, dict) and set(ring) == {"channel", "fullScreen"}
                                     and ring["channel"] in ("enabled", "disabled")
                                     and ring["fullScreen"] in ("granted", "denied")):
            errors.append(("body", "bad_format"))
        update = body.get("update")
        if "update" in body and not self._valid_device_update(update):
            errors.append(("update", "bad_format"))
        if errors:
            raise bad(*errors)
        published = {entry["versionCode"]: entry["versionName"]
                     for entry in await asyncio.to_thread(self.releases.history) if entry["kind"] == "published"}
        try:
            created = await self.store.app_device_put(install_id, who["friend_id"], fid, notifications, version,
                                                      ring and ring["channel"], ring and ring["fullScreen"],
                                                      published=published, update=update)
        except AppDeviceLimit:
            raise Problem("too_many_devices") from None
        devices = await self.store.app_devices(who["friend_id"], install_id)
        log.info("app_device %s fid=%s notifications=%s ring=%s", "added" if created else "updated", bool(fid),
                 notifications, ring["channel"] if ring else "none")
        return self._json(201 if created else 200, {"delivery": self.push.delivery(devices),
                                                    "ring": self.push.ring_route(devices)})

    # ── server ─────────────────────────────────────────────────

    def web_app(self) -> web.Application:
        from .app_diary import AppDiary
        from .app_listen import AppListen

        app = web.Application(client_max_size=BODY_MAX, middlewares=[self.guard])
        diary = AppDiary(self)
        if self.sessions is not None:
            from .diary_decor import DiaryDecor
            DiaryDecor(diary).register(app.router)
        diary.register(app)
        AppListen(self).register(app)
        app.router.add_get("/chat/healthz", self.health)
        app.router.add_route("*", NOTICE_CALL_PAGE, self.notice_call_page)
        if self.notice_call_enabled:
            app.router.add_post(INSTALLATION_CHECK_PATH, self.notice_installation_check)
        app.router.add_get(r"/chat/{asset:notice-call\.(?:js|css)}", self.web_notice_asset)
        app.router.add_get("/chat/admin/api/app-versions", self.admin.app_versions)
        if self.internal_shop is not None:
            from .internal_shop import LOOKUP_PATH
            app.router.add_post(LOOKUP_PATH, self.internal_shop.read)
        if self.sessions is not None:
            app.router.add_get("/chat/join/{token}", self.account_page)
            app.router.add_get("/chat/login", self.account_page)
            app.router.add_get("/chat/{name:unified\\.(?:css|js)|(?:account|admin|admin-items|profile|voice|friends|character|decor)\\.js}", self.page)
            app.router.add_get("/chat/api/invites/{token}", self.check_invite)
            app.router.add_post("/chat/api/join", self.join_with_invite)
            app.router.add_post("/chat/api/login/code", self.login_with_device_code)
            app.router.add_post("/chat/api/device-codes", self.create_device_code)
            app.router.add_post("/chat/api/logout", self.logout)
            if self.web_push_subscriptions is not None:
                app.router.add_get("/chat/{asset:web-notifications\\.js|web-notification-worker\\.js}",
                                   self.web_notice_asset)
                subscription = WEB_NOTICE_PATH + "/subscription"
                app.router.add_get(subscription, self.web_notice_status, allow_head=False)
                app.router.add_post(subscription + "/intent", self.web_notice_choice)
                app.router.add_put(subscription, self.web_notice_register)
                app.router.add_delete(subscription, self.web_notice_revoke)
                if self.web_push_references is not None:
                    app.router.add_post(WEB_NOTICE_PATH + "/target/resolve", self.web_notice_resolve)
                if self.web_push_call is not None:
                    app.router.add_post(WEB_NOTICE_PATH + "/call/accept", self.web_notice_accept)
                if self.web_push_delivery is not None:
                    app.router.add_post(WEB_NOTICE_PATH + "/reply-view", self.web_notice_reply_view)
            self.admin.register(app.router)
            self.profile.register(app.router)
            app.router.add_get("/chat/api/usage", self.profile.usage)
            self.friends.register(app.router)
            self.characters.register(app.router)
            from .pet_intro import PetIntro
            from .app_scenes import AppScenes
            PetIntro(self).register(app.router)
            AppScenes(self).register(app.router)
            self.decor.register(app.router)
        app.router.add_get("/chat", self.home)
        app.router.add_get("/chat/", self.page)
        app.router.add_get("/chat/{name:chat\\.(?:js|css)|update-banner\\.js}", self.page)
        app.router.add_get("/chat/{asset:manifest\\.webmanifest|icon-(?:180|192|512)\\.png}", self.web_asset)
        app.router.add_get("/chat/api/me", self.me)
        app.router.add_get("/chat/api/messages", self.messages)
        app.router.add_post("/chat/api/messages", self.send)
        app.router.add_get("/chat/api/messages/wait", self.wait)
        app.router.add_put("/chat/api/devices/{installId}", self.device)
        app.router.add_get("/chat/topics/{set}/{file}", self.picture)
        app.router.add_get(RELEASE_CHECK_PATH, self.app_release, allow_head=False)
        app.router.add_get("/chat/app/{file:.*}", self.app_apk, allow_head=False)
        self.persona.register(app)
        return app

    async def serve(self, host: str = "127.0.0.1") -> web.AppRunner:
        """127.0.0.1 only, no access log (SPEC-110)."""
        self.runner = web.AppRunner(self.web_app(), access_log=None, handle_signals=False)
        await self.runner.setup()
        await web.TCPSite(self.runner, host, self.port).start()
        log.info("app_chat_on port=%d", self.port)
        switch_on = os.getenv("MARONG_APP_UPDATE_PUSH", "").strip() != "0"
        fcm_on = self.push is not None and self.push.enabled
        log.info("app_update push switch=%s fcm=%s", "on" if switch_on else "off", "on" if fcm_on else "off")
        if switch_on and fcm_on:
            from .app_update_push import AppUpdatePush
            self._spawn(AppUpdatePush(self.store, self.releases, self.push.fcm, clock=self.clock).run())
        if self.web_push_subscriptions is not None:
            self._spawn(self._sweep_expired_subscriptions())
        return self.runner

    async def _sweep_expired_subscriptions(self):
        while True:
            try:
                await self.web_push_subscriptions.sweep_expired()
            except (psycopg.Error, TimeoutError) as error:
                log.warning("web_push_expiry_error %s", type(error).__name__)
            await asyncio.sleep(60)

    async def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.runner:
            await self.runner.cleanup()
