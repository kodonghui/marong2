"""Shared authentication and wire constants for API-315 and API-317."""

from datetime import timedelta
import hmac
import re
import secrets
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .app_session import SessionError
from .web_push_subscriptions import checked_bytes, decode, encode
from .web_push_targets import NoticeReferences


CALL_BRIDGE = "http://127.0.0.1:8792/internal/web-notification/accept"
BRIDGE_HEADER = "X-Marong-Call-Bridge"
SUBPROTOCOL = "marong-notified-v1"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def client_uuid(value):
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise SessionError("invalid_input")
    return UUID(value)


class NoticeCallProtocol:
    def __init__(self, challenge_key, references):
        self.bridge_secret = encode(hmac.digest(challenge_key, b"marong:notice-call:bridge:v1", "sha256"))
        self._client_key = hmac.digest(challenge_key, b"marong:notice-call:client:v1", "sha256")
        self._secret = AESGCM(hmac.digest(challenge_key, b"marong:notice-call:token:v1", "sha256"))
        self.references = references

    @classmethod
    def configured(cls, env):
        if env.get("MARONG_WEB_PUSH") != "1":
            return None
        try:
            key = checked_bytes(env["MARONG_WEB_PUSH_AUTHENTICATION_KEY"], 32)
            references = NoticeReferences(checked_bytes(env["MARONG_WEB_PUSH_TARGET_KEY"], 32),
                                          timedelta(seconds=int(env["MARONG_WEB_PUSH_TARGET_AGE_SECONDS"])))
            return cls(key, references)
        except (ValueError, KeyError, OverflowError):
            return None

    def bound_client(self, friend, ident, client):
        domain = friend.to_bytes(8, "big") + ident.bytes + client.bytes
        return str(UUID(bytes=hmac.digest(self._client_key, domain, "sha256")[:16], version=4))

    @staticmethod
    def _aad(sid, ident, client):
        return sid.to_bytes(8, "big") + ident.bytes + client.bytes

    def issue(self, sid, ident, client, call, ring, now):
        nonce = secrets.token_bytes(12)
        until = int((now + timedelta(seconds=120)).timestamp() * 1000).to_bytes(8, "big")
        return encode(nonce + self._secret.encrypt(nonce, UUID(call).bytes + ring.bytes + until,
                                                   self._aad(sid, ident, client)))

    def verify(self, sid, ident, client, token, now):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{48,768}", token):
            raise SessionError("invalid_input")
        try:
            raw = decode(token)
            plain = self._secret.decrypt(raw[:12], raw[12:], self._aad(sid, ident, client))
        except (InvalidTag, ValueError):
            raise SessionError("not_allowed") from None
        if int.from_bytes(plain[32:], "big") <= now.timestamp() * 1000:
            raise SessionError("not_allowed")
        return UUID(bytes=plain[:16]), UUID(bytes=plain[16:32])
