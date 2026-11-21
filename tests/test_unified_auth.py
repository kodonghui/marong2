"""Unified invite and device-session API tests against temporary PostgreSQL."""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import WSServerHandshakeError, web
from aiohttp.test_utils import TestClient, TestServer
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE
from marong.discord_store import DiscordStore
from marong.friend_card import FriendCards
from marong.unified_store import UnifiedStore
from pg import TestDB


ORIGIN = "https://fixture.invalid"
INVITES = "/chat/api/invites/"
JOIN = "/chat/api/join"
LOGIN = "/chat/api/login/code"
CODES = "/chat/api/device-codes"
LOGOUT = "/chat/api/logout"


class UnifiedAuthTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = TestDB()
        self.addCleanup(self.db.close)
        self.db.apply_unified_prerequisites()
        self.db.apply_unified()
        self.store = UnifiedStore(self.db.app_url)
        await self.store.open(wait=True)
        self.addAsyncCleanup(self.store.close)
        self.now = datetime(2026, 1, 3, 12, tzinfo=timezone.utc)
        self.key = secrets.token_bytes(32)
        self.sessions = AppSessions(self.store.pool, self.key, contact_schedule=(3, 8, 22), now=lambda: self.now)
        self.admin_hash = hashlib.sha256(b"fixture-admin").hexdigest()
        self.chat = AppChat(self.store, SimpleNamespace(friend_cards=None), None, None, None,
                            origin=ORIGIN, sessions=self.sessions, authentication="session",
                            admin_email_hash=self.admin_hash)
        self.client = TestClient(TestServer(self.chat.web_app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def post(self, path, payload=None, *, token=None, origin=ORIGIN):
        headers = {"Origin": origin, "CF-Connecting-IP": "192.0.2.15"}
        if token is not None:
            headers["Cookie"] = f"{COOKIE}={token}"
        return await self.client.post(path, json=payload, headers=headers)

    async def problem(self, response, status, code):
        self.assertEqual(response.status, status)
        self.assertEqual(response.content_type, "application/problem+json")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        data = await response.json()
        self.assertEqual((data["status"], data["code"]), (status, code))
        self.assertRegex(data["traceId"], r"^[a-f0-9]{16}$")
        self.assertEqual(data["type"], f"{ORIGIN}/problems/{code.replace('_', '-')}")

    async def joined(self):
        invite, _ = await self.sessions.create_invite("join")
        response = await self.post(JOIN, {"token": invite, "name": "Fixture"})
        self.assertEqual(response.status, 201)
        return response.cookies[COOKIE].value

    async def test_admin_invites_members_ticket_balance_and_revocation(self):
        base = "/chat/admin"
        admin = {"Cf-Access-Jwt-Assertion": "fixture-admin", "Origin": ORIGIN}
        self.chat.access = SimpleNamespace(check=AsyncMock(side_effect=lambda token: (
            "ok", hashlib.sha256(token.encode()).hexdigest())))
        cookie = await self.joined()
        owner = (await self.sessions.find_session(cookie))["friend_id"]
        member_cookie = {"Cookie": f"{COOKIE}={cookie}", "Origin": ORIGIN}
        for suffix in ("/", "/api/invites", "/api/members"):
            for headers in (member_cookie, {"Cf-Access-Jwt-Assertion": "fixture-member"}):
                await self.problem(await self.client.get(base + suffix, headers=headers), 403, "not_allowed")
        response = await self.client.get(base + "/", headers=admin)
        self.assertEqual(response.status, 200)
        self.assertIn("/chat/admin.js", await response.text())
        for asset in ("unified.js", "admin.js", "account.js", "unified.css"):
            self.assertEqual((await self.client.get("/chat/" + asset)).status, 200)
        path = base + "/api/invites"
        await self.problem(await self.client.post(path, json={"kind": "join"}, headers={
            **admin, "Origin": "https://other.invalid"}), 403, "cross_site")
        for payload in ({"kind": "join", "friendId": None}, {"kind": "link", "friendId": 0},
                        {"kind": "join", "note": "x" * 41}):
            await self.problem(await self.client.post(path, json=payload, headers=admin), 400, "invalid_input")
        unknown = 100_000
        await self.problem(await self.client.post(path, json={"kind": "relogin", "friendId": unknown}, headers=admin),
                           404, "not_found")
        legacy = self.db.admin("INSERT INTO marong.friends(name) VALUES ('Fixture legacy') RETURNING id")[0][0]
        await self.problem(await self.client.post(path, json={"kind": "relogin", "friendId": legacy}, headers=admin),
                           400, "invalid_input")
        invite = await self.client.post(path, json={"kind": "link", "friendId": legacy, "note": "Fixture"}, headers=admin)
        self.assertEqual(invite.status, 201)
        self.assertEqual(invite.headers["Cache-Control"], "no-store")
        url = (await invite.json())["url"]
        self.assertTrue(url.startswith(ORIGIN + "/chat/join/"))
        page = await self.client.get(url.removeprefix(ORIGIN))
        self.assertEqual(page.status, 200)
        self.assertNotIn(url.rsplit("/", 1)[1], await page.text())
        invite_list = await (await self.client.get(path, headers=admin)).json()
        self.assertNotIn(url, str(invite_list))
        self.assertEqual([item["state"] for item in invite_list["invites"]], ["open", "used"])
        people = await (await self.client.get(base + "/api/members", headers=admin)).json()
        self.assertEqual(people["unlinked"], [{"friendId": legacy, "name": "Fixture legacy"}])
        self.assertEqual((people["members"][0]["friendId"], people["members"][0]["sessions"]), (owner, 1))
        ticket = base + f"/api/members/{owner}/tickets"
        for add in (0, 1001, False, "5"):
            await self.problem(await self.client.post(ticket, json={"add": add}, headers=admin), 400, "invalid_input")
        for expected, add in ((3, 3), (8, 5)):
            response = await self.client.post(ticket, json={"add": add}, headers=admin)
            self.assertEqual((response.status, await response.json()), (200, {"tickets": expected}))
        profile_query = "SELECT bot_name, friend_code, tickets FROM marong.friend_profiles WHERE friend_id=%s"
        before = self.db.admin(profile_query, (owner,))
        linked = await self.client.post(path, json={"kind": "link", "friendId": owner}, headers=admin)
        self.assertEqual(linked.status, 201)
        link_token = (await linked.json())["url"].rsplit("/", 1)[1]
        redemption = await self.post(JOIN, {"token": link_token})
        self.assertEqual(redemption.status, 201)
        new_session = await self.sessions.find_session(redemption.cookies[COOKIE].value)
        self.assertEqual(new_session["friend_id"], owner)
        self.assertEqual(self.db.admin(profile_query, (owner,)), before)
        await self.problem(await self.post(JOIN, {"token": link_token}), 410, "invite_used")
        await self.problem(await self.client.post(base + f"/api/members/{unknown}/tickets", json={"add": 1},
                                                 headers=admin), 404, "not_found")
        code, _ = await self.sessions.create_device_code(owner)
        other_cookie = await self.joined()
        revoke = base + f"/api/members/{owner}/revoke"
        for _ in range(2):
            self.assertEqual((await self.client.post(revoke, headers=admin)).status, 204)
        await self.problem(await self.client.get("/chat/api/me", headers=member_cookie), 401, "login_required")
        await self.problem(await self.client.get("/chat/api/me", headers={
            "Cookie": f"{COOKIE}={redemption.cookies[COOKIE].value}",
        }), 401, "login_required")
        self.assertIsNotNone(await self.sessions.find_session(other_cookie))
        await self.problem(await self.post(LOGIN, {"code": code}), 401, "code_wrong")
        people = await (await self.client.get(base + "/api/members", headers=admin)).json()
        member = next(member for member in people["members"] if member["friendId"] == owner)
        self.assertEqual((member["tickets"], member["sessions"]), (8, 0))

        invite = await self.client.post(path, json={"kind": "join"}, headers=admin)
        self.assertEqual(invite.status, 201)
        address = (await invite.json())["url"]
        token = address.rsplit("/", 1)[1]
        available = await self.client.get(INVITES + token)
        self.assertEqual((available.status, await available.json()), (200, {"kind": "join", "state": "open"}))
        fresh = await self.post(JOIN, {"token": token, "name": "New Fixture"})
        self.assertEqual(fresh.status, 201)
        self.assertEqual(await fresh.json(), {"friendName": "New Fixture", "botName": "마롱이"})
        cookie = fresh.cookies[COOKIE]
        self.assertTrue(cookie["secure"] and cookie["httponly"])
        self.assertEqual((cookie["path"], cookie["samesite"]), ("/", "Lax"))
        profile = await self.client.get("/chat/api/profile", headers={"Cookie": f"{COOKIE}={cookie.value}"})
        self.assertEqual(profile.status, 200)
        self.assertEqual((await profile.json())["friendName"], "New Fixture")
        listed = await (await self.client.get(path, headers=admin)).json()
        self.assertNotIn(token, str(listed))

    async def test_check_redeem_and_validate_invites(self):
        token, expiry = await self.sessions.create_invite("join")
        self.assertEqual(expiry - self.now, timedelta(days=7))
        for invalid in ("bad-format", secrets.token_urlsafe(32)):
            await self.problem(await self.client.get(INVITES + invalid), 404, "invite_not_found")
            await self.problem(await self.post(JOIN, {"token": invalid, "name": "Tester"}), 404, "invite_not_found")
        await self.problem(await self.post(JOIN, {"token": token, "name": " "}), 400, "invalid_input")
        await self.problem(await self.post(JOIN, {"token": token, "name": "x" * 13}), 400, "invalid_input")
        await self.problem(await self.post(JOIN, {"token": token, "name": "Tester"}, origin="https://other.invalid"),
                           403, "cross_site")
        self.now = expiry - timedelta(hours=1)
        checked = await self.client.get(INVITES + token)
        self.assertEqual(checked.status, 200)
        self.assertEqual(await checked.json(), {"kind": "join", "state": "open"})
        self.assertEqual(self.db.admin("SELECT token_hash,used_at FROM marong.invites"),
                         [(hashlib.sha256(token.encode()).digest(), None)])
        first, second = sorted(
            await asyncio.gather(*(self.post(JOIN, {"token": token, "name": " Tester "}) for _ in range(2))),
            key=lambda r: r.status,
        )
        self.assertEqual(first.status, 201)
        self.assertEqual(await first.json(), {"friendName": "Tester", "botName": "마롱이"})
        self.assertEqual(first.headers["Cache-Control"], "no-store")
        await self.problem(second, 410, "invite_used")
        await self.problem(await self.client.get(INVITES + token), 410, "invite_used")
        self.assertEqual(self.db.admin("SELECT count(*) FROM marong.friends"), [(1,)])
        self.assertEqual(self.db.admin("SELECT kind,used_by FROM marong.invites"), [("join", 1)])
        expired, expiry = await self.sessions.create_invite("join")
        self.now = expiry + timedelta(minutes=1)
        await self.problem(await self.client.get(INVITES + expired), 410, "invite_expired")
        await self.problem(await self.post(JOIN, {"token": expired, "name": "Tester"}), 410, "invite_expired")
        self.assertEqual(self.db.admin("SELECT count(*) FROM marong.friends"), [(1,)])

    async def test_cookie_session_renewal_expiry_and_logout(self):
        invite, _ = await self.sessions.create_invite("join")
        response = await self.post(JOIN, {"token": invite, "name": "Tester"})
        cookie = response.cookies[COOKIE]
        self.assertTrue(cookie["secure"] and cookie["httponly"])
        self.assertEqual((cookie["path"], cookie["samesite"], cookie["max-age"]), ("/", "Lax", "7776000"))
        token = cookie.value
        self.assertIsNotNone(re.fullmatch(r"[A-Za-z0-9_-]{43}", token))
        self.assertEqual(self.db.admin("SELECT token_hash,method,label FROM marong.app_sessions"),
                         [(hashlib.sha256(token.encode()).digest(), "invite", "웹")])
        self.now += timedelta(hours=1)
        saved = await self.sessions.find_session(token)
        self.assertFalse(saved["renewed"])
        await self.problem(await self.post(CODES), 401, "login_required")
        self.now += timedelta(hours=24)
        rolled_cookie = await self.post(CODES, token=token)
        self.assertEqual(rolled_cookie.cookies[COOKIE].value, token)
        self.assertEqual(self.db.admin("SELECT last_seen_at,expires_at FROM marong.app_sessions"),
                         [(self.now, self.now + timedelta(days=90))])
        self.now += timedelta(days=89)
        self.assertTrue((await self.sessions.find_session(token))["renewed"])
        self.now += timedelta(days=90, minutes=1)
        await self.problem(await self.post(CODES, token=token), 401, "login_required")
        other = await self.joined()
        await self.problem(await self.post(LOGOUT, token=other, origin="https://other.invalid"), 403, "cross_site")
        self.assertIsNotNone(await self.sessions.find_session(other))
        logged_out = await self.post(LOGOUT, token=other)
        self.assertEqual((logged_out.status, logged_out.cookies[COOKIE]["max-age"]), (204, "0"))
        self.assertEqual((await self.post(LOGOUT)).status, 204)
        await self.problem(await self.post(CODES, token=other), 401, "login_required")

    async def test_code_replacement_redemption_and_limits(self):
        token = await self.joined()
        await self.problem(await self.post(LOGIN, {"code": "02479"}), 400, "invalid_input")
        await self.problem(await self.post(LOGIN, {"code": "006531"}, origin="https://other.invalid"),
                           403, "cross_site")
        await self.problem(await self.post(CODES, token=token, origin="https://other.invalid"), 403, "cross_site")
        with patch("marong.app_session.secrets.randbelow", side_effect=[31, 44, 57, 64, 78, 83]):
            one = await (await self.post(CODES, token=token)).json()
            two = await (await self.post(CODES, token=token)).json()
            self.assertEqual(two["code"], "000044")
            self.assertEqual(self.db.admin("SELECT code_hash FROM marong.device_codes ORDER BY id"),
                             [(hmac.digest(self.key, c.encode(), "sha256"),) for c in (one["code"], two["code"])])
            await self.problem(await self.post(LOGIN, {"code": one["code"]}), 401, "code_wrong")
            responses = await asyncio.gather(*(self.post(LOGIN, {"code": two["code"]}) for _ in range(2)))
            self.assertEqual(sorted(r.status for r in responses), [200, 401])
            signed = next(r for r in responses if r.status == 200)
            self.assertEqual(await signed.json(), {"friendName": "Fixture", "botName": "마롱이"})
            self.assertEqual((await self.sessions.find_session(signed.cookies[COOKIE].value))["friend_id"], 1)
            old = await (await self.post(CODES, token=token)).json()
            self.now += timedelta(minutes=10, seconds=1)
            await self.problem(await self.post(LOGIN, {"code": old["code"]}), 401, "code_wrong")
            for _ in range(4):  # expired code above was the first miss in this window
                await self.problem(await self.post(LOGIN, {"code": "456789"}), 401, "code_wrong")
            self.now += timedelta(minutes=1)
            active = await (await self.post(CODES, token=token)).json()
            blocked = await self.post(LOGIN, {"code": active["code"]})
            await self.problem(blocked, 429, "too_many_tries")
            self.assertEqual(blocked.headers["Retry-After"], "540")
            self.now += timedelta(minutes=9, seconds=1)
            self.assertEqual((await self.post(LOGIN, {"code": active["code"]})).status, 200)
            self.assertEqual((await self.post(CODES, token=token)).status, 201)
            limited = await self.post(CODES, token=token)
            await self.problem(limited, 429, "too_many_codes")
            self.assertGreater(int(limited.headers["Retry-After"]), 0)

    async def test_provision_and_rollback_and_link_to_existing_room(self):
        self.db.admin("""
            CREATE FUNCTION fail_fixture() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'fixture caller insert failure'; END
            $$;
            CREATE TRIGGER fail_fixture BEFORE INSERT ON call.callers
                FOR EACH ROW EXECUTE FUNCTION fail_fixture();
        """, None)
        invite, _ = await self.sessions.create_invite("join")
        await self.problem(await self.post(JOIN, {"token": invite, "name": "Fixture"}), 500, "internal")
        for table in ("friends", "rooms", "people", "friend_profiles", "contact_settings", "app_sessions"):
            self.assertEqual(self.db.admin(f"SELECT count(*) FROM marong.{table}"), [(0,)])
        self.assertEqual(self.db.admin("SELECT used_at,used_by FROM marong.invites"), [(None, None)])
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.kakao_guards"), [(0,)])
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.callers"), [(0,)])
        self.db.admin("DROP TRIGGER fail_fixture ON call.callers")
        created = await self.post(JOIN, {"token": invite, "name": "Fixture"})
        self.assertEqual(created.status, 201)
        friend = self.db.admin("SELECT id FROM marong.friends")[0][0]
        self.assertEqual(self.db.admin("SELECT room_key,owner_friend_id FROM marong.rooms"), [(f"app:{friend}", friend)])
        self.assertEqual(self.db.admin("SELECT user_key,friend_id FROM marong.people"), [(f"app-user:{friend}", friend)])
        self.assertEqual(self.db.admin("SELECT room_key,friend_id FROM call.kakao_guards"), [(f"app:{friend}", friend)])
        self.assertEqual(self.db.admin("SELECT friend_id,enabled FROM call.callers"), [(friend, True)])
        self.assertEqual(self.db.admin("SELECT per_day,start_hour,end_hour FROM marong.contact_settings"), [(3, 8, 22)])
        self.assertRegex(self.db.admin("SELECT friend_code FROM marong.friend_profiles")[0][0], r"^[A-HJ-NP-Z2-9]{6}$")
        old = self.db.admin("INSERT INTO marong.friends(name) VALUES ('Existing') RETURNING id")[0][0]
        old_room = "discord-dm:10000000000000012"
        self.db.admin("INSERT INTO marong.rooms(room_key,is_channel,owner_friend_id) VALUES (%s,true,%s)", (old_room, old))
        self.db.admin("INSERT INTO marong.messages(room_key,role,content) VALUES (%s,'assistant','Fixture history')", (old_room,))
        link, _ = await self.sessions.create_invite("link", old)
        linked = await self.post(JOIN, {"token": link, "name": "Ignored"})
        self.assertEqual(await linked.json(), {"friendName": "Existing", "botName": "마롱이"})
        linked_session = await self.sessions.find_session(linked.cookies[COOKIE].value)
        self.assertEqual((linked_session["friend_id"], linked_session["room_key"]), (old, old_room))
        self.assertEqual(self.db.admin("SELECT count(*) FROM marong.rooms WHERE owner_friend_id=%s", (old,)), [(1,)])
        self.assertEqual(self.db.admin("SELECT count(*) FROM marong.messages"), [(1,)])
        again, _ = await self.sessions.create_invite("relogin", old)
        response = await self.post(JOIN, {"token": again}, token=linked.cookies[COOKIE].value)
        self.assertEqual(response.status, 201)
        self.assertIsNotNone(await self.sessions.find_session(linked.cookies[COOKIE].value))

    async def test_auth_errors_follow_contract(self):
        cases = (
            ("check_invite", lambda: self.client.get(INVITES + "x" * 43)),
            ("join", lambda: self.post(JOIN, {"token": "x" * 43, "name": "Fixture"})),
            ("redeem_device_code", lambda: self.post(LOGIN, {"code": "456789"})),
            ("find_session", lambda: self.post(CODES, token="x" * 43)),
            ("logout", lambda: self.post(LOGOUT, token="x" * 43)),
        )
        for method, request in cases:
            for error, status, code in ((psycopg.OperationalError, 503, "db_unavailable"),
                                        (RuntimeError, 500, "internal")):
                with self.subTest(method=method, status=status):
                    with patch.object(self.sessions, method, AsyncMock(side_effect=error("fixture"))):
                        await self.problem(await request(), status, code)

    async def test_unified_auth_modes_and_chat_without_discord_link(self):
        token = await self.joined()
        saved = await self.sessions.find_session(token)
        email_hash = hashlib.sha256(b"fixture@example.invalid").hexdigest()
        self.db.admin("""
            INSERT INTO call.caller_logins(email_sha256,caller_id,email_hint) VALUES (%s,%s,'f***@example.invalid')
        """, (email_hash, saved["caller_id"]))
        self.chat.access = SimpleNamespace(check=AsyncMock(return_value=("ok", email_hash)))
        self.chat.push = AppPush(self.store)
        self.chat.client = SimpleNamespace(room_lock=lambda _: asyncio.Lock())
        self.chat.agent.friend_cards = FriendCards(self.store)

        async def answer(message, deliver):
            reply = "Synthetic reply"
            await deliver(reply)
            await self.store.add_message(message.room_key, "assistant", reply, reply_to=message.presaved_id,
                                         meta={"delivered": True})
            return reply

        self.chat.agent.handle = answer
        cookie = {"Cookie": f"{COOKIE}={token}"}
        access = {"Cf-Access-Jwt-Assertion": "fixture"}
        for mode, expectations in (("access", (401, 200)), ("both", (200, 200)), ("session", (200, 401))):
            self.chat.authentication = mode
            for headers, expected in zip((cookie, access), expectations, strict=True):
                reply = await self.client.get("/chat/api/me", headers=headers)
                self.assertEqual(reply.status, expected)
                await reply.read()
        redirect = await self.client.get("/chat/", allow_redirects=False)
        self.assertEqual((redirect.status, redirect.headers["Location"]), (302, "/chat/login"))
        posted = await self.post("/chat/api/messages", {
            "text": "Synthetic question", "clientId": "4b832c6a-722e-4376-a580-8e703395998e",
        }, token=token)
        self.assertEqual(posted.status, 202)
        await posted.read()
        if self.chat.tasks:
            await asyncio.gather(*self.chat.tasks)
        history = await self.client.get("/chat/api/messages", headers=cookie)
        self.assertEqual(history.status, 200)
        self.assertEqual([row["text"] if "text" in row else row["content"] for row in (await history.json())["messages"]],
                         ["Synthetic question", "Synthetic reply"])
        device = await self.client.put("/chat/api/devices/cdddb5b9-33ad-4c06-b696-3028c7e89102",
                                       headers={**cookie, "Origin": ORIGIN},
                                       json={"fid": None, "notifications": "granted", "appVersion": "0.3.0"})
        self.assertEqual(device.status, 201)
        self.assertEqual((await self.client.get("/chat/persona/api/card", headers=cookie)).status, 200)
        self.assertEqual(self.db.admin("SELECT count(*) FROM marong.discord_dm_links"), [(0,)])

    async def test_call_server_uses_unified_session_with_call_role(self):
        path = Path(__file__).resolve().parents[1] / "tools" / "vertex_live"
        sys.path.insert(0, str(path))
        self.addCleanup(sys.path.remove, str(path))
        with tempfile.TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)):
            import server as call_server
        token = await self.joined()
        member = await self.sessions.find_session(token)
        call_pool = call_server.MemoryStore(self.db.app_url.replace("marong@", "marong_call@", 1))
        await call_pool.pool.open(wait=True)
        self.addAsyncCleanup(call_pool.pool.close)
        self.db.admin("UPDATE marong.app_sessions SET last_seen_at=now()-interval '25 hours', "
                      "expires_at=now()+interval '10 days'")
        served = []

        class FixtureCall:
            def __init__(self, ws, owner, memory, person, *_args, **_kwargs):
                self.ws = ws
                served.append((owner, person.friend_id))

            async def run(self):
                await self.ws.send_json({"type": "fixture_call"})

        with patch.multiple(call_server, AUTHENTICATION="session", memory_store=call_pool, LiveSession=FixtureCall):
            app = web.Application(middlewares=[call_server.security_headers])
            app.router.add_get("/api/me", call_server.status)
            app.router.add_get("/live", call_server.live)
            app.router.add_get("/", call_server.static)
            app.router.add_post("/auth", call_server.auth)
            async with TestClient(TestServer(app)) as client:
                self.assertEqual((await client.get("/api/me")).status, 401)
                self.assertEqual((await client.get("/", allow_redirects=False)).headers["Location"], "/chat/login")
                self.assertEqual((await client.post("/auth")).status, 404)
                by_cookie = {"Cookie": f"{COOKIE}={token}"}
                me = await client.get("/api/me", headers=by_cookie)
                self.assertEqual((me.status, (await me.json())["name"]), (200, "Fixture"))
                self.assertEqual(me.cookies[COOKIE]["max-age"], "7776000")
                origin = str(client.make_url("/")).rstrip("/")
                with self.assertRaises(WSServerHandshakeError) as failure:
                    await client.ws_connect("/live", headers={"Origin": origin})
                self.assertEqual(failure.exception.status, 401)
                with self.assertRaises(WSServerHandshakeError) as failure:
                    await client.ws_connect("/live", headers={**by_cookie, "Origin": "https://other.invalid"})
                self.assertEqual(failure.exception.status, 403)
                async with client.ws_connect("/live", headers={**by_cookie, "Origin": origin}) as ws:
                    self.assertEqual(await ws.receive_json(), {"type": "fixture_call"})
                self.assertEqual(served, [(f"friend:{member['friend_id']}", member["friend_id"])])
                self.db.admin("UPDATE call.callers SET enabled=false")
                self.assertEqual((await client.get("/api/me", headers=by_cookie)).status, 403)
                self.db.admin("UPDATE call.callers SET enabled=true")
                self.chat.access = SimpleNamespace(check=AsyncMock(return_value=("ok", self.admin_hash)))
                revoked = await self.client.post(f"/chat/admin/api/members/{member['friend_id']}/revoke",
                    headers={"Cf-Access-Jwt-Assertion": "fixture-admin", "Origin": ORIGIN})
                self.assertEqual(revoked.status, 204)
                self.assertEqual((await client.get("/api/me", headers=by_cookie)).status, 401)
                with self.assertRaises(WSServerHandshakeError) as failure:
                    await client.ws_connect("/live", headers={**by_cookie, "Origin": origin})
                self.assertEqual(failure.exception.status, 401)

    async def test_owned_room_scope_for_recent_text_search_and_embeddings(self):
        member_a = await self.sessions.find_session(await self.joined())
        member_b = await self.sessions.find_session(await self.joined())
        room_a, room_b = member_a["room_key"], member_b["room_key"]
        self.db.admin("""
            INSERT INTO marong.rooms(room_key,is_channel,owner_friend_id)
              VALUES ('linked-but-shared',true,%s), ('ownerless',true,NULL)
        """, (member_a["friend_id"],))
        rooms = ((room_a, member_a["user_key"], "synthetic alpha"),
                 (room_b, member_b["user_key"], "synthetic beta"),
                 ("linked-but-shared", member_b["user_key"], "synthetic shared"),
                 ("ownerless", member_a["user_key"], "synthetic ownerless"))
        for room, person, content in rooms:
            msg = self.db.admin("""
                INSERT INTO marong.messages(room_key,user_key,role,content) VALUES (%s,%s,'user',%s) RETURNING id
            """, (room, person, content))[0][0]
            self.db.admin("""
                INSERT INTO marong.summaries(room_key,first_id,last_id,content) VALUES (%s,%s,%s,%s)
            """, (room, msg, msg, content + " summary"))
            self.db.admin("INSERT INTO marong.notes(room_key,user_key,content) VALUES (%s,%s,%s)",
                          (room, person, content + " note"))
            self.db.admin("""
                INSERT INTO marong.embeddings(model,source_type,source_id,room_key,embedding)
                  VALUES ('fixture','message',%s,%s,'[1,0]')
            """, (msg, room))
        unified = UnifiedStore(self.db.app_url)
        await unified.open(wait=True)
        self.addAsyncCleanup(unified.close)
        self.assertEqual([m["content"] for m in await unified.recent_turns(room_a, 5, 20)], ["synthetic alpha"])
        self.assertEqual([m["content"] for m in await unified.recent_turns(room_b, 5, 20)], ["synthetic beta"])
        self.assertEqual(await unified.recent_turns("ownerless", 5, 20), [])
        self.assertEqual([m["content"] for m in await unified.summaries(room_a, 10)], ["synthetic alpha summary"])
        self.assertEqual([m["content"] for m in await unified.notes(room_a)], ["synthetic alpha note"])
        hits, _ = await unified.keyword_hits(room_a, ["synthetic"], 100, [])
        self.assertEqual({m["content"] for m in hits}, {"synthetic alpha", "synthetic alpha summary"})
        vector = await unified.similar("fixture", room_a, [1, 0], 100, [], 10)
        self.assertEqual([m["content"] for m in vector], ["synthetic alpha"])

    async def test_migrated_legacy_chat_context_matches_existing_read(self):
        link_data = (
            ("10000000000000001", "fixture-kakao-one"),
            ("10000000000000002", "fixture-kakao-two"),
        )
        for suffix, private_room in link_data:
            friend = self.db.admin("INSERT INTO marong.friends(name) VALUES ('Existing') RETURNING id")[0][0]
            discord_room, user = f"discord-dm:{suffix}", f"discord-user:{suffix}"
            self.db.admin("""
                INSERT INTO marong.rooms(room_key,is_channel,owner_friend_id) VALUES (%s,true,%s),(%s,true,%s)
            """, (discord_room, friend, private_room, friend))
            self.db.admin("INSERT INTO marong.people(user_key,friend_id) VALUES (%s,%s)", (user, friend))
            self.db.admin("""
                INSERT INTO marong.discord_dm_links(discord_user_id,friend_id,room_key,kakao_room_key,user_key,
                                                     per_day,start_hour,end_hour)
                VALUES (%s,%s,%s,%s,%s,1,9,21)
            """, (suffix, friend, discord_room, private_room, user))
            for room in (discord_room, private_room):
                msg = self.db.admin("""
                    INSERT INTO marong.messages(room_key,user_key,role,content)
                    VALUES (%s,%s,'user','Synthetic reply context') RETURNING id
                """, (room, user))[0][0]
                self.db.admin("INSERT INTO marong.summaries(room_key,first_id,last_id,content) VALUES (%s,%s,%s,'Fixture')",
                              (room, msg, msg))
                self.db.admin("INSERT INTO marong.notes(room_key,user_key,content) VALUES (%s,%s,'Fixture')", (room, user))
            token, _ = await self.sessions.create_invite("link", friend)
            await self.sessions.join(token, None, "웹")

        unified = UnifiedStore(self.db.app_url)
        await unified.open(wait=True)
        self.addAsyncCleanup(unified.close)
        for suffix, _ in link_data:
            room = f"discord-dm:{suffix}"
            self.assertEqual(await unified.recent_turns(room, 5, 20), await self.store.recent_turns(room, 5, 20))
            self.assertEqual(await unified.summaries(room, 10), await self.store.summaries(room, 10))
            self.assertEqual(await unified.notes(room), await self.store.notes(room))


if __name__ == "__main__":
    unittest.main()
