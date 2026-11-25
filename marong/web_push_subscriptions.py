"""Installation-bound Web Push subscriptions (TASK-561–565, SPEC-522–530)."""

import asyncio
import base64
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import hmac
import ipaddress
import json
import math
import re
import secrets
import socket
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.errors import UniqueViolation

from .app_session import TOKEN, SessionError, now_utc, one, token_hash


REVOKE = {"revoke", "permission_revoked"}
REGISTER = {"enable", "refresh"}
CHOICE_AGE = timedelta(seconds=120)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,24}")
INSTALLATION_HEADER = "X-Marong-Installation"
CHOICE_HEADER = "X-Marong-Choice"
PATH = "/chat/api/web-notifications"
_INVALID_INPUT = "invalid_input"
_STALE = "state_changed"
_TABLE = "marong.web_push_subscriptions"


@dataclass(frozen=True)
class PushTarget:
    friend_id: int
    session_id: int
    installation_id: UUID
    revision: UUID


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode(value):
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if encode(raw) != value:
        raise ValueError("noncanonical base64url")
    return raw


def checked_bytes(value, size):
    if not isinstance(value, str) or not TOKEN_PATTERN.fullmatch(value) or len(value) != (size * 8 + 5) // 6:
        raise ValueError("invalid bytes")
    return decode(value)


def installation_id(proof):
    if proof is None:
        raise SessionError("not_allowed")
    try:
        raw = checked_bytes(proof, 32)
    except ValueError:
        raise SessionError(_INVALID_INPUT) from None
    return UUID(bytes=hashlib.sha256(b"marong:web-push:installation:v1\0" + raw).digest()[:16], version=4)


def endpoint_address(endpoint):
    """Validate the URL without rewriting its request target."""
    if (not isinstance(endpoint, str) or not 12 <= len(endpoint) <= 2048
            or not endpoint.startswith("https://") or any(not 33 <= ord(c) <= 126 for c in endpoint)
            or "#" in endpoint or "\\" in endpoint):
        raise ValueError("invalid endpoint")
    address = urlsplit(endpoint)
    host = address.hostname or ""
    if (address.username is not None or address.password is not None
            or address.port not in (None, 443)
            or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+push\.apple\.com", host)
            or address.netloc.lower() not in {host, f"{host}:443"}):
        raise ValueError("invalid provider")
    return address


async def public_provider_ips(host):
    async with asyncio.timeout(2):
        answers = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    ips = tuple(dict.fromkeys(answer[4][0] for answer in answers))
    if not ips or any(not _public_provider_ip(ip) for ip in ips):
        raise ValueError("provider resolved to a non-public address")
    return ips


def _public_provider_ip(value):
    ip = ipaddress.ip_address(value)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def public_point(value):
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), checked_bytes(value, 65))


def subscription(body, allowed_keys, now):
    try:
        if set(body) != {"vapidKeyId", "subscription"}:
            raise ValueError
        key_id, sub = body["vapidKeyId"], body["subscription"]
        if not isinstance(key_id, str) or key_id not in allowed_keys:
            raise ValueError
        if not isinstance(sub, dict) or set(sub) != {"endpoint", "expirationTime", "keys"}:
            raise ValueError
        address = endpoint_address(sub["endpoint"])
        expiry = sub["expirationTime"]
        if expiry is not None and (type(expiry) is not int or not now.timestamp() * 1000 < expiry <= 8640000000000000):
            raise ValueError
        keys = sub["keys"]
        if not isinstance(keys, dict) or set(keys) != {"p256dh", "auth"}:
            raise ValueError
        public_point(keys["p256dh"])
        checked_bytes(keys["auth"], 16)
    except ValueError:
        raise SessionError(_INVALID_INPUT) from None
    return address, {"vapidKeyId": key_id, **sub}


