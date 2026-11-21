"""Access-protected account administration (SPEC-395)."""

import asyncio
from datetime import datetime, timedelta
import hmac
import re

from aiohttp import web

from .app_chat import Problem
from .app_session import one
from .diary import KST
from .decor import KINDS, SLOTS
from .pet.cost import month_bounds


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
        if self.chat.decor.catalog:
            response.body = response.body.replace(b"<!-- decor-items -->",
                '<a href="/chat/admin/items" class="btn2">아이템</a>'.encode("utf-8"))
        return response

    async def image_costs(self, req):
        await self.require_admin(req)
        start, end = month_bounds(datetime.now(KST))
        costs = await self.chat.store._one("""
            WITH diary AS (
                SELECT coalesce(sum(cost_usd),0) AS total,
                       coalesce(sum(cost_usd) FILTER (WHERE prompt_version<>'scene-v1'),0) AS metered
                FROM marong.diary_ai_runs WHERE kind='draw' AND sent_at >= %(start)s AND sent_at < %(end)s
            ), scenes AS (
                SELECT coalesce(sum(cost_usd) FILTER (WHERE purpose='topic'),0) AS topic,
                       coalesce(sum(cost_usd) FILTER (WHERE purpose='reaction'),0) AS reaction
                FROM marong.scene_pictures WHERE finished_at >= %(start)s AND finished_at < %(end)s
            ), characters AS (
                SELECT coalesce(sum(cost_usd),0) AS amount FROM marong.character_jobs
                WHERE finished_at >= %(start)s AND finished_at < %(end)s
            )
            SELECT diary.total AS diary, diary.metered AS diary_metered, scenes.topic, scenes.reaction,
                   characters.amount AS character FROM diary CROSS JOIN scenes CROSS JOIN characters
        """, {"start": start, "end": end})

        def budget(limit, spent):
            if limit is None:
                return None
            return {"limitUsd": round(float(limit), 2), "usedUsd": round(float(spent), 2),
                    "ratio": float(spent / limit) if limit else 0}

        return self.chat._json(200, {
            "month": start.strftime("%Y-%m"),
            "byKind": {name: round(float(costs[name]), 2) for name in ("diary", "topic", "reaction", "character")},
            "budgets": {
                "diary": budget(self.chat.pet_app_settings.diary_image_budget, costs["diary_metered"]),
                "character": budget(self.chat.characters.budget, costs["character"]),
            },
        })

    async def _decor_item_states(self, ident=None):
        rows = await self.chat.store._all("""
            SELECT d.id,d.state,count(o.item_id) AS owners FROM marong.decor_items d
            LEFT JOIN marong.decor_owned o ON o.item_id=d.id
            WHERE d.item_set=%s AND (%s::text IS NULL OR d.id=%s)
            GROUP BY d.id
        """, (self.chat.decor.catalog.set, ident, ident))
        return {row["id"]: row for row in rows}

    async def _item_description(self, item, row=None):
        missing = await asyncio.to_thread(self.chat.decor.catalog.check, item)
        return {"id": item.id, "kind": item.kind, "slot": SLOTS.get(item.kind),
                "name": str(item.name or "")[:20], "state": row["state"] if row else "new",
                "starter": item.starter is True, "owners": row["owners"] if row else 0, "missing": missing}

    async def decor_page(self, req):
        self.chat.decor.require_catalog()
        await self.require_admin(req)
        return self.chat.unified_page("admin-items")

    async def decor_items(self, req):
        catalog = self.chat.decor.require_catalog()
        await self.require_admin(req)
        states = await self._decor_item_states()
        return self.chat._json(200, {"set": catalog.set, "items": [
            await self._item_description(item, states.get(item.id))
            for item in catalog.items.values() if item.kind in KINDS
        ]})

    async def set_decor_listing(self, req):
        catalog = self.chat.decor.require_catalog()
        await self.require_admin(req, write=True)
        ident = self.chat.decor.item_key(req.match_info["itemId"])
        item = catalog.items.get(ident)
        if item is None:
            raise Problem("not_found")
        if req.match_info["action"] == "list":
            missing = await asyncio.to_thread(catalog.check, item)
            if missing:
                raise Problem("item_invalid", missing=missing)
            await self.chat.store._one("""
                INSERT INTO marong.decor_items(id,item_set,kind,slot,starter)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE
                SET state='listed',listed_at=now(),unlisted_at=NULL
                WHERE marong.decor_items.state='unlisted' RETURNING id
            """, (ident, catalog.set, item.kind, item.slot, item.starter))
        else:
            if item.starter:
                raise Problem("invalid_input")
            await self.chat.store._one("""
                UPDATE marong.decor_items SET state='unlisted',unlisted_at=now()
                WHERE id=%s AND item_set=%s AND state='listed' AND NOT starter RETURNING id
            """, (ident, catalog.set))
        state = (await self._decor_item_states(ident)).get(ident)
        if not state:
            raise Problem("not_found")
        return self.chat._json(200, await self._item_description(item, state))

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
        router.add_get(ADMIN_PATH + "/api/image-costs", self.image_costs)
        router.add_get(ADMIN_PATH + "/items", self.decor_page)
        router.add_get(ADMIN_PATH + "/api/items", self.decor_items)
        router.add_post(ADMIN_PATH + "/api/items/{itemId}/{action:list|unlist}", self.set_decor_listing)
        router.add_get(ADMIN_PATH + "/api/invites", self.list_invites)
        router.add_post(ADMIN_PATH + "/api/invites", self.create_invite)
        router.add_get(ADMIN_PATH + "/api/members", self.list_members)
        router.add_post(ADMIN_PATH + "/api/members/{friendId}/revoke", self.revoke)
        router.add_post(ADMIN_PATH + "/api/members/{friendId}/tickets", self.add_tickets)
