"""In-app chat for the Marong app and browsers (docs/app-chat.md SPEC-110~124, SPEC-148~149,
api/app-chat.openapi.yaml API-101~106).

A small aiohttp server inside the Discord DM bot, on 127.0.0.1 only. The tunnel sends `/chat/` of the call address
here; Cloudflare Access stands in front and every API request's Access token is checked again (access.py). A friend
writes into their own Discord DM room, so Marong answers with the same memory, lock and tools in both places.
Logs carry result names and counts only: no text, FID, install id, email or token (SPEC-126).
"""
import asyncio
from collections import OrderedDict, defaultdict, deque
from contextlib import AsyncExitStack
import json
import logging
import math
from pathlib import Path
import re
import secrets
import time
from zoneinfo import ZoneInfo

from aiohttp import web
import psycopg

from tools.vertex_live.tool_trace import app_delivery, app_step, step as trace_step

from .app_release import AppReleases
from .app_session import COOKIE, SessionError, auth_mode, device_label, identify_request
from .character.records import CharacterError
from .app_store import APP_KEY
from .discord_dm import DEFAULT_ORIGIN, DiscordIncoming, proactive_preference
from .google_calendar import LINK_MARK, command as google_command
from .topics import KEY as TOPIC_KEY, NAME as PICTURE_NAME, SET_NAME, phrase as topic_phrase, picture_set

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
FILES = {"": ("index.html", "text/html"), "chat.js": ("chat.js", "text/javascript"),
         "chat.css": ("chat.css", "text/css")}
UNIFIED_FILES = {"account.html": "text/html", "admin.html": "text/html", "unified.css": "text/css",
                 "unified.js": "text/javascript", "account.js": "text/javascript", "admin.js": "text/javascript",
                 "profile.html": "text/html", "profile.js": "text/javascript",
                 "voice.html": "text/html", "voice.js": "text/javascript", "friends.html": "text/html",
                 "friends.js": "text/javascript",
                 "character.html": "text/html", "character.js": "text/javascript"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
FID = re.compile(r"[A-Za-z0-9_-]{16,200}\Z")
VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z")
RELEASE_CHECK_PATH = "/chat/api/app/release"
NUMBER = re.compile(r"[0-9]{1,18}\Z")
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
    "too_many_messages": (429, "1분에 20번 넘게 보냄"),
    "no_picture": (404, "그 이름의 그림이 없음"),
    "not_ready": (409, "아직 준비되지 않음"),
    "stale_revision": (409, "보낸 판 번호가 지금 판과 다름"),
    "busy": (409, "이 일기를 고치거나 다시 그리는 중"),
    "fix_limit": (409, "고치기 다섯 번을 다 씀"),
    "redraw_limit": (409, "다시 그리기 두 번을 다 씀"),
    "drawing_budget": (429, "이번 달 그림 월 예산을 다 씀"),
    "fix_failed": (503, "고치기 모델이 실패함"),
    "stale_test": (409, "화면이 연 시험과 지금 시험 묶음이 다름"),
    "no_release": (404, "지금 받을 수 있는 앱 파일이 아님"),
    "feature_off": (403, "이 기능이 꺼져 있음"),
    "needs_owner": (403, "선톡을 늘리는 요청은 동희님이 정함"),
    "not_found": (404, "이 계정으로 찾을 수 없음"),
    "rule_limit": (409, "그 종류의 친구 규칙이 이미 20개"),
    "card_closed": (409, "카드가 닫혔거나 다른 값으로 답함"),
    "too_many_requests": (429, "맞춤형 지침 요청이 너무 자주 도착함"),
    "ai_unavailable": (503, "맞춤형 지침을 읽지 못함"),
    "db_unavailable": (503, "DB에 닿지 않음"),
    "internal": (500, "예상하지 못한 서버 오류"),
}
HEADERS = {
    "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY", "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
                               "form-action 'none'",
}


class Problem(Exception):
    def __init__(self, code: str, errors: list | None = None, headers: dict | None = None, *, title=None):
        super().__init__(code)
        self.code, self.errors, self.headers = code, errors or [], headers or {}
        self.title = title


def bad(*errors) -> Problem:
    return Problem("invalid_request", [{"field": f, "reason": r} for f, r in errors][:10])


