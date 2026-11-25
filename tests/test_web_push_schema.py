"""TASK-560: approved Web Push migration on clean and existing app databases."""

from pathlib import Path
import sys
import unittest
from uuid import uuid4

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pg import ROOT, TestDB


TABLE = "marong.web_push_subscriptions"
MIGRATIONS = ROOT / "marong" / "migrations"
MIGRATION = MIGRATIONS / "024_web_push_subscriptions.sql"
APPROVED = ROOT / "docs" / "05-erd" / "024_web_push_subscriptions.draft.sql"
CALL_DEADLINES = ROOT / "marong" / "call" / "migrations" / "012_notice_call_deadlines.sql"


def app_database():
    db = TestDB()
    try:
        db.apply_unified_prerequisites()
        db.apply_unified()
        db.apply_pet_app_prerequisites()
        db.apply_pet_app()
        db.apply_admin()
        db.apply_sql(MIGRATIONS / "023_app_update_events.sql")
    except BaseException:
        db.close()
        raise
    return db


def session(db, fingerprint):
    (row,), = db.admin("""
        WITH friend AS (INSERT INTO marong.friends(name) VALUES ('Fixture') RETURNING id)
        INSERT INTO marong.app_sessions
            (friend_id, token_hash, method, label, created_at, last_seen_at, expires_at)
        SELECT id, %s, 'invite', 'Fixture', now(), now(), now() + interval '1 day' FROM friend
        RETURNING id
    """, (fingerprint,))
    return row


