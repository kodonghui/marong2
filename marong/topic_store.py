"""Tables of calls first and picture topics (marong/migrations/018_call_first.sql: TBL-125 topic_sends, TBL-126
topic_prefs, TBL-102 app_rings reason and topic). Mixed into DiscordStore (self._one, _all), like AppStore."""
from datetime import date, timedelta

from psycopg import errors

RANG = "('ringing', 'answered', 'missed')"   # rings that reached a phone (failed, busy and skipped never rang)
PREF_FIELDS = ("hello_call", "pictures")


class TopicStore:
    # ── topic rows (TBL-125) ───────────────────────────────────

    async def topic_history(self, friend_id: int, since: date) -> list[dict]:
        """The friend's topics from `since` (a Korean date), newest first."""
        return await self._all(
            "SELECT id, day, picture, kind, status, via, ring_id::text AS ring_id, answer FROM marong.topic_sends "
            "WHERE friend_id = %s AND day >= %s ORDER BY day DESC", (friend_id, since))

    async def topic_start(self, friend_id: int, day: date, picture: str) -> int | None:
        """Take the friend's topic of the day before anything is sent. None: this day already has one (SPEC-263)."""
        row = await self._one(
            "INSERT INTO marong.topic_sends (friend_id, day, picture, kind) VALUES (%s, %s, %s, 'text') "
            "ON CONFLICT (friend_id, day) DO NOTHING RETURNING id", (friend_id, day, picture))
        return row["id"] if row else None

    async def topic_call(self, topic_id: int, ring_id: str) -> None:
        """The hello call rang at least one phone (SPEC-266 ③)."""
        await self._one(
            "UPDATE marong.topic_sends SET kind = 'call', ring_id = %s::uuid, status = 'sent', via = 'app', "
            "sent_at = now() WHERE id = %s AND status = 'sending' RETURNING id", (ring_id, topic_id))

    async def topic_sent(self, topic_id: int, via: str) -> None:
        await self._one("UPDATE marong.topic_sends SET status = 'sent', via = %s, sent_at = now() "
                        "WHERE id = %s AND status = 'sending' RETURNING id", (via, topic_id))

    async def topic_failed(self, topic_id: int) -> None:
        await self._one("UPDATE marong.topic_sends SET status = 'failed' WHERE id = %s AND status = 'sending' "
                        "RETURNING id", (topic_id,))

    async def topic_noted(self, ring_id: str, via: str) -> None:
        """Where the note after a missed hello call went (SPEC-270)."""
        await self._one("UPDATE marong.topic_sends SET via = %s WHERE ring_id = %s::uuid RETURNING id", (via, ring_id))

    def _topic_message_room(self):
        return ("EXISTS (SELECT 1 FROM marong.discord_dm_links d "
                "WHERE d.room_key=m.room_key AND d.friend_id=o.friend_id)")

    def _topic_quiet_room(self):
        return "SELECT room_key,opted_in_at FROM marong.discord_dm_links WHERE friend_id=%(f)s"

    async def topic_answers(self, window: timedelta, limit: int = 50) -> list[str]:
        """Decide the answers of open topics (SPEC-275): a word from the friend in their DM or the in-app chat, a call
        they started or the hello call taken within `window` after the topic went out is 'answered', none by then is
        'none'. Rows that failed are never decided. Returns the answers decided now."""
        rows = await self._all(
            "WITH open AS (SELECT id, friend_id, sent_at, ring_id FROM marong.topic_sends "
            "  WHERE answer IS NULL AND status = 'sent' ORDER BY sent_at LIMIT %(n)s), "
            "found AS (SELECT o.id, o.sent_at, least("
            "  (SELECT min(m.created_at) FROM marong.messages m "
            "    WHERE " + self._topic_message_room() + " AND m.role = 'user' "
            "      AND m.created_at > o.sent_at AND m.created_at <= o.sent_at + %(w)s), "
            "  (SELECT min(c.started_at) FROM call.calls c JOIN call.callers k ON k.id = c.caller_id "
            "    WHERE k.friend_id = o.friend_id AND c.started_at > o.sent_at AND c.started_at <= o.sent_at + %(w)s), "
            "  (SELECT r.answered_at FROM marong.app_rings r WHERE r.id = o.ring_id AND r.status = 'answered' "
            "    AND r.answered_at <= o.sent_at + %(w)s)) AS at FROM open o) "
            "UPDATE marong.topic_sends t SET answer = CASE WHEN f.at IS NULL THEN 'none' ELSE 'answered' END, "
            "  answered_at = f.at FROM found f "
            "WHERE t.id = f.id AND t.answer IS NULL AND (f.at IS NOT NULL OR f.sent_at + %(w)s < now()) "
            "RETURNING t.answer", {"n": limit, "w": window})
        return [r["answer"] for r in rows]

    async def topic_quiet_days(self, friend_id: int, today: date, timezone: str) -> int:
        """Korean days before today on which only Marong reached out (SPEC-264): after the friend's last word (DM or
        in-app chat) or call start, or after they turned proactive messages on when they never spoke, a delivered
        proactive message or a hello call that rang."""
        row = await self._one(
            "WITH link AS (" + self._topic_quiet_room() + "), "
            "last AS (SELECT coalesce(greatest("
            "  (SELECT max(m.created_at) FROM marong.messages m JOIN link USING (room_key) WHERE m.role = 'user'), "
            "  (SELECT max(c.started_at) FROM call.calls c JOIN call.callers k ON k.id = c.caller_id "
            "    WHERE k.friend_id = %(f)s)), (SELECT opted_in_at FROM link)) AS at) "
            "SELECT count(DISTINCT day) AS days FROM ("
            "  SELECT (m.created_at AT TIME ZONE %(tz)s)::date AS day "
            "    FROM marong.messages m JOIN link USING (room_key) "
            "   WHERE m.role = 'assistant' AND m.meta->>'proactive' = 'true' AND m.meta->>'delivered' = 'true' "
            "     AND m.created_at > (SELECT at FROM last) "
            "  UNION ALL "
            "  SELECT (r.created_at AT TIME ZONE %(tz)s)::date FROM marong.app_rings r "
            "   WHERE r.friend_id = %(f)s AND r.reason = 'hello' AND r.status IN " + RANG + " "
            "     AND r.created_at > (SELECT at FROM last)) x WHERE day < %(today)s",
            {"f": friend_id, "tz": timezone, "today": today})
        return row["days"]

    # ── settings (TBL-126) ─────────────────────────────────────

    async def topic_prefs(self, friend_id: int) -> dict | None:
        return await self._one("SELECT hello_call, pictures, call_from, call_until, updated_at, updated_by "
                               "FROM marong.topic_prefs WHERE friend_id = %s", (friend_id,))

    async def topic_pref_set(self, friend_id: int, field: str, on: bool, by: str = "friend") -> None:
        """Turn hello calls or pictures on or off (SPEC-277, SPEC-279). The other values stay as they were."""
        if field not in PREF_FIELDS:
            raise ValueError(field)
        await self._one(
            f"INSERT INTO marong.topic_prefs (friend_id, {field}, updated_by) VALUES (%s, %s, %s) "
            f"ON CONFLICT (friend_id) DO UPDATE SET {field} = EXCLUDED.{field}, updated_at = now(), "
            "updated_by = EXCLUDED.updated_by RETURNING friend_id", (friend_id, on, by))

    async def topic_window_set(self, friend_id: int, start: int, end: int, by: str = "admin") -> None:
        await self._one(
            "INSERT INTO marong.topic_prefs (friend_id, call_from, call_until, updated_by) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (friend_id) DO UPDATE SET call_from = EXCLUDED.call_from, call_until = EXCLUDED.call_until, "
            "updated_at = now(), updated_by = EXCLUDED.updated_by RETURNING friend_id", (friend_id, start, end, by))

    # ── hello calls (TBL-102 reason 'hello') ───────────────────

    async def hello_last(self, friend_id: int) -> dict | None:
        """The friend's last hello call that rang (SPEC-265 ⑤)."""
        return await self._one(
            "SELECT created_at, status FROM marong.app_rings WHERE friend_id = %s AND reason = 'hello' "
            "AND status IN " + RANG + " ORDER BY created_at DESC LIMIT 1", (friend_id,))

    async def rings_recent(self, friend_id: int, within: timedelta) -> bool:
        """A ring that rang (any reason) or a call the friend started within `within` (SPEC-265 ⑥)."""
        row = await self._one(
            "SELECT EXISTS (SELECT 1 FROM marong.app_rings WHERE friend_id = %(f)s AND status IN " + RANG + " "
            "  AND created_at > now() - %(w)s) "
            "OR EXISTS (SELECT 1 FROM call.calls c JOIN call.callers k ON k.id = c.caller_id "
            "  WHERE k.friend_id = %(f)s AND c.started_at > now() - %(w)s) AS recent", {"f": friend_id, "w": within})
        return row["recent"]

    async def hello_count(self, within: timedelta) -> int:
        """Hello calls that rang today (all friends): each is one proactive turn of the daily maximum (SPEC-276)."""
        row = await self._one("SELECT count(*) AS n FROM marong.app_rings WHERE reason = 'hello' AND status IN "
                              + RANG + " AND created_at >= now() - %s", (within,))
        return row["n"]

    async def hello_add(self, friend_id: int, caller_id: int, title: str, say: str, topic: str | None,
                        answer_for: timedelta, *, scene_id=None) -> dict | None:
        """A ringing hello call without a schedule (SPEC-266 ①). None while another ring of this friend is ringing."""
        try:
            extra_column = ", scene_picture_id" if scene_id else ""
            extra_value = ", %s" if scene_id else ""
            params = (friend_id, caller_id, title, say, topic, answer_for)
            return await self._one(
                "INSERT INTO marong.app_rings (schedule_id, friend_id, caller_id, via, status, title, say, reason, "
                f"  topic, answer_until{extra_column}) "
                f"VALUES (NULL, %s, %s, 'app', 'ringing', %s, %s, 'hello', %s, now() + %s{extra_value}) "
                "RETURNING id::text AS id, via, status, answer_until",
                (*params, scene_id) if scene_id else params)
        except errors.UniqueViolation:
            return None
