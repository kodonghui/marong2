"""Access-protected account administration (SPEC-395)."""

from datetime import timedelta
import hmac
import re

from aiohttp import web

from .app_chat import Problem
from .app_session import one


HASH = re.compile(r"[a-f0-9]{64}")
FRIEND_ID = re.compile(r"[0-9]{1,19}")
ADMIN_PATH = "/chat/admin"


class AppAdmin:
    def __init__(self, chat, email_hash):
        self.chat = chat
        self.email_hash = email_hash if HASH.fullmatch(email_hash or "") else None

    async def require_admin(self, req, *, write=False):
        token = req.headers.get("Cf-Access-Jwt-Assertion", "")
        if not token or self.email_hash is None:
            raise Problem("not_allowed")
        status, email_hash = await self.chat.access.check(token)
        if status != "ok" or not email_hash or not hmac.compare_digest(self.email_hash, email_hash):
            raise Problem("not_allowed")
        if write:
            self.chat._require_app_origin(req)

    async def page(self, req):
        await self.require_admin(req)
        response = self.chat.unified_page("admin")
        characters = self.chat.characters
        if characters.enabled and characters.budget:
            async with self.chat.store.pool.connection() as conn:
                spent = await characters.spent(conn)
            percent = round(spent * 100 / characters.budget)
            display = f'<p class="caption">이번 달 그림 예산 사용률 {percent}%</p>'
            response.body = response.body.replace(b"<!-- image-budget -->", display.encode("utf-8"))
        return response

    async def create_invite(self, req):
        await self.require_admin(req, write=True)
        body = await self.chat._session_body(req, "kind", ("friendId", "note"))
        if body["kind"] == "join" and "friendId" in body:
            raise Problem("invalid_input")
        token, expires = await self.chat.sessions.create_invite(body["kind"], body.get("friendId"), body.get("note", ""))
        return self.chat._json(201, {"url": f"{self.chat.origin}/chat/join/{token}", "expiresAt": expires.isoformat()})

    async def list_invites(self, req):
        await self.require_admin(req)
        async with self.chat.store.pool.connection() as conn:
            rows = await (await conn.execute("""
                SELECT i.id,i.kind,i.note,i.expires_at,i.used_by,f.name,
                       CASE WHEN i.used_at IS NOT NULL THEN 'used' WHEN i.revoked_at IS NOT NULL THEN 'revoked'
                            WHEN i.expires_at<=%s THEN 'expired' ELSE 'open' END AS state
                FROM marong.invites i LEFT JOIN marong.friends f ON f.id=i.used_by
                ORDER BY i.created_at DESC,i.id DESC LIMIT 100
            """, (self.chat.sessions.now(),))).fetchall()
        return self.chat._json(200, {"invites": [
            {"id": r["id"], "kind": r["kind"], "note": r["note"], "state": r["state"],
             "expiresAt": r["expires_at"].isoformat(),
             "usedBy": {"friendId": r["used_by"], "name": r["name"]} if r["used_by"] is not None else None}
            for r in rows
        ]})

    async def list_members(self, req):
        await self.require_admin(req)
        now = self.chat.sessions.now()
        day = (now.astimezone(self.chat.tz) - timedelta(hours=4)).date()
        async with self.chat.store.pool.connection() as conn:
            rows = await (await conn.execute("""
                SELECT f.id,f.name,p.friend_id AS profile_id,p.bot_name,p.tickets,s.sessions,s.last_seen,
                       coalesce(u.chat_turns,0) AS chat_turns,coalesce(u.call_seconds,0) AS call_seconds,
                       coalesce(u.images,0) AS images,coalesce(u.units,0) AS units
                FROM marong.friends f
                LEFT JOIN marong.friend_profiles p ON p.friend_id=f.id
                LEFT JOIN marong.usage_daily u ON u.friend_id=f.id AND u.day=%s
                LEFT JOIN LATERAL (
                    SELECT count(*) AS sessions,max(last_seen_at) AS last_seen
                    FROM marong.app_sessions WHERE friend_id=f.id AND revoked_at IS NULL AND expires_at>%s
                ) s ON p.friend_id IS NOT NULL
                ORDER BY p.created_at NULLS LAST,f.id
            """, (day, now))).fetchall()
        members, unlinked = [], []
        for r in rows:
            member = {"friendId": r["id"], "name": r["name"]}
            if r["profile_id"] is None:
                unlinked.append(member)
            else:
                last_seen = r["last_seen"]
                members.append({**member, "botName": r["bot_name"], "sessions": r["sessions"], "tickets": r["tickets"],
                                "lastSeenAt": last_seen.isoformat() if last_seen else None, "usageToday": {
                                    "chatTurns": r["chat_turns"], "callSeconds": r["call_seconds"],
                                    "images": r["images"], "units": r["units"],
                                }})
        return self.chat._json(200, {"members": members, "unlinked": unlinked})

    @staticmethod
    def friend_id(req):
        raw = req.match_info["friendId"]
        if not FRIEND_ID.fullmatch(raw) or not 0 < int(raw) <= 2**63 - 1:
            raise Problem("invalid_input")
        return int(raw)

    async def revoke(self, req):
        await self.require_admin(req, write=True)
        friend = self.friend_id(req)
        now = self.chat.sessions.now()
        async with self.chat.store.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"marong.device-code:{friend}",))
            if not await one(conn, "SELECT friend_id FROM marong.friend_profiles WHERE friend_id=%s", (friend,)):
                raise Problem("not_found")
            await conn.execute("UPDATE marong.device_codes SET used_at=%s WHERE friend_id=%s AND used_at IS NULL",
                               (now, friend))
            await conn.execute("""
                UPDATE marong.app_sessions SET revoked_at=%s WHERE friend_id=%s AND revoked_at IS NULL AND expires_at>%s
            """, (now, friend, now))
        return web.Response(status=204)

    async def add_tickets(self, req):
        await self.require_admin(req, write=True)
        friend = self.friend_id(req)
        body = await self.chat._session_body(req, "add")
        add = body["add"]
        if type(add) is not int or not 1 <= add <= 1000:
            raise Problem("invalid_input")
        row = await self.chat.store._one("""
            UPDATE marong.friend_profiles SET tickets=tickets+%s,updated_at=now()
            WHERE friend_id=%s RETURNING tickets
        """, (add, friend))
        if row is None:
            raise Problem("not_found")
        return self.chat._json(200, {"tickets": row["tickets"]})

    def register(self, router):
        router.add_get(ADMIN_PATH + "/", self.page)
        router.add_get(ADMIN_PATH + "/api/invites", self.list_invites)
        router.add_post(ADMIN_PATH + "/api/invites", self.create_invite)
        router.add_get(ADMIN_PATH + "/api/members", self.list_members)
        router.add_post(ADMIN_PATH + "/api/members/{friendId}/revoke", self.revoke)
        router.add_post(ADMIN_PATH + "/api/members/{friendId}/tickets", self.add_tickets)
