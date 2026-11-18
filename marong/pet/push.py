"""Member-scoped Web Push subscriptions and fixed alert contents (SPEC-337)."""

import asyncio
import json
import os
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from urllib.parse import urlsplit

from aiohttp import web
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .http import POOL, Problem, body_json, require_member, uuid_param
from .settings import SettingsError

_KEY = re.compile(r"[a-zA-Z0-9_-]+={0,2}\Z")
_HOSTS = {"fcm.googleapis.com", "updates.push.services.mozilla.com"}
_HOST_SUFFIXES = (".notify.windows.com", ".push.apple.com")
_LINES = {
    "sheet": "캐릭터 시트가 완성됐어요.",
    "proactive": "말을 걸었어요",
    "diary": "그림일기가 왔어요.",
    "refund": "결제가 자동으로 취소됐어요.",
    "export": "내보내기가 끝났어요.",
}


def endpoint_allowed(endpoint):
    if not isinstance(endpoint, str) or not 9 <= len(endpoint) <= 2008 or re.search(r"[\s\\]", endpoint):
        return False
    try:
        url = urlsplit(endpoint)
        host = url.hostname or ""
        return (url.scheme == "https" and url.port is None and url.netloc.lower() == host and not url.fragment
                and len(url.path) > 1 and (host in _HOSTS or host.endswith(_HOST_SUFFIXES)))
    except ValueError:
        return False


def _decode(value, limit):
    if not isinstance(value, str) or len(value) > limit or not _KEY.fullmatch(value):
        raise ValueError("invalid key")
    return urlsafe_b64decode(value.rstrip("=") + "=" * (-len(value.rstrip("=")) % 4))


async def save(req):
    owner = await require_member(req)
    data = await body_json(req)
    keys = data.get("keys")
    if set(data) != {"endpoint", "keys"} or not endpoint_allowed(data.get("endpoint")):
        raise Problem("invalid_input")
    if not isinstance(keys, dict) or set(keys) != {"p256dh", "auth"}:
        raise Problem("invalid_input")
    try:
        point = _decode(keys["p256dh"], 200)
        if len(point) != 65 or point[0] != 4 or len(_decode(keys["auth"], 100)) != 16:
            raise ValueError("invalid key length")
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except ValueError:
        raise Problem("invalid_input") from None
    async with req.app[POOL].connection() as conn:
        cur = await conn.execute(
            """INSERT INTO pet.push_subscriptions AS subscribed(member_id,endpoint,p256dh,auth)
            VALUES (%s,%s,%s,%s) ON CONFLICT(endpoint) DO UPDATE SET p256dh=EXCLUDED.p256dh,auth=EXCLUDED.auth
            WHERE subscribed.member_id=EXCLUDED.member_id RETURNING id""",
            (owner["id"], data["endpoint"], keys["p256dh"], keys["auth"]),
        )
        row = await cur.fetchone()
    if not row:
        raise Problem("invalid_input")
    return web.json_response({"jobId": str(row["id"])}, status=201)


async def remove(req):
    owner = await require_member(req)
    subscription = uuid_param(req.match_info["id"])
    async with req.app[POOL].connection() as conn:
        result = await conn.execute("DELETE FROM pet.push_subscriptions WHERE id=%s AND member_id=%s",
                                    (subscription, owner["id"]))
    if result.rowcount != 1:
        raise Problem("not_found")
    return web.Response(status=204)


class VapidSender:
    def __init__(self, private_key, subject):
        from py_vapid import Vapid

        try:
            self.signer = Vapid.from_file(private_key) if os.path.isfile(private_key) else Vapid.from_string(private_key)
            point = self.signer.public_key.public_bytes(serialization.Encoding.X962,
                                                        serialization.PublicFormat.UncompressedPoint)
            if len(point) != 65:
                raise ValueError("invalid public point")
        except Exception:
            raise SettingsError("the VAPID key is invalid") from None
        self.public_key = urlsafe_b64encode(point).decode("ascii").rstrip("=")
        self.subject = subject

    def _post(self, row, payload):
        import requests
        from pywebpush import WebPushException, webpush

        class NoRedirectSession(requests.Session):
            def request(self, method, url, **kwargs):
                return super().request(method, url, **{**kwargs, "allow_redirects": False})

        with NoRedirectSession() as session:
            session.trust_env = False
            subscription = {"endpoint": row["endpoint"], "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}}
            try:
                response = webpush(subscription, payload, vapid_private_key=self.signer,
                                   vapid_claims={"sub": self.subject}, ttl=3600, timeout=5, requests_session=session)
                return response.status_code
            except WebPushException as error:
                return error.response.status_code if error.response is not None else 503
            except requests.RequestException:
                return 503

    async def __call__(self, row, payload):
        if not endpoint_allowed(row["endpoint"]):
            return 404
        return await asyncio.to_thread(self._post, row, json.dumps(payload, ensure_ascii=False))


SENDER = web.AppKey("pet_push_sender", VapidSender)


async def notify(pool, member, pet, kind, *, send):
    """Each delivery reads the active pet state and uses only preset copy."""
    line = _LINES[kind]
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """SELECT s.*,p.name FROM pet.push_subscriptions s
            JOIN pet.members m ON m.id=s.member_id AND m.status='active'
            JOIN pet.pets p ON p.member_id=s.member_id AND p.id=%s AND p.mode='living' AND p.status='active'
            WHERE s.member_id=%s ORDER BY s.id""", (pet, member),
        )
        targets = await cursor.fetchall()
    delivered = 0
    for target in targets:
        payload = {"title": f'{target["name"]}(AI)', "body": line}
        for _ in range(2):
            try:
                status = await send(target, payload)
            except (OSError, TimeoutError):
                status = 503
            if status in (404, 410) or 200 <= status < 300:
                async with pool.connection() as conn:
                    if status in (404, 410):
                        await conn.execute("DELETE FROM pet.push_subscriptions WHERE id=%s AND p256dh=%s AND auth=%s",
                                           (target["id"], target["p256dh"], target["auth"]))
                    else:
                        await conn.execute("UPDATE pet.push_subscriptions SET last_ok_at=now() WHERE id=%s",
                                           (target["id"],))
                        delivered += 1
                break
    return delivered


def register(app, *, sender=None):
    if sender is not None:
        app[SENDER] = sender
    app.router.add_post("/api/me/push", save)
    app.router.add_delete("/api/me/push/{id}", remove)
