"""In-app chat for the Marong app and browsers (docs/app-chat.md SPEC-110~124, SPEC-148~149,
api/app-chat.openapi.yaml API-101~106).

A small aiohttp server inside the Discord DM bot, on 127.0.0.1 only. The tunnel sends `/chat/` of the call address
here; Cloudflare Access stands in front and every API request's Access token is checked again (access.py). A friend
writes into their own Discord DM room, so Marong answers with the same memory, lock and tools in both places.
Logs carry result names and counts only: no text, FID, install id, email or token (SPEC-126).
"""
import asyncio
from collections import defaultdict, deque
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
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
FID = re.compile(r"[A-Za-z0-9_-]{16,200}\Z")
VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z")
NUMBER = re.compile(r"[0-9]{1,18}\Z")
PROBLEMS = {
    "invalid_request": (400, "요청 모양이 틀림(빠진 칸, 길이·형식·범위 밖)"),
    "not_found": (404, "없는 그림이거나 로그인한 친구의 그림이 아님"),
    "unauthenticated": (401, "Access 로그인 증명이 없거나 맞지 않음"),
    "not_allowed": (403, "허용 목록에 없는 계정이거나 통화하는 친구가 꺼짐"),
    "cross_site": (403, "다른 사이트에서 온 쓰기 요청"),
    "no_dm": (403, "이 친구의 디스코드 DM 연결이 없거나 아직 DM을 한 번도 보내지 않음"),
    "too_many_messages": (429, "1분에 20번 넘게 보냄"),
    "no_picture": (404, "그 이름의 그림이 없음"),
    "not_ready": (409, "준비된 일기가 아님"),
    "stale_revision": (409, "보낸 판 번호가 지금 판과 다름"),
    "busy": (409, "이 일기를 고치거나 다시 그리는 중"),
    "fix_limit": (409, "고치기 다섯 번을 다 씀"),
    "redraw_limit": (409, "다시 그리기 두 번을 다 씀"),
    "drawing_budget": (429, "이번 달 그림 월 예산을 다 씀"),
    "fix_failed": (503, "고치기 모델이 실패함"),
    "stale_test": (409, "화면이 연 시험과 지금 시험 묶음이 다름"),
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
                               "img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
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
                 timezone: str = "Asia/Seoul", clock=time.monotonic, diary_models=None):
        self.store = store
        self.agent = agent      # DiscordAgent: the same one that answers the Discord DM
        self.client = client    # DiscordDM: its room locks keep one answer at a time per room
        self.access = access    # access.AccessVerifier
        self.push = push        # app_push.AppPush
        self.origin = origin
        self.port = port
        self.tz = ZoneInfo(timezone)
        self.clock = clock
        self.tick = asyncio.Event()          # set and replaced whenever a message is saved in this process
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
        except web.HTTPException as e:
            res = e
        except psycopg.OperationalError as e:  # includes the pool timeout
            log.warning("app_chat_db_unavailable %s", type(e).__name__)
            res = self._problem(Problem("db_unavailable"), trace)
        except Exception as e:
            log.error("app_chat_error %s trace=%s", type(e).__name__, trace)
            res = self._problem(Problem("internal"), trace)
        res.headers.update(HEADERS)
        if req.get("cache") and res.status == 200:  # a picture of a picture set never changes (API-140)
            res.headers["Cache-Control"] = req["cache"]
        return res

    async def _who(self, req, write: bool = False) -> dict:
        """The signed-in call friend and their DM room (SPEC-111). Writes must come from the call address."""
        if write and req.headers.get("Origin") != self.origin:
            raise Problem("cross_site")
        status, email_hash = await self.access.check(req.headers.get("Cf-Access-Jwt-Assertion", ""))
        if status == "unavailable":
            raise Problem("db_unavailable")
        if status != "ok":
            raise Problem(status)
        who = await self.store.app_login(email_hash)
        if not who or not who["enabled"]:
            raise Problem("not_allowed")
        if not who["room_key"] or not who["channel_id"]:
            raise Problem("no_dm")
        return who

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
        return self._json(200, {"messages": await self.persona.messages(who, rows[:limit][::-1]),
                                "hasMore": len(rows) > limit, "readUpTo": marks["readUpTo"],
                                "answeredUpTo": marks["answeredUpTo"]})

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
        await self.store.incoming(who["discord_user_id"], who["channel_id"], key, preference)
        saved = await self.store.add_message(room, "user", text, user_key=who["user_key"], kakao_id=key,
                                             meta={"transport": "app"})
        row = await self.store.app_message(room, key)
        if saved is None:  # the same message arrived twice at once: the other request answers it
            return self._json(200, {"message": self.message(row)})
        self._spawn(self._answer(who, saved, text, key, preference))
        self.pulse()
        log.info("app_chat_sent")
        return self._json(202, {"message": self.message(row)})

    async def _delivered(self, text: str) -> bool:
        return True  # the reply reaches the screen through the wait (API-104), or a notification

    async def _answer(self, who: dict, saved_id: int, text: str, key: str, preference) -> None:
        room = who["room_key"]
        reply = None
        try:
            link = await self.store.link(who["discord_user_id"])
            msg = DiscordIncoming(room, who["user_key"], text, kakao_id=key, proactive_preference=preference,
                                  google_command=google_command(text), topic_command=topic_phrase(text),
                                  friend_id=who["friend_id"], dm_link=link, via="app", presaved_id=saved_id)
            async with self.client.room_lock(room):
                self._took_up(room, saved_id)
                self.pulse()  # '읽음' and '대답 중' once this answer holds the room (SPEC-148, SPEC-149)
                reply = await self.agent.handle(msg, self._delivered)
        except Exception as e:
            log.error("app_chat_reply_failed %s", type(e).__name__)
        finally:
            self.pulse()
        if reply is None:
            return
        log.info("app_chat_replied")
        # The friend closed the chat before the answer came: tell their phone (SPEC-120). Never Discord.
        if not self.waiters.get(who["friend_id"]) and self.push.enabled:
            try:
                await self.push.notify(who["friend_id"], "reply", reply, ttl_s=REPLY_TTL_S)
            except Exception as e:
                log.warning("app_reply_notify_failed %s", type(e).__name__)

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
        return self._json(200, {"messages": await self.persona.messages(who, rows), **marks})

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
        app.router.add_get("/chat", self.home)
        app.router.add_get("/chat/", self.page)
        app.router.add_get("/chat/{name:chat\\.(?:js|css)}", self.page)
        app.router.add_get("/chat/api/me", self.me)
        app.router.add_get("/chat/api/messages", self.messages)
        app.router.add_post("/chat/api/messages", self.send)
        app.router.add_get("/chat/api/messages/wait", self.wait)
        app.router.add_put("/chat/api/devices/{installId}", self.device)
        app.router.add_get("/chat/topics/{set}/{file}", self.picture)
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
