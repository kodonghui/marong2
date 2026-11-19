"""Invite redemption and device sessions for the unified app (SPEC-370–374)."""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import math
import re
import secrets

from .room_scope import writing_room, writing_room_key, writing_user_key


COOKIE = "marong_session"
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
CODE = re.compile(r"[0-9]{6}")
FRIEND_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PROFILE_LOCK = "marong.profile:"


class SessionError(Exception):
    def __init__(self, code, *, retry_after=None):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


def now_utc():
    return datetime.now(timezone.utc)


def token_hash(value):
    return hashlib.sha256(value.encode("ascii")).digest()


def device_label(agent):
    if "MarongApp/" in agent:
        return "Android 앱"
    if "iPhone" in agent:
        return "iPhone Safari"
    return "웹"


@dataclass(frozen=True)
class SignedIn:
    token: str = field(repr=False)
    friend_name: str
    bot_name: str

    def public(self):
        return {"friendName": self.friend_name, "botName": self.bot_name}


@dataclass
class CodeAttempts:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    failed: deque = field(default_factory=deque)
    blocked_until: float = 0.0


async def one(conn, sql, params=()):
    return await (await conn.execute(sql, params)).fetchone()


MEMBER_COLUMNS = f"""
    f.id AS friend_id, f.name, p.friend_id AS profile_id, COALESCE(p.bot_name,'마롱이') AS bot_name,
    p.character_id, p.voice,
    c.id AS caller_id, c.enabled AS call_enabled, c.context_revision,
    {writing_room_key('f.id')} AS room_key,
    {writing_user_key('f.id')} AS user_key
"""
MEMBER_JOINS = """
    LEFT JOIN marong.friend_profiles p ON p.friend_id=f.id
    LEFT JOIN call.callers c ON c.friend_id=f.id
"""


def auth_mode(value):
    if value not in {"access", "both", "session"}:
        raise ValueError("MARONG_AUTH must be access, both, or session")
    return value


async def identify_request(mode, token, session_lookup, access_lookup):
    if mode != "access" and token and (who := await session_lookup(token)) is not None:
        return who
    if mode == "session":
        raise SessionError("login_required")
    return await access_lookup()


async def find_session(pool, token, clock=now_utc, age=timedelta(days=90)):
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        return None
    async with asyncio.timeout(2), pool.connection() as conn, conn.transaction():
        now = clock()
        row = await one(conn, """
            SELECT s.id AS session_id,s.last_seen_at, """ + MEMBER_COLUMNS + """
            FROM marong.app_sessions s JOIN marong.friends f ON f.id=s.friend_id
            """ + MEMBER_JOINS + """
            WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>%s
        """, (token_hash(token), now))
        if row is None:
            return None
        row["renewed"] = False
        cutoff = now - timedelta(days=1)
        if row["last_seen_at"] < cutoff:
            refreshed = await one(conn, """
                UPDATE marong.app_sessions SET last_seen_at=%s,expires_at=%s
                WHERE id=%s AND revoked_at IS NULL AND expires_at>%s AND last_seen_at<%s
                RETURNING id
            """, (now, now + age, row["session_id"], now, cutoff))
            row["renewed"] = refreshed is not None
        return row


