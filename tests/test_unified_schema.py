"""TASK-379: apply the unified migrations twice on both clean and populated databases."""

from pathlib import Path
import sys
import unittest

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pg import TestDB


UNIFIED_TABLES = {
    "invites", "app_sessions", "device_codes", "friend_profiles", "contact_settings",
    "characters", "character_images", "character_jobs", "usage_daily",
}


class UnifiedSchemaTest(unittest.TestCase):
    def setUp(self):
        self.db = TestDB()
        self.addCleanup(self.db.close)
        self.db.apply_unified_prerequisites()

    def test_empty_database_with_role_restrictions(self):
        self.db.apply_unified()
        self.db.apply_unified()
        tables = {
            name for (name,) in self.db.admin(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'marong'"
            )
        }
        self.assertTrue(UNIFIED_TABLES <= tables)
        for name in UNIFIED_TABLES:
            with self.subTest(table=name):
                perms = self.db.admin(
                    "SELECT has_table_privilege('marong', %s, 'SELECT'), "
                    "has_table_privilege('marong', %s, 'INSERT'), "
                    "has_table_privilege('marong', %s, 'UPDATE'), "
                    "has_table_privilege('marong', %s, 'DELETE')",
                    (f"marong.{name}",) * 4,
                )
                self.assertEqual(perms, [(True, True, True, False)])
        self.assertEqual(self.db.admin("""
            SELECT has_table_privilege('marong_call', 'marong.app_sessions', 'SELECT'),
                   has_column_privilege('marong_call', 'marong.app_sessions', 'expires_at', 'UPDATE'),
                   has_column_privilege('marong_call', 'marong.app_sessions', 'last_seen_at', 'UPDATE'),
                   has_column_privilege('marong_call', 'marong.app_sessions', 'revoked_at', 'UPDATE'),
                   has_table_privilege('marong_call', 'marong.app_sessions', 'INSERT'),
                   has_column_privilege('marong_call', 'marong.friend_profiles', 'tickets', 'UPDATE'),
                   has_column_privilege('marong_call', 'marong.friend_profiles', 'bot_name', 'UPDATE'),
                   has_table_privilege('marong', 'call.callers', 'INSERT')
        """), [(True, True, True, False, False, True, False, True)])
        with psycopg.connect(self.db.app_url) as app:
            friend = app.execute("INSERT INTO marong.friends(name) VALUES ('Fixture') RETURNING id").fetchone()[0]
            app.execute("INSERT INTO call.callers(friend_id) VALUES (%s)", (friend,))
            for source in ("discord", "call", "app"):
                app.execute(
                    "INSERT INTO marong.schedules(friend_id, source, title, event_at) VALUES (%s, %s, 'Test', now())",
                    (friend, source),
                )
        self.assertEqual(self.db.admin("SELECT source FROM marong.schedules ORDER BY id"),
                         [("discord",), ("call",), ("app",)])

    def test_backfill_preserves_room_and_memory_rows(self):
        self.db.admin("""
            INSERT INTO marong.friends(name) VALUES ('Fixture A'), ('Fixture B'), ('Fixture C');
            INSERT INTO marong.rooms(room_key, is_channel) VALUES
                ('discord-dm:10000000000000001', true), ('fixture-kakao-a', true),
                ('discord-dm:10000000000000002', true), ('fixture-kakao-b', true),
                ('discord-ch:10000000000000003', false);
            INSERT INTO marong.people(user_key, friend_id) VALUES
                ('discord-user:10000000000000001', 1), ('discord-user:10000000000000002', 2);
            INSERT INTO marong.discord_dm_links
                (discord_user_id, friend_id, room_key, kakao_room_key, user_key, channel_id, last_incoming_at,
                 opted_in_at, proactive_moved_at, per_day, start_hour, end_hour, last_slot, last_attempt_at, failures)
            VALUES
                ('10000000000000001', 1, 'discord-dm:10000000000000001', 'fixture-kakao-a',
                 'discord-user:10000000000000001', '10000000000000011', '2026-01-01Z',
                 '2026-01-01Z', '2026-01-02Z', 4, 8, 22, '2026-01-03Z', '2026-01-04Z', 1),
                ('10000000000000002', 2, 'discord-dm:10000000000000002', 'fixture-kakao-b',
                 'discord-user:10000000000000002', NULL, NULL,
                 NULL, NULL, 2, 9, 21, NULL, NULL, 0);
            INSERT INTO marong.friendships(friend_a, friend_b, close) VALUES (1, 2, true), (2, 3, false);
            INSERT INTO marong.messages(room_key, user_key, role, content) VALUES
                ('fixture-kakao-a', 'discord-user:10000000000000001', 'user', 'Fixture message A'),
                ('fixture-kakao-b', 'discord-user:10000000000000002', 'user', 'Fixture message B');
            INSERT INTO marong.summaries(room_key, first_id, last_id, content) VALUES
                ('fixture-kakao-a', 1, 1, 'Fixture summary A'),
                ('fixture-kakao-b', 2, 2, 'Fixture summary B');
            INSERT INTO marong.notes(room_key, user_key, content) VALUES
                ('fixture-kakao-a', 'discord-user:10000000000000001', 'Fixture note A'),
                ('fixture-kakao-b', 'discord-user:10000000000000002', 'Fixture note B');
            INSERT INTO marong.embeddings(model, source_type, source_id, room_key, embedding) VALUES
                ('fixture', 'message', 1, 'fixture-kakao-a', '[0,1]'),
                ('fixture', 'message', 2, 'fixture-kakao-b', '[1,0]');
        """, None)
        history = ("messages", "summaries", "notes", "embeddings")
        before = {table: self.db.admin(f"SELECT * FROM marong.{table} ORDER BY room_key") for table in history}
        projection = ("friend_id, opted_in_at, proactive_moved_at, per_day, start_hour, end_hour, "
                      "last_incoming_at, last_slot, last_attempt_at, failures")
        expected = self.db.admin(f"SELECT {projection} FROM marong.discord_dm_links ORDER BY friend_id")
        self.db.apply_unified()
        self.assertEqual(self.db.admin(f"SELECT {projection} FROM marong.contact_settings ORDER BY friend_id"),
                         expected)
        self.db.admin("UPDATE marong.contact_settings SET per_day=5 WHERE friend_id=1")
        self.db.apply_unified()
        self.assertEqual(self.db.admin("SELECT room_key, owner_friend_id FROM marong.rooms ORDER BY room_key"), [
            ("discord-ch:10000000000000003", None), ("discord-dm:10000000000000001", 1),
            ("discord-dm:10000000000000002", 2), ("fixture-kakao-a", 1), ("fixture-kakao-b", 2),
        ])
        self.assertEqual(self.db.admin("SELECT friend_id, per_day FROM marong.contact_settings ORDER BY friend_id"),
                         [(1, 5), (2, 2)])
        self.assertEqual(self.db.admin("SELECT state, close, close_a, close_b FROM marong.friendships ORDER BY friend_a"),
                         [("accepted", True, True, True), ("accepted", False, False, False)])
        self.assertEqual(
            {table: self.db.admin(f"SELECT * FROM marong.{table} ORDER BY room_key") for table in history}, before
        )


if __name__ == "__main__":
    unittest.main()
