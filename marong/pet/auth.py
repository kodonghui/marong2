"""Authorization code login and member/pending sessions (SPEC-310)."""

import asyncio
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import hmac
import json
from secrets import token_urlsafe
from time import monotonic, time
from urllib.parse import urlencode

import aiohttp
from aiohttp import web
import jwt

from .http import CONFIG, COOKIE, POOL, Problem, cookie_hash, require_member, set_session_cookie
from .inventory import sync_defaults
from .settings import SettingsError

STATE_COOKIE = "pet_oidc"
STATE_S = 600
PENDING = timedelta(minutes=30)
MEMBER = timedelta(days=30)
MEMBER_MAX = timedelta(days=90)
AUTH = web.AppKey("pet_auth")
CLOCK_LEEWAY_S = 0
PROVIDERS = {
    "google": ("https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token",
               "https://www.googleapis.com/oauth2/v3/certs", ("https://accounts.google.com", "accounts.google.com")),
    "kakao": ("https://kauth.kakao.com/oauth/authorize", "https://kauth.kakao.com/oauth/token",
              "https://kauth.kakao.com/.well-known/jwks.json", ("https://kauth.kakao.com",)),
}


class ProviderError(ValueError):
    pass


@dataclass(frozen=True)
class Provider:
    client_id: str
    secret: str = field(repr=False)
    authorize_url: str
    token_url: str
    jwks_url: str
    issuers: tuple[str, ...]


@dataclass(frozen=True)
class AuthConfig:
    providers: dict[str, Provider]
    secret: bytes = field(repr=False)

    @classmethod
    def read(cls, env):
        clients = {}
        for service, endpoints in PROVIDERS.items():
            prefix = f"PET_{service.upper()}"
            client_id = env.get(f"{prefix}_CLIENT_ID", "").strip()
            secret = env.get(f"{prefix}_CLIENT_SECRET", "").strip()
            if client_id:
                clients[service] = Provider(client_id, secret, *endpoints)
        secret = env.get("PET_AUTH_SECRET", "").encode("utf-8")
        if clients and len(secret) < 32:
            raise SettingsError("PET_AUTH_SECRET is missing or too short")
        return cls(clients, secret)


def _base64(data):
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _seal(secret, payload):
    data = _base64(json.dumps(payload, separators=(",", ":")).encode("ascii"))
    signature = hmac.digest(secret, b"state\0" + data.encode("ascii"), "sha256")
    return f"{data}.{_base64(signature)}"


def _open(secret, raw, provider, state):
    if not raw or len(raw) > 1500 or not state or len(state) > 128:
        return None
    try:
        data, signature = raw.split(".", 1)
        signed = hmac.digest(secret, b"state\0" + data.encode("ascii"), "sha256")
        if not hmac.compare_digest(signature, _base64(signed)):
            return None
        payload = json.loads(urlsafe_b64decode(data + "=" * (-len(data) % 4)))
        if (payload["provider"] != provider or not hmac.compare_digest(payload["state"], state)
                or not 0 <= time() - payload["created"] < STATE_S):
            return None
    except (TypeError, ValueError, KeyError, UnicodeError):
        return None
    return payload


def subject_hash(secret, provider, sub):
    return hmac.digest(secret, b"subject\0" + provider.encode("ascii") + b"\0" + sub.encode("utf-8"), "sha256")


def _release_state(response):
    response.set_cookie(STATE_COOKIE, "", max_age=0, secure=True, httponly=True, samesite="Lax", path="/api/auth/")
    return response


