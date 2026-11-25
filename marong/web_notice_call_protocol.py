"""Shared authentication and wire constants for API-315 and API-317."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
ENDED_PATH = "/internal/web-notification/ended"
ENDED_BRIDGE = f"http://127.0.0.1:8792{ENDED_PATH}"
INSTALLATION_CHECK_PATH = "/internal/web-notification/installation"
BRIDGE_HEADER = "X-Marong-Call-Bridge"
READ_BRIDGE_HEADER = "X-Marong-Call-Read-Bridge"
ORDINARY_CHOICE_HEADER = "X-Marong-Ordinary-Choice"
RECEIPT_HEADER = "X-Marong-Notice-Receipt"
RECEIPT_EXPIRES_HEADER = "X-Marong-Notice-Receipt-Expires"
REDIAL_HEADER = "X-Marong-Redial-Choice"
CONSENT_HEADER = "X-Marong-Notice-Consent"
SUBPROTOCOL = "marong-notified-v1"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MICROSECOND = timedelta(microseconds=1)
REDIAL_AGE = timedelta(minutes=5)
RECEIPT_AGE = timedelta(hours=24)


def client_uuid(value):
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise SessionError("invalid_input")
    return UUID(value)


def notice_client(value):
    """Version 8 is reserved for this feature's internal client identities."""
    return (value if isinstance(value, UUID) else UUID(value)).version == 8


def _notice_uuid(data):
    raw = bytearray(data[:16])
    raw[6] = raw[6] & 0x0F | 0x80
    raw[8] = raw[8] & 0x3F | 0x80
    return UUID(bytes=bytes(raw))


@dataclass(frozen=True)
class NoticeReceipt:
    call: UUID
    owner: UUID
    expires: datetime


class NoticeCallProtocol:
    def __init__(self, challenge_key, references):
        self.bridge_secret = encode(hmac.digest(challenge_key, b"marong:notice-call:bridge:v1", "sha256"))
        self.read_secret = encode(hmac.digest(challenge_key, b"marong:notice-call:read:v1", "sha256"))
        self._client_key = hmac.digest(challenge_key, b"marong:notice-call:client:v1", "sha256")
        self._document_key = hmac.digest(challenge_key, b"marong:notice-call:document:v1", "sha256")
        self._ordinary_key = hmac.digest(challenge_key, b"marong:notice-call:ordinary:v1", "sha256")
        self._receipt_key = AESGCM(hmac.digest(challenge_key, b"marong:notice-call:receipt:v1", "sha256"))
        self._redial_key = AESGCM(hmac.digest(challenge_key, b"marong:notice-call:redial:v1", "sha256"))
        self._redial_document_key = hmac.digest(challenge_key, b"marong:notice-call:redial-document:v1", "sha256")
        # Only the locked API-315 check of a server-issued answer document may mint v2 tokens.
        self._secret = AESGCM(hmac.digest(challenge_key, b"marong:notice-call:token:v2", "sha256"))
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

    def bound_client(self, friend, sid, ident, client):
        domain = friend.to_bytes(8, "big") + self._aad(sid, ident, client)
        return str(_notice_uuid(hmac.digest(self._client_key, domain, "sha256")))

    def document_client(self, sid, ident, reference, consent, *, client=None):
        # Keep a random 56-bit nonce and a 66-bit MAC in the existing UUID field.
        nonce = secrets.token_bytes(7) if client is None else client.bytes[:6] + client.bytes[7:8]
        prefix = sid.to_bytes(8, "big") + ident.bytes + nonce
        encoded_ref = reference.encode("ascii")
        if consent is None:
            tag = hmac.digest(self._ordinary_key, b"document\0" + prefix + encoded_ref, "sha256")
        else:
            tag = hmac.digest(self._document_key, prefix + consent.encode("ascii") + encoded_ref, "sha256")
        return _notice_uuid(nonce[:6] + tag[:1] + nonce[6:] + tag[1:9])

    def matches_document(self, sid, ident, reference, consent, client):
        if not notice_client(client):
            return False
        expected = self.document_client(sid, ident, reference, consent, client=client)
        return hmac.compare_digest(client.bytes, expected.bytes)

    def ordinary_choice(self, sid, ident, reference):
        domain = b"choice\0" + sid.to_bytes(8, "big") + ident.bytes + reference.encode("ascii")
        return encode(hmac.digest(self._ordinary_key, domain, "sha256"))

    @staticmethod
    def receipt_scope(friend, sid, ident, reference, consent):
        return friend.to_bytes(8, "big") + sid.to_bytes(8, "big") + ident.bytes + consent.encode("ascii") + reference.encode("ascii")

    def receipt(self, scope, claim):
        return self._seal_redial(self._receipt_key, scope, claim, claim.expires)

    def redial_choice(self, scope, claim, now):
        return self._seal_redial(self._redial_key, scope, claim, min(claim.expires, now + REDIAL_AGE))

    @staticmethod
    def _seal_redial(key, scope, claim, until):
        nonce = secrets.token_bytes(12)
        plain = (claim.call.bytes + claim.owner.bytes + ((claim.expires - _EPOCH) // _MICROSECOND).to_bytes(8, "big")
                 + ((until - _EPOCH) // _MICROSECOND).to_bytes(8, "big"))
        return encode(nonce + key.encrypt(nonce, plain, scope))

    def check_redial(self, scope, token, now, *, choice=False):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{102}", token):
            raise SessionError("not_allowed")
        key = self._redial_key if choice else self._receipt_key
        try:
            raw = decode(token)
            if encode(raw) != token:
                raise ValueError
            plain = key.decrypt(raw[:12], raw[12:], scope)
            expires = _EPOCH + timedelta(microseconds=int.from_bytes(plain[32:40], "big"))
            until = _EPOCH + timedelta(microseconds=int.from_bytes(plain[40:], "big"))
        except (InvalidTag, ValueError, OverflowError):
            raise SessionError("not_allowed") from None
        if not now < until <= expires:
            raise SessionError("not_allowed")
        return NoticeReceipt(UUID(bytes=plain[:16]), UUID(bytes=plain[16:32]), expires)

    def redial_document(self, choice):
        # A new document for the same choice must use the same persistent call client.
        return _notice_uuid(hmac.digest(self._redial_document_key, choice.encode("ascii"), "sha256"))

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
        if not notice_client(client):
            raise SessionError("not_allowed")
        try:
            raw = decode(token)
            plain = self._secret.decrypt(raw[:12], raw[12:], self._aad(sid, ident, client))
        except (InvalidTag, ValueError):
            raise SessionError("not_allowed") from None
        if int.from_bytes(plain[32:], "big") <= now.timestamp() * 1000:
            raise SessionError("not_allowed")
        return UUID(bytes=plain[:16]), UUID(bytes=plain[16:32])