class AppSessions:
    def __init__(self, pool, secret: bytes, *, contact_schedule, now=now_utc,
                 invite_days: int = 7, session_days: int = 90):
        if len(secret) < 32:
            raise ValueError("MARONG_SESSION_SECRET must contain at least 32 bytes")
        self.pool = pool
        self.secret = secret
        self.contact_schedule = contact_schedule
        self.now = now
        self.invite_age = timedelta(days=invite_days)
        self.session_age = timedelta(days=session_days)
        self.attempts: dict[str, CodeAttempts] = {}
        self.next_prune = 0.0

    def _check_invite(self, row, now):
        if row is None:
            raise SessionError("invite_not_found")
        if row["used_at"] is not None:
            raise SessionError("invite_used")
        if row["revoked_at"] is not None or row["expires_at"] <= now:
            raise SessionError("invite_expired")
        return row

    async def create_invite(self, kind, friend_id=None, note=""):
        if (kind not in ("join", "link", "relogin") or not isinstance(note, str) or len(note) > 40
                or (kind == "join" and friend_id is not None)
                or (kind != "join" and (type(friend_id) is not int or not 0 < friend_id <= 2**63 - 1))):
            raise SessionError("invalid_input")
        now = self.now()
        expiry = now + self.invite_age
        async with self.pool.connection() as conn, conn.transaction():
            if friend_id is not None:
                friend = await one(conn, """
                    SELECT f.id, p.friend_id AS profile_id FROM marong.friends f
                    LEFT JOIN marong.friend_profiles p ON p.friend_id=f.id WHERE f.id=%s
                """, (friend_id,))
                if friend is None:
                    raise SessionError("not_found")
                if kind == "relogin" and friend["profile_id"] is None:
                    raise SessionError("invalid_input")
            for _ in range(5):
                token = secrets.token_urlsafe(32)
                row = await one(conn, """
                    INSERT INTO marong.invites(token_hash, kind, friend_id, note, created_at, expires_at)
                    VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (token_hash) DO NOTHING RETURNING id
                """, (token_hash(token), kind, friend_id, note, now, expiry))
                if row is not None:
                    return token, expiry
        raise SessionError("internal")

    async def check_invite(self, token):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise SessionError("invite_not_found")
        async with self.pool.connection() as conn:
            row = await one(conn, """
                SELECT kind, used_at, revoked_at, expires_at FROM marong.invites WHERE token_hash=%s
            """, (token_hash(token),))
        return self._check_invite(row, self.now())["kind"]

    async def join(self, token, name, label):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise SessionError("invite_not_found")
        async with self.pool.connection() as conn, conn.transaction():
            row = await one(conn, """
                SELECT id, kind, friend_id, used_at, revoked_at, expires_at
                FROM marong.invites WHERE token_hash=%s FOR UPDATE
            """, (token_hash(token),))
            now = self.now()
            invite = self._check_invite(row, now)
            friend_id = invite["friend_id"]
            if invite["kind"] == "join":
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 12:
                    raise SessionError("invalid_input")
                friend = await one(conn, "INSERT INTO marong.friends(name) VALUES (%s) RETURNING id", (name.strip(),))
                friend_id = friend["id"]
            if invite["kind"] != "relogin":
                await self.provision(conn, friend_id, now)
            await conn.execute("UPDATE marong.invites SET used_at=%s, used_by=%s WHERE id=%s",
                               (now, friend_id, invite["id"]))
            return await self._sign_in(conn, friend_id, "invite", label, now)

    async def provision(self, conn, friend_id, now):
        """Create the missing linked-account rows inside the caller's transaction."""
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           (f"{PROFILE_LOCK}{friend_id}",))
        friend = await one(conn, "SELECT name FROM marong.friends WHERE id=%s", (friend_id,))
        exists = await one(conn, "SELECT friend_id FROM marong.friend_profiles WHERE friend_id=%s", (friend_id,))
        if exists is None:
            for _ in range(5):
                code = "".join(secrets.choice(FRIEND_ALPHABET) for _ in range(6))
                inserted = await one(conn, """
                    INSERT INTO marong.friend_profiles(friend_id, friend_code) VALUES (%s,%s)
                    ON CONFLICT (friend_code) DO NOTHING RETURNING friend_id
                """, (friend_id, code))
                if inserted is not None:
                    break
            else:
                raise SessionError("internal")
        per_day, start, end = self.contact_schedule
        await conn.execute("""
            INSERT INTO marong.contact_settings(friend_id,opted_in_at,per_day,start_hour,end_hour)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT (friend_id) DO NOTHING
        """, (friend_id, now, per_day, start, end))
        room = await one(conn, f"""
            SELECT r.room_key FROM marong.rooms r WHERE r.owner_friend_id=%s AND {writing_room('r')} LIMIT 1
        """, (friend_id,))
        if room is None:
            room_key = f"app:{friend_id}"
            await conn.execute("""
                INSERT INTO marong.rooms(room_key,is_channel,owner_friend_id,proactive,group_proactive)
                VALUES (%s,true,%s,false,false)
            """, (room_key, friend_id))
            await conn.execute("""
                INSERT INTO marong.people(user_key,name,friend_id) VALUES (%s,%s,%s)
            """, (f"app-user:{friend_id}", friend["name"], friend_id))
        await conn.execute("INSERT INTO call.callers(friend_id) VALUES (%s) ON CONFLICT (friend_id) DO NOTHING",
                           (friend_id,))
        if room is None:
            await conn.execute("""
                INSERT INTO call.kakao_guards(room_key,friend_id,message_floor,note_floor,summary_floor)
                VALUES (%s,%s,0,0,0)
            """, (room_key, friend_id))

    async def _sign_in(self, conn, friend_id, method, label, now):
        names = await one(conn, """
            SELECT f.name, COALESCE(p.bot_name,'마롱이') AS bot_name FROM marong.friends f
            LEFT JOIN marong.friend_profiles p ON p.friend_id=f.id WHERE f.id=%s
        """, (friend_id,))
        token = secrets.token_urlsafe(32)
        await conn.execute("""
            INSERT INTO marong.app_sessions(friend_id,token_hash,method,label,created_at,last_seen_at,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (friend_id, token_hash(token), method, label, now, now, now + self.session_age))
        return SignedIn(token, names["name"], names["bot_name"])

    async def find_session(self, token):
        return await find_session(self.pool, token, self.now, self.session_age)

    async def find_access_member(self, email_hash):
        async with asyncio.timeout(2), self.pool.connection() as conn:
            return await one(conn, """
                SELECT """ + MEMBER_COLUMNS + """
                FROM call.caller_logins l JOIN call.callers source ON source.id=l.caller_id
                JOIN marong.friends f ON f.id=source.friend_id
                """ + MEMBER_JOINS + """ WHERE l.email_sha256=%s
            """, (email_hash,))

    async def ensure_profile(self, friend_id):
        async with self.pool.connection() as conn, conn.transaction():
            await self.provision(conn, friend_id, self.now())

    def _device_hash(self, code):
        return hmac.digest(self.secret, code.encode("ascii"), "sha256")

    async def create_device_code(self, friend_id):
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                               (f"marong.device-code:{friend_id}",))
            now = self.now()
            limit = timedelta(hours=1)
            recent = await one(conn, """
                SELECT count(*) AS count,min(created_at) AS first
                FROM marong.device_codes WHERE friend_id=%s AND created_at>%s
            """, (friend_id, now - limit))
            if recent["count"] >= 5:
                after = math.ceil((recent["first"] + limit - now).total_seconds())
                raise SessionError("too_many_codes", retry_after=after)
            await conn.execute("UPDATE marong.device_codes SET used_at=%s WHERE friend_id=%s AND used_at IS NULL",
                               (now, friend_id))
            expiry = now + timedelta(minutes=10)
            for _ in range(10):
                code = f"{secrets.randbelow(1_000_000):06d}"
                row = await one(conn, """
                    INSERT INTO marong.device_codes(friend_id,code_hash,created_at,expires_at)
                    VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id
                """, (friend_id, self._device_hash(code), now, expiry))
                if row is not None:
                    return code, expiry
            raise SessionError("internal")

    async def redeem_device_code(self, code, address, label):
        if not isinstance(code, str) or not CODE.fullmatch(code):
            raise SessionError("invalid_input")
        now = self.now().timestamp()
        if now >= self.next_prune:
            self.attempts = {
                ip: prior for ip, prior in self.attempts.items()
                if (prior.lock.locked() or prior.blocked_until > now
                    or (prior.failed and prior.failed[-1] > now - 600))
            }
            self.next_prune = now + 600
        state = self.attempts.setdefault(address, CodeAttempts())
        async with state.lock:
            now = self.now()
            instant = now.timestamp()
            if state.blocked_until > instant:
                raise SessionError("too_many_tries", retry_after=math.ceil(state.blocked_until - instant))
            async with self.pool.connection() as conn, conn.transaction():
                row = await one(conn, """
                    UPDATE marong.device_codes SET used_at=%s
                    WHERE code_hash=%s AND used_at IS NULL AND expires_at>%s RETURNING friend_id
                """, (now, self._device_hash(code), now))
                if row is not None:
                    return await self._sign_in(conn, row["friend_id"], "code", label, now)
            while state.failed and state.failed[0] <= instant - 600:
                state.failed.popleft()
            state.failed.append(instant)
            if len(state.failed) == 5:
                state.blocked_until = instant + 600
            raise SessionError("code_wrong")

    async def logout(self, token):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            return
        async with self.pool.connection() as conn:
            await conn.execute("""
                UPDATE marong.app_sessions SET revoked_at=%s WHERE token_hash=%s AND revoked_at IS NULL
            """, (self.now(), token_hash(token)))
