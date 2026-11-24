"""Admin overview and controls against a disposable PostgreSQL database."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import secrets
import sys
from time import monotonic, time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import psycopg
from psycopg.rows import dict_row

from pg import ROOT, TestDB

sys.path.insert(0, str(ROOT))
from marong.access import AccessConfig, AccessVerifier, email_hash
from marong.app_admin import overview_attention
from marong.app_chat import AppChat
from marong.app_session import AppSessions, one, token_hash
from marong.unified_store import UnifiedStore
from marong.usage import month_bounds, usage_day
from tools.vertex_live.call_cost import MonthlyCost


NOW = datetime(2026, 11, 24, 19, 10, tzinfo=timezone.utc)
OVERVIEW = "/chat/admin/api/overview"
ORIGIN = "https://fixture.invalid"
ADMIN_HASH = "a" * 64
SCREENS = (("", "overview"), ("members", "members"), ("members/7", "members"),
           ("invites", "invites"), ("app", "app"), ("costs", "costs"), ("items", "items"))


class OverviewAttentionTest(unittest.TestCase):
    def test_tc625_thresholds(self):
        for percent, state, level in ((79, "ok", None), (80, "warn", "warn"),
                                      (100, "exhausted", "danger"), (120, "hard_stop", "danger")):
            with self.subTest(percent=percent):
                attention = overview_attention(NOW, {"unlinked": 0}, {"state": state, "percent": percent},
                                               None, None, None)
                self.assertEqual([row["level"] for row in attention], [level] if level else [])
        for percent, level in ((79, None), (80, "warn"), (100, "danger")):
            with self.subTest(percent=percent):
                attention = overview_attention(NOW, {"unlinked": 0}, None,
                                               {"budgetPercent": percent}, None, None)
                self.assertEqual([row["level"] for row in attention], [level] if level else [])
        for hours, state, paused, expected in (
            (23, "downloaded", False, []), (24, "downloaded", False, [("app_behind", "warn")]),
            (25, "downloaded", False, [("app_behind", "warn")]),
            (23, "needs_confirm", False, [("app_behind", "danger")]),
            (23, "failed", False, [("app_behind", "danger")]),
            (25, "failed", True, [("app_paused", "warn")]),
        ):
            with self.subTest(hours=hours, state=state, paused=paused):
                app = {"paused": paused, "latest": {"publishedAt": (NOW - timedelta(hours=hours)).isoformat()},
                       "devices": [{"behind": True, "events": [{"kind": "push_failed"},
                                                               {"kind": "state", "state": state},
                                                               {"kind": "state", "state": "failed"}]}]}
                attention = overview_attention(NOW, {"unlinked": 0}, None, None, app, None)
                self.assertEqual([(row["kind"], row["level"]) for row in attention], expected)
                if paused:
                    self.assertNotIn("value", attention[0])


class AdminTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = TestDB()
        self.addCleanup(self.db.close)
        self.db.apply_unified_prerequisites()
        self.db.apply_unified()
        self.db.apply_pet_app_prerequisites()
        self.db.apply_pet_app()
        self.db.apply_sql(ROOT / "marong" / "migrations" / "023_app_update_events.sql")
        self.db.apply_admin()
        self.store = UnifiedStore(self.db.app_url)
        await self.store.open(wait=True)
        self.addAsyncCleanup(self.store.close)
        self.now = NOW
        self.sessions = AppSessions(self.store.pool, secrets.token_bytes(32), contact_schedule=(3, 8, 22),
                                    now=lambda: self.now)
        self.chat = AppChat(self.store, SimpleNamespace(friend_cards=None), None, None, None,
                            origin=ORIGIN, sessions=self.sessions, authentication="session",
                            admin_email_hash=ADMIN_HASH)
        self.proof = secrets.token_urlsafe()
        self.headers = {"Cf-Access-Jwt-Assertion": self.proof, "Origin": ORIGIN}
        self.chat.access = SimpleNamespace(check=AsyncMock(side_effect=self.access))
        self.client = TestClient(TestServer(self.chat.web_app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def access(self, proof):
        return "ok", ADMIN_HASH if proof == self.proof else "b" * 64

    async def overview(self, status=200, code=None, headers=None):
        response = await self.client.get(OVERVIEW, headers=self.headers if headers is None else headers)
        return await self.response(response, status, code)

    async def response(self, response, status, code=None):
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        data = await response.json()
        self.assertEqual(response.status, status, data)
        if code:
            self.assertEqual(response.content_type, "application/problem+json")
            self.assertEqual((data["status"], data["code"]), (status, code))
            self.assertRegex(data["traceId"], r"^[0-9a-f]{16}$")
        return data

    def call_rows(self):
        (friend,), = self.db.admin("INSERT INTO marong.friends(name) VALUES ('시험친구 가') RETURNING id")
        (caller,), = self.db.admin("INSERT INTO call.callers(friend_id) VALUES (%s) RETURNING id", (friend,))
        (call,), = self.db.admin("INSERT INTO call.calls(caller_id,client_id,entrypoint,prompt_version,voice) "
                                "VALUES (%s,%s,'web','fixture','fixture') RETURNING id", (caller, uuid4()))
        segments = (uuid4(), uuid4(), uuid4())
        prices = []
        for n, rate in enumerate((3, 6)):
            (price,), = self.db.admin("""
                INSERT INTO call.live_prices(model,starts_at,text_in,audio_in,image_in,text_out,audio_out,
                    search_per_1000,search_free_per_month,checked_on,source)
                VALUES ('fixture',%s,3,%s,1,6,1,14,5000,'2026-11-24','fixture') RETURNING id
            """, (NOW - timedelta(days=40 - 40 * n), rate))
            prices.append(price)
        for segment, at, tokens, rate, searches, price in (
            (segments[0], NOW - timedelta(seconds=1), 10_000, 3, 5200, prices[0]),
            (segments[1], NOW, 1000, 6, 0, prices[1]),
            (segments[2], NOW.replace(month=10), 10_000, 3, 0, prices[0]),
        ):
            self.db.admin("""
                INSERT INTO call.live_usage(call_id, segment_ref, seq, received_at, entrypoint, model,
                    audio_in, searches, price_id, usd)
                VALUES (%s,%s,1,%s,'web','fixture',%s,%s,%s,%s)
            """, (call, segment, at, tokens, searches, price, Decimal(tokens * rate) / 1_000_000))
        self.db.admin("""
            INSERT INTO call.ai_runs(kind,call_id,trace_id,model,prompt_version,sent_at,input_tokens,
                output_tokens,thoughts_tokens,outcome)
            VALUES ('organize',%s,'fixture','fixture','fixture',%s,10000,1000,1000,'ok')
        """, (call, NOW))
        self.db.admin("UPDATE call.settings SET value='175' WHERE key='monthly_budget_usd'")
        return friend, call

    async def test_tc631_call_month_matches_report(self):
        self.call_rows()
        dsn = self.db.admin_url.replace("postgres:@", "marong_call@", 1)
        async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
            async def read(sql, params):
                return await one(conn, sql, params)

            report = await MonthlyCost(SimpleNamespace(one=read)).report(NOW, fresh=True)
        self.assertEqual(report["total"].quantize(Decimal(".0001")), Decimal("2.8780"))
        for budget in (175, 150):
            ((spent, amount),) = self.db.admin("SELECT * FROM call.month_budget(%s,%s)", month_bounds(NOW))
            self.assertEqual(spent.quantize(Decimal(".0001")), report["total"].quantize(Decimal(".0001")))
            self.assertEqual(amount, budget)
            self.db.admin("DELETE FROM call.settings WHERE key='monthly_budget_usd'")

    async def test_tc632_permissions_and_repeat_application(self):
        friend, _ = self.call_rows()
        self.db.apply_admin()
        args = month_bounds(NOW)
        with psycopg.connect(self.db.app_url, autocommit=True) as conn:
            def read():
                return (conn.execute("SELECT * FROM call.month_budget(%s,%s)", args).fetchone(),
                        conn.execute("SELECT call.friend_month_usd(%s,%s,%s)", (friend, *args)).fetchone())

            original = read()
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT * FROM call.live_usage")
            conn.execute("CREATE TEMP TABLE live_usage (usd numeric)")
            conn.execute("INSERT INTO live_usage VALUES (99)")
            conn.execute("CREATE TEMP TABLE settings (key text, value jsonb)")
            conn.execute("INSERT INTO settings VALUES ('monthly_budget_usd', '99')")
            # A non-null timestamp would fail this constraint if either function
            # resolved its types against this session's temporary domain.
            conn.execute("CREATE DOMAIN pg_temp.timestamptz AS pg_catalog.timestamptz CHECK (VALUE IS NULL)")
            self.assertEqual(read(), original)
            # Same name again, now checked by a temporary function that only raises.
            conn.execute("DROP DOMAIN pg_temp.timestamptz")
            conn.execute("""
                CREATE FUNCTION pg_temp.intercept(pg_catalog.timestamptz) RETURNS boolean
                LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'intercepted'; END $$
            """)
            conn.execute("CREATE DOMAIN pg_temp.timestamptz AS pg_catalog.timestamptz "
                         "CHECK (pg_temp.intercept(VALUE))")
            # The trap is live: in this session the bare type name resolves to the temporary domain.
            with self.assertRaisesRegex(psycopg.errors.RaiseException, "intercepted"):
                conn.execute("SELECT %s::timestamptz", (args[0],))
            self.assertEqual(read(), original)

        dsn = self.db.admin_url.replace("postgres:@", "marong_call@", 1)
        with psycopg.connect(dsn) as conn, self.assertRaises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM call.month_budget(%s,%s)", args)
        self.assertEqual(self.db.admin("""
            SELECT proname,proconfig,prosecdef,prosqlbody IS NOT NULL,
                   EXISTS (SELECT FROM aclexplode(proacl) x WHERE x.grantee=0 AND x.privilege_type='EXECUTE')
            FROM pg_proc WHERE pronamespace='call'::regnamespace
              AND proname IN ('month_budget','friend_month_usd') ORDER BY proname
        """), [("friend_month_usd", ["search_path=pg_catalog, pg_temp"], True, False, False),
                ("month_budget", ["search_path=pg_catalog, pg_temp"], True, True, False)])

    async def test_tc622_overview_sums_and_attention(self):
        friend, call = self.call_rows()
        self.db.admin("UPDATE call.settings SET value='150' WHERE key='monthly_budget_usd'")
        self.db.admin("UPDATE call.live_usage SET usd=118.552 WHERE call_id=%s AND searches=5200", (call,))
        for name in ("시험친구 나", "시험친구 다", "시험친구 라"):
            self.db.admin("INSERT INTO marong.friends(name) VALUES (%s)", (name,))
        self.db.admin("""
            INSERT INTO marong.friend_profiles(friend_id,friend_code)
            SELECT id, 'AAAAA' || chr(65 + (id - %s)::int) FROM marong.friends WHERE id<%s
        """, (friend, friend + 3))
        day = usage_day(NOW)
        self.db.admin("""
            INSERT INTO marong.usage_daily(friend_id,day,chat_turns,call_seconds,images,units)
            VALUES (%s,%s,40,1260,2,410), (%s,%s,1,0,0,10), (%s,%s,9,9,9,999), (%s,%s,9,9,9,999)
        """, (friend, day, friend + 1, day, friend, day - timedelta(days=1), friend + 3, day))
        self.chat.characters.budget = Decimal(20)
        (character,), = self.db.admin("INSERT INTO marong.characters(friend_id,kind) VALUES (%s,'dog') RETURNING id",
                                     (friend,))
        self.db.admin("""INSERT INTO marong.character_jobs(character_id,step,state,cost_usd,finished_at)
                      VALUES (%s,'sheet','done',17,%s)""", (character, NOW))
        for hours, used in ((23, False), (25, False), (23, True)):
            await self.sessions.create_invite("join")
            self.db.admin("""
                UPDATE marong.invites SET created_at=%s,expires_at=%s,used_at=%s,used_by=%s
                WHERE id=(SELECT max(id) FROM marong.invites)
            """, (NOW - timedelta(days=1), NOW + timedelta(hours=hours), NOW if used else None,
                  friend if used else None))

        latest = {"versionName": "0.3.3", "versionCode": 11,
                  "publishedAt": (NOW - timedelta(hours=30)).isoformat()}
        app = {"latest": latest, "paused": False, "devices": [
            {"behind": True, "events": [], "friend": "시험친구 가", "friendId": friend},
            {"behind": False, "events": [], "friend": "시험친구 나", "friendId": friend + 1},
        ]}
        with patch.object(self.chat.admin, "read_app_versions", return_value=app):
            data = await self.overview()
        self.assertEqual(data["members"], {"count": 3, "unlinked": 1})
        self.assertEqual(data["usageToday"], {"day": day.isoformat(), "chatTurns": 41, "callSeconds": 1260,
                                             "images": 2, "units": 420})
        self.assertEqual(data["callMonth"], {"month": "2026-11", "spentUsd": "121.40", "budgetUsd": "150.00",
                                            "percent": 80, "state": "warn"})
        self.assertEqual(data["images"], {"month": "2026-11", "totalUsd": "17.00", "budgetPercent": 85})
        self.assertEqual(data["app"], {"latest": latest, "paused": False, "devices": 2, "behind": 1})
        self.assertEqual([(item["kind"], item["value"]) for item in data["attention"]],
                         [("call_budget", 80), ("image_budget", 85), ("app_behind", 1),
                          ("invite_expiring", 1), ("unlinked_friend", 1)])
        self.assertNotIn("시험친구", str(data))
        self.assertNotIn("friendId", str(data))
        self.assertNotIn("events", str(data))

    async def test_tc623_partial_timeout_and_pool_limit(self):
        self.assertEqual((await self.overview())["attention"], [])
        seen = []
        active = 0
        pool_connection = self.store.pool.connection

        @asynccontextmanager
        async def counted(*args, **kwargs):
            nonlocal active
            async with pool_connection(*args, **kwargs) as conn:
                self.assertEqual(active, 0)
                active += 1
                try:
                    yield conn
                finally:
                    active -= 1

        def delayed(part):
            async def read(conn, *_):
                seen.append((part, conn))
                if part == "app":
                    await asyncio.sleep(2)
                else:
                    await conn.execute("SELECT pg_sleep(2)")
            return read

        for part, key in (("call", "callMonth"), ("images", "images"), ("invites", None)):
            with self.subTest(part=part), patch.object(self.chat.admin, f"_overview_{part}", new=delayed(part)):
                with self.assertLogs("marong.app_admin", "WARNING") as events:
                    data = await self.overview()
                self.assertEqual(events.output, [f"WARNING:marong.app_admin:admin_overview part={part} result=failed"])
                for column in ("callMonth", "images", "app", "usageToday"):
                    self.assertEqual(data[column] is None, column == key, column)

        with patch.object(self.chat.admin, "read_app_versions", new=None):
            self.assertIsNone((await self.overview())["app"])
        parts = ("call", "images", "app", "usage", "invites")
        seen.clear()
        async with AsyncExitStack() as stack:
            for part in parts:
                stack.enter_context(patch.object(self.chat.admin, f"_overview_{part}", new=delayed(part)))
            stack.enter_context(patch.object(self.store.pool, "connection", new=counted))
            with self.assertLogs("marong.app_admin", "WARNING") as events:
                start = monotonic()
                data = await self.overview()
                self.assertLess(monotonic() - start, 8)
        self.assertEqual([part for part, _ in seen], list(parts))
        self.assertEqual(len({id(conn) for _, conn in seen}), 1)
        self.assertEqual(len(events.output), 5)
        self.assertEqual(data, {"members": {"count": 0, "unlinked": 0}, "attention": [],
                                "callMonth": None, "images": None, "app": None, "usageToday": None})
        async with AsyncExitStack() as stack:
            for _ in range(4):
                await stack.enter_async_context(pool_connection())
            start = monotonic()
            await self.overview(503, "db_unavailable")
            self.assertGreaterEqual(monotonic() - start, 1.9)

    async def test_tc624_access_and_database_failure(self):
        await self.overview(403, "not_allowed", headers={})
        await self.overview(403, "not_allowed", headers={"Cf-Access-Jwt-Assertion": secrets.token_urlsafe()})
        with patch.object(self.chat.admin, "_overview_members", side_effect=RuntimeError):
            await self.overview(500, "internal")
        with patch.object(self.chat.admin, "_overview_members", side_effect=psycopg.OperationalError):
            await self.overview(503, "db_unavailable")

    async def test_tc620_html_tabs_and_csp(self):
        self.chat.decor.catalog = object()
        hrefs = {"overview": "/chat/admin/", **{name: f"/chat/admin/{name}"
                 for name in ("members", "invites", "app", "costs", "items")}}
        for path, tab in SCREENS:
            with self.subTest(path=path):
                response = await self.client.get(f"/chat/admin/{path}", headers=self.headers)
                self.assertEqual((response.status, response.content_type), (200, "text/html"))
                self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
                html = await response.text()
                nav = html.split('<nav class="admin-nav"', 1)[1].split("</nav>", 1)[0]
                self.assertEqual(nav.count("<a "), 6)
                self.assertEqual(nav.count('aria-current="page"'), 1)
                for key, href in hrefs.items():
                    attribute = ' aria-current="page"' if key == tab else ''
                    self.assertIn(f'<a href="{href}"{attribute}>', nav)

    async def test_tc621_forbidden_unknown_and_redirect(self):
        for path, _ in SCREENS:
            for proof in ({}, {"Cf-Access-Jwt-Assertion": secrets.token_urlsafe()}):
                with self.subTest(path=path):
                    req = {**proof, "Accept": "text/html"}
                    response = await self.client.get(f"/chat/admin/{path}", headers=req)
                    self.assertEqual(response.status, 403)
                    html = await response.text()
                    self.assertIn("관리자만 볼 수 있어요", html)
                    self.assertNotIn('class="admin-tabs"', html)
        for path in ("foo", "members/abc", "members/0", "members/9223372036854775808"):
            response = await self.client.get(f"/chat/admin/{path}", headers=self.headers)
            self.assertEqual(response.status, 404)
            self.assertIn("없는 화면이에요", await response.text())
        redirect = await self.client.get("/chat/admin/members/?kind=link", headers=self.headers, allow_redirects=False)
        self.assertEqual((redirect.status, redirect.headers["Location"]), (301, "/chat/admin/members?kind=link"))

    async def test_tc652_items_page_with_catalog_disabled(self):
        address = uuid4().hex + chr(64) + "example.invalid"
        config = AccessConfig("fixture.cloudflareaccess.com", "fixture", frozenset({address}))
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk["kid"] = "fixture"
        now = int(time())
        verifier = AccessVerifier(config)
        verifier.keys = [jwk]
        verifier.fetched = now
        verifier.expires = now + 600
        proof = jwt.encode({"sub": "fixture", "email": address, "iat": now, "exp": now + 300,
                            "aud": config.aud, "iss": f"https://{config.team}"},
                           key, algorithm="RS256", headers={"kid": jwk["kid"]})
        self.chat.access = verifier
        self.chat.admin.email_hash = email_hash(address)
        self.assertIsNone(self.chat.decor.catalog)
        self.assertEqual(self.db.admin("SELECT count(*) FROM marong.friend_profiles"), [(0,)])

        headers = {"Cf-Access-Jwt-Assertion": proof, "Origin": ORIGIN, "Accept": "text/html"}
        for method, path in (("GET", "/api/items"), ("POST", "/api/items/fixture/list"),
                             ("POST", "/api/items/fixture/unlist")):
            response = await self.client.request(method, "/chat/admin" + path, headers=headers)
            await self.response(response, 404, "not_found")
        refused = await self.client.get("/chat/admin/items", headers={"Accept": "text/html"})
        self.assertEqual((refused.status, refused.content_type), (403, "text/html"))

        for path, _ in SCREENS:
            with self.subTest(path=path):
                response = await self.client.get(f"/chat/admin/{path}", headers=headers)
                self.assertEqual((response.status, response.content_type), (200, "text/html"))
                html = await response.text()
                self.assertIn('href="/chat/admin/items"', html)
                if path == "items":
                    self.assertIn('href="/chat/admin/items" aria-current="page"', html)
                    self.assertIn('id="item-admin"', html)

    async def make_invite(self):
        token, expires = await self.sessions.create_invite("join")
        ((ident,),) = self.db.admin("SELECT id FROM marong.invites WHERE token_hash=%s", (token_hash(token),))
        return ident, token, expires

    async def revoke_invite(self, ident, status, code=None, headers=None):
        result = await self.client.post(f"/chat/admin/api/invites/{ident}/revoke",
                                        headers=self.headers if headers is None else headers)
        return await self.response(result, status, code)

    async def join_invite(self, token):
        return await self.client.post("/chat/api/join", headers={"Origin": ORIGIN},
                                      json={"token": token, "name": "시험친구 가"})

    async def test_tc635_revoke_statuses_and_idempotence(self):
        ident, token, expires = await self.make_invite()
        await self.revoke_invite(ident, 403, "not_allowed", headers={})
        await self.revoke_invite(ident, 403, "cross_site", headers={**self.headers, "Origin": "https://other.invalid"})
        await self.revoke_invite("abc", 404, "not_found")
        await self.revoke_invite(99_999, 404, "not_found")
        with patch("marong.app_admin.one", side_effect=RuntimeError):
            await self.revoke_invite(ident, 500, "internal")
        with self.assertLogs("marong.app_admin", "INFO") as events:
            first = await self.revoke_invite(ident, 200)
        self.assertEqual(events.output, [f"INFO:marong.app_admin:admin_invite_revoke invite={ident} result=revoked"])
        self.assertEqual(first["invite"]["state"], "revoked")
        self.assertEqual(datetime.fromisoformat(first["invite"]["revokedAt"]), NOW)
        self.assertEqual(first, await self.revoke_invite(ident, 200))
        await self.response(await self.join_invite(token), 410, "invite_expired")
        self.now = expires + timedelta(seconds=1)
        self.assertEqual(first, await self.revoke_invite(ident, 200))

        used, used_token, _ = await self.make_invite()
        self.assertEqual((await self.join_invite(used_token)).status, 201)
        expired, _, expires = await self.make_invite()
        self.now = expires + timedelta(seconds=1)
        for closed in (used, expired):
            await self.revoke_invite(closed, 409, "invite_closed")
        self.assertEqual(self.db.admin("SELECT revoked_at FROM marong.invites WHERE id IN (%s,%s)", (used, expired)),
                         [(None,), (None,)])
        await self.store.close()
        await self.revoke_invite(ident, 503, "db_unavailable")

    async def test_tc635_join_and_revoke_compete_for_the_same_row(self):
        ident, token, _ = await self.make_invite()
        async with self.store.pool.connection() as conn, conn.transaction():
            await one(conn, "SELECT id FROM marong.invites WHERE id=%s FOR UPDATE", (ident,))
            tasks = [asyncio.create_task(self.join_invite(token)), asyncio.create_task(
                self.client.post(f"/chat/admin/api/invites/{ident}/revoke", headers=self.headers))]
            async with asyncio.timeout(4):
                while True:
                    await conn.execute("SELECT pg_stat_clear_snapshot()")
                    waiting = await one(conn, """
                        SELECT count(*) FROM pg_stat_activity WHERE usename=current_user AND wait_event_type='Lock'
                    """)
                    if waiting["count"] == 2:
                        break
                    await asyncio.sleep(.02)
        joined, revoked = await asyncio.gather(*tasks)
        self.assertIn((joined.status, revoked.status), {(201, 409), (410, 200)})


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    unittest.main()
