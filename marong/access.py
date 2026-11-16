"""Cloudflare Access sign-in check for the bot's in-app chat (docs/app-chat.md SPEC-111).

The same rules as the call server's identity() (tools/vertex_live/server.py): an RS256 token signed by one of the
team's published keys, the application audience, the team as issuer, exp/iat/sub/email present and the email on an
exact allowlist. Only the sha256 of the lowercased email leaves this module: never the email or the token.
"""
import asyncio
from dataclasses import dataclass
import hashlib
import logging
import os
import re
import time

import httpx
import jwt

log = logging.getLogger("marong.access")
TEAM = re.compile(r"[a-z0-9-]+\.cloudflareaccess\.com")
TOKEN_MAX = 16_000
KEYS_TTL_S = 3600        # Access rotates its keys every 6 weeks and publishes the next one early
KEYS_RETRY_S = 300       # an unknown key id fetches the keys again, at most this often
CERTS_TIMEOUT_S = 10


@dataclass(frozen=True)
class AccessConfig:
    team: str               # <team>.cloudflareaccess.com
    aud: str                # the Access application's audience tag
    emails: frozenset       # lowercased allowlist

    @classmethod
    def from_env(cls, env=os.environ) -> "AccessConfig | None":
        """None unless all three values are set and the team domain has the Access form (SPEC-110)."""
        team = env.get("CF_ACCESS_TEAM_DOMAIN", "").strip().removeprefix("https://").rstrip("/")
        aud = env.get("CF_ACCESS_AUD", "").strip()
        emails = frozenset(v.strip().lower() for v in env.get("CF_ACCESS_EMAILS", "").split(",") if v.strip())
        if not TEAM.fullmatch(team) or not aud or not emails:
            return None
        return cls(team, aud, emails)


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


class AccessVerifier:
    """check(token) -> ("ok", email sha256) | ("not_allowed", None) | ("unauthenticated", None)."""

    def __init__(self, config: AccessConfig, http: httpx.AsyncClient | None = None, clock=time.time):
        self.c = config
        self.http = http
        self.clock = clock
        self.keys: list[dict] = []
        self.expires = 0.0
        self.fetched = 0.0
        self.lock = asyncio.Lock()  # one key fetch at a time; the others use its result

    async def _fetch(self) -> None:
        own = self.http is None
        http = self.http or httpx.AsyncClient(timeout=CERTS_TIMEOUT_S)
        try:
            r = await http.get(f"https://{self.c.team}/cdn-cgi/access/certs", timeout=CERTS_TIMEOUT_S)
            r.raise_for_status()
            keys = r.json()["keys"]
            if not isinstance(keys, list):
                raise ValueError("keys")
            self.keys = [k for k in keys if isinstance(k, dict)]
            now = self.clock()
            self.expires, self.fetched = now + KEYS_TTL_S, now
        finally:
            if own:
                await http.aclose()

    async def _key(self, kid) -> dict | None:
        async with self.lock:
            if self.expires < self.clock():
                await self._fetch()
            key = next((k for k in self.keys if k.get("kid") == kid), None)
            if key is None and self.clock() - self.fetched > KEYS_RETRY_S:
                await self._fetch()  # a key published after the last fetch
                key = next((k for k in self.keys if k.get("kid") == kid), None)
            return key

    async def check(self, token: str) -> tuple[str, str | None]:
        """unavailable: Access's key list could not be read (the client retries later instead of signing in again)."""
        if not token or len(token) > TOKEN_MAX:
            return "unauthenticated", None
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                return "unauthenticated", None
        except jwt.PyJWTError:
            return "unauthenticated", None
        try:
            key = await self._key(header.get("kid"))
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as e:
            log.warning("access_keys_unavailable %s", type(e).__name__)
            return "unavailable", None
        if not key:
            return "unauthenticated", None
        try:
            claims = jwt.decode(token, jwt.PyJWK.from_dict(key).key, algorithms=["RS256"], audience=self.c.aud,
                                issuer=f"https://{self.c.team}", options={"require": ["exp", "iat", "sub", "email"]})
            email = claims["email"]
            if not isinstance(email, str):
                return "unauthenticated", None
        except (jwt.PyJWTError, ValueError, KeyError, TypeError) as e:
            log.info("access_rejected %s", type(e).__name__)
            return "unauthenticated", None
        if email.strip().lower() not in self.c.emails:
            return "not_allowed", None
        return "ok", email_hash(email)
