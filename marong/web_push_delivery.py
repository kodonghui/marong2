"""Apple Web Push transport (TASK-566, SPEC-529, SPEC-535, SPEC-537–538)."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
import hmac
from itertools import count
import json
import logging
import math
import re
import ssl

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import http_ece
import jwt

from .app_session import now_utc, one
from .web_push_subscriptions import (
    ActiveSubscriptionMaterial, WebPushSubscriptions, checked_bytes, decode, encode, endpoint_address,
    public_provider_ips,
)
from .web_push_targets import NoticeReferences


log = logging.getLogger(__name__)
_BODY = {
    "reply": "새 답변이 있어.",
    "proactive": "새 선톡이 있어.",
    "reminder": "일정 알림이 있어.",
    "call": "약속 전화 알림이 있어.",
}
_STATUS = re.compile(rb"HTTP/1\.[01] ([1-5][0-9]{2})(?: [^\r\n]*)?\r\n")
_RETRY_SECONDS = re.compile(r"[0-9]{1,10}")


@dataclass(frozen=True)
class ProviderResult:
    status: int
    retry_after: str | None = field(default=None, repr=False)


class AppleRequest:
    """One request per validated TLS socket. Response handling never retries the socket."""

    def __init__(self, reader, writer, target, host, token, payload, tag, urgency):
        self.reader = reader
        self.writer = writer
        self.target = target
        self.host = host
        self.token = token
        self.payload = payload
        self.tag = tag
        self.urgency = urgency

    async def write(self, ttl):
        header = (f"POST {self.target} HTTP/1.1\r\nHost: {self.host}\r\n"
                  f"Authorization: {self.token}\r\nTTL: {ttl}\r\nTopic: {self.tag}\r\nUrgency: {self.urgency}\r\n"
                  f"Content-Encoding: aes128gcm\r\nContent-Length: {len(self.payload)}\r\nConnection: close\r\n\r\n")
        self.writer.transport.set_write_buffer_limits(high=0, low=0)
        self.writer.write(header.encode("ascii") + self.payload)
        await self.writer.drain()
        if self.writer.is_closing():
            raise ConnectionError("Web Push connection ended during handoff")

    def abort(self):
        self.writer.transport.abort()

    async def response(self):
        async with asyncio.timeout(4):
            status = _STATUS.fullmatch(await self.reader.readline())
            if not status or int(status[1]) < 200:
                raise ValueError("Invalid provider status")
            retry_after = None
            for _ in range(40):
                line = await self.reader.readline()
                if line == b"\r\n":
                    return ProviderResult(int(status[1]), retry_after)
                name, colon, value = line.partition(b":")
                if not colon or not line.endswith(b"\r\n"):
                    break
                if name.lower() == b"retry-after":
                    retry_after = value.decode("ascii").strip()
            raise ValueError("Invalid provider reply headers")


class AppleWebPush:
    def __init__(self, keys, subject, *, now, resolve=public_provider_ips, connect=asyncio.open_connection):
        if not subject.startswith(("mailto:", "https://")) or any(ord(c) <= 32 for c in subject):
            raise ValueError("Invalid Web Push VAPID contact")
        self._keys = dict(keys)
        self.public_keys = {
            key_id: encode(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
            for key_id, key in keys.items()
        }
        self._subject = subject
        self._now = now
        self._resolve = resolve
        self._connect = connect
        self._tls = ssl.create_default_context()
        self._tls.set_alpn_protocols(["http/1.1"])
        self._tokens = OrderedDict()

    def _authorization(self, key_id, host):
        entries = (key_id, host)
        now = int(self._now().timestamp())
        cached = self._tokens.get(entries)
        if cached is None or cached[1] <= now + 60:
            expiry = now + 12 * 3600
            signed = jwt.encode({"aud": f"https://{host}", "exp": expiry, "sub": self._subject},
                                self._keys[key_id], algorithm="ES256")
            cached = (f"vapid t={signed}, k={self.public_keys[key_id]}", expiry)
            self._tokens[entries] = cached
        self._tokens.move_to_end(entries)
        if len(self._tokens) > 256:
            self._tokens.popitem(last=False)
        return cached[0]

    async def prepare(self, material, payload, tag, *, urgent=False):
        endpoint = material["endpoint"]
        address = endpoint_address(endpoint)
        if len(payload) > 2048 or not re.fullmatch(r"[A-Za-z0-9_-]{24}", tag):
            raise ValueError("Invalid Web Push presentation size or tag")
        send_key = ec.generate_private_key(ec.SECP256R1())
        encrypted = http_ece.encrypt(payload, private_key=send_key, dh=decode(material["keys"]["p256dh"]),
                                     auth_secret=decode(material["keys"]["auth"]), version="aes128gcm")
        if len(encrypted) > 4096:
            raise ValueError("Invalid Web Push encrypted size")
        authorization = self._authorization(material["vapidKeyId"], address.hostname)
        target = endpoint[len("https://") + len(address.netloc):] or "/"
        if target.startswith("?"):
            target = "/" + target
        async with asyncio.timeout(3):
            ips = await self._resolve(address.hostname)
            reader, writer = await self._connect(ips[0], 443, ssl=self._tls, server_hostname=address.hostname, limit=8192)
        return AppleRequest(reader, writer, target, address.netloc, authorization, encrypted, tag,
                            "high" if urgent else "normal")


def _retry_delay(value, now):
    if not value:
        return 1
    if _RETRY_SECONDS.fullmatch(value):
        return max(1, int(value))
    try:
        date = parsedate_to_datetime(value)
        return max(1, math.ceil((date.astimezone(timezone.utc) - now).total_seconds()))
    except (ValueError, TypeError, OverflowError):
        return 1


class WebPushDelivery:
    def __init__(self, subscriptions, references, transport, *, origin, tag_key, sleep=asyncio.sleep):
        if len(tag_key) != 32:
            raise ValueError("Invalid Web Push tag configuration")
        self.subscriptions = subscriptions
        self.references = references
        self.transport = transport
        self.origin = origin
        self._tag_key = tag_key
        self._sleep = sleep
        self._parallel = asyncio.Semaphore(8)
        self._events = {}
        self._reply_views = OrderedDict()
        self._arrivals = count()

    def reply_arrival(self):
        return next(self._arrivals), self.subscriptions.monotonic()

    def report_reply_view(self, friend_session, ident, message, view, arrival):
        key = (friend_session, ident, message)
        previous = self._reply_views.get(key)
        if previous is not None and previous[0][0] > arrival[0]:
            return
        self._reply_views[key] = (arrival, view)
        self._reply_views.move_to_end(key)
        if len(self._reply_views) > 2048:
            self._reply_views.popitem(last=False)

    def reply_seen(self, target, message):
        signal = self._reply_views.get((target.session_id, target.installation_id, message))
        return (signal is not None and signal[1] == "visible"
                and self.subscriptions.monotonic() - signal[0][1] < 5)

    def presentation(self, kind, event_id, friend, ident, now):
        event = f"{kind}:{event_id}".encode("ascii")
        tag = encode(hmac.digest(self._tag_key, b"marong:notice-tag:v1\0" + ident.bytes + event, "sha256")[:18])
        reference = self.references.seal(kind, friend, event_id, now)
        document = {"web_push": 8030, "notification": {
            "title": "마롱이", "body": _BODY[kind], "lang": "ko",
            "navigate": f"{self.origin}/chat/#notice={reference}", "tag": tag, "renotify": False,
        }}
        return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode(), tag

    async def _send(self, target, kind, event_id, deadline, *, event_deadline=None):
        now = self.subscriptions.now()
        payload, tag = self.presentation(kind, event_id, target.friend_id, target.installation_id, now)
        if kind == "reply":
            async def reply_deadline(_):
                return None if self.reply_seen(target, event_id) else deadline
            event_deadline = reply_deadline
        for attempt in range(2):
            if kind == "reply" and self.reply_seen(target, event_id):
                return "seen"
            if (deadline - self.subscriptions.now()).total_seconds() < 1:
                return "expired"
            try:
                async with self._parallel:
                    prepared = await self.subscriptions.prepare_target(
                        target, lambda material: self.transport.prepare(material, payload, tag, urgent=kind == "call"))
                    if prepared is None or not await self.subscriptions.handoff(
                            target, deadline, prepared, event_deadline=event_deadline):
                        return "ineligible"
                    try:
                        result = await prepared.response()
                    finally:
                        prepared.abort()
            except (OSError, TimeoutError, ValueError, KeyError):
                return "unconfirmed"
            if result.status == 201:
                return "accepted"
            if result.status == 410:
                return "invalid" if await self.subscriptions.invalidate(target) else "stale"
            if result.status not in (429, 503) or attempt:
                return "rejected"
            current = self.subscriptions.now()
            delay = _retry_delay(result.retry_after, current)
            if (deadline - current).total_seconds() - delay < 1:
                return "expired"
            await self._sleep(delay)
        return "rejected"

    async def send(self, friend, kind, event_id, deadline, *, event_deadline=None):
        now = self.subscriptions.now()
        self._events = {key: until for key, until in self._events.items() if until > now}
        key = (kind, event_id)
        if key in self._events or (deadline - now).total_seconds() < 1:
            return {}
        self._events[key] = deadline
        targets = await self.subscriptions.recipients(friend)
        if kind == "reply" and targets:
            await self._sleep(min(2, max(0, (deadline - self.subscriptions.now()).total_seconds() - 1)))
        results = await asyncio.gather(
            *(self._send(target, kind, event_id, deadline, event_deadline=event_deadline) for target in targets),
            return_exceptions=True,
        )
        counts = {}
        for result in results:
            outcome = "error" if isinstance(result, BaseException) else result
            counts[outcome] = counts.get(outcome, 0) + 1
        for outcome, count in counts.items():
            log.info("web_push kind=%s outcome=%s count=%d", kind, outcome, count)
        return counts

    async def publish(self, friend, kind, event_id, ttl):
        try:
            async def ring_record(conn):
                row = await one(conn, """
                    SELECT created_at,answer_until FROM marong.app_rings
                    WHERE id=%s AND friend_id=%s AND reason='promise' AND status='ringing' FOR SHARE
                """, (event_id, friend))
                return row

            async def ring_deadline(conn):
                row = await ring_record(conn)
                return row["answer_until"] if row else None

            async with asyncio.timeout(3), self.subscriptions.pool.connection() as conn:
                if kind == "call":
                    source = await ring_record(conn)
                else:
                    source = await one(conn, """
                        SELECT m.created_at FROM marong.messages m JOIN marong.rooms r ON r.room_key=m.room_key
                        WHERE m.id=%s AND r.owner_friend_id=%s AND m.role='assistant'
                    """, (event_id, friend))
            if source is None:
                return
            deadline = source["created_at"] + timedelta(seconds=ttl)
            if kind == "call":
                await self.send(friend, kind, event_id, min(deadline, source["answer_until"]), event_deadline=ring_deadline)
            else:
                await self.send(friend, kind, event_id, deadline)
        except Exception:
            log.warning("web_push kind=%s outcome=error", kind)


def configured_web_push(env, pool, origin, *, now=now_utc):
    if env.get("MARONG_WEB_PUSH") != "1":
        return None
    try:
        def secret(name):
            return checked_bytes(env[name], 32)

        vapid = {key: ec.derive_private_key(int.from_bytes(checked_bytes(value, 32), "big"), ec.SECP256R1())
                 for key, value in json.loads(env["MARONG_WEB_PUSH_VAPID_KEYS"]).items()}
        provider = AppleWebPush(vapid, env["MARONG_WEB_PUSH_SUBJECT"], now=now)
        envelopes = {key: checked_bytes(value, 32)
                     for key, value in json.loads(env["MARONG_WEB_PUSH_ENVELOPE_KEYS"]).items()}
        material = ActiveSubscriptionMaterial(env["MARONG_WEB_PUSH_ACTIVE_ENVELOPE_KEY"], envelopes,
                                              secret("MARONG_WEB_PUSH_FINGERPRINT_KEY"))
        subscriptions = WebPushSubscriptions(
            pool, authentication_key=secret("MARONG_WEB_PUSH_AUTHENTICATION_KEY"), material=material, now=now,
            active_vapid_key=env["MARONG_WEB_PUSH_ACTIVE_VAPID_KEY"], vapid_public_keys=provider.public_keys,
        )
        references = NoticeReferences(secret("MARONG_WEB_PUSH_TARGET_KEY"),
                                      timedelta(seconds=int(env["MARONG_WEB_PUSH_TARGET_AGE_SECONDS"])))
        return WebPushDelivery(subscriptions, references, provider, origin=origin,
                               tag_key=secret("MARONG_WEB_PUSH_TAG_KEY"))
    except (ValueError, KeyError, AttributeError, TypeError, OverflowError):
        log.warning("web_push configuration=unavailable")
        return None