class Auth:
    def __init__(self, config, client):
        self.config = config
        self.client = client
        self.keys = {}
        self.lock = asyncio.Lock()

    def _callback(self, req, name):
        return f"{req.app[CONFIG].origin}/api/auth/{name}/callback"

    async def start(self, req):
        name = req.match_info["provider"]
        provider = self.config.providers.get(name)
        if provider is None:
            raise Problem("server_error")
        verifier, state, nonce = token_urlsafe(32), token_urlsafe(32), token_urlsafe(32)
        proof = _base64(hashlib.sha256(verifier.encode("ascii")).digest())
        query = urlencode({"client_id": provider.client_id, "response_type": "code", "scope": "openid",
                           "redirect_uri": self._callback(req, name), "state": state, "nonce": nonce,
                           "code_challenge": proof, "code_challenge_method": "S256"})
        response = web.HTTPFound(f"{provider.authorize_url}?{query}")
        pending = _seal(self.config.secret, {"provider": name, "verifier": verifier, "state": state,
                                             "nonce": nonce, "created": time()})
        response.set_cookie(STATE_COOKIE, pending, max_age=STATE_S, secure=True, httponly=True, samesite="Lax",
                            path="/api/auth/")
        return response

    async def _key(self, provider, key_id):
        async with self.lock:
            expires, keys = self.keys.get(provider.jwks_url, (0, {}))
            now = monotonic()
            if expires <= now or (key_id not in keys and expires - now < 270):
                async with self.client.get(provider.jwks_url, allow_redirects=False) as response:
                    if response.status != 200:
                        raise ProviderError
                    raw = await response.json()
                    keys = {item["kid"]: item for item in raw["keys"] if item.get("kty") == "RSA"}
                self.keys[provider.jwks_url] = (now + 300, keys)
            if key_id not in keys:
                raise ProviderError
            return jwt.algorithms.RSAAlgorithm.from_jwk(keys[key_id])

    async def _exchange(self, req, provider, name, code, state):
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": self._callback(req, name),
                "client_id": provider.client_id, "code_verifier": state["verifier"]}
        if provider.secret:
            data["client_secret"] = provider.secret
        async with self.client.post(provider.token_url, data=data, allow_redirects=False) as response:
            if response.status != 200:
                raise ProviderError
            reply = await response.json()
        token = reply.get("id_token")
        if not isinstance(token, str) or len(token) > 16_384:
            raise ProviderError
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(key_id, str) or not 1 <= len(key_id) <= 128:
            raise ProviderError
        key = await self._key(provider, key_id)
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=provider.client_id, issuer=provider.issuers,
                            leeway=CLOCK_LEEWAY_S, options={"require": ["iss", "aud", "exp", "nonce", "sub"]})
        azp = claims.get("azp")
        if ((azp is not None and azp != provider.client_id)
                or (isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and azp != provider.client_id)):
            raise ProviderError
        nonce, sub = claims["nonce"], claims["sub"]
        if (not isinstance(nonce, str) or not nonce.isascii() or not hmac.compare_digest(nonce, state["nonce"])
                or not isinstance(sub, str) or not 1 <= len(sub) <= 255):
            raise ProviderError
        return subject_hash(self.config.secret, name, sub)

    async def callback(self, req):
        name = req.match_info["provider"]
        provider = self.config.providers.get(name)
        state = _open(self.config.secret, req.cookies.get(STATE_COOKIE), name, req.query.get("state"))
        if state is None:
            return _release_state(web.HTTPFound("/?loginError=auth_state"))
        code = req.query.get("code")
        if provider is None or not code or len(code) > 512 or "error" in req.query:
            return _release_state(web.HTTPFound("/?loginError=auth_provider"))
        try:
            async with asyncio.timeout(10):
                digest = await self._exchange(req, provider, name, code, state)
        except (aiohttp.ClientError, TimeoutError, jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError):
            return _release_state(web.HTTPFound("/?loginError=auth_provider"))
        raw = token_urlsafe(32)
        async with req.app[POOL].connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT id,status FROM pet.members WHERE provider=%s AND sub_hash=%s FOR UPDATE", (name, digest),
            )
            member = await cur.fetchone()
            if member and member["status"] == "minor_locked":
                return _release_state(web.HTTPFound("/?loginError=underage"))
            if member and member["status"] != "active":
                return _release_state(web.HTTPFound("/?loginError=auth_provider"))
            life = MEMBER if member else PENDING
            await conn.execute(
                """INSERT INTO pet.sessions(token_hash,kind,member_id,provider,sub_hash,expires_at,absolute_expires_at)
                VALUES (%s,%s,%s,%s,%s,now()+%s,now()+%s)""",
                (cookie_hash(raw), "member" if member else "pending", member["id"] if member else None, name,
                 None if member else digest, life, MEMBER_MAX if member else PENDING),
            )
            if member:
                await sync_defaults(conn, member["id"])
                await conn.execute("UPDATE pet.members SET last_login_at=now() WHERE id=%s", (member["id"],))
        reply = _release_state(web.HTTPFound("/" if member else "/signup"))
        set_session_cookie(reply, raw, int(life.total_seconds()))
        return reply


async def _start(req):
    return await req.app[AUTH].start(req)


async def _callback(req):
    return await req.app[AUTH].callback(req)


async def _logout(req):
    await require_member(req)
    async with req.app[POOL].connection() as conn:
        await conn.execute("DELETE FROM pet.sessions WHERE token_hash=%s", (req["session_hash"],))
    response = web.Response(status=204)
    set_session_cookie(response, "", 0)
    return response


def register(app, config):
    async def clients(app):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
            app[AUTH] = Auth(config, http)
            yield

    app.cleanup_ctx.append(clients)
    app.router.add_get(r"/api/auth/{provider:kakao|google}/start", _start, allow_head=False)
    app.router.add_get(r"/api/auth/{provider:kakao|google}/callback", _callback, allow_head=False)
    app.router.add_post("/api/auth/logout", _logout)
