"""Access-protected account administration (SPEC-395)."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hmac
import logging
import math
import re

from aiohttp import web
from psycopg.errors import QueryCanceled

from .app_chat import Problem
from .app_release import utc_timestamp, version_parts
from .app_session import one
from .diary import KST
from .decor import KINDS, SLOTS
from .pet.cost import month_bounds as picture_month_bounds
from .usage import effective_limits, month_bounds, usage_day


HASH = re.compile(r"[a-f0-9]{64}")
FRIEND_ID = re.compile(r"[0-9]{1,19}")
ADMIN_PATH = "/chat/admin"
TABS = {
    "overview": (f"{ADMIN_PATH}/", "개요"),
    "members": (f"{ADMIN_PATH}/members", "회원"),
    "invites": (f"{ADMIN_PATH}/invites", "초대 링크"),
    "app": (f"{ADMIN_PATH}/app", "앱 버전"),
    "costs": (f"{ADMIN_PATH}/costs", "비용"),
    "items": (f"{ADMIN_PATH}/items", "아이템"),
}
USD = re.compile(r"[0-9]{1,4}(?:\.[0-9]{1,2})?")
log = logging.getLogger(__name__)


def usd(value):
    return format(value, ".2f") if value is not None else None


def limit_amounts(daily, monthly):
    return {"dailyUnits": daily, "callMonthlyUsd": usd(monthly)}


def positive_id(raw):
    return int(raw) if FRIEND_ID.fullmatch(raw) and 0 < int(raw) <= 2**63 - 1 else None


def admin_invite(row):
    def iso(key):
        value = row[key]
        return value.isoformat() if value is not None else None

    return {"id": row["id"], "kind": row["kind"], "note": row["note"], "state": row["state"],
            "expiresAt": iso("expires_at"), "createdAt": iso("created_at"), "usedAt": iso("used_at"),
            "revokedAt": iso("revoked_at"), "usedBy": {"friendId": row["used_by"], "name": row["name"]}
            if row["used_by"] is not None else None}


def overview_attention(now, members, call, images, app, expiring):
    items = []

    def add(kind, destination, level="warn", value=None):
        item = {"kind": kind, "level": level, "target": f"{ADMIN_PATH}/{destination}"}
        if value is not None:
            item["value"] = value
        items.append(item)

    if call and call["state"] != "ok":
        add("call_budget", "costs", "warn" if call["state"] == "warn" else "danger", call["percent"])
    if images and images["budgetPercent"] is not None and images["budgetPercent"] >= 80:
        percent = images["budgetPercent"]
        add("image_budget", "costs", "danger" if percent >= 100 else "warn", percent)
    if app and app["paused"]:
        add("app_paused", "app")
    elif app and app["latest"]:
        past_grace_period = now - utc_timestamp(app["latest"]["publishedAt"]) >= timedelta(hours=24)
        needing_attention = 0
        danger = False
        for phone in app["devices"]:
            if phone["behind"]:
                state = next((event["state"] for event in phone["events"] if event["kind"] == "state"), None)
                urgent = state in ("needs_confirm", "failed")
                needing_attention += urgent or past_grace_period
                danger |= urgent
        if needing_attention:
            add("app_behind", "app", "danger" if danger else "warn", needing_attention)
    if expiring:
        add("invite_expiring", "invites", value=expiring)
    if members["unlinked"]:
        add("unlinked_friend", "members", value=members["unlinked"])
    return items


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

    async def app_versions(self, req):
        """API-267: read the release history and the current owners' device records."""
        await self.require_admin(req)
        return self.chat._json(200, await self.read_app_versions())

    async def read_app_versions(self, conn=None):
        releases = self.chat.releases

        def read_releases():
            return releases.manifest(), releases.paused(), releases.history()

        latest, paused, history = await asyncio.to_thread(read_releases)
        devices = await self.chat.store.admin_app_devices(conn=conn)
        fetches = await self.chat.store.admin_app_fetches(conn=conn)
        current = version_parts(latest.name) if latest else None
        ordered = sorted(reversed(history), key=lambda entry: utc_timestamp(entry["at"]), reverse=True)
        return {
            "latest": {"versionCode": latest.code, "versionName": latest.name,
                       "publishedAt": latest.published_at} if latest else None,
            "paused": paused,
            "releases": [{key: value for key, value in entry.items() if key != "file"} for entry in ordered],
            "devices": [{"friend": row["friend"], "friendId": row["friend_id"], "phone": row["phone"],
                         "appVersion": row["app_version"], "seenAt": row["seen_at"].isoformat(),
                         "notifications": row["notifications"], "events": row["events"],
                         "behind": current is not None and version_parts(row["app_version"]) < current}
                        for row in devices],
            "fetches": [{"friend": row["friend"], "friendId": row["friend_id"], "items": row["items"]}
                        for row in fetches],
        }

    @staticmethod
    async def _overview_read(conn, read, *args):
        async with asyncio.timeout(1), conn.transaction():
            await conn.execute("SET LOCAL statement_timeout = '1s'")
            return await read(conn, *args)

    async def _overview_part(self, conn, part, read, *args):
        try:
            return await self._overview_read(conn, read, *args)
        except Exception:
            log.warning("admin_overview part=%s result=failed", part)
            return None

    async def overview(self, req):
        await self.require_admin(req)
        now = self.chat.sessions.now()
        async with self.chat.store.pool.connection(timeout=2) as conn:
            try:
                members = await self._overview_read(conn, self._overview_members)
            except QueryCanceled:
                raise Problem("db_unavailable") from None
            call = await self._overview_part(conn, "call", self._overview_call, now)
            images = await self._overview_part(conn, "images", self._overview_images, now)
            app = await self._overview_part(conn, "app", self._overview_app)
            usage = await self._overview_part(conn, "usage", self._overview_usage, now)
            expiring = await self._overview_part(conn, "invites", self._overview_invites, now)

        return self.chat._json(200, {
            "members": members, "callMonth": call, "images": images, "usageToday": usage,
            "attention": overview_attention(now, members, call, images, app, expiring),
            "app": {"latest": app["latest"], "paused": app["paused"], "devices": len(app["devices"]),
                    "behind": sum(phone["behind"] for phone in app["devices"])} if app is not None else None,
        })

    async def _overview_members(self, conn):
        return await one(conn, """
            SELECT count(p.friend_id) AS count, count(*) FILTER (WHERE p.friend_id IS NULL) AS unlinked
            FROM marong.friends f LEFT JOIN marong.friend_profiles p ON p.friend_id=f.id
        """)

    async def _overview_call(self, conn, now):
        start, end = month_bounds(now.astimezone(timezone.utc))
        row = await one(conn, "SELECT * FROM call.month_budget(%s,%s)", (start, end))
        spent, budget = row["spent_usd"], row["budget_usd"]
        if budget <= 0:
            raise ValueError("nonpositive call budget")
        percent = math.floor(spent * 100 / budget)
        state = "ok"
        for threshold, name in ((80, "warn"), (100, "exhausted"), (120, "hard_stop")):
            if spent * 100 >= budget * threshold:
                state = name
        return {"month": start.strftime("%Y-%m"), "spentUsd": usd(spent), "budgetUsd": usd(budget),
                "percent": percent, "state": state}

    async def _overview_images(self, conn, now):
        images = await self.read_image_costs(conn, now)
        ratios = [Decimal(str(budget["ratio"])) for budget in images["budgets"].values() if budget is not None]
        total = sum(Decimal(str(cost)) for cost in images["byKind"].values())
        return {"month": images["month"], "totalUsd": usd(total),
                "budgetPercent": math.floor(max(ratios) * 100) if ratios else None}

    async def _overview_app(self, conn):
        reader = getattr(self, "read_app_versions", None)
        return await reader(conn) if reader else None

    async def _overview_usage(self, conn, now):
        day = usage_day(now)
        totals = await one(conn, """
            SELECT coalesce(sum(u.chat_turns),0) AS "chatTurns",
                   coalesce(sum(u.call_seconds),0) AS "callSeconds",
                   coalesce(sum(u.images),0) AS images, coalesce(sum(u.units),0) AS units
            FROM marong.friend_profiles p JOIN marong.usage_daily u ON u.friend_id=p.friend_id AND u.day=%s
        """, (day,))
        return {"day": day.isoformat(), **totals}

    async def _overview_invites(self, conn, now):
        row = await one(conn, """
            SELECT count(*) FROM marong.invites
            WHERE used_at IS NULL AND revoked_at IS NULL AND expires_at>%s AND expires_at<=%s
        """, (now, now + timedelta(hours=24)))
        return row["count"]

    async def page(self, req):
        try:
            await self.require_admin(req)
        except Problem as error:
            if error.code != "not_allowed" or "text/html" not in req.headers.get("Accept", ""):
                raise
            return self.page_status(403, "관리자만 볼 수 있어요")

        path = req.path
        if path == ADMIN_PATH:
            raise web.HTTPMovedPermanently(location=f"{ADMIN_PATH}/")
        canonical = path[:-1] if path != TABS["overview"][0] and path.endswith("/") else path
        tab = next((key for key, (href, _) in TABS.items() if href == canonical), None)
        if tab is None and canonical.rpartition("/")[0] == TABS["members"][0]:
            if positive_id(canonical.rpartition("/")[2]) is not None:
                tab = "members"
        if tab is None:
            return self.page_status(404, "없는 화면이에요", '<a href="/chat/admin/">개요로</a>')
        if path != canonical:
            raise web.HTTPMovedPermanently(location=req.rel_url.with_path(canonical, keep_query=True))
        if tab == "items":
            self.chat.decor.require_catalog()
        response = self.chat.unified_page("admin-items" if tab == "items" else "admin")
        links = []
        for key, (href, label) in TABS.items():
            current = ' aria-current="page"' if key == tab else ""
            links.append(f'<a href="{href}"{current}>{label}</a>')
        nav = '<nav class="admin-nav" aria-label="마롱이 관리"><div class="admin-tabs">' + "".join(links) + "</div></nav>"
        response.body = response.body.replace(b"<!-- admin-tabs -->", nav.encode("utf-8"))
        return response

    @staticmethod
    def page_status(status, message, action=""):
        return web.Response(status=status, content_type="text/html", text=f"""<!doctype html>
<html lang="ko" data-theme="night"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>마롱이 관리</title><link rel="stylesheet" href="/chat/chat.css">
<link rel="stylesheet" href="/chat/unified.css"></head>
<body><main class="unified admin-layout"><section class="stack">
<p>{message}</p>{action}</section></main></body></html>""")

    async def image_costs(self, req):
        await self.require_admin(req)
        async with self.chat.store.pool.connection() as conn:
            costs = await self.read_image_costs(conn, datetime.now(KST))
        return self.chat._json(200, costs)

    async def read_image_costs(self, conn, now):
        start, end = picture_month_bounds(now.astimezone(KST))
        costs = await one(conn, """
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

        return {
            "month": start.strftime("%Y-%m"),
            "byKind": {name: round(float(costs[name]), 2) for name in ("diary", "topic", "reaction", "character")},
            "budgets": {
                "diary": budget(self.chat.pet_app_settings.diary_image_budget, costs["diary_metered"]),
                "character": budget(self.chat.characters.budget, costs["character"]),
            },
        }

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
                SELECT i.id,i.kind,i.note,i.expires_at,i.created_at,i.used_at,i.revoked_at,i.used_by,f.name,
                       CASE WHEN i.used_at IS NOT NULL THEN 'used' WHEN i.revoked_at IS NOT NULL THEN 'revoked'
                            WHEN i.expires_at<=%s THEN 'expired' ELSE 'open' END AS state
                FROM marong.invites i LEFT JOIN marong.friends f ON f.id=i.used_by
                ORDER BY i.created_at DESC,i.id DESC LIMIT 100
            """, (self.chat.sessions.now(),))).fetchall()
        return self.chat._json(200, {"invites": [admin_invite(row) for row in rows]})

    async def revoke_invite(self, req):
        await self.require_admin(req, write=True)
        invite = positive_id(req.match_info["inviteId"])
        if invite is None:
            raise Problem("not_found", title="찾지 못함")
        now = self.chat.sessions.now()
        async with self.chat.store.pool.connection() as conn, conn.transaction():
            row = await one(conn, """
                UPDATE marong.invites SET revoked_at=%s
                WHERE id=%s AND used_at IS NULL AND revoked_at IS NULL AND expires_at>%s
                RETURNING id, kind, note, expires_at, created_at, used_at, revoked_at, used_by,
                          NULL AS name
            """, (now, invite, now))
            if row is None:
                row = await one(conn, """
                    SELECT i.id,i.kind,i.note,i.expires_at,i.created_at,i.used_at,i.revoked_at,i.used_by,f.name
                    FROM marong.invites i LEFT JOIN marong.friends f ON f.id=i.used_by WHERE i.id=%s
                """, (invite,))
        if row is None:
            log.info("admin_invite_revoke invite=%d result=missing", invite)
            raise Problem("not_found", title="찾지 못함")
        if row["revoked_at"] is None:
            log.info("admin_invite_revoke invite=%d result=closed", invite)
            raise Problem("invite_closed")
        log.info("admin_invite_revoke invite=%d result=revoked", invite)
        return self.chat._json(200, {"invite": admin_invite({**row, "state": "revoked"})})

    async def list_members(self, req):
        await self.require_admin(req)
        now = self.chat.sessions.now()
        day = usage_day(now)
        async with self.chat.store.pool.connection() as conn:
            rows = await (await conn.execute("""
                SELECT f.id,f.name,p.friend_id AS profile_id,p.bot_name,p.tickets,s.sessions,s.last_seen,
                       p.usage_unlimited,p.daily_units,p.call_monthly_usd,
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
        month_costs = await self.month_costs([r["id"] for r in rows if r["profile_id"] is not None], now)
        for r in rows:
            member = {"friendId": r["id"], "name": r["name"]}
            if r["profile_id"] is None:
                unlinked.append(member)
            else:
                last_seen = r["last_seen"]
                members.append({**member, "botName": r["bot_name"], "sessions": r["sessions"], "tickets": r["tickets"],
                                "lastSeenAt": last_seen.isoformat() if last_seen else None,
                                **self.limit_status(r), "callMonthUsd": usd(month_costs.get(r["id"])),
                                "usageToday": {
                                    "chatTurns": r["chat_turns"], "callSeconds": r["call_seconds"],
                                    "images": r["images"], "units": r["units"],
                                }})
        return self.chat._json(200, {"members": members, "unlinked": unlinked,
                                     "defaults": limit_amounts(self.chat.usage.limit, self.chat.usage.call_limit)})

    async def month_costs(self, friends, now):
        if not friends:
            return {}
        start, end = month_bounds(now.astimezone(timezone.utc))
        try:
            async with asyncio.timeout(1), self.chat.store.pool.connection() as conn:
                rows = await (await conn.execute("""
                    SELECT friend, call.friend_month_usd(friend,%s,%s) AS usd
                    FROM unnest(%s::bigint[]) AS ids(friend)
                """, (start, end, friends))).fetchall()
            return {row["friend"]: row["usd"] for row in rows}
        except Exception:
            log.warning("admin_call_month_unknown")
            return {}

    def limit_status(self, row):
        daily, monthly = row["daily_units"], row["call_monthly_usd"]
        mode = "unlimited" if row["usage_unlimited"] else (
            "custom" if daily is not None or monthly is not None else "default")
        effective = effective_limits(row, self.chat.usage.limit, self.chat.usage.call_limit)
        return {"limits": {"mode": mode, **limit_amounts(daily, monthly)}, "effective": limit_amounts(*effective)}

    @staticmethod
    def friend_id(req):
        friend = positive_id(req.match_info["friendId"])
        if friend is None:
            raise Problem("invalid_input")
        return friend

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

    async def set_limits(self, req):
        await self.require_admin(req, write=True)
        friend = self.friend_id(req)
        body = await self.chat._session_body(req, "mode", ("dailyUnits", "callMonthlyUsd"))
        mode = body["mode"]
        daily = monthly = None
        if mode == "custom":
            if len(body) == 1:
                raise Problem("invalid_input")
            if "dailyUnits" in body:
                daily = body["dailyUnits"]
                if type(daily) is not int or not 1 <= daily <= 100000:
                    raise Problem("invalid_input")
            if "callMonthlyUsd" in body:
                raw = body["callMonthlyUsd"]
                if not isinstance(raw, str) or not USD.fullmatch(raw):
                    raise Problem("invalid_input")
                monthly = Decimal(raw)
                if not Decimal("0.01") <= monthly <= 1000:
                    raise Problem("invalid_input")
        elif mode not in ("unlimited", "default") or len(body) != 1:
            raise Problem("invalid_input")
        unlimited = mode == "unlimited"
        row = await self.chat.store._one("""
            UPDATE marong.friend_profiles SET
                usage_unlimited=%s, daily_units=%s, call_monthly_usd=%s,
                updated_at=CASE WHEN (usage_unlimited,daily_units,call_monthly_usd) IS DISTINCT FROM
                    (%s, %s::integer, %s::numeric) THEN now() ELSE updated_at END
            WHERE friend_id=%s
            RETURNING usage_unlimited,daily_units,call_monthly_usd
        """, (unlimited, daily, monthly, unlimited, daily, monthly, friend))
        if row is None:
            raise Problem("not_found")
        log.info("admin_limits friend=%d mode=%s", friend, mode)
        return self.chat._json(200, self.limit_status(row))

    def register(self, router):
        router.add_get(ADMIN_PATH, self.page)
        router.add_get(ADMIN_PATH + "/{path:(?!api(?:/|$)).*}", self.page)
        router.add_get(ADMIN_PATH + "/api/overview", self.overview)
        router.add_get(ADMIN_PATH + "/api/image-costs", self.image_costs)
        router.add_get(ADMIN_PATH + "/api/items", self.decor_items)
        router.add_post(ADMIN_PATH + "/api/items/{itemId}/{action:list|unlist}", self.set_decor_listing)
        router.add_get(ADMIN_PATH + "/api/invites", self.list_invites)
        router.add_post(ADMIN_PATH + "/api/invites", self.create_invite)
        router.add_post(ADMIN_PATH + "/api/invites/{inviteId}/revoke", self.revoke_invite)
        router.add_get(ADMIN_PATH + "/api/members", self.list_members)
        router.add_post(ADMIN_PATH + "/api/members/{friendId}/revoke", self.revoke)
        router.add_post(ADMIN_PATH + "/api/members/{friendId}/tickets", self.add_tickets)
        router.add_put(ADMIN_PATH + "/api/members/{friendId}/limits", self.set_limits)
