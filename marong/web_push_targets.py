"""Sealed notification references and the read-only API-314 resolver (TASK-572)."""

from datetime import timedelta
import re
import secrets
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .app_session import SessionError, one
from .room_scope import writing_room_key
from .web_push_subscriptions import decode, encode


_REFERENCE = re.compile(r"[A-Za-z0-9_-]{48,768}")
_MESSAGE_KINDS = {"reply": b"r", "proactive": b"p", "reminder": b"m"}
_CALL_KIND = b"c"


class NoticeReferences:
    """The validity age is injected by the environment; it is separate from push TTL."""

    def __init__(self, key, age):
        if len(key) != 32 or not isinstance(age, timedelta) or age <= timedelta(0):
            raise ValueError("Invalid notification reference configuration")
        self._key = AESGCM(key)
        self.age = age

    def seal(self, kind, friend, event_id, now):
        nonce = secrets.token_bytes(12)
        target = UUID(str(event_id)).bytes if kind == "call" else event_id.to_bytes(8, "big")
        tag = _CALL_KIND if kind == "call" else _MESSAGE_KINDS[kind]
        expires = int((now + self.age).timestamp() * 1000).to_bytes(8, "big")
        associated = b"marong:notice-target:v1\0" + friend.to_bytes(8, "big")
        return encode(nonce + self._key.encrypt(nonce, tag + expires + target, associated))

    def open(self, reference, friend, now):
        if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
            raise SessionError("invalid_input")
        associated = b"marong:notice-target:v1\0" + friend.to_bytes(8, "big")
        try:
            blob = decode(reference)
            content = self._key.decrypt(blob[:12], blob[12:], associated)
        except (InvalidTag, ValueError):
            raise SessionError("not_found") from None
        tag, milliseconds, target = content[:1], content[1:9], content[9:]
        if int.from_bytes(milliseconds, "big") <= now.timestamp() * 1000:
            raise SessionError("not_found")
        if tag == _CALL_KIND and len(target) == 16:
            return "call", UUID(bytes=target)
        if tag in _MESSAGE_KINDS.values() and len(target) == 8:
            return "message", int.from_bytes(target, "big")
        raise SessionError("not_found")


async def visible_message(conn, store, friend, message_id, *, reply_only=False):
    return await one(conn, f"""
        SELECT m.id FROM marong.messages m
        WHERE m.id=%(message)s AND m.room_key={writing_room_key('%(friend)s')}
          AND m.role='assistant' AND (NOT %(reply_only)s OR m.reply_to IS NOT NULL)
    """ + store._shown("m.room_key"), {"friend": friend, "message": message_id, "reply_only": reply_only})


async def resolve_target(conn, store, references, session, reference, now):
    friend = session["friend_id"]
    kind, ident = references.open(reference, friend, now)
    if kind == "message":
        found = await visible_message(conn, store, friend, ident)
        if found is None:
            raise SessionError("not_found")
        return {"state": "chat", "path": "/chat/"}
    ring = await one(conn, """
        SELECT r.status,r.answer_until,r.call_id,c.enabled
        FROM marong.app_rings r JOIN call.callers c ON c.id=r.caller_id AND c.friend_id=r.friend_id
        WHERE r.id=%s AND r.friend_id=%s AND r.reason='promise'
    """, (ident, friend))
    if ring is None:
        raise SessionError("not_found")
    if ring["status"] == "answered":
        return {"state": "ring_answered"}
    if ring["status"] in {"ringing", "missed"} and ring["answer_until"] <= now:
        return {"state": "ring_expired"}
    if ring["status"] == "ringing" and ring["enabled"]:
        return {"state": "ring_ready", "answerUntil": ring["answer_until"].isoformat()}
    return {"state": "ring_unavailable"}