class ActiveSubscriptionMaterial:
    """Only the active subscription processing and dispatch path holds envelope keys."""

    def __init__(self, active_key_id, keys, fingerprint_key):
        if (active_key_id not in keys or any(not KEY_ID.fullmatch(k) or len(v) != 32 for k, v in keys.items())
                or len(fingerprint_key) != 32):
            raise ValueError("Invalid Web Push envelope configuration")
        self.active_key_id = active_key_id
        self._keys = {key_id: AESGCM(key) for key_id, key in keys.items()}
        self._fingerprint_key = fingerprint_key

    @staticmethod
    def _aad(ident, session, revision):
        return b"marong:web-push:envelope:v1\0" + ident.bytes + session.to_bytes(8, "big") + revision.bytes

    def fingerprint(self, address):
        # Domain, port spelling and an omitted root path do not change the destination.
        target = address.path or "/"
        if address.query:
            target += "?" + address.query
        normalized = f"https://{address.hostname}{target}"
        return hmac.digest(self._fingerprint_key, normalized.encode("ascii"), "sha256")

    def _open(self, ident, session, row):
        key, encrypted = bytes(row["protected_material"]).split(b"\0", 1)
        aad = self._aad(ident, session, row["revision"])
        return json.loads(self._keys[key.decode("ascii")].decrypt(encrypted[:12], encrypted[12:], aad))

    def create(self, ident, session, revision, supplied, *, refresh=None):
        repeated = self._open(ident, session, refresh) if refresh else None
        consent = repeated["consent"] if repeated else encode(secrets.token_bytes(32))
        key_id = self.active_key_id
        nonce = secrets.token_bytes(12)
        aad = self._aad(ident, session, revision)
        ciphertext = self._keys[key_id].encrypt(nonce, json.dumps({**supplied, "consent": consent}).encode(), aad)
        return key_id.encode("ascii") + b"\0" + nonce + ciphertext

    def matches(self, ident, session, row, supplied):
        stored = self._open(ident, session, row)
        return all(stored[field] == value for field, value in supplied.items())

    def consent_check(self, ident, session, row, challenge):
        consent = decode(self._open(ident, session, row)["consent"])
        return encode(hmac.digest(consent, b"marong:web-push:consent:v1\0" + decode(challenge), "sha256"))


