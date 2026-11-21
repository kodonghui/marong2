"""The app store uses an account's owned room keys for its reply context."""

import asyncio
import os
from psycopg.types.json import Jsonb

from .discord_store import DiscordStore
from .friend_scope import accepted_circle
from .graphs.memory import lock_message_writer, schedule_text
from .room_scope import writing_room, writing_room_key, writing_user_key
from .store import PROACTIVE_MESSAGE
from .unified_prompt import CHARACTER_PROFILE, PET_INTRO_COLUMNS


CONTACT_STATE = f"""
SELECT d.*, f.name, room.room_key, true AS is_channel, d.last_incoming_at AS last_said,
       {writing_user_key('d.friend_id')} AS user_key,
       p.character_id IS NOT NULL AS wearing_character,
       now()-greatest(d.last_incoming_at,d.opted_in_at) AS quiet_for,
       now()-greatest(d.last_attempt_at, unanswered.last_sent) AS sent_ago,
       unanswered.n AS unanswered
FROM marong.contact_settings d
JOIN marong.friends f ON f.id=d.friend_id
LEFT JOIN marong.friend_profiles p ON p.friend_id=d.friend_id
JOIN LATERAL (SELECT {writing_room_key('d.friend_id')} AS room_key) room ON room.room_key IS NOT NULL
CROSS JOIN LATERAL (
    SELECT count(*) AS n,max(m.created_at) AS last_sent
    FROM marong.messages m
    WHERE m.room_key=room.room_key AND m.role='assistant' AND m.meta->>'delivered'='true'
      AND {PROACTIVE_MESSAGE}
      AND m.created_at > greatest(d.last_incoming_at, d.opted_in_at, (
          SELECT max(c.started_at) FROM call.calls c JOIN call.callers k ON k.id=c.caller_id
          WHERE k.friend_id=d.friend_id
      ))
) unanswered
"""


