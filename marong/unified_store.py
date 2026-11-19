"""The app store uses an account's owned room keys for its reply context."""

from .discord_store import DiscordStore
from .room_scope import writing_room


class UnifiedStore(DiscordStore):
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