class WebPushSubscriptions:
    def __init__(self, pool, *, authentication_key, material, active_vapid_key, vapid_public_keys,
                 now=now_utc, monotonic=time.monotonic, resolve=public_provider_ips):
        if len(authentication_key) != 32 or active_vapid_key not in vapid_public_keys:
            raise ValueError("Invalid Web Push token or VAPID configuration")
        for key_id, public_key in vapid_public_keys.items():
            if not KEY_ID.fullmatch(key_id):
                raise ValueError("Invalid Web Push VAPID key ID")
            public_point(public_key)
        self.pool = pool
        self.now = now
        self.monotonic = monotonic
        self.resolve = resolve
        self.material = material
        self.public_keys = dict(vapid_public_keys)
        self.vapid = {"keyId": active_vapid_key, "publicKey": vapid_public_keys[active_vapid_key]}
        self._token_key = AESGCM(authentication_key)
        self._limits = OrderedDict()

    def _issue(self, purpose, sid, ident, claims, expires):
        nonce = secrets.token_bytes(12)
        context = f"marong:web-push:{purpose}:v1:{sid}:{ident}".encode("ascii")
        body = json.dumps({**claims, "until": expires.timestamp()}, separators=(",", ":")).encode()
        return encode(nonce + self._token_key.encrypt(nonce, body, context))

    def _verify(self, purpose, sid, ident, token, now):
        maximum = 512 if purpose == "state" else 768
        if not isinstance(token, str) or not 48 <= len(token) <= maximum or not TOKEN_PATTERN.fullmatch(token):
            raise SessionError(_INVALID_INPUT)
        context = f"marong:web-push:{purpose}:v1:{sid}:{ident}".encode("ascii")
        try:
            raw = decode(token)
            claims = json.loads(self._token_key.decrypt(raw[:12], raw[12:], context))
        except (InvalidTag, ValueError):
            raise SessionError(_STALE) from None
        if claims["until"] <= now.timestamp():
            raise SessionError(_STALE)
        return claims

    def limit(self, session, ident, *, limit=60):
        key = (session, ident, limit)
        now = self.monotonic()
        while self._limits and next(iter(self._limits.values()))[-1] <= now - 60:
            self._limits.popitem(last=False)
        if key not in self._limits and len(self._limits) >= 4096:
            earliest = next(iter(self._limits.values()))[-1]
            raise SessionError("request_limit", retry_after=math.ceil(earliest + 60 - now))
        recent = self._limits.setdefault(key, deque())
        while recent and recent[0] <= now - 60:
            recent.popleft()
        if len(recent) >= limit:
            raise SessionError("request_limit", retry_after=math.ceil(recent[0] + 60 - now))
        recent.append(now)
        self._limits.move_to_end(key)

    @staticmethod
    def _version(row):
        return str(row["revision"]) if row else None

    @staticmethod
    def _state(row, ident, sid, now):
        if row is None or row["revision"] == rebound_revision(ident, sid):
            return "not_registered"
        if row["state"] == "active" and row["expires_ms"] is not None and row["expires_ms"] <= now.timestamp() * 1000:
            return "expired"
        return row["state"]

    @staticmethod
    async def _row(conn, ident):
        return await one(conn, f"""
            SELECT session_id, revision, state, protected_material,
                   floor(extract(epoch FROM subscription_expires_at) * 1000)::bigint AS expires_ms
            FROM {_TABLE} WHERE installation_id=%s
        """, (ident,))

    async def active_consent(self, conn, ident, sid, now):
        row = await self._row(conn, ident)
        if row is None or row["session_id"] != sid or self._state(row, ident, sid, now) != "active":
            raise SessionError("not_allowed")
        consent = self.material.consent_check(ident, sid, row, encode(b"marong:notice-document:v1"))
        return consent, row["expires_ms"]

    @asynccontextmanager
    async def _operation(self, token, ident, *, write=False):
        async with self.authenticated(token, ident, write=write) as (conn, session, now):
            sid = session["id"]
            if write:
                await lock_installation(conn, ident)
                now = self.now()
                if session["expires_at"] <= now:
                    raise SessionError("login_required")
            row = await self._row(conn, ident)
            own = row if row and row["session_id"] == sid else None
            yield conn, session, row, own, now

    @asynccontextmanager
    async def authenticated(self, token, ident, *, write=False, limit=60):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise SessionError("login_required")
        async with asyncio.timeout(3), self.pool.connection() as conn, conn.transaction():
            session = await one(conn, """
                SELECT id, friend_id, revoked_at, expires_at FROM marong.app_sessions WHERE token_hash=%s
            """ + (" FOR UPDATE" if write else ""), (token_hash(token),))
            now = self.now()
            if session is None or session["revoked_at"] is not None or session["expires_at"] <= now:
                raise SessionError("login_required")
            self.limit(session["id"], ident, limit=limit)
            yield conn, session, now

    def _state_claims(self, ident, sid, row):
        claims = {"prior": self._version(row)}
        if row and row["state"] == "active":
            salt = encode(secrets.token_bytes(16))
            claims.update(salt=salt, check=self.material.consent_check(ident, sid, row, salt))
        return claims

    def _same_consent(self, ident, sid, row, claims):
        return (row is not None and row["state"] == "active" and "check" in claims
                and hmac.compare_digest(claims["check"], self.material.consent_check(ident, sid, row, claims["salt"])))

    def _result(self, ident, sid, row, now):
        return {"state": self._state(row, ident, sid, now), "vapid": self.vapid,
                "stateToken": self._issue("state", sid, ident, self._state_claims(ident, sid, row), now + CHOICE_AGE)}

    async def status(self, token, ident):
        async with self._operation(token, ident) as (_, session, _, own, now):
            return self._result(ident, session["id"], own, now)

    async def choice(self, token, ident, body):
        if set(body) != {"action", "stateToken"} or not isinstance(body["action"], str):
            raise SessionError(_INVALID_INPUT)
        action = body["action"]
        if action not in REGISTER | REVOKE:
            raise SessionError(_INVALID_INPUT)
        async with self._operation(token, ident) as (_, session, _, own, now):
            sid = session["id"]
            prior = self._verify("state", sid, ident, body["stateToken"], now)
            revoked_during_refresh = action in REVOKE and self._same_consent(ident, sid, own, prior)
            if prior["prior"] != self._version(own) and not revoked_during_refresh:
                raise SessionError(_STALE)
            is_active = self._state(own, ident, sid, now) == "active"
            if (action == "enable" and is_active) or (action == "refresh" and not is_active):
                raise SessionError(_STALE)
            claims = {**self._state_claims(ident, sid, own), "action": action, "result": str(uuid4())}
            expiry = now + CHOICE_AGE
            return {"choiceToken": self._issue("choice", sid, ident, claims, expiry), "expiresAt": expiry.isoformat()}

    async def register(self, token, ident, choice, body):
        async with self._operation(token, ident, write=True) as (conn, session, row, own, now):
            sid = session["id"]
            selected = self._verify("choice", sid, ident, choice, now)
            if selected["action"] not in REGISTER:
                raise SessionError(_STALE)
            address, supplied = subscription(body, self.public_keys, now)
            if row is not None and own is None:
                raise SessionError("subscription_conflict")
            state = self._state(own, ident, sid, now)
            if self._version(own) == selected["result"] and state == "active":
                if self.material.matches(ident, sid, own, supplied):
                    return self._result(ident, sid, own, now)
                raise SessionError(_STALE)
            if self._version(own) != selected["prior"] or (state == "active") != (selected["action"] == "refresh"):
                raise SessionError(_STALE)
            try:
                await self.resolve(address.hostname)
            except TimeoutError:
                raise
            except (OSError, ValueError):
                raise SessionError(_INVALID_INPUT) from None
            now = self.now()
            if session["expires_at"] <= now:
                raise SessionError("login_required")
            self._verify("choice", sid, ident, choice, now)
            if self._state(own, ident, sid, now) != state:
                raise SessionError(_STALE)
            revision = UUID(selected["result"])
            envelope = self.material.create(ident, sid, revision, supplied, refresh=own if state == "active" else None)
            try:
                await conn.execute(f"""
                    INSERT INTO {_TABLE}
                        (installation_id, session_id, revision, state, endpoint_fingerprint,
                         protected_material, subscription_expires_at)
                    VALUES (%s,%s,%s,'active',%s,%s,to_timestamp(%s::bigint / 1000.0))
                    ON CONFLICT (installation_id) DO UPDATE SET revision=EXCLUDED.revision,
                        state=EXCLUDED.state, endpoint_fingerprint=EXCLUDED.endpoint_fingerprint,
                        protected_material=EXCLUDED.protected_material,
                        subscription_expires_at=EXCLUDED.subscription_expires_at
                """, (ident, sid, revision, self.material.fingerprint(address), envelope, supplied["expirationTime"]))
            except UniqueViolation as exc:
                if exc.diag.constraint_name == "web_push_subscriptions_active_endpoint_idx":
                    raise SessionError("subscription_conflict") from None
                raise
            return self._result(ident, sid, await self._row(conn, ident), now)

    async def revoke(self, token, ident, choice):
        async with self._operation(token, ident, write=True) as (conn, session, _, own, now):
            sid = session["id"]
            selected = self._verify("choice", sid, ident, choice, now)
            if selected["action"] not in REVOKE:
                raise SessionError(_STALE)
            version = self._version(own)
            if version == selected["result"]:
                return self._result(ident, sid, own, now)
            if version != selected["prior"] and not self._same_consent(ident, sid, own, selected):
                raise SessionError(_STALE)
            if own and self._state(own, ident, sid, now) not in {"revoked", "not_registered"}:
                await deactivate(conn, ident, UUID(selected["result"]))
                own = await self._row(conn, ident)
            return self._result(ident, sid, own, now)

    async def switch_installation(self, conn, ident, session_id):
        # A concurrent sign-in can change the owning session between the first
        # read and the installation lock. Roll back the savepoint and re-order.
        for _ in range(5):
            try:
                async with conn.transaction():
                    before = await self._row(conn, ident)
                    if before is not None:
                        await one(conn, "SELECT id FROM marong.app_sessions WHERE id=%s FOR UPDATE",
                                  (before["session_id"],))
                    await lock_installation(conn, ident)
                    current = await self._row(conn, ident)
                    if current is not None and (before is None or before["session_id"] != current["session_id"]):
                        raise _InstallationMoved
                    if current is not None:
                        await conn.execute(f"""
                            UPDATE {_TABLE} SET session_id=%s,revision=%s,state='revoked',
                                endpoint_fingerprint=NULL,protected_material=NULL,subscription_expires_at=NULL
                            WHERE installation_id=%s
                        """, (session_id, rebound_revision(ident, session_id), ident))
                return
            except _InstallationMoved:
                continue
        raise SessionError("db_unavailable")

    @staticmethod
    async def revoke_sessions(conn, sessions):
        if sessions:
            # These session rows are already locked. Every subscription writer
            # acquires the owner session before touching the installation.
            await conn.execute(f"""
                UPDATE {_TABLE} SET revision=gen_random_uuid(),state='revoked',
                    endpoint_fingerprint=NULL,protected_material=NULL,subscription_expires_at=NULL
                WHERE session_id=ANY(%s) AND state='active'
            """, (sessions,))

    async def recipients(self, friend_id):
        now = self.now()
        async with asyncio.timeout(3), self.pool.connection() as conn:
            rows = await (await conn.execute(f"""
                SELECT a.friend_id,p.session_id,p.installation_id,p.revision
                FROM {_TABLE} p JOIN marong.app_sessions a ON a.id=p.session_id
                WHERE a.friend_id=%s AND a.revoked_at IS NULL AND a.expires_at>%s
                  AND p.state='active' AND (p.subscription_expires_at IS NULL OR p.subscription_expires_at>%s)
                ORDER BY p.session_id,p.installation_id
            """, (friend_id, now, now))).fetchall()
        return [PushTarget(**row) for row in rows]

    @staticmethod
    def _valid_target(target, session, row, now):
        return (session is not None and session["friend_id"] == target.friend_id
                and session["revoked_at"] is None and session["expires_at"] > now
                and row is not None and row["revision"] == target.revision
                and row["state"] == "active" and row["session_id"] == target.session_id
                and (row["expires_ms"] is None or row["expires_ms"] > now.timestamp() * 1000))

    @staticmethod
    async def _target_session(conn, target, *, lock=False):
        return await one(conn, """
            SELECT friend_id, revoked_at, expires_at FROM marong.app_sessions WHERE id=%s
        """ + (" FOR UPDATE" if lock else ""), (target.session_id,))

    async def prepare_target(self, target, prepare):
        """Pass material only to a transport preparer. It may connect, but cannot send here."""
        async with asyncio.timeout(3), self.pool.connection() as conn:
            session = await self._target_session(conn, target)
            row = await self._row(conn, target.installation_id)
            if not self._valid_target(target, session, row, self.now()):
                return None
            material = self.material._open(target.installation_id, target.session_id, row)
        return await prepare(material)

    async def handoff(self, target, deadline, request, *, event_deadline=None):
        """Serialize the complete request write against session and installation changes.

        The transport aborts synchronously on failure, before the locks are released.
        Reading the provider response is a separate operation and holds no lock.
        """
        handed = aborted = False
        try:
            async with asyncio.timeout(3), self.pool.connection() as conn, conn.transaction():
                try:
                    session = await self._target_session(conn, target, lock=True)
                    if session is None:
                        return False
                    await lock_installation(conn, target.installation_id)
                    row = await self._row(conn, target.installation_id)
                    if event_deadline is not None:
                        current_deadline = await event_deadline(conn)
                        if current_deadline is None:
                            return False
                        deadline = min(deadline, current_deadline)
                    now = self.now()
                    if not self._valid_target(target, session, row, now):
                        return False
                    remaining = (deadline - now).total_seconds()
                    ttl = math.floor(remaining)
                    if ttl < 1:
                        return False
                    window = min(2, remaining, (session["expires_at"] - now).total_seconds())
                    if row["expires_ms"] is not None:
                        window = min(window, row["expires_ms"] / 1000 - now.timestamp())
                    async with asyncio.timeout(window):
                        await request.write(ttl)
                    handed = True
                finally:
                    if not handed:
                        aborted = True
                        request.abort()
        finally:
            if not handed and not aborted:
                request.abort()
        return handed

    async def invalidate(self, target):
        async with asyncio.timeout(3), self.pool.connection() as conn, conn.transaction():
            session = await self._target_session(conn, target, lock=True)
            if session is None:
                return False
            await lock_installation(conn, target.installation_id)
            row = await self._row(conn, target.installation_id)
            if not self._valid_target(target, session, row, self.now()):
                return False
            await deactivate(conn, target.installation_id, uuid4(), "invalid")
            return True

    async def sweep_expired(self, limit=64):
        async with asyncio.timeout(3), self.pool.connection() as conn:
            candidates = await (await conn.execute(f"""
                SELECT installation_id, session_id, revision FROM {_TABLE}
                WHERE state='active' AND subscription_expires_at<=%s
                ORDER BY subscription_expires_at, installation_id LIMIT %s
            """, (self.now(), limit))).fetchall()
        completed = 0
        for candidate in candidates:
            ident, sid = candidate["installation_id"], candidate["session_id"]
            async with asyncio.timeout(3), self.pool.connection() as conn, conn.transaction():
                session = await one(conn, "SELECT id FROM marong.app_sessions WHERE id=%s FOR UPDATE", (sid,))
                if session is None:
                    continue
                await lock_installation(conn, ident)
                row = await self._row(conn, ident)
                if (row is None or row["session_id"] != sid or row["revision"] != candidate["revision"]
                        or row["state"] != "active" or self._state(row, ident, sid, self.now()) != "expired"):
                    continue
                await deactivate(conn, ident, uuid4(), "expired")
                completed += 1
        return completed


class _InstallationMoved(Exception):
    pass


async def lock_installation(conn, ident):
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"marong.web-push:{ident}",))


def rebound_revision(ident, session):
    """A new login sees an empty subscription without deleting the prior row."""
    material = f"marong:web-push:rebound:v1:{ident}:{session}".encode("ascii")
    return UUID(bytes=hashlib.sha256(material).digest()[:16], version=5)


async def deactivate(conn, ident, revision, state="revoked"):
    await conn.execute(f"""
        UPDATE {_TABLE} SET revision=%s,state=%s,endpoint_fingerprint=NULL,
            protected_material=NULL,subscription_expires_at=NULL WHERE installation_id=%s
    """, (revision, state, ident))
