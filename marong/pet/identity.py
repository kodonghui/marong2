"""First-payment identity verification using an injected provider (SPEC-313)."""

import asyncio
import hmac
from dataclasses import dataclass, field
from datetime import date

from .account import korea_today, me, min_age
from .http import POOL, Problem, body_json, require_member
from .log import logger


@dataclass(frozen=True)
class IdentityResult:
    birth_date: date = field(repr=False)
    ci: str = field(repr=False)


def register(app, verify, digest_key):
    async def identity(req):
        member = await require_member(req)
        body = await body_json(req)
        token = body.get("token")
        if (set(body) != {"token"} or not isinstance(token, str) or not 1 <= len(token) <= 500
                or not token.isascii() or not token.isprintable()):
            raise Problem("invalid_input")
        async with app[POOL].connection() as conn:
            cur = await conn.execute("SELECT identity_verified_at FROM pet.members WHERE id=%s", (member["id"],))
            prior = await cur.fetchone()
        if prior and prior["identity_verified_at"]:
            return await me(req)
        if verify is None or not isinstance(digest_key, bytes) or len(digest_key) < 32:
            raise Problem("identity_provider")
        today = korea_today()
        try:
            result = await asyncio.wait_for(verify(token, member["id"]), timeout=10)
            if (not isinstance(result, IdentityResult) or type(result.birth_date) is not date
                    or result.birth_date > today or not isinstance(result.ci, str) or not 1 <= len(result.ci) <= 500):
                raise ValueError("identity_result_invalid")
            digest = hmac.digest(digest_key, b"pet-ci\0" + result.ci.encode("utf-8"), "sha256")
        except Exception:
            logger.warning("pet_identity_provider_failed")
            raise Problem("identity_provider") from None

        minor = min_age(result.birth_date, today) < 19
        async with app[POOL].connection() as conn, conn.transaction():
            cur = await conn.execute("""
                SELECT status,identity_verified_at FROM pet.members WHERE id=%s FOR UPDATE
            """, (member["id"],))
            current = await cur.fetchone()
            if not current or current["status"] != "active":
                raise Problem("unauthenticated")
            if current["identity_verified_at"]:
                minor = False
            elif minor:
                await conn.execute("UPDATE pet.members SET status='minor_locked',minor_locked_at=now() WHERE id=%s",
                                   (member["id"],))
                await conn.execute("DELETE FROM pet.sessions WHERE member_id=%s", (member["id"],))
                await conn.execute("""
                    INSERT INTO pet.jobs(kind,member_id,queued_at,run_after)
                    VALUES ('account_delete',%s,now()+interval '7 days',now()+interval '7 days')
                """, (member["id"],))
            else:
                await conn.execute("""
                    UPDATE pet.members SET identity_verified_at=now(),identity_ci_hash=%s WHERE id=%s
                """, (digest, member["id"]))
        if minor:
            req.pop("member", None)
            raise Problem("underage")
        return await me(req)

    app.router.add_post("/api/me/identity", identity)
