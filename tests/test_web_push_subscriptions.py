"""TASK-561–564: installation-scoped API-310–313 against isolated PostgreSQL."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import secrets
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from aiohttp import WSServerHandshakeError, web
from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import http_ece
import jwt
from psycopg import OperationalError

from test_web_push_schema import MIGRATION, ROOT, app_database, session
from marong.app_chat import AppChat
from marong.app_session import AppSessions, COOKIE, token_hash
from marong.unified_delivery import UnifiedDelivery
from marong.unified_store import UnifiedStore
from marong.web_push_delivery import AppleWebPush, ProviderResult, WebPushDelivery, configured_web_push
from marong.web_push_subscriptions import (
    CHOICE_HEADER, INSTALLATION_HEADER, PATH, ActiveSubscriptionMaterial, WebPushSubscriptions, encode,
    installation_id,
)
from marong.web_push_targets import NoticeReferences
from marong.web_notice_call_protocol import SUBPROTOCOL, NoticeCallProtocol, client_uuid


ORIGIN = "https://fixture.invalid"
SUB = PATH + "/subscription"
INTENT = SUB + "/intent"
LOGOUT = "/chat/api/logout"
RESOLVE = PATH + "/target/resolve"
VIEW = PATH + "/reply-view"
ACCEPT = PATH + "/call/accept"


class FakeRequest:
    def __init__(self, *, wait=False, fail=False):
        self.writing = asyncio.Event()
        self.release = asyncio.Event()
        self.wait = wait
        self.fail = fail
        self.handed = []
        self.aborted = 0
        self.response = AsyncMock(return_value=ProviderResult(201))

    async def write(self, ttl):
        self.writing.set()
        if self.wait:
            await self.release.wait()
        if self.fail:
            raise OSError
        self.handed.append(ttl)

    def abort(self):
        self.aborted += 1


def point():
    return encode(ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint))


class WebPushSubscriptionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = app_database()
        cls.addClassCleanup(cls.db.close)
        cls.db.apply_sql(MIGRATION)

    async def asyncSetUp(self):
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.monotonic = 0
        self.token = secrets.token_urlsafe(32)
        self.alt = secrets.token_urlsafe(32)
        self.proof = secrets.token_urlsafe(32)
        self.other_proof = secrets.token_urlsafe(32)
        self.sid = session(self.db, token_hash(self.token))
        self.alt_sid = session(self.db, token_hash(self.alt))
        self.store = UnifiedStore(self.db.app_url)
        await self.store.open(wait=True)
        self.addAsyncCleanup(self.store.close)
        self.sessions = AppSessions(self.store.pool, secrets.token_bytes(32), contact_schedule=(3, 8, 22))
        self.public_key = point()
        material = ActiveSubscriptionMaterial("fixture", {"fixture": secrets.token_bytes(32)}, secrets.token_bytes(32))
        self.service = WebPushSubscriptions(self.store.pool, authentication_key=secrets.token_bytes(32),
                                            material=material, active_vapid_key="fixture",
                                            vapid_public_keys={"fixture": self.public_key},
                                            now=lambda: self.now, monotonic=lambda: self.monotonic,
                                            resolve=AsyncMock(return_value=("1.1.1.1",)))
        self.references = NoticeReferences(secrets.token_bytes(32), timedelta(days=1))
        self.transport = Mock()
        self.transport.prepare = AsyncMock(side_effect=lambda *args, **kwargs: FakeRequest())
        self.delivery = WebPushDelivery(self.service, self.references, self.transport, origin=ORIGIN,
                                        tag_key=secrets.token_bytes(32), sleep=AsyncMock())
        self.chat = AppChat(self.store, None, None, None, None, origin=ORIGIN,
                            sessions=self.sessions, authentication="session", web_push_subscriptions=self.service,
                            web_push_references=self.references)
        self.chat.web_push_delivery = self.delivery
        self.client = TestClient(TestServer(self.chat.web_app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def request(self, method, path, *, proof=True, token=True, choice=None, body=None, headers=None):
        values = {}
        if method != "GET":
            values["Origin"] = ORIGIN
        if proof is not None:
            values[INSTALLATION_HEADER] = self.proof if proof is True else proof
        if token is not None:
            values["Cookie"] = f"{COOKIE}={self.token if token is True else token}"
        if choice is not None:
            values[CHOICE_HEADER] = choice
        return await self.client.request(method, path, json=body, headers={**values, **(headers or {})})

    async def problem(self, response, status, code):
        self.assertEqual(response.status, status)
        self.assertEqual(response.content_type, "application/problem+json")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        error = await response.json()
        self.assertEqual((error["status"], error["code"]), (status, code))
        self.assertRegex(error["traceId"], r"^[a-f0-9]{16}$")
        self.assertTrue(error["title"])
        if status == 429:
            self.assertRegex(response.headers["Retry-After"], r"^[1-9][0-9]{0,3}$")

    async def state(self, response, expected):
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        body = await response.json()
        self.assertEqual(set(body), {"state", "stateToken", "vapid"})
        self.assertEqual(body["state"], expected)
        self.assertRegex(body["stateToken"], r"^[A-Za-z0-9_-]{48,512}$")
        self.assertEqual(body["vapid"], {"keyId": "fixture", "publicKey": self.public_key})
        return body

    async def select(self, action, *, prior=None, proof=True, token=True):
        if prior is None:
            before = await self.request("GET", SUB, proof=proof, token=token)
            self.assertEqual(before.status, 200)
            prior = (await before.json())["stateToken"]
        response = await self.request("POST", INTENT, proof=proof, token=token,
                                      body={"action": action, "stateToken": prior})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        body = await response.json()
        self.assertEqual(set(body), {"choiceToken", "expiresAt"})
        self.assertRegex(body["choiceToken"], r"^[A-Za-z0-9_-]{48,768}$")
        self.assertEqual(datetime.fromisoformat(body["expiresAt"]), self.now + timedelta(seconds=120))
        return body["choiceToken"]

    def subscription(self, *, expires=None):
        return {
            "vapidKeyId": "fixture",
            "subscription": {
                "endpoint": f"https://fixture.push.apple.com/{secrets.token_urlsafe(18)}",
                "expirationTime": expires,
                "keys": {"p256dh": point(), "auth": encode(secrets.token_bytes(16))},
            },
        }

    def row(self, proof=True):
        ident = installation_id(self.proof if proof is True else proof)
        return self.db.admin("""
            SELECT state, revision, endpoint_fingerprint, protected_material, subscription_expires_at
            FROM marong.web_push_subscriptions WHERE installation_id=%s
        """, (ident,))

    async def test_561_status_is_read_only_private_and_reports_5_states(self):
        await self.state(await self.request("GET", SUB), "not_registered")
        self.assertEqual(self.row(), [])
        choice = await self.select("enable")
        await self.state(await self.request("PUT", SUB, choice=choice, body=self.subscription()), "active")
        original = self.row()
        await self.state(await self.request("GET", SUB), "active")
        await self.state(await self.request("GET", SUB, token=self.alt), "not_registered")
        await self.state(await self.request("GET", SUB, proof=self.other_proof), "not_registered")
        self.assertEqual(self.row(), original)
        for state in ("revoked", "expired", "invalid"):
            self.db.admin("""
                UPDATE marong.web_push_subscriptions SET state=%s,endpoint_fingerprint=NULL,
                    protected_material=NULL WHERE session_id=%s
            """, (state, self.sid))
            await self.state(await self.request("GET", SUB), state)

    async def test_562_choices_bind_120_seconds_installation_and_session_and_do_not_write(self):
        new = await self.select("enable")
        self.assertEqual(self.row(), [])
        body = self.subscription()
        await self.problem(await self.request("PUT", SUB, choice=new, body=body, proof=self.other_proof),
                           409, "state_changed")
        await self.problem(await self.request("PUT", SUB, choice=new, body=body, token=self.alt), 409, "state_changed")
        self.now += timedelta(seconds=120)
        await self.problem(await self.request("PUT", SUB, choice=new, body=body), 409, "state_changed")
        enable = await self.select("enable")
        await self.state(await self.request("PUT", SUB, choice=enable, body=body), "active")
        original = self.row()
        for action in ("refresh", "revoke", "permission_revoked"):
            await self.select(action)
            self.assertEqual(self.row(), original)

    async def test_563_registration_replay_stale_requests_and_cross_installation_race(self):
        choice, alternate = await asyncio.gather(self.select("enable"), self.select("enable", proof=self.other_proof))
        body = self.subscription()
        first, second = await asyncio.gather(
            self.request("PUT", SUB, choice=choice, body=body),
            self.request("PUT", SUB, choice=alternate, body=body, proof=self.other_proof),
        )
        self.assertEqual(sorted((first.status, second.status)), [200, 409])
        if first.status == 409:
            await self.problem(first, 409, "subscription_conflict")
            await self.state(second, "active")
            proof, choice = self.other_proof, alternate
        else:
            await self.problem(second, 409, "subscription_conflict")
            await self.state(first, "active")
            proof = self.proof
        original = self.row(proof)
        await self.state(await self.request("PUT", SUB, proof=proof, choice=choice, body=body), "active")
        self.assertEqual(self.row(proof), original)
        self.assertNotIn(body["subscription"]["endpoint"].encode(), bytes(original[0][3]))
        refresh = await self.select("refresh", proof=proof)
        await self.state(await self.request("PUT", SUB, proof=proof, choice=refresh, body=self.subscription()), "active")
        await self.problem(await self.request("PUT", SUB, proof=proof, choice=choice, body=body), 409, "state_changed")

    async def test_564_refresh_before_revoke_and_old_revoke_after_new_consent(self):
        new = await self.select("enable")
        await self.state(await self.request("PUT", SUB, choice=new, body=self.subscription()), "active")
        old = await self.select("permission_revoked")
        refresh = await self.select("refresh")
        await self.state(await self.request("PUT", SUB, choice=refresh, body=self.subscription()), "active")
        await self.state(await self.request("DELETE", SUB, choice=old), "revoked")
        revoked = self.row()
        self.assertEqual(revoked[0][2:], (None, None, None))
        await self.state(await self.request("DELETE", SUB, choice=old), "revoked")
        self.assertEqual(self.row(), revoked)
        new = await self.select("enable")
        expiry = round(self.now.timestamp() * 1000) + 1000
        await self.state(await self.request("PUT", SUB, choice=new, body=self.subscription(expires=expiry)), "active")
        await self.problem(await self.request("DELETE", SUB, choice=old), 409, "state_changed")
        self.now += timedelta(seconds=1)
        await self.state(await self.request("GET", SUB), "expired")
        self.assertEqual(self.row()[0][0], "active")
        empty = await self.select("revoke", proof=self.other_proof)
        await self.state(await self.request("DELETE", SUB, choice=empty, proof=self.other_proof), "not_registered")
        self.assertEqual(self.row(self.other_proof), [])

    async def test_shared_error_responses_on_all_four_operations(self):
        enable = await self.select("enable")
        prior = (await (await self.request("GET", SUB)).json())["stateToken"]
        methods = (
            ("GET", SUB, {}, {"proof": "malformed"}, "status"),
            ("POST", INTENT, {"body": {"action": "enable", "stateToken": prior}}, {"body": {}}, "choice"),
            ("PUT", SUB, {"body": self.subscription(), "choice": enable}, {"body": {}}, "register"),
            ("DELETE", SUB, {"choice": enable}, {"choice": "malformed"}, "revoke"),
        )
        for method, path, valid, invalid, handler in methods:
            with self.subTest(method=method):
                await self.problem(await self.request(method, path, **(valid | invalid)), 400, "invalid_input")
                await self.problem(await self.request(method, path, **valid, token=None), 401, "login_required")
                await self.problem(await self.request(method, path, **valid, proof=None), 403, "not_allowed")
                await self.problem(await self.request(method, path, **valid, headers={"Origin": "https://off.invalid"}),
                                   403, "cross_site")
                with patch.object(self.service, handler, side_effect=OperationalError):
                    await self.problem(await self.request(method, path, **valid), 503, "db_unavailable")
                with patch.object(self.service, handler, side_effect=RuntimeError):
                    await self.problem(await self.request(method, path, **valid), 500, "internal")
        self.monotonic += 61
        for _ in range(60):
            self.service.limit(self.sid, installation_id(self.proof))
        for method, path, valid, _, _ in methods:
            await self.problem(await self.request(method, path, **valid), 429, "request_limit")
        self.assertEqual(self.row(), [])

    async def register_fixture(self, proof=True, token=True):
        selected = await self.select("enable", proof=proof, token=token)
        response = await self.request("PUT", SUB, choice=selected, body=self.subscription(), proof=proof, token=token)
        await self.state(response, "active")
        sid = self.sid if token is True else self.alt_sid
        (friend_id,), = self.db.admin("SELECT friend_id FROM marong.app_sessions WHERE id=%s", (sid,))
        return next(r for r in await self.service.recipients(friend_id)
                    if r.installation_id == installation_id(self.proof if proof is True else proof))

    async def test_565_login_switch_clears_only_verified_installation(self):
        await self.register_fixture()
        await self.register_fixture(proof=self.other_proof)
        invite, _ = await self.sessions.create_invite("join")
        response = await self.request("POST", "/chat/api/join", proof=None,
                                      body={"token": invite, "name": "Fixture A"})
        self.assertEqual(response.status, 201)
        self.assertEqual(self.row()[0][0], "active")
        friend = (await self.sessions.find_session(response.cookies[COOKIE].value))["friend_id"]
        code, _ = await self.sessions.create_device_code(friend)
        response = await self.request("POST", "/chat/api/login/code", body={"code": code})
        self.assertEqual(response.status, 200)
        changed = response.cookies[COOKIE].value
        self.assertEqual(self.row()[0][0], "revoked")
        self.assertEqual(self.row()[0][2:], (None, None, None))
        await self.state(await self.request("GET", SUB, token=changed), "not_registered")
        await self.state(await self.request("GET", SUB), "not_registered")
        self.assertEqual(self.row(self.other_proof)[0][0], "active")
        old = await self.select("enable")
        await self.problem(await self.request("PUT", SUB, choice=old, body=self.subscription()),
                           409, "subscription_conflict")
        new = await self.select("enable", token=changed)
        await self.state(await self.request("PUT", SUB, token=changed, choice=new, body=self.subscription()), "active")

    async def test_565_logout_before_handoff_and_handoff_before_logout(self):
        target = await self.register_fixture()
        until = self.now + timedelta(seconds=10)
        first = FakeRequest(wait=True)
        running = asyncio.create_task(self.service.handoff(target, until, first))
        await asyncio.wait_for(first.writing.wait(), 3)
        logout = asyncio.create_task(self.request("POST", LOGOUT))
        await asyncio.sleep(.05)
        self.assertFalse(logout.done())
        first.release.set()
        self.assertTrue(await running)
        self.assertEqual(first.handed, [10])
        response = await logout
        self.assertEqual(response.status, 204)
        self.assertEqual(self.row()[0][0], "revoked")
        self.assertFalse(await self.service.invalidate(target))
        second = FakeRequest()
        self.assertFalse(await self.service.handoff(target, until, second))
        self.assertEqual((second.handed, second.aborted), ([], 1))
        await self.problem(await self.request("GET", SUB), 401, "login_required")

    async def test_565_partial_write_timeout_deadline_and_session_expiry(self):
        target = await self.register_fixture()
        until = self.now + timedelta(seconds=10)
        partial = FakeRequest(wait=True)
        with self.assertRaises(TimeoutError):
            await self.service.handoff(target, until, partial)
        self.assertEqual((partial.handed, partial.aborted), ([], 1))
        broken = FakeRequest(fail=True)
        with self.assertRaises(OSError):
            await self.service.handoff(target, until, broken)
        self.assertEqual((broken.handed, broken.aborted), ([], 1))
        short = FakeRequest()
        self.assertFalse(await self.service.handoff(target, self.now + timedelta(milliseconds=999), short))
        self.assertEqual((short.handed, short.aborted), ([], 1))
        self.assertEqual(self.row()[0][0], "active")
        self.db.admin("UPDATE marong.app_sessions SET expires_at=created_at+interval '1 second' WHERE id=%s", (self.sid,))
        self.now += timedelta(seconds=2)
        self.assertEqual(await self.service.recipients(target.friend_id), [])
        self.assertFalse(await self.service.invalidate(target))

    async def test_572_target_resolution_all_states_and_no_writes(self):
        invite, _ = await self.sessions.create_invite("join")
        signed_in = await self.sessions.join(invite, "Fixture", "Fixture")
        who = await self.sessions.find_session(signed_in.token)
        friend = who["friend_id"]
        message = await self.store.add_message(who["room_key"], "assistant", "Synthetic reply",
                                               meta={"delivered": True})
        ref = self.references.seal("reply", friend, message, self.now)

        def request(ref, **options):
            return self.request("POST", RESOLVE, body={"targetRef": ref}, token=options.pop("token", signed_in.token),
                                **options)

        response = await request(ref)
        self.assertEqual((response.status, await response.json()), (200, {"state": "chat", "path": "/chat/"}))
        for invalid in (self.references.seal("reply", friend, message + 2**32, self.now),
                        self.references.seal("reply", friend, message, self.now - timedelta(days=1)),
                        ("A" if ref[0] != "A" else "B") + ref[1:]):
            await self.problem(await request(invalid), 404, "not_found")
        await self.problem(await request(ref, token=self.alt), 404, "not_found")
        await self.problem(await request("broken"), 400, "invalid_input")
        await self.problem(await request(ref, token=None), 401, "login_required")
        await self.problem(await request(ref, proof=None), 403, "not_allowed")
        await self.problem(await request(ref, headers={"Origin": "https://off.invalid"}), 403, "cross_site")
        self.db.admin("DELETE FROM marong.messages WHERE id=%s", (message,))
        await self.problem(await request(ref), 404, "not_found")

        (schedule,), = self.db.admin("""
            INSERT INTO marong.schedules(friend_id,source,title,event_at,action)
            VALUES (%s,'app','Fixture',now(),'call') RETURNING id
        """, (friend,))
        (ring,), = self.db.admin("""
            INSERT INTO marong.app_rings(schedule_id,friend_id,caller_id,via,title,answer_until)
            VALUES (%s,%s,%s,'app','Fixture',%s) RETURNING id
        """, (schedule, friend, who["caller_id"], self.now + timedelta(seconds=5)))
        ref = self.references.seal("call", friend, ring, self.now)
        original = self.db.admin("SELECT * FROM marong.app_rings WHERE id=%s", (ring,))
        response = await request(ref)
        data = await response.json()
        self.assertEqual((response.status, data["state"]), (200, "ring_ready"))
        self.assertEqual(datetime.fromisoformat(data["answerUntil"]), self.now + timedelta(seconds=5))
        self.db.admin("UPDATE call.callers SET enabled=false WHERE id=%s", (who["caller_id"],))
        self.assertEqual(await (await request(ref)).json(), {"state": "ring_unavailable"})
        self.now += timedelta(seconds=5)
        self.assertEqual(await (await request(ref)).json(), {"state": "ring_expired"})
        self.assertEqual(self.db.admin("SELECT * FROM marong.app_rings WHERE id=%s", (ring,)), original)
        (call,), = self.db.admin("""
            INSERT INTO call.calls(caller_id,client_id,prompt_version,voice)
            VALUES (%s,gen_random_uuid(),'fixture','fixture') RETURNING id
        """, (who["caller_id"],))
        self.db.admin("UPDATE marong.app_rings SET status='answered',answered_at=now(),call_id=%s WHERE id=%s",
                      (call, ring))
        self.assertEqual(await (await request(ref)).json(), {"state": "ring_answered"})
        with patch.object(self.references, "open", side_effect=OperationalError):
            await self.problem(await request(ref), 503, "db_unavailable")
        with patch.object(self.references, "open", side_effect=RuntimeError):
            await self.problem(await request(ref), 500, "internal")
        self.monotonic += 61
        for _ in range(60):
            self.service.limit(who["session_id"], installation_id(self.proof))
        await self.problem(await request(ref), 429, "request_limit")

    async def test_566_validated_transport_encrypts_to_browser_and_signs_for_apple(self):
        self.assertIsNone(configured_web_push({}, None, ORIGIN))
        receiver = ec.generate_private_key(ec.SECP256R1())
        signing = ec.generate_private_key(ec.SECP256R1())
        auth = secrets.token_bytes(16)
        public = receiver.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        resolver = AsyncMock(return_value=("1.1.1.1",))
        reader = asyncio.StreamReader()
        reader.feed_data(b"HTTP/1.1 201 Created\r\nConnection: close\r\n\r\n")
        writer = Mock(drain=AsyncMock(), is_closing=Mock(return_value=False))
        connect = AsyncMock(return_value=(reader, writer))
        provider = AppleWebPush({"fixture": signing}, "mailto:fixture@example.invalid", now=lambda: self.now,
                                resolve=resolver, connect=connect)
        endpoint = "https://web.push.apple.com/path%2Ffixture?x=1"
        material = {"endpoint": endpoint, "vapidKeyId": "fixture",
                    "keys": {"p256dh": encode(public), "auth": encode(auth)}}
        for invalid in ("http://web.push.apple.com/path", "https://web.push.apple.com.invalid/path",
                        "https://a@web.push.apple.com/path", "https://web.push.apple.com:8443/path",
                        "https://[::1]/path", "https://web.push.apple.com/path#fragment"):
            with self.assertRaises(ValueError):
                await provider.prepare({**material, "endpoint": invalid}, b"fixture", "a" * 24)
        connect.assert_not_awaited()
        request = await provider.prepare(material, b"fixture", "a" * 24)
        args, options = connect.await_args
        self.assertEqual(args, ("1.1.1.1", 443))
        self.assertEqual(options["server_hostname"], "web.push.apple.com")
        self.assertTrue(options["ssl"].check_hostname)
        await request.write(20)
        headers, encrypted = writer.write.call_args.args[0].split(b"\r\n\r\n", 1)
        self.assertIn(b"POST /path%2Ffixture?x=1 HTTP/1.1", headers)
        self.assertIn(b"TTL: 20", headers)
        self.assertEqual(http_ece.decrypt(encrypted, private_key=receiver, auth_secret=auth), b"fixture")
        self.assertNotEqual(encrypted[21:86], signing.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
        signed = request.token.split("t=", 1)[1].split(",", 1)[0]
        body = jwt.decode(signed, signing.public_key(), algorithms=["ES256"], audience="https://web.push.apple.com",
                          options={"verify_exp": False})
        self.assertEqual(body["exp"], int(self.now.timestamp()) + 12 * 3600)
        self.now += timedelta(minutes=15)
        self.assertEqual(request.token, provider._authorization("fixture", "web.push.apple.com"))
        self.assertEqual(await request.response(), ProviderResult(201))

    async def test_566_provider_outcomes_and_retry_does_not_replay_unconfirmed(self):
        target = await self.register_fixture()
        until = self.now + timedelta(seconds=20)
        cases = (([404], "rejected"), ([429, 201], "accepted"), ([503, 503], "rejected"),
                 ([ConnectionError()], "unconfirmed"), ([ProviderResult(429, "60")], "expired"))
        for values, outcome in cases:
            with self.subTest(outcome=outcome):
                requests = []
                for value in values:
                    request = FakeRequest()
                    if isinstance(value, Exception):
                        request.response.side_effect = value
                    else:
                        request.response.return_value = value if isinstance(value, ProviderResult) else ProviderResult(value)
                    requests.append(request)
                self.transport.prepare.reset_mock(side_effect=True)
                self.transport.prepare.side_effect = requests
                self.assertEqual(await self.delivery.send(target.friend_id, "reminder", secrets.randbelow(2**48), until),
                                 {outcome: 1})
                self.assertEqual(self.transport.prepare.await_count, len(values))
                self.assertEqual(self.row()[0][0], "active")
        stale = FakeRequest()

        async def late_result():
            refresh = await self.select("refresh")
            await self.state(await self.request("PUT", SUB, choice=refresh, body=self.subscription()), "active")
            return ProviderResult(410)

        stale.response.side_effect = late_result
        self.transport.prepare.side_effect = [stale]
        self.assertEqual(await self.delivery.send(target.friend_id, "reminder", 500, until), {"stale": 1})
        self.assertEqual(self.row()[0][0], "active")
        current = FakeRequest()
        current.response.return_value = ProviderResult(410)
        self.transport.prepare.side_effect = [current]
        self.assertEqual(await self.delivery.send(target.friend_id, "reminder", 501, until), {"invalid": 1})
        self.assertEqual(self.row()[0][0], "invalid")
        self.assertEqual(self.row()[0][2:], (None, None, None))

    async def test_568_reply_views_only_suppress_one_exact_installation_and_reply(self):
        target = await self.register_fixture()
        other = await self.register_fixture(proof=self.other_proof)
        user = (await self.sessions.find_session(self.token))["friend_id"]
        await self.sessions.ensure_profile(user)
        me = await self.sessions.find_session(self.token)
        incoming = await self.store.add_message(me["room_key"], "user", "Synthetic question")
        reply = await self.store.add_message(me["room_key"], "assistant", "Synthetic reply", reply_to=incoming,
                                             meta={"delivered": True})
        valid = {"messageId": str(reply), "view": "visible"}
        await self.problem(await self.request("POST", VIEW, body={**valid, "messageId": str(incoming)}), 404, "not_found")
        await self.problem(await self.request("POST", VIEW, body=valid, token=self.alt), 403, "not_allowed")
        await self.problem(await self.request("POST", VIEW, body={**valid, "messageId": str(2**63)}), 400, "invalid_input")
        await self.problem(await self.request("POST", VIEW, body=valid, token=None), 401, "login_required")
        await self.problem(await self.request("POST", VIEW, body=valid, headers={"Origin": "https://off.invalid"}),
                           403, "cross_site")
        result = await self.request("POST", VIEW, body=valid)
        self.assertEqual((result.status, await result.json()), (200, {"state": "recorded"}))
        self.assertTrue(self.delivery.reply_seen(target, reply))
        self.assertFalse(self.delivery.reply_seen(other, reply))
        self.assertFalse(self.delivery.reply_seen(target, reply + 1))
        end = self.now + timedelta(seconds=30)
        self.assertEqual(await self.delivery.send(user, "reply", reply, end), {"seen": 1, "accepted": 1})
        self.delivery._sleep.assert_awaited_with(2)
        self.assertEqual(await self.delivery.send(user, "reply", reply, end), {})
        for kind in ("proactive", "reminder"):
            self.assertEqual(await self.delivery.send(user, kind, reply, end), {"accepted": 2})
        earlier = self.delivery.reply_arrival()
        result = await self.request("POST", VIEW, body={**valid, "view": "hidden"})
        self.assertEqual((result.status, await result.json()), (200, {"state": "cleared"}))
        self.delivery.report_reply_view(self.sid, target.installation_id, reply, "visible", earlier)
        self.assertFalse(self.delivery.reply_seen(target, reply))
        await self.request("POST", VIEW, body=valid)
        self.monotonic += 5
        self.assertFalse(self.delivery.reply_seen(target, reply))
        with patch("marong.app_chat.visible_message", side_effect=OperationalError):
            await self.problem(await self.request("POST", VIEW, body=valid), 503, "db_unavailable")
        with patch("marong.app_chat.visible_message", side_effect=RuntimeError):
            await self.problem(await self.request("POST", VIEW, body=valid), 500, "internal")
        self.monotonic += 61
        for _ in range(120):
            self.service.limit(self.sid, installation_id(self.proof), limit=120)
        await self.problem(await self.request("POST", VIEW, body=valid), 429, "request_limit")
        self.assertEqual(self.row()[0][0], "active")

    async def test_567_existing_commit_only_fans_out_and_preserves_fcm(self):
        target = await self.register_fixture()
        await self.register_fixture(proof=self.other_proof)
        await self.sessions.ensure_profile(target.friend_id)
        fcm = Mock(enabled=True, notify=AsyncMock(return_value=(1, 1)))
        jobs = []
        saved = Mock()
        delivery = UnifiedDelivery(self.store, fcm, "session", saved, web_push=self.delivery, spawn=jobs.append)
        for kind in ("proactive", "reminder"):
            result = await delivery.say(target.friend_id, "Synthetic message", kind=kind, key=f"fixture:{kind}")
            self.assertEqual(result, "app")
            self.assertEqual(await delivery.say(target.friend_id, "Synthetic resend", kind=kind, key=f"fixture:{kind}"),
                             "later")
        self.assertEqual(saved.call_count, 2)
        self.assertEqual(fcm.notify.await_count, 2)
        self.assertEqual(len(jobs), 2)
        await asyncio.gather(*jobs)
        self.assertEqual(self.transport.prepare.await_count, 4)
        for material, payload, tag in (call.args for call in self.transport.prepare.await_args_list):
            self.assertNotIn(b"Synthetic", payload)
            self.assertEqual(len(tag), 24)
            self.assertEqual(json.loads(payload)["web_push"], 8030)
        totals = self.db.admin("""
            SELECT count(*) FROM marong.messages m JOIN marong.rooms r USING (room_key)
            WHERE r.owner_friend_id=%s
        """, (target.friend_id,))
        self.assertEqual(totals, [(2,)])

    async def test_569_only_pending_promise_with_remaining_life_has_handoff(self):
        target = await self.register_fixture()
        await self.sessions.ensure_profile(target.friend_id)
        who = await self.sessions.find_session(self.token)
        future = self.ring(who)
        first = FakeRequest()
        self.transport.prepare.side_effect = [first]
        await self.delivery.publish(target.friend_id, "call", str(future), 60)
        self.assertEqual(self.transport.prepare.await_count, 1)
        self.assertEqual(len(first.handed), 1)
        self.assertGreater(first.handed[0], 0)
        self.assertLessEqual(first.handed[0], 31)
        await self.delivery.publish(target.friend_id, "call", str(future), 60)
        self.db.admin("UPDATE marong.app_rings SET status='missed',resolved_at=now() WHERE id=%s", (future,))
        expired = self.ring(who, until=-10)
        await self.delivery.publish(target.friend_id, "call", str(expired), 60)
        self.assertEqual(self.transport.prepare.await_count, 1)
        self.assertEqual(self.row()[0][0], "active")

    async def call_fixture(self):
        sys.path.insert(0, str(ROOT / "tools" / "vertex_live"))
        import server
        from call_memory import MemoryStore

        call_db = self.db.admin_url.replace("postgres:@", "marong_call@", 1)
        store = MemoryStore(call_db)
        await store.open()
        self.addAsyncCleanup(store.close)
        protocol = NoticeCallProtocol(secrets.token_bytes(32), self.references)
        call_app = web.Application()
        call_app.router.add_post("/internal/web-notification/accept", server.notice_accept)
        call_app.router.add_get("/live/web-notification", server.notice_live)
        call_site = TestServer(call_app)
        await call_site.start_server()
        self.addAsyncCleanup(call_site.close)
        for obj, key, value in (
            (server, "memory_store", store), (server, "NOTICE_CALL", protocol),
            (server, "budget_status", AsyncMock(return_value="ok")),
            (server, "person_budget_blocked", AsyncMock(return_value=False)),
            (store.daily_usage, "blocked", AsyncMock(return_value=False)),
        ):
            patcher = patch.object(obj, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        call_bridge = patch("marong.app_chat.CALL_BRIDGE", str(call_site.make_url("/internal/web-notification/accept")))
        call_bridge.start()
        self.addCleanup(call_bridge.stop)
        self.chat.web_push_call = protocol
        public = TestClient(TestServer(self.chat.web_app()))
        await public.start_server()
        self.addAsyncCleanup(public.close)
        self.client = public
        self.call_site = call_site
        await self.sessions.ensure_profile((await self.sessions.find_session(self.token))["friend_id"])
        who = await self.sessions.find_session(self.token)
        return server, store, protocol, who

    def ring(self, who, *, until=30):
        (schedule,), = self.db.admin("""
            INSERT INTO marong.schedules(friend_id,source,title,event_at,action)
            VALUES (%s,'app','Fixture',now(),'call') RETURNING id
        """, (who["friend_id"],))
        (ring,), = self.db.admin("""
            INSERT INTO marong.app_rings(schedule_id,friend_id,caller_id,via,title,answer_until)
            VALUES (%s,%s,%s,'app','Fixture',now()+(%s * interval '1 second')) RETURNING id
        """, (schedule, who["friend_id"], who["caller_id"], until))
        return ring

    async def test_574_web_first_replay_and_android_first_share_atomic_ring(self):
        server, store, protocol, who = await self.call_fixture()
        from call_memory import CallBusy, Principal

        p = Principal(who["caller_id"], who["friend_id"], "Fixture", unified=True)
        ring = self.ring(who)
        reference = self.references.seal("call", who["friend_id"], ring, self.now)
        web_client = uuid4()
        answer = {"targetRef": reference, "clientId": str(web_client)}
        with patch.object(server, "CALL_MAX", 0):
            await self.problem(await self.request("POST", ACCEPT, body=answer), 409, "calls_full")
        with patch.object(server, "active_calls", {who["friend_id"]: server.CallSlot(str(uuid4()))}):
            await self.problem(await self.request("POST", ACCEPT, body=answer), 409, "call_busy")
        with patch.object(server, "person_budget_blocked", AsyncMock(return_value=True)):
            await self.problem(await self.request("POST", ACCEPT, body=answer), 409, "budget_exhausted")
        with patch.object(store.daily_usage, "blocked", AsyncMock(return_value=True)):
            await self.problem(await self.request("POST", ACCEPT, body=answer), 429, "daily_limit")
        with patch.object(store, "one", AsyncMock(side_effect=OperationalError)):
            await self.problem(await self.request("POST", ACCEPT, body=answer), 503, "db_unavailable")
        with patch.object(store, "one", AsyncMock(side_effect=RuntimeError)):
            await self.problem(await self.request("POST", ACCEPT, body=answer), 500, "internal")
        self.db.admin("UPDATE call.callers SET enabled=false WHERE id=%s", (p.caller_id,))
        self.assertEqual(await (await self.request("POST", ACCEPT, body=answer)).json(), {"state": "ring_unavailable"})
        self.db.admin("UPDATE call.callers SET enabled=true WHERE id=%s", (p.caller_id,))
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s", (p.caller_id,)), [(0,)])
        first = await self.request("POST", ACCEPT, body=answer)
        self.assertEqual(first.status, 200)
        accepted = await first.json()
        self.assertEqual(accepted.get("state"), "accepted")
        repeated = await (await self.request("POST", ACCEPT, body=answer)).json()
        self.assertEqual(repeated["callId"], accepted["callId"])
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s", (p.caller_id,)), [(1,)])
        self.assertEqual(self.db.admin("SELECT status,call_id::text FROM marong.app_rings WHERE id=%s", (ring,)),
                         [("answered", accepted["callId"])])
        with self.assertRaises(CallBusy):
            await store.reserve_notice_ring(p, str(uuid4()), "Fixture", "fixture", ring, legacy=True)
        result = await (await self.request("POST", ACCEPT, body={**answer, "clientId": str(uuid4())})).json()
        self.assertEqual(result, {"state": "ring_answered"})
        await self.problem(await self.request("POST", ACCEPT, body=answer, token=self.alt), 404, "not_found")
        await self.problem(await self.request("POST", ACCEPT, body={**answer, "clientId": "bad"}), 400, "invalid_input")
        await self.problem(await self.request("POST", ACCEPT, body=answer, token=None), 401, "login_required")
        await self.problem(await self.request("POST", ACCEPT, body=answer, proof=None), 403, "not_allowed")
        await self.problem(await self.request("POST", ACCEPT, body=answer, headers={"Origin": "https://off.invalid"}),
                           403, "cross_site")

        self.db.admin("""UPDATE call.calls SET status='ended',ended_at=now(),end_reason='hangup',organize_status='pending'
                         WHERE id=%s""", (accepted["callId"],))
        expired = self.ring(who, until=-1)
        expired_ref = self.references.seal("call", who["friend_id"], expired, self.now)
        expired_answer = {**answer, "targetRef": expired_ref}
        self.assertEqual(await (await self.request("POST", ACCEPT, body=expired_answer)).json(), {"state": "ring_expired"})
        self.db.admin("UPDATE marong.app_rings SET status='missed',resolved_at=now() WHERE id=%s", (expired,))
        second = self.ring(who)
        winner = await store.reserve_notice_ring(p, str(uuid4()), "Fixture", "fixture", second, legacy=True)
        second_ref = self.references.seal("call", who["friend_id"], second, self.now)
        self.assertEqual(await (await self.request("POST", ACCEPT, body={**answer, "targetRef": second_ref})).json(),
                         {"state": "ring_answered"})
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s", (p.caller_id,)), [(2,)])
        self.db.admin("""UPDATE call.calls SET status='ended',ended_at=now(),end_reason='hangup',organize_status='pending'
                         WHERE id=%s""", (winner[0],))
        third = self.ring(who)
        third_ref = self.references.seal("call", who["friend_id"], third, self.now)
        submitted = await asyncio.gather(
            self.request("POST", ACCEPT, body={**answer, "targetRef": third_ref}),
            self.request("POST", ACCEPT, body={"clientId": str(uuid4()), "targetRef": third_ref}),
        )
        self.assertEqual(sorted([(await item.json())["state"] for item in submitted]), ["accepted", "ring_answered"])
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s", (p.caller_id,)), [(3,)])
        self.db.admin("""UPDATE call.calls SET status='ended',ended_at=now(),end_reason='hangup',organize_status='pending'
                         WHERE caller_id=%s AND status='live'""", (p.caller_id,))
        contested = self.ring(who)
        contested_ref = self.references.seal("call", who["friend_id"], contested, self.now)
        web_request, android = await asyncio.gather(
            self.request("POST", ACCEPT, body={**answer, "targetRef": contested_ref}),
            store.reserve_notice_ring(p, str(uuid4()), "Fixture", "fixture", contested, legacy=True),
            return_exceptions=True,
        )
        web_result = await web_request.json()
        if web_result["state"] == "accepted":
            self.assertIsInstance(android, CallBusy)
        else:
            self.assertEqual(web_result, {"state": "ring_answered"})
            self.assertIsInstance(android, tuple)
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s", (p.caller_id,)), [(4,)])
        self.monotonic += 61
        for _ in range(60):
            self.service.limit(self.sid, installation_id(self.proof))
        await self.problem(await self.request("POST", ACCEPT, body=answer), 429, "request_limit")

    async def test_575_socket_protocol_first_frame_and_preaccepted_call(self):
        server, store, protocol, who = await self.call_fixture()
        origin = str(self.call_site.make_url("/")).rstrip("/")
        ring = self.ring(who)
        reference = self.references.seal("call", who["friend_id"], ring, self.now)
        client = str(uuid4())
        result = await self.request("POST", ACCEPT, body={"targetRef": reference, "clientId": client})
        self.assertEqual(result.status, 200)
        accepted = await result.json()
        headers = {"Cookie": f"{COOKIE}={self.token}", "Origin": origin}
        endpoint = self.call_site.make_url("/live/web-notification")

        class CallDouble:
            def __init__(self, websocket, *args, **kwargs):
                self.websocket = websocket
                self.explicit = False
                self.d = {}

            async def run(self):
                call, _, _, ring, *_ = self.notified_start
                await self.websocket.send_json({"type": "ready", "callId": call,
                                                "memoryConnected": True, "ring": bool(ring)})
                pcm = await self.websocket.receive_bytes(timeout=2)
                await self.websocket.send_bytes(pcm)

        with patch.object(server, "LiveSession", CallDouble):
            for incoming, offers, status in (
                (headers, (), 400), ({**headers, "Origin": "https://off.invalid"}, [SUBPROTOCOL], 403),
                ({"Origin": origin}, [SUBPROTOCOL], 401),
            ):
                with self.assertRaises(WSServerHandshakeError) as caught:
                    await self.client.session.ws_connect(endpoint, protocols=offers, headers=incoming)
                self.assertEqual(caught.exception.status, status)
            pending = server.CallSlot(client, reconnecting=True)
            previews = (
                (patch.object(server, "active_calls", {who["friend_id"]: pending}), 409),
                (patch.object(server, "notice_identity", side_effect=OperationalError), 503),
                (patch.object(server, "notice_identity", side_effect=RuntimeError), 500),
            )
            for condition, status in previews:
                with condition, self.assertRaises(WSServerHandshakeError) as caught:
                    await self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=headers)
                self.assertEqual(caught.exception.status, status)
            valid = {"type": "start_notified", "clientId": client, "installationProof": self.proof,
                     "connectToken": accepted["connectToken"]}
            expired_token = protocol.issue(
                self.sid, installation_id(self.proof), client_uuid(client), accepted["callId"], ring,
                self.now - timedelta(seconds=120))
            for body, failure in (({**valid, "extra": "x" * 2048}, "invalid_input"),
                                  ({**valid, "installationProof": self.other_proof}, "not_allowed"),
                                  ({**valid, "connectToken": expired_token}, "not_allowed")):
                async with self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=headers) as ws:
                    self.assertEqual(ws.protocol, SUBPROTOCOL)
                    await ws.send_json(body)
                    self.assertEqual(await ws.receive_json(timeout=3), {"type": failure})
            async with self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=headers) as ws:
                await ws.send_json(valid)
                self.assertEqual(await ws.receive_json(timeout=3), {
                    "type": "ready", "callId": accepted["callId"], "ring": True, "memoryConnected": True,
                })
                await ws.send_bytes(b"synthetic-audio")
                self.assertEqual(await ws.receive_bytes(timeout=3), b"synthetic-audio")
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s", (who["caller_id"],)), [(1,)])
        self.db.admin("""UPDATE call.calls SET status='ended',ended_at=now(),end_reason='hangup',organize_status='pending'
                         WHERE id=%s""", (accepted["callId"],))
        expired = self.ring(who, until=-5)
        reference = self.references.seal("call", who["friend_id"], expired, self.now)
        ordinary = {"type": "start_ordinary", "clientId": client, "installationProof": self.proof,
                    "targetRef": reference}
        with patch.object(server, "LiveSession", CallDouble):
            async with self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=headers) as ws:
                await ws.send_json(ordinary)
                ready = await ws.receive_json(timeout=3)
                self.assertEqual((ready["type"], ready["ring"]), ("ready", False))
                await ws.send_bytes(b"synthetic-audio")
                self.assertEqual(await ws.receive_bytes(timeout=3), b"synthetic-audio")
        self.assertEqual(self.db.admin("SELECT status,call_id FROM marong.app_rings WHERE id=%s", (expired,)),
                         [("ringing", None)])


if __name__ == "__main__":
    unittest.main()
