"""Signup, personal profile and consent records (SPEC-311, SPEC-312)."""

from datetime import date, datetime
from hashlib import sha256
import re
from secrets import choice, token_urlsafe
from zoneinfo import ZoneInfo

from aiohttp import web

from .auth import MEMBER, MEMBER_MAX
from .http import CONFIG, COOKIE, POOL, Problem, body_json, cookie_hash, problem_response, require_member, set_session_cookie
from .inventory import sync_defaults

KST = ZoneInfo("Asia/Seoul")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z", re.ASCII)
CODE = re.compile(r"[A-Z0-9]{8}\Z")
MEMBER_SYMBOLS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SIGNUP_FIELDS = {
    "agreeTerms": "terms", "agreePrivacy": "privacy", "aiNoticeConfirmed": "ai_notice",
    "overseasTransfer": "overseas_transfer",
}


def korea_today():
    return datetime.now(KST).date()


def min_age(birth, today):
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def parse_signup(data):
    if set(data) - {*SIGNUP_FIELDS, "birthDate", "inviteCode"}:
        raise Problem("invalid_input")
    raw = data.get("birthDate")
    try:
        if not isinstance(raw, str) or not DATE.fullmatch(raw):
            raise ValueError
        birth = date.fromisoformat(raw)
    except ValueError:
        raise Problem("invalid_input") from None
    today = korea_today()
    if birth > today or any(type(data.get(key)) is not bool for key in SIGNUP_FIELDS):
        raise Problem("invalid_input")
    invite = data.get("inviteCode")
    if "inviteCode" in data and (not isinstance(invite, str) or not CODE.fullmatch(invite)):
        raise Problem("invalid_input")
    return min_age(birth, today), invite


async def _invite(conn, code):
    if not code:
        raise Problem("invite_required")
    digest = sha256(code.encode("ascii")).digest()
    cur = await conn.execute(
        """UPDATE pet.invites SET uses_left=uses_left-1 WHERE code_hash=%s
        AND uses_left>0 AND (expires_at IS NULL OR expires_at>now()) RETURNING id""", (digest,),
    )
    row = await cur.fetchone()
    if not row:
        raise Problem("invite_required")
    return row["id"]


async def _add_member(conn, pending, invite_id):
    for _ in range(8):
        number = "".join(choice(MEMBER_SYMBOLS) for _ in range(8))
        cur = await conn.execute(
            """INSERT INTO pet.members(member_no,provider,sub_hash,adult_self_declared_at,invite_id,last_login_at)
            VALUES (%s,%s,%s,now(),%s,now()) ON CONFLICT (member_no) DO NOTHING RETURNING id""",
            (number, pending["provider"], pending["sub_hash"], invite_id),
        )
        inserted = await cur.fetchone()
        if inserted:
            return inserted["id"]
    raise Problem("server_error")


async def _pending(conn, digest):
    cur = await conn.execute(
        """SELECT kind,provider,sub_hash FROM pet.sessions WHERE token_hash=%s
        AND expires_at>now() AND absolute_expires_at>now() FOR UPDATE""", (digest,),
    )
    session = await cur.fetchone()
    if not session:
        raise Problem("unauthenticated")
    if session["kind"] != "pending":
        raise Problem("already_member")
    return session


async def signup(req):
    digest = cookie_hash(req.cookies.get(COOKIE))
    if not digest:
        raise Problem("unauthenticated")
    data = await body_json(req)
    settings = req.app[CONFIG]
    async with req.app[POOL].connection() as conn, conn.transaction():
        pending = await _pending(conn, digest)
        age, invite = parse_signup(data)
        if age < 19:
            await conn.execute("DELETE FROM pet.sessions WHERE token_hash=%s", (digest,))
            response = problem_response(req, Problem("underage"))
            set_session_cookie(response, "", 0)
            return response
        if any(not data[key] for key in ("agreeTerms", "agreePrivacy", "aiNoticeConfirmed")):
            raise Problem("consents_missing")
        lock = f"pet:signup:{pending['provider']}:{pending['sub_hash'].hex()}"
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (lock,))
        cur = await conn.execute("SELECT 1 FROM pet.members WHERE provider=%s AND sub_hash=%s",
                                 (pending["provider"], pending["sub_hash"]))
        if await cur.fetchone():
            raise Problem("already_member")
        invite_id = await _invite(conn, invite) if settings.signup == "invite" else None
        member_id = await _add_member(conn, pending, invite_id)
        for field, kind in SIGNUP_FIELDS.items():
            await conn.execute(
                """INSERT INTO pet.consents(member_id,kind,doc_version,value)
                VALUES (%s,%s,%s,%s)""", (member_id, kind, settings.consent_version, data[field]),
            )
        await sync_defaults(conn, member_id)
        raw = token_urlsafe(32)
        await conn.execute("DELETE FROM pet.sessions WHERE token_hash=%s", (digest,))
        await conn.execute(
            """INSERT INTO pet.sessions(token_hash,kind,member_id,provider,expires_at,absolute_expires_at)
            VALUES (%s,'member',%s,%s,now()+%s,now()+%s)""",
            (cookie_hash(raw), member_id, pending["provider"], MEMBER, MEMBER_MAX),
        )
        profile = await _profile(conn, member_id)
    response = web.json_response(profile, status=201)
    set_session_cookie(response, raw, int(MEMBER.total_seconds()))
    return response