class UnifiedStore(DiscordStore):
    def __init__(self, conninfo, timeout=5, call_bridge=None, *, fixed_proactive_friends=()):
        super().__init__(conninfo, timeout, call_bridge)
        self.fixed_proactive_friends = frozenset(fixed_proactive_friends)

    def _contact_policy(self, row):
        if row and row["friend_id"] in self.fixed_proactive_friends:
            return {**row, "fixed_proactive": True}
        return row

    async def friend_circle(self, user_key, limit):
        if os.getenv("MARONG_FRIENDS") != "1":
            return []
        async with asyncio.timeout(.7):
            person = await self._one("SELECT friend_id FROM marong.people WHERE user_key=%s", (user_key,))
            if not person or person["friend_id"] is None:
                return []
            query = accepted_circle(self._forget_guard("'shared_note'", "x.id"))
            return await self._all(query, {"friend": person["friend_id"], "limit": min(20, limit)})

    async def character_prompt(self, friend_id, friends_enabled, *, pet_voice=False):
        columns = PET_INTRO_COLUMNS if pet_voice else ""
        return await self._one(CHARACTER_PROFILE.format(intro_columns=columns), (friends_enabled, friend_id))

    async def app_bot_name(self, friend_id):
        row = await self._one("SELECT bot_name FROM marong.friend_profiles WHERE friend_id=%s", (friend_id,))
        return row["bot_name"] if row else None

    async def writing_target(self, friend_id):
        return await self._one(f"""
            SELECT {writing_room_key('f.id')} AS room_key,
                   EXISTS (SELECT 1 FROM marong.app_sessions s WHERE s.friend_id=f.id
                           AND s.revoked_at IS NULL AND s.expires_at>now()) AS has_session
            FROM marong.friends f WHERE f.id=%s
        """, (friend_id,))

    async def contact(self, friend_id):
        row = await self._one("SELECT * FROM marong.contact_settings WHERE friend_id=%s", (friend_id,))
        return self._contact_policy(row)

    async def app_incoming(self, who, key, text, preference):
        insert = """
            WITH saved AS (
                INSERT INTO marong.messages(room_key,user_key,role,content,kakao_id,meta)
                VALUES (%(room)s,%(user)s,'user',%(text)s,%(key)s,%(meta)s)
                ON CONFLICT (room_key,kakao_id) DO NOTHING RETURNING id,created_at
            ), touched AS (
              UPDATE marong.contact_settings SET last_incoming_at=clock_timestamp(),failures=0,
              opted_in_at=CASE WHEN %(preference)s::boolean IS TRUE THEN coalesce(opted_in_at,clock_timestamp())
                               WHEN %(preference)s::boolean IS FALSE THEN NULL ELSE opted_in_at END,
              proactive_moved_at=CASE WHEN coalesce(%(preference)s::boolean,opted_in_at IS NOT NULL)
                                     THEN coalesce(proactive_moved_at,clock_timestamp()) ELSE proactive_moved_at END
              WHERE friend_id=%(friend)s AND EXISTS (SELECT 1 FROM saved)
            )
            SELECT id,created_at FROM saved
        """
        values = {"friend": who["friend_id"], "preference": preference, "room": who["room_key"],
              "user": who["user_key"], "text": text, "key": key, "meta": Jsonb({"transport": "app"})}
        if self.friend_memory_enabled:
            async with self.pool.connection() as conn, conn.transaction():
                friend_id = await lock_message_writer(conn, who["user_key"])
                cursor = await conn.execute(insert, values)
                row = await cursor.fetchone()
                if row and friend_id == who["friend_id"]:
                    await schedule_text(conn, friend_id, row["created_at"])
        else:
            row = await self._one(insert, values)
        return row["id"] if row else None

    async def proactive_rooms(self, room_key=None):
        rooms = await self._all(
            CONTACT_STATE + " WHERE d.opted_in_at IS NOT NULL AND (%s::text IS NULL OR room.room_key=%s)"
                            " ORDER BY d.per_day DESC,d.last_incoming_at",
            (room_key, room_key),
        )
        return [self._contact_policy(room) for room in rooms]

    async def proactive_count(self, within):
        row = await self._one(f"""
            SELECT count(*) AS n FROM marong.messages m JOIN marong.rooms r USING (room_key)
            WHERE {writing_room('r')} AND m.meta->>'proactive'='true' AND m.created_at>=now()-%s
        """, (within,))
        return row["n"]

    async def claim_slot(self, room, begin):
        row = await self._one("""
            UPDATE marong.contact_settings SET last_slot=%s,last_attempt_at=clock_timestamp()
            WHERE friend_id=%s AND opted_in_at=%s AND last_incoming_at IS NOT DISTINCT FROM %s
              AND per_day=%s AND start_hour=%s AND end_hour=%s AND failures<2
              AND (last_slot IS NULL OR last_slot<%s) RETURNING friend_id
        """, (begin, room["friend_id"], room["opted_in_at"], room["last_incoming_at"],
              room["per_day"], room["start_hour"], room["end_hour"], begin))
        return bool(row)

    async def record_delivery(self, room, begin, ok):
        await self._one("""
            UPDATE marong.contact_settings SET failures=CASE WHEN %s THEN 0 ELSE least(2,failures+1) END
            WHERE friend_id=%s AND last_slot=%s AND last_incoming_at IS NOT DISTINCT FROM %s RETURNING friend_id
        """, (ok, room["friend_id"], begin, room["last_incoming_at"]))

    def _reminder_destination(self):
        return f"{writing_room_key('s.friend_id')} AS dm_room"

    def _topic_message_room(self):
        return f"m.room_key = {writing_room_key('o.friend_id')}"

    def _topic_quiet_room(self):
        return f"""SELECT {writing_room_key('d.friend_id')} AS room_key,d.opted_in_at
                   FROM marong.contact_settings d WHERE d.friend_id=%(f)s"""

    def _reply_rooms(self, room: str) -> str:
        # room appears once because the vector search passes it as one positional parameter.
        return f"""(
            SELECT rooms.room_key FROM (SELECT {room}::text AS room_key) asked
            CROSS JOIN LATERAL (
              SELECT asked.room_key WHERE asked.room_key LIKE 'discord-ch:%%'
              UNION ALL
              SELECT candidate.room_key FROM marong.rooms current_room
              JOIN marong.rooms candidate ON candidate.owner_friend_id=current_room.owner_friend_id
              WHERE current_room.room_key=asked.room_key AND {writing_room("current_room")}
                AND (
                  candidate.room_key=current_room.room_key
                  OR (
                    candidate.is_channel AND candidate.memory_room IS NULL AND NOT ({writing_room("candidate")})
                    AND NOT EXISTS (
                      SELECT 1 FROM marong.messages m LEFT JOIN marong.people p USING (user_key)
                      WHERE m.room_key=candidate.room_key AND m.role='user'
                        AND p.friend_id IS DISTINCT FROM current_room.owner_friend_id
                    )
                  )
                )
            ) rooms
        )"""

    def _writing_or_channel(self, key):
        return (f"({key} LIKE 'discord-ch:%%' OR EXISTS "
                f"(SELECT 1 FROM marong.rooms owned WHERE owned.room_key={key} AND {writing_room('owned')}))")

    def _reply_embedding_filter(self) -> str:
        return f"AND (e.source_type='message' OR {self._writing_or_channel('e.room_key')}) "

    def _summary_keyword_filter(self) -> str:
        return f"AND {self._writing_or_channel('s.room_key')} "

    def _history_rooms(self, room: str) -> str:
        return f"(SELECT r.room_key FROM marong.rooms r WHERE r.room_key={room} AND {self._writing_or_channel('r.room_key')})"
