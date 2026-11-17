"""PET HTTP response rules, member sessions, and private assets (SPEC-364–366)."""

from datetime import datetime, timezone
from hashlib import sha256
from secrets import token_hex
from uuid import UUID
import re

from aiohttp import web
from psycopg_pool import AsyncConnectionPool

from .log import logger, member_ref
from .settings import Settings

POOL = web.AppKey("pet_database", AsyncConnectionPool)
CONFIG = web.AppKey("pet_settings", Settings)
COOKIE = "pet_session"
_TOKEN = re.compile(r"[a-zA-Z0-9_-]{43}\Z")
_WRITES = {"POST", "PUT", "PATCH", "DELETE"}
_ORIGIN_EXEMPT = {"payment_webhook", "internal_call_verify", "internal_call_minute", "internal_call_end"}
ERRORS = {
    "invalid_input": (400, "형식·길이·범위·목록 밖 값", "입력을 확인해 주세요."),
    "unauthenticated": (401, "세션이 없거나 끝남", "다시 로그인해 주세요."),
    "cross_site": (403, "쓰기 요청의 Origin이 서비스 주소가 아님", "요청을 처리할 수 없어요."),
    "not_found": (404, "없거나 남의 것이거나 지운 것(같은 본문)", "찾을 수 없어요."),
    "budget_paused": (409, "이번 달 운영 예산을 다 씀", "오늘은 새 그림과 통화가 쉬어요. 글로는 계속 이야기할 수 있어요."),
    "server_error": (500, "예상하지 못한 오류", "잠시 뒤 다시 해 주세요."),
}


class Problem(Exception):
    def __init__(self, code, *, extra=None):
        super().__init__(code)
        self.code = code
        self.extra = extra or {}


def problem_response(req, error):
    status, title, detail = ERRORS[error.code]
    type_url = req.app[CONFIG].origin + "/problems/" + error.code.replace("_", "-")
    body = {"type": type_url, "status": status, "title": title, "code": error.code,
            "detail": detail, "traceId": req["trace"], **error.extra}
    return web.json_response(body, status=status, content_type="application/problem+json")


def check_origin(req):
    if req.method not in _WRITES or req.match_info.route.name in _ORIGIN_EXEMPT:
        return
    origin = req.headers.get("Origin")
    if origin is None:
        allowed = req.headers.get("Sec-Fetch-Site") == "same-origin"
    else:
        allowed = origin == req.app[CONFIG].origin
    if not allowed:
        raise Problem("cross_site")


def set_session_cookie(response, raw, lifespan):
    response.set_cookie(COOKIE, raw, max_age=lifespan, secure=True, httponly=True, samesite="Lax", path="/")


@web.middleware
async def guard(req, handler):
    req["trace"] = token_hex(16)
    try:
        check_origin(req)
        response = await handler(req)
    except Problem as error:
        response = problem_response(req, error)
    except web.HTTPNotFound:
        response = problem_response(req, Problem("not_found"))
    except web.HTTPException as error:
        response = error
    except Exception:
        member = req.get("member")
        logger.error("pet_request_failed trace=%s member=%s", req["trace"],
                     member_ref(member["member_no"]) if member else "-")
        response = problem_response(req, Problem("server_error"))
    response.headers["Cache-Control"] = req.get("cache", "no-store") if response.status == 200 else "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if req.get("member") and COOKIE not in response.cookies and response.status < 500:
        remaining = (req["member"]["expires_at"] - datetime.now(timezone.utc)).total_seconds()
        if remaining > 0:
            set_session_cookie(response, req.cookies[COOKIE], int(remaining))
    return response


def uuid_param(raw):
    try:
        value = UUID(raw)
    except (ValueError, TypeError, AttributeError):
        raise Problem("invalid_input") from None
    if str(value) != raw.lower():
        raise Problem("invalid_input")
    return value


def cookie_hash(raw):
    return sha256(raw.encode("ascii")).digest() if _TOKEN.fullmatch(raw or "") else None


async def require_member(req):
    """Resolve the active session only. Slide it without exceeding the original 90-day limit."""
    digest = cookie_hash(req.cookies.get(COOKIE))
    if not digest:
        raise Problem("unauthenticated")
    async with req.app[POOL].connection() as conn:
        cursor = await conn.execute(
            """UPDATE pet.sessions s SET expires_at=LEAST(now()+interval '30 days',s.absolute_expires_at)
            FROM pet.members m WHERE s.token_hash=%s AND s.kind='member' AND s.member_id=m.id
              AND m.status='active' AND s.expires_at>now() AND s.absolute_expires_at>now()
            RETURNING m.id,m.member_no,m.provider,m.status,s.expires_at""",
            (digest,),
        )
        member = await cursor.fetchone()
    if not member:
        raise Problem("unauthenticated")
    req["member"] = member
    req["session_hash"] = digest
    return member


async def read_media(req):
    member = await require_member(req)
    media_id = uuid_param(req.match_info["id"])
    async with req.app[POOL].connection() as conn:
        cursor = await conn.execute(
            """SELECT storage_key,content_type FROM pet.media WHERE id=%s AND member_id=%s
            AND (delete_after IS NULL OR delete_after>now())""",
            (media_id, member["id"]),
        )
        row = await cursor.fetchone()
    if not row:
        raise Problem("not_found")
    root = req.app[CONFIG].media_dir.resolve()
    source = (root / row["storage_key"]).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise Problem("not_found")
    req["cache"] = "private, max-age=31536000, immutable"
    return web.FileResponse(source, headers={"Content-Type": row["content_type"]})