class AppChat:
    def __init__(self, store, agent, client, access, push, *, origin: str = DEFAULT_ORIGIN, port: int = DEFAULT_PORT,
                 timezone: str = "Asia/Seoul", clock=time.monotonic, releases: AppReleases | None = None,
                 sessions=None, authentication="access", admin_email_hash=None, diary_models=None):
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
        self.delivery = None
        self.internal_shop = None
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
        from .app_persona import AppPersona
        self.persona = AppPersona(self)
        from .app_admin import AppAdmin
        from .app_profile import AppProfile
        self.admin = AppAdmin(self, admin_email_hash)
        self.profile = AppProfile(self)
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
            res = self._problem(Problem(p.code, headers=headers), trace)
        except CharacterError as p:
            res = self._problem(Problem(p.code, p.errors), trace)
        except web.HTTPException as e:
            res = e
        except (psycopg.OperationalError, TimeoutError) as e:  # includes the pool timeout
            log.warning("app_chat_db_unavailable %s", type(e).__name__)
            res = self._problem(Problem("db_unavailable"), trace)
        except Exception as e:
            log.error("app_chat_error %s trace=%s", type(e).__name__, trace)
            res = self._problem(Problem("internal"), trace)
        if req.method == "GET" and req.path == RELEASE_CHECK_PATH:
            prefix, _, version = req.headers.get("User-Agent", "").partition("/")
            if prefix == "MarongApp" and VERSION.fullmatch(version):
                log.info("app_release check version=%s status=%d", version, res.status)
        if req.get("session_refresh") and res.status < 400:
            self._set_session_cookie(res, req["session_refresh"])
        res.headers.update(HEADERS)
        if req.get("cache") and res.status == 200:  # a picture of a picture set never changes (API-140)
            res.headers["Cache-Control"] = req["cache"]
        return res

    def _require_app_origin(self, req):
        if req.headers.get("Origin") != self.origin:
            raise Problem("cross_site")

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
        session = await self.sessions.join(body["token"], body.get("name"), device_label(req.headers.get("User-Agent", "")))
        return self._set_session_cookie(self._json(201, session.public()), session.token)

    async def login_with_device_code(self, req):
        self._require_app_origin(req)
        body = await self._session_body(req, "code")
        address = req.headers.get("CF-Connecting-IP") or req.remote or "unknown"
        session = await self.sessions.redeem_device_code(body["code"], address,
                                                         device_label(req.headers.get("User-Agent", "")))
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
        await self._who(req, require_dm=False)
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
    def _number(raw, field: str, *, minimum: int, maximum: int | None = None, required: bool = False) -> int | None:
        if raw is None or raw == "":
            if required:
                raise bad((field, "required"))
            return None
        if not NUMBER.fullmatch(raw):
            raise bad((field, "bad_format"))
        value = int(raw)
        if value < minimum or (maximum is not None and value > maximum):
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
        picture = self._picture(meta.get("topic")) if row["role"] == "assistant" else None
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
        return web.Response(body=data, content_type=kind, charset="utf-8")

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

    async def device(self, req):
        """API-105: this phone's notification state (SPEC-115, SPEC-139)."""
        who = await self._who(req, write=True)
        install_id = req.match_info["installId"]
        if not UUID.fullmatch(install_id):
            raise bad(("installId", "bad_format"))
        body = await self._body(req)
        errors = [("body", "bad_format")] if set(body) - {"fid", "notifications", "appVersion", "ring"} else []
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
        if errors:
            raise bad(*errors)
        created = await self.store.app_device_put(install_id, who["friend_id"], fid, notifications, version,
                                                  ring and ring["channel"], ring and ring["fullScreen"])
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
        AppDiary(self).register(app)
        AppListen(self).register(app)
        app.router.add_get("/chat/healthz", self.health)
        if self.internal_shop is not None:
            from .internal_shop import LOOKUP_PATH
            app.router.add_post(LOOKUP_PATH, self.internal_shop.read)
        if self.sessions is not None:
            app.router.add_get("/chat/join/{token}", self.account_page)
            app.router.add_get("/chat/login", self.account_page)
            app.router.add_get("/chat/{name:unified\\.(?:css|js)|(?:account|admin|profile|voice|friends|character)\\.js}", self.page)
            app.router.add_get("/chat/api/invites/{token}", self.check_invite)
            app.router.add_post("/chat/api/join", self.join_with_invite)
            app.router.add_post("/chat/api/login/code", self.login_with_device_code)
            app.router.add_post("/chat/api/device-codes", self.create_device_code)
            app.router.add_post("/chat/api/logout", self.logout)
            self.admin.register(app.router)
            self.profile.register(app.router)
            self.friends.register(app.router)
            self.characters.register(app.router)
        app.router.add_get("/chat", self.home)
        app.router.add_get("/chat/", self.page)
        app.router.add_get("/chat/{name:chat\\.(?:js|css)}", self.page)
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
        return self.runner

    async def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.runner:
            await self.runner.cleanup()
