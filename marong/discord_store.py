"""Account binding, private history and persistent Discord DM delivery slots."""
import re

from .app_store import AppStore
from .google_calendar import GoogleStore
from .schedules import ScheduleStore
from .store import Store

SNOWFLAKE = re.compile(r"[1-9][0-9]{16,19}\Z")


def bind_dm(conn, discord_user_id: str, friend_id: int, per_day: int, start: int, end: int) -> None:
    """Run as the DB administrator after verifying the Discord account's owner."""
    if not SNOWFLAKE.fullmatch(discord_user_id) or not 1 <= per_day <= 48 or not 0 <= start < end <= 24:
        raise ValueError("Invalid account or schedule")
    room_key = f"discord-dm:{discord_user_id}"
    user_key = f"discord-user:{discord_user_id}"
    with conn.transaction():
        rows = conn.execute(
            """SELECT r.room_key,f.name FROM marong.rooms r CROSS JOIN marong.friends f
                WHERE f.id=%s AND r.is_channel AND r.memory_room IS NULL
                  AND r.room_key NOT LIKE 'discord-dm:%%'
                  AND EXISTS (SELECT 1 FROM marong.messages m WHERE m.room_key=r.room_key AND m.role='user')
                  AND NOT EXISTS (
                    SELECT 1 FROM marong.messages m LEFT JOIN marong.people p USING (user_key)
                    WHERE m.room_key=r.room_key AND m.role='user' AND p.friend_id IS DISTINCT FROM f.id
                  )""", (friend_id,),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError("Expected one verified private Kakao history room")
        history_room, name = rows[0]
        conn.execute(
            """INSERT INTO marong.rooms(room_key,is_channel,proactive,group_proactive)
               VALUES(%s,true,false,false) ON CONFLICT DO NOTHING""", (room_key,),
        )
        conn.execute(
            """INSERT INTO marong.people(user_key,name,friend_id) VALUES(%s,%s,%s)
               ON CONFLICT DO NOTHING""", (user_key, name, friend_id),
        )
        check = conn.execute(
            """SELECT p.friend_id, r.is_channel, r.memory_room, r.proactive, r.group_proactive
               FROM marong.people p CROSS JOIN marong.rooms r WHERE p.user_key=%s AND r.room_key=%s""",
            (user_key, room_key),
        ).fetchone()
        if check != (friend_id, True, None, False, False):
            raise ValueError("Discord identity or room conflicts with an existing binding")
        conn.execute(
            """INSERT INTO call.kakao_guards(room_key,friend_id,message_floor,note_floor,summary_floor)
               VALUES(%s,%s,0,0,0) ON CONFLICT DO NOTHING""", (room_key, friend_id),
        )
        guard = conn.execute(
            """SELECT friend_id,message_floor,note_floor,summary_floor FROM call.kakao_guards WHERE room_key=%s""",
            (room_key,),
        ).fetchone()
        if guard != (friend_id, 0, 0, 0):
            raise ValueError("Discord room lacks the private memory guard")
        added = conn.execute(
            """INSERT INTO marong.discord_dm_links
                 (discord_user_id,friend_id,room_key,kakao_room_key,user_key,per_day,start_hour,end_hour)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(discord_user_id) DO UPDATE
               SET per_day=EXCLUDED.per_day,start_hour=EXCLUDED.start_hour,end_hour=EXCLUDED.end_hour
               WHERE discord_dm_links.friend_id=EXCLUDED.friend_id
                 AND discord_dm_links.kakao_room_key=EXCLUDED.kakao_room_key
               RETURNING discord_user_id""",
            (discord_user_id, friend_id, room_key, history_room, user_key, per_day, start, end),
        ).fetchone()
        if not added:
            raise ValueError("An existing Discord identity cannot be reassigned")


DM_STATE = """
SELECT d.*, f.name, true AS is_channel, d.last_incoming_at AS last_said,
       now()-greatest(d.last_incoming_at,d.opted_in_at) AS quiet_for,
       now()-d.last_attempt_at AS sent_ago
  FROM marong.discord_dm_links d
  JOIN marong.people p ON p.user_key=d.user_key AND p.friend_id=d.friend_id
  JOIN marong.friends f ON f.id=d.friend_id
  JOIN marong.rooms r ON r.room_key=d.room_key AND r.is_channel AND r.memory_room IS NULL
  JOIN call.kakao_guards g ON g.room_key=d.room_key AND g.friend_id=d.friend_id
 WHERE g.message_floor=0 AND g.note_floor=0 AND g.summary_floor=0
"""


class DiscordStore(AppStore, GoogleStore, ScheduleStore, Store):
    def _reply_rooms(self, room: str) -> str:
        # No memory_room traversal: it would pull in linked Kakao group chats.
        return f"""(SELECT source.room_key FROM marong.discord_dm_links d
                    CROSS JOIN LATERAL (
                      SELECT d.room_key UNION ALL
                      SELECT k.room_key FROM marong.rooms k
                      WHERE k.room_key=d.kakao_room_key AND k.is_channel AND k.memory_room IS NULL
                        AND NOT EXISTS (
                          SELECT 1 FROM marong.messages m LEFT JOIN marong.people p USING(user_key)
                           WHERE m.room_key=k.room_key AND m.role='user'
                             AND p.friend_id IS DISTINCT FROM d.friend_id
                        )
                    ) source WHERE d.room_key={room})"""

    def _reply_embedding_filter(self) -> str:
        # Legacy summaries may combine the direct and linked group rooms.
        return "AND (e.source_type='message' OR e.room_key LIKE 'discord-dm:%%') "

    async def private_revision(self, room_key: str) -> int | None:
        row = await self._one(
            """SELECT coalesce(max(c.context_revision),0) AS revision
                 FROM marong.discord_dm_links d JOIN call.kakao_guards g ON g.friend_id=d.friend_id
                 JOIN call.callers c ON c.friend_id=g.friend_id
                WHERE d.room_key=%s AND g.room_key IN (d.room_key,d.kakao_room_key)""", (room_key,),
        )
        return row["revision"]

    async def link(self, discord_user_id: str) -> dict | None:
        return await self._one(DM_STATE + " AND d.discord_user_id=%s", (discord_user_id,))

    async def dm_target(self, friend_id: int) -> dict | None:
        """The friend's own DM channel and room, for notes Marong sends outside a reply."""
        return await self._one("SELECT channel_id, room_key FROM marong.discord_dm_links WHERE friend_id=%s", (friend_id,))

    async def incoming(self, user_id: str, channel_id: str, message_key: str, preference: bool | None) -> bool:
        row = await self._one(
            """UPDATE marong.discord_dm_links d
                  SET channel_id=%(channel)s,last_incoming_at=clock_timestamp(),failures=0,
                      opted_in_at=CASE WHEN %(preference)s::boolean IS TRUE THEN coalesce(opted_in_at,clock_timestamp())
                                       WHEN %(preference)s::boolean IS FALSE THEN NULL ELSE opted_in_at END,
                      proactive_moved_at=CASE WHEN coalesce(%(preference)s::boolean, opted_in_at IS NOT NULL)
                                             THEN coalesce(proactive_moved_at,clock_timestamp()) ELSE proactive_moved_at END
                WHERE discord_user_id=%(user)s AND (channel_id IS NULL OR channel_id=%(channel)s)
                  AND NOT EXISTS (
                      SELECT 1 FROM marong.messages m WHERE m.room_key=d.room_key AND m.kakao_id=%(message)s
                  )
                RETURNING discord_user_id""",
            {"user": user_id, "channel": channel_id, "message": message_key, "preference": preference},
        )
        return bool(row)

    async def has_delivered_reply(self, room_key: str, *, replay_text: str | None = None) -> bool:
        row = await self._one(
            """SELECT EXISTS (SELECT 1 FROM marong.messages WHERE room_key=%s
                              AND role='assistant' AND meta->>'delivered'='true'
                              AND (%s::text IS NULL OR
                                   (meta->>'discord_opening_replay'='true' AND content=%s))) AS delivered""",
            (room_key, replay_text, replay_text),
        )
        return row["delivered"]

    async def proactive_rooms(self, room_key: str | None = None) -> list[dict]:
        return await self._all(
            DM_STATE + " AND d.opted_in_at IS NOT NULL AND d.channel_id IS NOT NULL "
                       "AND (%s::text IS NULL OR d.room_key=%s) "
                       "ORDER BY d.per_day DESC, d.last_incoming_at",
            (room_key, room_key),
        )

    async def proactive_count(self, within) -> int:
        row = await self._one(
            """SELECT count(*) AS n FROM marong.messages m JOIN marong.discord_dm_links d USING(room_key)
                WHERE m.meta->>'proactive'='true' AND m.created_at>=now()-%s""", (within,),
        )
        return row["n"]

    async def friend_circle(self, user_key: str, limit: int) -> list[dict]:
        # Each Discord account gets its own history, without other friends' notes.
        return []

    async def claim_slot(self, room: dict, begin) -> bool:
        row = await self._one(
            """UPDATE marong.discord_dm_links SET last_slot=%s,last_attempt_at=clock_timestamp()
                WHERE discord_user_id=%s AND channel_id=%s AND opted_in_at=%s
                  AND last_incoming_at=%s AND failures<2 AND (last_slot IS NULL OR last_slot<%s)
                RETURNING discord_user_id""",
            (begin, room["discord_user_id"], room["channel_id"], room["opted_in_at"], room["last_incoming_at"], begin),
        )
        return bool(row)

    async def record_delivery(self, room: dict, begin, ok: bool) -> None:
        await self._one(
            """UPDATE marong.discord_dm_links
                  SET failures=CASE WHEN %s THEN 0 ELSE least(2,failures+1) END
                WHERE discord_user_id=%s AND last_slot=%s AND last_incoming_at=%s
                RETURNING discord_user_id""",
            (ok, room["discord_user_id"], begin, room["last_incoming_at"]),
        )