class WebPushSchemaTests(unittest.TestCase):
    def setUp(self):
        self.db = app_database()
        self.addCleanup(self.db.close)

    def schema(self):
        return (
            self.db.admin("""
                SELECT attname, format_type(atttypid, atttypmod), attnotnull,
                       pg_get_expr(adbin, adrelid)
                FROM pg_attribute
                LEFT JOIN pg_attrdef ON adrelid=attrelid AND adnum=attnum
                WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped
                ORDER BY attnum
            """, (TABLE,)),
            self.db.admin("""
                SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
                WHERE conrelid=%s::regclass ORDER BY conname
            """, (TABLE,)),
            self.db.admin("""
                SELECT indexname, indexdef FROM pg_indexes
                WHERE schemaname='marong' AND tablename='web_push_subscriptions' ORDER BY indexname
            """),
            self.db.admin("""
                SELECT relowner::regrole::text, relacl::text
                FROM pg_class WHERE oid=%s::regclass
            """, (TABLE,)),
        )

    def test_empty_database_and_roles(self):
        self.db.apply_sql(APPROVED)
        expected = self.schema()
        self.db.admin(f"DROP TABLE {TABLE}")
        self.db.apply_sql(MIGRATION, MIGRATION)
        self.assertEqual(self.schema(), expected)
        self.assertEqual(self.db.admin(f"SELECT count(*) FROM {TABLE}"), [(0,)])
        self.db.admin("CREATE ROLE web_push_fixture_public")
        for role, expected in (
            ("marong", (True, True, True, False)),
            ("marong_call", (False, False, False, False)),
            ("web_push_fixture_public", (False, False, False, False)),
        ):
            with self.subTest(role=role):
                self.assertEqual(self.db.admin("""
                    SELECT has_table_privilege(%s, %s, 'SELECT'),
                           has_table_privilege(%s, %s, 'INSERT'),
                           has_table_privilege(%s, %s, 'UPDATE'),
                           has_table_privilege(%s, %s, 'DELETE')
                """, (role, TABLE) * 4), [expected])

    def test_existing_sessions_and_constraint_boundaries(self):
        first = session(self.db, b"a" * 32)
        second = session(self.db, b"b" * 32)
        before = self.db.admin("SELECT * FROM marong.app_sessions ORDER BY id")
        self.db.apply_sql(MIGRATION)
        self.assertEqual(self.db.admin("SELECT * FROM marong.app_sessions ORDER BY id"), before)
        fingerprint = b"x" * 32
        insert = f"""
            INSERT INTO {TABLE}
                (installation_id, session_id, state, endpoint_fingerprint, protected_material, subscription_expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        with psycopg.connect(self.db.app_url, autocommit=True) as app:
            installation = uuid4()
            app.execute(insert, (installation, first, "active", fingerprint, b"fixture", None))
            for error, values in (
                (psycopg.errors.UniqueViolation, (second, "active", fingerprint, b"fixture", None)),
                (psycopg.errors.ForeignKeyViolation, (0, "active", b"y" * 32, b"fixture", None)),
                (psycopg.errors.CheckViolation, (first, "active", b"short", b"fixture", None)),
                (psycopg.errors.CheckViolation, (first, "active", b"y" * 32, b"", None)),
                (psycopg.errors.CheckViolation, (first, "invalid", None, b"fixture", None)),
                (psycopg.errors.CheckViolation, (first, "revoked", fingerprint, None, None)),
                (psycopg.errors.CheckViolation, (first, "expired", None, None, "2026-01-01Z")),
            ):
                with self.subTest(error=error.__name__), self.assertRaises(error):
                    app.execute(insert, (uuid4(), *values))
            app.execute(f"""
                UPDATE {TABLE} SET state='revoked', endpoint_fingerprint=NULL, protected_material=NULL,
                    subscription_expires_at=NULL WHERE installation_id=%s
            """, (installation,))
            app.execute(insert, (uuid4(), second, "active", fingerprint, b"fixture", None))
        before_schema = self.schema()
        before_rows = self.db.admin(f"SELECT * FROM {TABLE} ORDER BY session_id")
        self.db.apply_sql(MIGRATION)
        self.assertEqual(self.schema(), before_schema)
        self.assertEqual(self.db.admin(f"SELECT * FROM {TABLE} ORDER BY session_id"), before_rows)
        self.db.admin("DELETE FROM marong.app_sessions WHERE id=%s", (first,))
        self.assertEqual(self.db.admin(f"SELECT session_id FROM {TABLE}"), [(second,)])


class NoticeCallSchemaTests(unittest.TestCase):
    def test_deadline_migration_on_empty_and_existing_calls(self):
        fields = ('notice_first_connected_at', 'notice_connection_deadline_at')
        approved = ROOT / 'docs' / '05-erd' / '012_notice_call_deadlines.draft.sql'
        self.assertEqual(CALL_DEADLINES.read_bytes(), approved.read_bytes())
        for seeded in (False, True):
            with self.subTest(seeded=seeded):
                db = app_database()
                self.addCleanup(db.close)
                if seeded:
                    db.admin("""
                        WITH friend AS (INSERT INTO marong.friends(name) VALUES ('Fixture') RETURNING id),
                        caller AS (INSERT INTO call.callers(friend_id) SELECT id FROM friend RETURNING id)
                        INSERT INTO call.calls(caller_id,status,client_id,prompt_version,voice,ended_at,end_reason,
                                               organize_status)
                        SELECT id,'resting',%s,'fixture','Fixture',NULL,NULL,'none' FROM caller
                        UNION ALL
                        SELECT id,'ended',%s,'fixture','Fixture',now(),'hangup','pending' FROM caller
                    """, (uuid4(), uuid4()))
                row_sql = "SELECT to_jsonb(c)-%s::text[] FROM call.calls c ORDER BY id"
                column_sql = """
                    SELECT attname,format_type(atttypid,atttypmod),attnotnull,atthasdef,attacl
                    FROM pg_attribute WHERE attrelid='call.calls'::regclass AND attnum>0 AND NOT attisdropped
                    ORDER BY attnum
                """
                acl_sql = "SELECT relowner,relacl FROM pg_class WHERE oid='call.calls'::regclass"
                before = (db.admin(row_sql, (list(fields),)), db.admin(column_sql), db.admin(acl_sql))
                self.assertEqual(len(before[0]), 2 if seeded else 0)
                for _ in range(2):
                    db.apply_sql(CALL_DEADLINES)
                    rows, columns, acl = db.admin(row_sql, (list(fields),)), db.admin(column_sql), db.admin(acl_sql)
                    self.assertEqual((rows, columns[:-2], acl), before)
                    self.assertEqual(columns[-2:], [(field, 'timestamp with time zone', False, False, None)
                                                    for field in fields])
                    self.assertEqual(db.admin('SELECT notice_first_connected_at, notice_connection_deadline_at '
                                              'FROM call.calls'), [(None, None)] * len(rows))
                for field in fields:
                    for role, allowed in (('marong_call', True), ('marong', False)):
                        self.assertEqual(db.admin("SELECT has_column_privilege(%s,'call.calls',%s,'UPDATE')",
                                                  (role, field)), [(allowed,)])


if __name__ == "__main__":
    unittest.main()