async def _profile(conn, member_id):
    cur = await conn.execute(
        """SELECT m.member_no,m.status,m.identity_verified_at IS NOT NULL AS verified,m.free_tickets,
        COALESCE((SELECT value FROM pet.consents WHERE member_id=m.id AND kind='overseas_transfer'
                  ORDER BY created_at DESC,id DESC LIMIT 1),false) AS consent,
        COALESCE((SELECT value='true'::jsonb FROM pet.settings WHERE key='payments_enabled'),false) AS payments,
        (SELECT value FROM pet.settings WHERE key='business_info') AS business
        FROM pet.members m WHERE m.id=%s""", (member_id,),
    )
    row = await cur.fetchone()
    if not row or row["status"] == "deleting":
        raise Problem("unauthenticated")
    return {"memberNo": row["member_no"], "status": row["status"], "identityVerified": row["verified"],
            "freeTickets": row["free_tickets"], "paymentsEnabled": row["payments"], "overseasTransfer": row["consent"],
            "business": row["business"] if row["payments"] else None}


async def me(req):
    member = await require_member(req)
    async with req.app[POOL].connection() as conn:
        return web.json_response(await _profile(conn, member["id"]))


async def _consents(conn, member):
    cur = await conn.execute(
        """SELECT DISTINCT ON(kind) kind,value,doc_version,created_at FROM pet.consents WHERE member_id=%s
        ORDER BY kind,created_at DESC,id DESC""", (member,),
    )
    return [{"kind": row["kind"], "value": row["value"], "docVersion": row["doc_version"],
             "at": row["created_at"].isoformat()} for row in await cur.fetchall()]


async def get_consents(req):
    member = await require_member(req)
    async with req.app[POOL].connection() as conn:
        return web.json_response({"items": await _consents(conn, member["id"])})


async def put_consent(req):
    member = await require_member(req)
    kind = req.match_info["kind"]
    data = await body_json(req)
    if kind not in SIGNUP_FIELDS.values() or set(data) != {"value"} or type(data["value"]) is not bool:
        raise Problem("invalid_input")
    if kind != "overseas_transfer" and not data["value"]:
        raise Problem("use_delete_account")
    async with req.app[POOL].connection() as conn, conn.transaction():
        owner = await conn.execute("SELECT id FROM pet.members WHERE id=%s AND status='active' FOR UPDATE", (member["id"],))
        if not await owner.fetchone():
            raise Problem("unauthenticated")
        if kind == "overseas_transfer":
            cur = await conn.execute(
                """SELECT value FROM pet.consents WHERE member_id=%s AND kind=%s
                ORDER BY created_at DESC,id DESC LIMIT 1""", (member["id"], kind),
            )
            previous = await cur.fetchone()
            if previous is None or previous["value"] != data["value"]:
                await conn.execute(
                    """INSERT INTO pet.consents(member_id,kind,doc_version,value)
                    VALUES (%s,%s,%s,%s)""", (member["id"], kind, req.app[CONFIG].consent_version, data["value"]),
                )
        return web.json_response({"items": await _consents(conn, member["id"])})


async def require_overseas(conn, member_id):
    cur = await conn.execute(
        """SELECT value FROM pet.consents WHERE member_id=%s AND kind='overseas_transfer'
        ORDER BY created_at DESC,id DESC LIMIT 1""", (member_id,),
    )
    row = await cur.fetchone()
    if not row or not row["value"]:
        raise Problem("consent_required")


def register(app):
    app.router.add_post("/api/signup", signup)
    app.router.add_get("/api/me", me, allow_head=False)
    app.router.add_get("/api/me/consents", get_consents, allow_head=False)
    app.router.add_put("/api/me/consents/{kind}", put_consent)
