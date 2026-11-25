"""Tables of the Marong app (marong/migrations/014_app_chat.sql, 015_app_ring.sql): signed-in friends, their phones,
in-app chat history and the calls Marong places at a time a friend set. Mixed into DiscordStore (self._one, _all,
pool, _call_guard), like ScheduleStore and GoogleStore."""
from datetime import timedelta
import logging

import psycopg
from psycopg import errors

from .app_release import version_parts

DEVICE_FRESH = timedelta(days=30)       # a phone that has not reported for longer gets nothing (SPEC-116)
RING_GAP = timedelta(minutes=10)        # no new ring this soon after the last one (REQ-132)
RECENT = timedelta(seconds=60)          # the wait also returns messages this recent (late commits, SPEC-114)
APP_KEY = "app:"                        # kakao_id of a message sent from the in-app chat (SPEC-112)
log = logging.getLogger("marong.app")

MESSAGE_COLUMNS = """m.id, m.role, m.content, m.created_at, m.kakao_id, m.meta, m.reply_to,
       (SELECT q.kakao_id FROM marong.messages q WHERE q.id = m.reply_to) AS reply_key"""


class AppDeviceLimit(Exception):
    """This friend's recent device slots are all occupied (D134)."""


class AppStore:
    # ── sign-in and phones ─────────────────────────────────────

    async def app_login(self, email_sha256: str) -> dict | None:
        """The call friend behind an Access email hash, with their Discord DM link (its fields are NULL when the
        friend has no verified DM link). None: not a call friend."""
        from .discord_store import DM_STATE  # discord_store mixes this class in
        return await self._one(
            "SELECT c.id AS caller_id, c.friend_id, c.enabled, f.name, d.discord_user_id, d.room_key, d.user_key, "
            "       d.channel_id "
            "FROM call.caller_logins l JOIN call.callers c ON c.id = l.caller_id "
            "JOIN marong.friends f ON f.id = c.friend_id "
            "LEFT JOIN (" + DM_STATE + ") d ON d.friend_id = c.friend_id "
            "WHERE l.email_sha256 = %s", (email_sha256,))

    async def app_device_put(self, install_id: str, friend_id: int, fid: str | None, notifications: str,
                             app_version: str, ring_channel: str | None, full_screen: str | None,
                             *, published: dict[int, str] | None = None, update: dict | None = None) -> bool:
        """Add or update a phone (SPEC-115). Another phone row with the same FID loses it; an install id seen with
        another friend moves to this one. True when the row is new."""
        async with self.pool.connection() as c:
            async with c.transaction():
                # A phone can change friend, so serialize reports for the installation as well as the destination.
                for lock in (f"marong.app-install:{install_id}", f"marong.app-devices:{friend_id}"):
                    await c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock,))
                before = await (await c.execute(
                    "SELECT friend_id, app_version, seen_at > now() - %s AS fresh FROM marong.app_devices "
                    "WHERE install_id = %s", (DEVICE_FRESH, install_id))).fetchone()
                if not before or before["friend_id"] != friend_id or not before["fresh"]:
                    cur = await c.execute("SELECT count(*) AS recent FROM marong.app_devices "
                                          "WHERE friend_id = %s AND seen_at > now() - %s", (friend_id, DEVICE_FRESH))
                    if (await cur.fetchone())["recent"] >= 20:
                        raise AppDeviceLimit
                if fid:
                    await c.execute("UPDATE marong.app_devices SET fid = NULL WHERE fid = %s AND install_id <> %s",
                                    (fid, install_id))
                cur = await c.execute(
                    "INSERT INTO marong.app_devices AS d (install_id, friend_id, fid, notifications, app_version, "
                    "  ring_channel, full_screen) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (install_id) DO UPDATE SET friend_id = EXCLUDED.friend_id, fid = EXCLUDED.fid, "
                    "  notifications = EXCLUDED.notifications, app_version = EXCLUDED.app_version, seen_at = now(), "
                    "  dropped_at = NULL, ring_channel = EXCLUDED.ring_channel, full_screen = EXCLUDED.full_screen "
                    "RETURNING (xmax = 0) AS created",
                    (install_id, friend_id, fid, notifications, app_version, ring_channel, full_screen))
                created = (await cur.fetchone())["created"]
                if published is not None:
                    await self._app_update_report(c, friend_id, install_id, before, app_version, published, update)
                return created

    async def _app_update_report(self, conn, friend_id, install_id, before, app_version, published, update):
        state = update["state"] if update else None
        if state and state != "installed":
            code = update["versionCode"]
            if code in published:
                await self._app_update_event(conn, "state", friend_id, install_id, code,
                                             state=state, status=update.get("status"))
            else:
                log.info("app_update record skipped reason=unknown_version")
        if before and version_parts(before["app_version"]) < version_parts(app_version):
            codes = [code for code, name in published.items() if name == app_version]
            if codes:
                reported_code = update["versionCode"] if state == "installed" else None
                code = reported_code if reported_code in codes else max(codes)
                await self._app_update_event(conn, "installed", friend_id, install_id, code, app_version=app_version)

    async def _app_update_event(self, conn, kind, friend_id, install_id, code, *, app_version=None, state=None, status=None):
        try:
            # A failed audit write must leave the phone report in the outer transaction intact.
            async with conn.transaction():
                if kind == "state":
                    rows = await conn.execute("""
                        SELECT state, status FROM marong.app_update_events WHERE kind = 'state'
                            AND install_id = %s AND version_code = %s
                        ORDER BY at DESC, id DESC LIMIT 1
                    """, (install_id, code))
                    if await rows.fetchone() == {"state": state, "status": status}:
                        log.info("app_update record skipped reason=duplicate")
                        return
                rows = await conn.execute("""
                    SELECT count(*) AS recent FROM marong.app_update_events
                    WHERE friend_id = %s AND kind IN ('state', 'installed') AND at > now() - interval '1 hour'
                """, (friend_id,))
                if (await rows.fetchone())["recent"] >= 30:
                    log.info("app_update record skipped reason=rate_limit")
                    return
                await conn.execute("""
                    INSERT INTO marong.app_update_events (kind, friend_id, install_id, version_code, app_version, state, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                """, (kind, friend_id, install_id, code, app_version, state, status))
        except (psycopg.Error, TimeoutError):
            log.warning("app_update record failed kind=%s", kind)

    async def app_update_fetched(self, friend_id: int, code: int) -> None:
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                               (f"marong.app-fetched:{friend_id}:{code}",))
            await conn.execute("""
                INSERT INTO marong.app_update_events (kind, friend_id, version_code)
                SELECT 'fetched', %(friend)s, %(code)s WHERE NOT EXISTS (
                    SELECT FROM marong.app_update_events WHERE kind = 'fetched' AND friend_id = %(friend)s
                        AND version_code = %(code)s AND at > now() - interval '1 hour'
                )
            """, {"friend": friend_id, "code": code})

    async def app_devices(self, friend_id: int, install_id: str | None = None) -> list[dict]:
        """The friend's phones, last reported first. fresh: reported within 30 days."""
        return await self._all(
            "SELECT install_id::text AS install_id, fid, notifications, app_version, ring_channel, full_screen, "
            "  seen_at, dropped_at, seen_at > now() - %(fresh)s AS fresh "
            "FROM marong.app_devices WHERE friend_id = %(f)s AND (%(id)s::uuid IS NULL OR install_id = %(id)s::uuid) "
            "ORDER BY seen_at DESC LIMIT 20", {"f": friend_id, "id": install_id, "fresh": DEVICE_FRESH})

    async def drop_fid(self, install_id: str, fid: str) -> None:
        """FCM said this installation is gone: forget the FID (the app sends a new one when it opens again)."""
        await self._one("UPDATE marong.app_devices SET fid = NULL, dropped_at = now() "
                        "WHERE install_id = %s AND fid = %s RETURNING install_id", (install_id, fid))

    async def app_update_targets(self, code: int, version: tuple[int, ...], limit: int) -> list[dict]:
        return await self._all("""
            WITH recent AS (
                SELECT d.install_id, d.friend_id, d.fid, d.app_version, d.seen_at, d.dropped_at,
                       row_number() OVER (PARTITION BY d.friend_id ORDER BY d.seen_at DESC, d.install_id) AS rank
                FROM marong.app_devices d WHERE d.seen_at > now() - %(fresh)s
            )
            SELECT d.install_id, d.friend_id, d.fid, coalesce(p.attempt + 1, 1) AS attempt,
                   count(*) OVER () AS total
            FROM recent d
            LEFT JOIN LATERAL (
                SELECT attempt FROM marong.app_update_events
                WHERE install_id = d.install_id AND version_code = %(code)s AND kind = 'pushed'
                ORDER BY attempt DESC LIMIT 1
            ) p ON true
            LEFT JOIN marong.app_update_events failure
                ON failure.install_id = d.install_id AND failure.version_code = %(code)s
                AND failure.attempt = p.attempt AND failure.kind = 'push_failed'
            WHERE d.rank <= 20 AND d.fid IS NOT NULL AND d.dropped_at IS NULL
                AND string_to_array(d.app_version, '.')::int[] < %(version)s::int[]
                AND (p.attempt IS NULL OR (p.attempt < 3 AND failure.at <= now() - interval '10 minutes'))
            ORDER BY d.seen_at DESC, d.install_id LIMIT %(limit)s
        """, {"code": code, "version": list(version), "limit": limit, "fresh": DEVICE_FRESH})

    async def app_update_claim(self, target: dict, code: int, version: tuple[int, ...]) -> bool:
        row = await self._one("""
            INSERT INTO marong.app_update_events (kind, friend_id, install_id, version_code, attempt)
            SELECT 'pushed', friend_id, install_id, %(code)s, %(attempt)s FROM marong.app_devices
            WHERE install_id = %(install_id)s AND friend_id = %(friend_id)s AND fid = %(fid)s
                AND dropped_at IS NULL AND seen_at > now() - %(fresh)s
                AND string_to_array(app_version, '.')::int[] < %(version)s::int[]
            ON CONFLICT DO NOTHING RETURNING id
        """, {**target, "code": code, "version": list(version), "fresh": DEVICE_FRESH})
        return row is not None

    async def app_update_push_failed(self, target: dict, code: int, status: int) -> None:
        await self._one("""
            INSERT INTO marong.app_update_events (kind, friend_id, install_id, version_code, status, attempt)
            VALUES ('push_failed', %(friend_id)s, %(install_id)s, %(code)s, %(status)s, %(attempt)s)
            ON CONFLICT DO NOTHING RETURNING id
        """, {**target, "code": code, "status": status})

    async def admin_app_devices(self, *, conn=None) -> list[dict]:
        query = """
            WITH recent AS (
                SELECT install_id, friend_id, app_version, notifications, seen_at, created_at, dropped_at,
                       row_number() OVER (PARTITION BY friend_id ORDER BY seen_at DESC, install_id) AS rank
                FROM marong.app_devices WHERE seen_at > now() - interval '90 days'
            ), visible AS (
                SELECT d.*, f.name AS friend,
                       row_number() OVER (PARTITION BY d.friend_id ORDER BY d.created_at, d.install_id) AS phone
                FROM recent d JOIN marong.friends f ON f.id = d.friend_id WHERE d.rank <= 20
                ORDER BY f.name, d.friend_id, phone LIMIT 200
            )
            SELECT d.friend, d.friend_id, d.phone, d.app_version, d.seen_at, d.notifications, d.dropped_at,
                   coalesce(events.items, '[]'::jsonb) AS events
            FROM visible d
            LEFT JOIN LATERAL (
                SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                    'kind', kind, 'versionCode', version_code, 'appVersion', app_version,
                    'state', state, 'status', status, 'attempt', attempt, 'at', at
                )) ORDER BY at DESC, id DESC) AS items
                FROM (
                    SELECT id, kind, version_code, app_version, state, status, attempt, at
                    FROM marong.app_update_events WHERE install_id = d.install_id AND friend_id = d.friend_id
                    ORDER BY at DESC, id DESC LIMIT 20
                ) e
            ) events ON true
            ORDER BY d.friend, d.friend_id, d.phone
        """
        if conn is None:
            return await self._all(query)
        return await (await conn.execute(query)).fetchall()

    async def admin_app_fetches(self, *, conn=None) -> list[dict]:
        query = """
            WITH visible AS (
                SELECT f.id AS friend_id, f.name AS friend FROM marong.friends f
                WHERE EXISTS (SELECT FROM marong.app_update_events e WHERE e.friend_id = f.id
                              AND e.kind = 'fetched' AND e.at > now() - interval '90 days')
                ORDER BY f.name, f.id LIMIT 100
            )
            SELECT f.friend, f.friend_id, events.items
            FROM visible f
            CROSS JOIN LATERAL (
                SELECT jsonb_agg(jsonb_build_object('versionCode', version_code, 'at', at)
                                 ORDER BY at DESC, id DESC) AS items
                FROM (
                    SELECT id, version_code, at FROM marong.app_update_events WHERE friend_id = f.friend_id
                        AND kind = 'fetched' AND at > now() - interval '90 days'
                    ORDER BY at DESC, id DESC LIMIT 20
                ) e
            ) events
            ORDER BY f.friend, f.friend_id
        """
        if conn is None:
            return await self._all(query)
        return await (await conn.execute(query)).fetchall()

    # ── in-app chat history (API-102, API-104) ─────────────────

    async def app_message(self, room_key: str, kakao_id: str) -> dict | None:
        return await self._one("SELECT " + MESSAGE_COLUMNS + " FROM marong.messages m "
                               "WHERE m.room_key = %s AND m.kakao_id = %s", (room_key, kakao_id))

    def _shown(self, requested="%(room)s") -> str:
        # Marong's words that never reached the friend and memory deleted in a call (SPEC-113).
        return ("AND NOT (m.role = 'assistant' AND m.meta->>'delivered' = 'false') "
                + self._call_guard('message', 'm.id', 'm.room_key', requested))

    async def app_messages(self, room_key: str, before: int | None, limit: int) -> list[dict]:
        """Up to limit+1 messages of the DM room before `before`, newest first (the extra one says there is more)."""
        return await self._all(
            "SELECT " + MESSAGE_COLUMNS + " FROM marong.messages m WHERE m.room_key = %(room)s "
            "AND (%(before)s::bigint IS NULL OR m.id < %(before)s::bigint) " + self._shown()
            + "ORDER BY m.id DESC LIMIT %(n)s", {"room": room_key, "before": before, "n": limit + 1})

    async def app_messages_after(self, room_key: str, after: int) -> list[dict]:
        """Messages after `after`, and those of the last minute (a message whose id came first may commit later)."""
        return await self._all(
            "SELECT " + MESSAGE_COLUMNS + " FROM marong.messages m WHERE m.room_key = %(room)s "
            "AND (m.id > %(after)s OR m.created_at > now() - %(recent)s) " + self._shown()
            + "ORDER BY m.id LIMIT 100", {"room": room_key, "after": after, "recent": RECENT})

    async def app_answered(self, room_key: str) -> dict:
        """The friend's newest message in the DM room and the newest of their messages Marong answered: the largest
        reply_to of her last answers (an answer to a quick burst answers its last message, docs/app-chat.md
        SPEC-148). 0 when there is none."""
        row = await self._one(
            "SELECT (SELECT id FROM marong.messages WHERE room_key = %(room)s AND role = 'user' "
            "        ORDER BY id DESC LIMIT 1) AS newest, "
            "       (SELECT max(reply_to) FROM (SELECT reply_to FROM marong.messages WHERE room_key = %(room)s "
            "        AND role = 'assistant' AND reply_to IS NOT NULL ORDER BY id DESC LIMIT 20) a) AS answered",
            {"room": room_key})
        return {"newest": row["newest"] or 0, "answered": row["answered"] or 0}

    # ── calls Marong places (TBL-102) ──────────────────────────

    async def call_friend(self, friend_id: int) -> int | None:
        """The friend's caller id when calls are on for them (SPEC-128, SPEC-130 ③)."""
        row = await self._one("SELECT id FROM call.callers WHERE friend_id = %s AND enabled", (friend_id,))
        return row["id"] if row else None

    async def call_live(self, caller_id: int) -> bool:
        row = await self._one("SELECT EXISTS (SELECT 1 FROM call.calls WHERE caller_id = %s AND status = 'live' "
                              "AND deleted_at IS NULL) AS live", (caller_id,))
        return row["live"]

    async def recent_ring(self, friend_id: int) -> bool:
        """A ring (ringing, answered or missed) in the last ten minutes. Failed and skipped ones do not count."""
        row = await self._one(
            "SELECT EXISTS (SELECT 1 FROM marong.app_rings WHERE friend_id = %s AND status IN "
            "('ringing', 'answered', 'missed') AND created_at > now() - %s) AS recent", (friend_id, RING_GAP))
        return row["recent"]

    async def ring_add(self, schedule: dict, caller_id: int, via: str, status: str, answer_for: timedelta,
                       devices: int = 0) -> dict | None:
        """A new ring row. None when another ring of this friend is still ringing (one at a time, REQ-132)."""
        try:
            return await self._one(
                "INSERT INTO marong.app_rings (schedule_id, friend_id, caller_id, via, status, title, say, devices, "
                "  answer_until, resolved_at) VALUES (%(s)s, %(f)s, %(c)s, %(via)s, %(status)s, %(title)s, %(say)s, "
                "  %(devices)s, now() + %(answer)s, CASE WHEN %(status)s = 'ringing' THEN NULL ELSE now() END) "
                "RETURNING id::text AS id, via, status, answer_until",
                {"s": schedule["id"], "f": schedule["friend_id"], "c": caller_id, "via": via, "status": status,
                 "title": schedule["title"], "say": schedule["say"], "devices": devices, "answer": answer_for})
        except errors.UniqueViolation:
            return None

    async def ring_update(self, ring_id: str, *, devices: int | None = None, via: str | None = None,
                          answer_for: timedelta | None = None, failed: bool = False) -> bool:
        """Change a ring that is still ringing: the devices FCM accepted, the Discord path (via, a longer answer
        window) or failed. False when it is no longer ringing (answered or missed meanwhile)."""
        row = await self._one(
            "UPDATE marong.app_rings SET devices = coalesce(%(devices)s, devices), via = coalesce(%(via)s, via), "
            "  answer_until = CASE WHEN %(answer)s::interval IS NULL THEN answer_until ELSE now() + %(answer)s END, "
            "  status = CASE WHEN %(failed)s THEN 'failed' ELSE status END, "
            "  resolved_at = CASE WHEN %(failed)s THEN now() ELSE resolved_at END "
            "WHERE id = %(id)s::uuid AND status = 'ringing' RETURNING id",
            {"id": ring_id, "devices": devices, "via": via, "answer": answer_for, "failed": failed})
        return row is not None

    async def rings_missed(self, limit: int = 20, *, with_scenes=False) -> list[dict]:
        """Rings whose answer window passed become missed (SPEC-138). A call that answered first wins: the update
        only takes rows still ringing. reason: promise | hello (a hello call, docs/04-functional-spec/call-first.md
        SPEC-270), topic: its picture or None."""
        fields = (
            "coalesce(r.topic, (SELECT s.topic FROM marong.scene_pictures s "
            "WHERE s.id=r.scene_picture_id)) AS topic, r.scene_picture_id"
            if with_scenes else "r.topic"
        )
        return await self._all(
            "WITH due AS (SELECT id FROM marong.app_rings WHERE status = 'ringing' AND answer_until < now() "
            "  ORDER BY answer_until LIMIT %s FOR UPDATE SKIP LOCKED) "
            "UPDATE marong.app_rings r SET status = 'missed', resolved_at = now() FROM due "
            "WHERE r.id = due.id AND r.status = 'ringing' "
            f"RETURNING r.id::text AS id, r.friend_id, r.via, r.schedule_id, r.reason, {fields}", (limit,))
