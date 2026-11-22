"""TC-496–498: migration, constraints and call cost access with a disposable Postgres."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase, main
from uuid import uuid4

from psycopg.errors import CheckViolation

from pg import TestDB


START = datetime(2026, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 12, 1, tzinfo=timezone.utc)
MONTH_SUM = "SELECT call.friend_month_usd(%s, %s, %s)"
FUNCTION = "call.friend_month_usd(bigint,timestamptz,timestamptz)"


class UsageLimitMigrationTests(TestCase):
    def setUp(self):
        self.db = TestDB()
        self.addCleanup(self.db.close)
        self.db.apply_unified_prerequisites()
        self.db.apply_unified()

    def friend(self, name, *, profile=False):
        friend, = self.db.admin("INSERT INTO marong.friends(name) VALUES (%s) RETURNING id", (name,))[0]
        if profile:
            code = ("AAAAAA", "BBBBBB", "CCCCCC")[friend - 1]
            self.db.admin("INSERT INTO marong.friend_profiles(friend_id,friend_code) VALUES (%s,%s)", (friend, code))
        return friend

    def limits(self, friend):
        return self.db.admin("""
            SELECT usage_unlimited, daily_units, call_monthly_usd FROM marong.friend_profiles WHERE friend_id=%s
        """, (friend,))[0]

    def test_existing_profiles_only_are_backfilled(self):
        existing = [self.friend(name, profile=True) for name in ("Fixture A", "Fixture B")]
        self.db.apply_usage_limit()
        self.assertEqual([self.limits(friend) for friend in existing], [(True, None, None)] * 2)
        self.assertEqual(self.limits(self.friend("Fixture C", profile=True)), (False, None, None))

    def test_reapply_respects_limits_and_constraints(self):
        friend = self.friend("Fixture", profile=True)
        self.db.apply_usage_limit()
        update = """
            UPDATE marong.friend_profiles SET usage_unlimited=%s,daily_units=%s,call_monthly_usd=%s WHERE friend_id=%s
        """
        self.db.admin(update, (False, None, None, friend))
        self.db.apply_usage_limit()
        self.assertEqual(self.limits(friend), (False, None, None))
        for values in [(True, 5, None), (False, 0, None), (False, 100001, None),
                       (False, None, 0), (False, None, Decimal("1000.01"))]:
            with self.subTest(values=values), self.assertRaises(CheckViolation):
                self.db.admin(update, (*values, friend))
        self.db.admin(update, (False, 200, Decimal("5"), friend))
        self.assertEqual(self.limits(friend), (False, 200, Decimal("5.00")))

    def segment(self, friend, *, closed=False):
        caller, = self.db.admin("INSERT INTO call.callers(friend_id) VALUES (%s) RETURNING id", (friend,))[0]
        client = uuid4()
        call, = self.db.admin("""
            INSERT INTO call.calls(caller_id,client_id,prompt_version,voice) VALUES (%s,%s,'fixture','fixture')
            RETURNING id
        """, (caller, client))[0]
        segment, = self.db.admin("""
            INSERT INTO call.segments(call_id,mode,client_id,opened_at) VALUES (%s,'start',%s,%s) RETURNING id
        """, (call, client, START))[0]
        if closed:
            self.db.admin("""
                UPDATE call.segments SET state='closed',closed_at=%s,close_reason='user_hangup' WHERE id=%s
            """, (START + timedelta(minutes=2), segment))
        return call, segment

    def test_monthly_sum_and_role_permissions(self):
        self.db.apply_usage_limit()
        measured = self.friend("Measured")
        estimated = self.friend("Estimated")
        call, segment = self.segment(measured)
        self.segment(estimated, closed=True)
        for seq, tokens, rate in [(1, 10000, 3), (2, 1000, 6)]:
            when = START + timedelta(seconds=seq)
            price, = self.db.admin("""
                INSERT INTO call.live_prices(model,starts_at,text_in,audio_in,image_in,text_out,audio_out,checked_on,source)
                VALUES ('fixture',%s,1,%s,1,1,1,%s,'fixture') RETURNING id
            """, (when, rate, START.date()))[0]
            self.db.admin("""
                INSERT INTO call.live_usage(call_id,segment_id,segment_ref,seq,received_at,entrypoint,model,
                                            audio_in,price_id,usd)
                VALUES (%s,%s,%s,%s,%s,'web','fixture',%s,%s,%s)
            """, (call, segment, segment, seq, when, tokens, price, Decimal(tokens * rate) / 1000000))

        self.assertEqual(self.db.admin(MONTH_SUM, (measured, START, END)), [(Decimal("0.036"),)])
        self.assertEqual(self.db.admin(MONTH_SUM, (estimated, START, END)), [(Decimal("0.10"),)])
        self.assertEqual(self.db.admin(MONTH_SUM, (measured, END, END + timedelta(days=31))), [(0,)])
        self.assertEqual(self.db.admin(MONTH_SUM, (self.friend("No caller"), START, END)), [(0,)])
        self.db.admin("CREATE ROLE usage_limit_fixture_public")
        for role, can_call in [("marong", True), ("marong_call", True), ("usage_limit_fixture_public", False)]:
            with self.subTest(role=role):
                self.assertEqual(self.db.admin("SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, FUNCTION)),
                                 [(can_call,)])
        self.assertEqual(self.db.admin("SELECT has_table_privilege('marong','call.live_usage','SELECT')"), [(False,)])
        self.assertEqual(self.db.admin("""
            SELECT has_column_privilege('marong_call','marong.friend_profiles','usage_unlimited','UPDATE')
        """), [(False,)])


if __name__ == "__main__":
    main()
