"""TC-608: migration 023 on a fresh local Postgres database."""
from pathlib import Path
import sys
import unittest

import psycopg
from psycopg import errors

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pg import ROOT, TestDB

PHONE = "00000000-0000-4000-8000-000000000001"
INSERT = """INSERT INTO marong.app_update_events
    (kind, friend_id, install_id, version_code, app_version, state, status, attempt)
    VALUES (%s, 1, %s, %s, %s, %s, %s, %s)"""
ROWS = [
    ("pushed", PHONE, 11, None, None, None, 1),
    ("push_failed", PHONE, 11, None, None, 500, 1),
    ("state", PHONE, 11, None, "downloaded", None, None),
    ("state", PHONE, 11, None, "failed", 101, None),
    ("installed", PHONE, None, "0.3.3", None, None, None),
    ("fetched", None, 11, None, None, None, None),
]


class AppUpdateEventsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = TestDB()
        cls.addClassCleanup(cls.db.close)
        migrations = ROOT / "marong" / "migrations"
        cls.db.apply_sql(ROOT / "marong/call/schema.sql")
        cls.migrations = (migrations / "014_app_chat.sql", migrations / "023_app_update_events.sql")
        cls.db.apply_sql(*cls.migrations)
        cls.db.admin("INSERT INTO marong.friends(name) VALUES ('시험 친구')")
        cls.db.admin("INSERT INTO marong.app_devices(install_id, friend_id, notifications, app_version) "
                     "VALUES (%s, 1, 'denied', '0.3.2')", (PHONE,))

    def test_applies_twice_and_preserves_records(self):
        self.db.admin(INSERT, ROWS[-1])
        try:
            self.db.apply_sql(*self.migrations)
            self.assertEqual(self.db.admin("SELECT kind FROM marong.app_update_events"), [("fetched",)])
        finally:
            self.db.admin("DELETE FROM marong.app_update_events")

    def test_kind_constraints(self):
        invalid = [
            ("pushed", PHONE, 11, None, None, None, None),
            ("push_failed", PHONE, 11, None, None, None, 1),
            ("push_failed", PHONE, 11, None, None, 500, None),
            ("push_failed", PHONE, 11, None, None, 200, 1),
            ("state", PHONE, 11, None, "installed", None, None),
            ("state", PHONE, 11, None, "downloaded", 101, None),
            ("state", PHONE, 11, None, "failed", None, None),
            ("installed", PHONE, 11, None, None, None, None),
            ("fetched", PHONE, 11, None, None, None, None),
        ]
        with psycopg.connect(self.db.app_url) as conn:
            for row in ROWS:
                conn.execute(INSERT, row)
            for row in invalid:
                with self.subTest(row=row), self.assertRaises(errors.CheckViolation), conn.transaction():
                    conn.execute(INSERT, row)
            conn.rollback()

    def test_unique_claim_and_install(self):
        with psycopg.connect(self.db.app_url) as conn:
            for row in (ROWS[0], ROWS[1], ROWS[4]):
                conn.execute(INSERT, row)
                with self.subTest(kind=row[0]), self.assertRaises(errors.UniqueViolation), conn.transaction():
                    conn.execute(INSERT, row)
            conn.rollback()

    def test_bot_can_append_and_read_only(self):
        with psycopg.connect(self.db.app_url) as conn:
            conn.execute(INSERT, ROWS[0])
            self.assertEqual(conn.execute("SELECT kind FROM marong.app_update_events").fetchone(), ("pushed",))
            for command in ("UPDATE marong.app_update_events SET attempt = 2", "DELETE FROM marong.app_update_events"):
                with self.subTest(command=command), self.assertRaises(errors.InsufficientPrivilege), conn.transaction():
                    conn.execute(command)
            conn.rollback()

    def test_hourly_report_count_can_use_partial_index(self):
        with psycopg.connect(self.db.app_url) as conn:
            # Prefer usable indexes on an empty fixture, where a sequential scan is normally cheaper.
            conn.execute("SET LOCAL enable_seqscan = off")
            plan = conn.execute("""
                EXPLAIN SELECT count(*) FROM marong.app_update_events
                WHERE friend_id = %s AND kind IN ('state', 'installed') AND at > now() - interval '1 hour'
            """, (1,)).fetchall()
        self.assertIn("app_update_events_reports_idx", "\n".join(line for line, in plan))


if __name__ == "__main__":
    unittest.main()
