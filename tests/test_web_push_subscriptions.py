"""TASK-561–564: installation-scoped API-310–313 against isolated PostgreSQL."""

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import json
import secrets
import subprocess
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

from test_web_push_schema import CALL_DEADLINES, CALL_RECEIPTS, MIGRATION, ROOT, app_database, session
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE, token_hash
from marong.unified_delivery import UnifiedDelivery
from marong.unified_store import UnifiedStore
from marong.web_push_delivery import AppleWebPush, ProviderResult, WebPushDelivery, configured_web_push
from marong.web_push_subscriptions import (
    CHOICE_HEADER, INSTALLATION_HEADER, PATH, ActiveSubscriptionMaterial, WebPushSubscriptions, encode,
    installation_id,
)
from marong.web_push_targets import NoticeReferences
from marong.web_notice_call_protocol import (BRIDGE_HEADER, ENDED_PATH, INSTALLATION_CHECK_PATH, READ_BRIDGE_HEADER,
    RECEIPT_EXPIRES_HEADER, RECEIPT_HEADER, REDIAL_HEADER, SUBPROTOCOL, NoticeCallProtocol, client_uuid)


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
        cls.db.apply_sql(CALL_DEADLINES, CALL_RECEIPTS, MIGRATION)

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
        self.reference_key = secrets.token_bytes(32)
        self.references = NoticeReferences(self.reference_key, timedelta(days=1))
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
        store = MemoryStore(call_db, notice_deadlines=True)
        await store.open()
        self.addAsyncCleanup(store.close)
        self.notice_key = secrets.token_bytes(32)
        protocol = NoticeCallProtocol(self.notice_key, self.references)
        call_app = web.Application()
        call_app.router.add_post("/internal/web-notification/accept", server.notice_accept)
        call_app.router.add_post(ENDED_PATH, server.notice_ended)
        call_app.router.add_get("/live/web-notification", server.notice_live)
        call_app.router.add_get("/live", server.live)
        call_app.router.add_post("/api/rtc", server.rtc_config)
        call_app.router.add_get("/status", server.status)
        call_app.router.add_get("/api/me", server.status)
        call_app.router.add_post("/api/calls/{id}/end", server.end_call)
        call_site = TestServer(call_app)
        await call_site.start_server()
        self.addAsyncCleanup(call_site.close)
        for obj, key, value in (
            (server, "memory_store", store), (server, "NOTICE_CALL", protocol),
            (server, "AUTHENTICATION", "session"), (server, "active_calls", {}), (server, "resume_state", {}),
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
        ended_bridge = patch("marong.app_chat.ENDED_BRIDGE", str(call_site.make_url(ENDED_PATH)))
        ended_bridge.start()
        self.addCleanup(ended_bridge.stop)
        self.chat.web_push_call = protocol
        public = TestClient(TestServer(self.chat.web_app()))
        await public.start_server()
        self.addAsyncCleanup(public.close)
        check_bridge = patch.object(server, 'NOTICE_CHECK', str(public.make_url(INSTALLATION_CHECK_PATH)))
        check_bridge.start()
        self.addCleanup(check_bridge.stop)
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

    async def answer_body(self, reference):
        ident = installation_id(self.proof)
        async with self.service.pool.connection() as conn:
            consent, _ = await self.service.active_consent(conn, ident, self.sid, self.now)
        client = self.chat.web_push_call.document_client(self.sid, ident, reference, consent)
        return {'targetRef': reference, 'clientId': str(client)}

    def notice_call_state(self, call_id):
        (row,) = self.db.admin("""
            SELECT status,notice_first_connected_at,notice_connection_deadline_at,ended_at,end_reason
            FROM call.calls WHERE id=%s
        """, (call_id,))
        return row

    async def test_notice_segment_preparation_failure_preserves_pending_deadline(self):
        import live_session
        from test_relay import HTTP, Upstream, event

        server, store, protocol, who = await self.call_fixture()
        await self.register_fixture()
        now = self.now
        store.notice_clock = lambda: now
        endpoint = self.call_site.make_url('/live/web-notification')
        headers = {'Cookie': f'{COOKIE}={self.token}', 'Origin': str(endpoint.origin())}

        async def socket():
            return await self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=headers)

        with (patch.object(server, 'google_headers', AsyncMock(return_value={})),
              patch.object(live_session, 'ClientSession', side_effect=lambda **_: HTTP(Upstream()))):
            for recovering in (False, True):
                failures = (('start_segment', False), ('segment_ready', False), ('segment_ready', True))
                for fault, missing_transition in failures:
                    with self.subTest(recovering=recovering, fault=fault, missing_transition=missing_transition):
                        ring, body, result, _ = await self.notice_reservation(who, protocol)
                        call = result['callId']
                        start = {'type': 'start_notified', 'clientId': body['clientId'],
                                 'installationProof': self.proof, 'connectToken': result['connectToken']}
                        first_connected = None
                        if recovering:
                            now += timedelta(seconds=5)
                            async with await socket() as first:
                                await first.send_json(start)
                                self.assertEqual((await event(first, 'ready'))['callId'], call)
                                slot = server.active_calls[who['friend_id']]
                                first_connected = now
                                now += timedelta(seconds=10)
                            await asyncio.wait_for(slot.released.wait(), 5)
                        deadline = now + timedelta(seconds=120)
                        now += timedelta(seconds=10)
                        failing_slot = None

                        async def fail(*args, **kwargs):
                            nonlocal failing_slot
                            failing_slot = server.active_calls[who['friend_id']]
                            if missing_transition:
                                return False
                            raise TimeoutError('synthetic segment preparation timeout')

                        with patch.object(store, fault, side_effect=fail):
                            async with await socket() as ws:
                                await ws.send_json(start)
                                async with asyncio.timeout(5):
                                    async for message in ws:
                                        frame = message.json()
                                        if frame['type'] in {'ready', 'db_unavailable'}:
                                            break
                                    else:
                                        self.fail('Missing readiness or preparation failure response')
                            await asyncio.wait_for(failing_slot.released.wait(), 5)
                        after_failure = self.notice_call_state(call)
                        now = deadline
                        await store.expire_notice_calls(who['caller_id'])
                        at_deadline = self.notice_call_state(call)
                        self.assertEqual(self.db.admin('SELECT status,call_id::text FROM marong.app_rings WHERE id=%s',
                                                       (ring,)), [('answered', call)])
                        # Keep the next subtest independent even on a pre-fix implementation.
                        now += timedelta(seconds=120)
                        await store.expire_notice_calls(who['caller_id'])
                        self.assertEqual((frame['type'], after_failure, at_deadline), (
                            'db_unavailable', ('resting', first_connected, deadline, None, None),
                            ('ended', first_connected, None, deadline, 'reconnect_limit'),
                        ))

    async def notice_reservation(self, who, protocol):
        ring = self.ring(who, until=3600)
        reference = self.references.seal('call', who['friend_id'], ring, self.now)
        request = await self.answer_body(reference)
        reply = await self.request('POST', ACCEPT, body=request)
        self.assertEqual(reply.status, 200)
        accepted = await reply.json()
        self.assertEqual(accepted['state'], 'accepted')
        client = protocol.bound_client(who['friend_id'], self.sid, installation_id(self.proof),
                                       client_uuid(request['clientId']))
        return ring, request, accepted, client

    async def test_ended_notice_redial_choice_after_normal_hangup_and_relay_reopen(self):
        server, store, protocol, who = await self.call_fixture()
        await self.register_fixture(proof=self.other_proof)
        await self.register_fixture()
        from call_memory import Principal
        import live_session
        from test_relay import HTTP, Upstream, event

        ring = self.ring(who, until=3600)
        reference = self.references.seal('call', who['friend_id'], ring, self.now)
        answer = await self.answer_body(reference)
        accepted = await self.request('POST', ACCEPT, body=answer)
        call = (await accepted.json())['callId']
        receipt = accepted.headers[RECEIPT_HEADER]
        expiry = accepted.headers[RECEIPT_EXPIRES_HEADER]
        repeated = await self.request('POST', ACCEPT, body=answer)
        self.assertEqual((await repeated.json())['callId'], call)
        self.assertEqual(repeated.headers[RECEIPT_EXPIRES_HEADER], expiry)

        async def lookup(**kwargs):
            response = await self.request('POST', RESOLVE, body={'targetRef': reference},
                                          headers={RECEIPT_HEADER: receipt}, **kwargs)
            self.assertEqual(await response.json(), {'state': 'ring_answered'})
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            return response.headers.get(REDIAL_HEADER)

        self.assertIsNone(await lookup())
        pending_call = self.notice_call_state(call)
        deadline = pending_call[2]
        for offset in (-1, 0, 1):
            store.notice_clock = lambda: deadline + timedelta(microseconds=offset)
            self.assertIsNone(await lookup())
            self.assertEqual(self.notice_call_state(call), pending_call)
        store.notice_clock = None
        principal = Principal(who['caller_id'], who['friend_id'], 'Fixture', 0, unified=True)
        owner = protocol.bound_client(who['friend_id'], self.sid, installation_id(self.proof),
                                      client_uuid(answer['clientId']))
        attached = (await store.attach_notice_call(principal, owner, call, ring, self.sid))[-1]
        await store.confirm_notice_connection(principal, attached)
        self.assertIsNone(await lookup())
        await store.finish_notice_connection(principal, attached, explicit=True)
        original = self.notice_call_state(call)
        ring_query = 'SELECT status,call_id,answered_at FROM marong.app_rings WHERE id=%s'
        answer_history = self.db.admin(ring_query, (ring,))
        original_subscription = self.row()
        self.assertIsNone(await lookup(proof=self.other_proof))
        public = await self.request('POST', RESOLVE, body={'targetRef': reference})
        self.assertNotIn(REDIAL_HEADER, public.headers)
        choice = await lookup()
        self.assertIsNotNone(choice)
        self.assertIsNotNone(await lookup())
        self.assertEqual(self.row(), original_subscription)
        self.assertEqual(self.notice_call_state(call), original)
        self.assertEqual(self.db.admin(ring_query, (ring,)), answer_history)
        refresh = await self.select('refresh')
        await self.state(await self.request('PUT', SUB, choice=refresh, body=self.subscription()), 'active')
        another_choice = await lookup()
        self.assertIsNotNone(another_choice)

        headers = {'Cookie': f'{COOKIE}={self.token}'}
        async def open_document(selected):
            form = {'targetRef': reference, 'installationProof': self.proof, 'navigation': uuid4().hex,
                    'redialChoice': selected}
            return await self.client.post('/chat/notice-call', data=form, headers=headers | {'Origin': ORIGIN})

        denied = await open_document(receipt)
        self.assertEqual(denied.status, 403)
        self.assertIn('microphone=()', denied.headers['Permissions-Policy'])
        direct = await self.client.get('/chat/notice-call', headers=headers)
        self.assertIn('microphone=()', direct.headers['Permissions-Policy'])
        doc = await open_document(choice)
        self.assertEqual(doc.status, 200)
        self.assertIn('microphone=(self)', doc.headers['Permissions-Policy'])
        self.assertEqual(doc.headers['Cache-Control'], 'no-store')
        markup = await doc.text()
        self.assertIn('data-purpose="redial"', markup)
        for secret in (choice, receipt, reference, self.proof):
            self.assertNotIn(secret, markup)
        client = markup.split('data-client-id="', 1)[1].split('"', 1)[0]
        doc_check = await self.request('POST', RESOLVE, body={'targetRef': reference},
                                       headers={REDIAL_HEADER: choice, 'X-Marong-Notice-Document': client})
        self.assertEqual(await doc_check.json(), {'state': 'ring_answered'})
        rejected_answer = await self.request('POST', ACCEPT, body={'targetRef': reference, 'clientId': client})
        self.assertEqual(rejected_answer.status, 403)

        ident = installation_id(self.proof)
        async with self.store.pool.connection() as conn:
            consent, _ = await self.service.active_consent(conn, ident, self.sid, self.now)
        scope = protocol.receipt_scope(who['friend_id'], self.sid, ident, reference, consent)
        claim = protocol.check_redial(scope, receipt, self.now)
        expired = protocol.redial_choice(scope, claim, self.now - timedelta(minutes=5))
        self.assertEqual((await open_document(expired)).status, 403)

        bridge = self.call_site.make_url(ENDED_PATH)
        read_body = {'friend': who['friend_id'], 'session': self.sid, 'targetRef': reference, 'receipt': receipt,
                     'choice': False, 'consent': 'a' * 43}
        for auth in ({BRIDGE_HEADER: protocol.bridge_secret}, {READ_BRIDGE_HEADER: protocol.read_secret}):
            async with self.client.session.post(bridge, json=read_body, headers=auth) as response:
                self.assertEqual(response.status, 404)
        writer = self.call_site.make_url('/internal/web-notification/accept')
        async with self.client.session.post(writer, json=answer, headers={READ_BRIDGE_HEADER: protocol.read_secret}) as response:
            self.assertEqual(response.status, 404)

        frame = {'type': 'start_ordinary', 'clientId': client, 'installationProof': self.proof,
                 'targetRef': reference, 'redialChoice': choice}
        endpoint = self.call_site.make_url('/live/web-notification')
        async def sockets(url):
            return await self.client.session.ws_connect(url, protocols=[SUBPROTOCOL],
                                                        headers=headers | {'Origin': str(url.origin())})

        async with await sockets(endpoint) as ws:
            await ws.send_json(frame | {'clientId': str(protocol.redial_document(expired)), 'redialChoice': expired})
            self.assertEqual(await ws.receive_json(timeout=3), {'type': 'not_allowed'})

        with (patch.object(server, 'google_headers', AsyncMock(return_value={})),
              patch.object(live_session, 'ClientSession', side_effect=lambda *a, **k: HTTP(Upstream()))):
            async with await sockets(endpoint) as ws:
                await ws.send_json(frame)
                ready = await event(ws, 'ready')
                self.assertFalse(ready['ring'])
                replacement = ready['callId']
                self.assertNotEqual(replacement, call)
                slot = server.active_calls[who['friend_id']]
                async with await sockets(endpoint) as competing:
                    await competing.send_json(frame | {'clientId': str(protocol.redial_document(another_choice)),
                                                       'redialChoice': another_choice})
                    self.assertEqual(await competing.receive_json(timeout=3), {'type': 'call_busy'})
                await ws.send_json({'type': 'stop'})
                await asyncio.wait_for(slot.released.wait(), 5)
        self.assertEqual(self.notice_call_state(replacement)[::4], ('ended', 'hangup'))
        self.assertEqual(self.db.admin('SELECT notice_receipt_expires_at FROM call.calls WHERE id=%s', (replacement,)),
                         [(None,)])
        # The same choice still opens its document. A fresh relay process has no previous socket
        # state, so rejecting the start depends on the recorded ordinary call.
        retry_doc = await open_document(choice)
        self.assertEqual(retry_doc.status, 200)
        self.assertIn(f'data-client-id="{client}"', await retry_doc.text())
        from yarl import URL
        child_code = '''
import asyncio, json, sys
from datetime import timedelta
from unittest.mock import AsyncMock, Mock
from aiohttp import web
from aiohttp.test_utils import TestServer
sys.path.insert(0, 'tools/vertex_live')
import server
from marong.web_notice_call_protocol import NoticeCallProtocol
from marong.web_push_targets import NoticeReferences

async def main():
    dsn, auth_key, ref_key, installation_check = json.loads(sys.stdin.readline())
    store = server.MemoryStore(dsn, notice_deadlines=True)
    await store.open()
    server.memory_store = store
    server.NOTICE_CALL = NoticeCallProtocol(bytes.fromhex(auth_key), NoticeReferences(bytes.fromhex(ref_key), timedelta(days=1)))
    server.AUTHENTICATION = 'session'
    server.NOTICE_CHECK = installation_check
    server.budget_status = AsyncMock(return_value='ok')
    server.person_budget_blocked = AsyncMock(return_value=False)
    store.daily_usage.blocked = AsyncMock(return_value=False)
    server.LiveSession = Mock(side_effect=AssertionError('unexpected call startup'))
    app = web.Application()
    app.router.add_get('/live/web-notification', server.notice_live)
    try:
        async with TestServer(app) as site:
            print(site.make_url('/live/web-notification'), flush=True)
            await asyncio.to_thread(sys.stdin.readline)
        server.LiveSession.assert_not_called()
    finally:
        await store.close()

asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
'''
        with subprocess.Popen([sys.executable, '-c', child_code], cwd=ROOT, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as relay:
            config = [self.db.admin_url.replace('postgres:@', 'marong_call@', 1), self.notice_key.hex(),
                      self.reference_key.hex(), server.NOTICE_CHECK]
            try:
                relay.stdin.write(json.dumps(config) + '\n')
                relay.stdin.flush()
                endpoint_line = await asyncio.wait_for(asyncio.to_thread(relay.stdout.readline), 8)
                self.assertTrue(endpoint_line.startswith('http://127.0.0.1:'))
                async with await sockets(URL(endpoint_line.strip())) as ws:
                    await ws.send_json(frame)
                    self.assertEqual(await ws.receive_json(timeout=3), {'type': 'ring_unavailable'})
            finally:
                if relay.poll() is None:
                    try:
                        relay.stdin.write('\n')
                        relay.stdin.flush()
                        await asyncio.to_thread(relay.wait, 5)
                    except (OSError, subprocess.TimeoutExpired):
                        relay.terminate()
            self.assertEqual(relay.returncode, 0)
        self.assertEqual(self.db.admin('SELECT count(*) FROM call.calls WHERE caller_id=%s', (who['caller_id'],)), [(2,)])
        self.assertEqual(self.db.admin(ring_query, (ring,)), answer_history)
        self.assertEqual(self.notice_call_state(call), original)

        revoke = await self.select('revoke')
        original_ended = self.chat._notice_ended

        async def revoke_during_lookup(*args, **kwargs):
            ended = await original_ended(*args, **kwargs)
            await self.state(await self.request('DELETE', SUB, choice=revoke), 'revoked')
            return ended

        with patch.object(self.chat, '_notice_ended', side_effect=revoke_during_lookup):
            self.assertIsNone(await lookup())
        self.assertIsNone(await lookup())
        self.assertEqual((await open_document(choice)).status, 403)
        async with await sockets(endpoint) as ws:
            await ws.send_json(frame | {'clientId': str(protocol.redial_document(another_choice)),
                                        'redialChoice': another_choice})
            self.assertEqual(await ws.receive_json(timeout=3), {'type': 'not_allowed'})
        await self.register_fixture()
        self.assertIsNone(await lookup())
        self.assertEqual((await open_document(choice)).status, 403)

    async def test_notice_receipt_keeps_locked_session_cutoff_across_renewal_and_result_retry(self):
        server, _, _, who = await self.call_fixture()
        await self.register_fixture()
        from marong.app_session import find_session

        original_until = self.now + timedelta(hours=3)
        renewed_at = self.now + timedelta(hours=2)
        self.db.admin('UPDATE marong.app_sessions SET last_seen_at=%s,expires_at=%s WHERE id=%s',
                      (self.now - timedelta(hours=23), original_until, self.sid))
        ring = self.ring(who, until=3600)
        reference = self.references.seal('call', who['friend_id'], ring, self.now)
        answer = await self.answer_body(reference)
        checked, release = asyncio.Event(), asyncio.Event()
        validation = server.validate_notice_installation

        async def pause_after_subscription(*args):
            verified = await validation(*args)
            checked.set()
            await release.wait()
            return verified

        with patch.object(server, 'validate_notice_installation', side_effect=pause_after_subscription):
            first = asyncio.create_task(self.request('POST', ACCEPT, body=answer))
            await asyncio.wait_for(checked.wait(), 2)
            renewal = asyncio.create_task(find_session(self.store.pool, self.token, clock=lambda: renewed_at,
                                                       age=timedelta(days=2)))
            try:
                async with asyncio.timeout(1.5):
                    while not self.db.admin("""
                        SELECT 1 FROM pg_stat_activity WHERE usename='marong' AND wait_event_type='Lock'
                          AND query LIKE '%%UPDATE marong.app_sessions SET last_seen_at=%%'
                    """):
                        await asyncio.sleep(0.01)
            finally:
                release.set()
            accepted = await first
            self.assertTrue((await renewal)['renewed'])
        self.assertEqual(accepted.status, 200)
        call = (await accepted.json())['callId']
        expiry = accepted.headers[RECEIPT_EXPIRES_HEADER]
        self.assertEqual(datetime.fromisoformat(expiry), original_until)
        self.assertEqual(self.db.admin('SELECT expires_at FROM marong.app_sessions WHERE id=%s', (self.sid,)),
                         [(renewed_at + timedelta(days=2),)])

        replay = await self.request('POST', ACCEPT, body=answer)
        self.assertEqual((await replay.json())['callId'], call)
        self.assertIn(RECEIPT_HEADER, replay.headers)
        self.assertEqual(replay.headers[RECEIPT_EXPIRES_HEADER], expiry)
        self.assertEqual(self.db.admin('SELECT notice_receipt_expires_at FROM call.calls WHERE id=%s', (call,)),
                         [(original_until,)])
        self.assertEqual(self.db.admin('SELECT count(*) FROM call.calls WHERE caller_id=%s', (who['caller_id'],)), [(1,)])

    async def test_notice_receipt_uses_target_and_first_acceptance_bounds_and_rolls_back(self):
        _, store, _, who = await self.call_fixture()
        await self.register_fixture()
        from call_memory import Principal
        principal = Principal(who['caller_id'], who['friend_id'], 'Fixture', 0, unified=True)
        self.db.admin('UPDATE marong.app_sessions SET expires_at=%s WHERE id=%s',
                      (self.now + timedelta(days=5), self.sid))
        for age in (timedelta(hours=2), timedelta(days=3)):
            with self.subTest(age=age):
                self.references.age = age
                ring = self.ring(who, until=3600)
                reference = self.references.seal('call', who['friend_id'], ring, self.now)
                body = await self.answer_body(reference)
                if age < timedelta(days=1):
                    actual = self.now
                    store.notice_clock = lambda: actual
                    start_locked = store._start_locked

                    async def pass_reference_boundary(*args, **kwargs):
                        nonlocal actual
                        inserted = await start_locked(*args, **kwargs)
                        actual = self.now + age
                        return inserted

                    with patch.object(store, '_start_locked', side_effect=pass_reference_boundary):
                        rejected = await self.request('POST', ACCEPT, body=body)
                    await self.problem(rejected, 404, 'not_found')
                    self.assertNotIn(RECEIPT_HEADER, rejected.headers)
                    self.assertEqual(self.db.admin('SELECT count(*) FROM call.calls WHERE caller_id=%s',
                                                   (who['caller_id'],)), [(0,)])
                    self.assertEqual(self.db.admin('SELECT status,call_id,answered_at FROM marong.app_rings WHERE id=%s',
                                                   (ring,)), [('ringing', None, None)])
                    store.notice_clock = None
                accepted = await self.request('POST', ACCEPT, body=body)
                self.assertEqual(accepted.status, 200)
                call = (await accepted.json())['callId']
                (answered, stored), = self.db.admin("""
                    SELECT r.answered_at,c.notice_receipt_expires_at FROM marong.app_rings r
                    JOIN call.calls c ON c.id=r.call_id WHERE r.id=%s
                """, (ring,))
                expiry = min(self.now + age, answered + timedelta(days=1))
                self.assertEqual(stored, expiry)
                self.assertEqual(datetime.fromisoformat(accepted.headers[RECEIPT_EXPIRES_HEADER]), expiry)
                if age < timedelta(days=1):
                    self.db.admin('UPDATE call.calls SET notice_receipt_expires_at=NULL WHERE id=%s', (call,))
                    old = await self.request('POST', ACCEPT, body=body)
                    self.assertEqual((await old.json())['callId'], call)
                    self.assertNotIn(RECEIPT_HEADER, old.headers)
                (owner,), = self.db.admin('SELECT client_id FROM call.calls WHERE id=%s', (call,))
                connection = (await store.attach_notice_call(principal, str(owner), call, ring, self.sid))[-1]
                await store.confirm_notice_connection(principal, connection)
                await store.finish_notice_connection(principal, connection, explicit=True)

    async def test_notice_first_connection_deadline_and_unanswered_preparation(self):
        from call_memory import NoticeRingState, Principal

        _, store, protocol, who = await self.call_fixture()
        await self.register_fixture()
        p = Principal(who['caller_id'], who['friend_id'], 'Fixture', unified=True)
        now = self.now
        store.notice_clock = lambda: now
        for offset in (-1, 0, 1):
            with self.subTest(offset=offset):
                accepted_at = now
                deadline = now + timedelta(seconds=120)
                ring, body, accepted, client = await self.notice_reservation(who, protocol)
                call = accepted['callId']
                self.assertEqual(self.notice_call_state(call), ('live', None, deadline, None, None))
                now = accepted_at + timedelta(seconds=3)
                first = (await store.attach_notice_call(p, client, call, ring, self.sid))[-1]
                await store.finish_notice_connection(p, first)  # Setup failed or the browser withdrew.
                now = accepted_at + timedelta(seconds=20)
                await store.finish_notice_connection(p, first)
                replay = await self.request('POST', ACCEPT, body=body)
                self.assertEqual((await replay.json())['callId'], call)
                read = await self.request('POST', RESOLVE, body={'targetRef': body['targetRef']})
                self.assertEqual(await read.json(), {'state': 'ring_answered'})
                self.assertEqual(self.notice_call_state(call), ('resting', None, deadline, None, None))
                connecting = None
                if offset == 0:
                    now = deadline - timedelta(microseconds=1)
                    connecting = (await store.attach_notice_call(p, client, call, ring, self.sid))[-1]
                now = deadline + timedelta(microseconds=offset)
                if offset < 0:
                    current = (await store.attach_notice_call(p, client, call, ring, self.sid))[-1]
                    await store.confirm_notice_connection(p, current)
                    first_connected = now
                    now += timedelta(days=1)
                    await store.expire_notice_calls(p.caller_id)
                    self.assertEqual(self.notice_call_state(call), ('live', first_connected, None, None, None))
                    await store.finish_notice_connection(p, current, explicit=True)
                    self.assertEqual(self.notice_call_state(call), ('ended', first_connected, None, now, 'hangup'))
                    now = deadline + timedelta(seconds=1)
                else:
                    if connecting:
                        with self.assertRaisesRegex(NoticeRingState, 'ring_answered'):
                            await store.confirm_notice_connection(p, connecting)
                    with self.assertRaisesRegex(NoticeRingState, 'ring_answered'):
                        await store.expire_notice_calls(p.caller_id)
                        await store.attach_notice_call(p, client, call, ring, self.sid)
                    if connecting:
                        await store.finish_notice_connection(p, connecting)
                    await store.expire_notice_calls(p.caller_id)
                    await store.expire_notice_calls(p.caller_id)
                    self.assertEqual(self.notice_call_state(call), ('ended', None, None, now, 'reconnect_limit'))
                    result = await self.request('POST', ACCEPT, body=body)
                    self.assertEqual(await result.json(), {'state': 'ring_answered'})
                self.assertEqual(self.db.admin("SELECT status,call_id::text,answered_at FROM marong.app_rings WHERE id=%s",
                                               (ring,)), [('answered', call, accepted_at)])

    async def test_notice_recovery_deadline_race_and_stale_close(self):
        from call_memory import NoticeRingState, Principal

        _, store, protocol, who = await self.call_fixture()
        await self.register_fixture()
        p = Principal(who['caller_id'], who['friend_id'], 'Fixture', unified=True)
        now = self.now
        store.notice_clock = lambda: now
        for offset in (-1, 0, 1):
            with self.subTest(offset=offset):
                ring, body, result, client = await self.notice_reservation(who, protocol)
                call = result['callId']
                attach = lambda: store.attach_notice_call(p, client, call, ring, self.sid)
                old = (await attach())[-1]
                now += timedelta(seconds=4)
                await store.confirm_notice_connection(p, old)
                first = now
                now += timedelta(seconds=10)
                deadline = now + timedelta(seconds=120)
                await store.finish_notice_connection(p, old)
                self.assertEqual(self.notice_call_state(call), ('resting', first, deadline, None, None))
                now += timedelta(seconds=7)
                failed = (await attach())[-1]
                await store.finish_notice_connection(p, failed)
                await store.finish_notice_connection(p, old, explicit=True)
                replay = await self.request('POST', ACCEPT, body=body)
                self.assertEqual((await replay.json())['callId'], call)
                self.assertEqual(self.notice_call_state(call), ('resting', first, deadline, None, None))
                now = deadline + timedelta(microseconds=offset)
                if offset < 0:
                    recovered = (await attach())[-1]
                    now = deadline
                    await asyncio.gather(store.expire_notice_calls(p.caller_id),
                                         store.finish_notice_connection(p, failed, explicit=True),
                                         store.confirm_notice_connection(p, recovered))
                    self.assertEqual(self.notice_call_state(call), ('live', first, None, None, None))
                    now += timedelta(seconds=10)
                    await store.finish_notice_connection(p, recovered)
                    new_deadline = now + timedelta(seconds=120)
                    self.assertEqual(self.notice_call_state(call), ('resting', first, new_deadline, None, None))
                    final = (await attach())[-1]
                    await store.confirm_notice_connection(p, final)
                    await store.finish_notice_connection(p, final, explicit=True)
                    self.assertEqual(self.notice_call_state(call), ('ended', first, None, now, 'hangup'))
                else:
                    # Move the clock while the reconnect waits for the existing caller lock.
                    now = deadline - timedelta(microseconds=1)
                    waiting = asyncio.Event()
                    authenticate = store._notice_session

                    async def session_checked(*args):
                        result = await authenticate(*args)
                        waiting.set()
                        return result

                    with patch.object(store, '_notice_session', side_effect=session_checked):
                        async with store.pool.connection() as conn, conn.transaction():
                            await conn.execute('SELECT id FROM call.callers WHERE id=%s FOR UPDATE', (p.caller_id,))
                            late = asyncio.create_task(attach())
                            await asyncio.wait_for(waiting.wait(), 2)
                            now = deadline + timedelta(microseconds=offset)
                            expiry = asyncio.create_task(store.expire_notice_calls(p.caller_id))
                        with self.assertRaisesRegex(NoticeRingState, 'ring_answered'):
                            await late
                        await expiry
                    self.assertEqual(self.notice_call_state(call), ('ended', first, None, now, 'reconnect_limit'))
                    with self.assertRaisesRegex(NoticeRingState, 'ring_answered'):
                        await attach()
                self.assertEqual(self.db.admin('SELECT status,call_id::text FROM marong.app_rings WHERE id=%s', (ring,)),
                                 [('answered', call)])

    async def test_notice_restart_creates_one_recovery_deadline_and_preserves_older_rows(self):
        from call_memory import MemoryStore, Principal

        _, old_store, protocol, who = await self.call_fixture()
        await self.register_fixture()
        p = Principal(who['caller_id'], who['friend_id'], 'Fixture', unified=True)
        now = self.now
        old_store.notice_clock = lambda: now
        ring, _, result, client = await self.notice_reservation(who, protocol)
        call = result['callId']
        first = (await old_store.attach_notice_call(p, client, call, ring, self.sid))[-1]
        await old_store.confirm_notice_connection(p, first)
        first_connected = now

        # Older open rows have no reliable timestamps, including earlier draft notification calls.
        older_session = await self.sessions.find_session(self.alt)
        await self.sessions.ensure_profile(older_session['friend_id'])
        older = await self.sessions.find_session(self.alt)
        older_ring = self.ring(older)
        previous_client = protocol.bound_client(older['friend_id'], self.alt_sid, installation_id(self.other_proof),
                                                uuid4())
        legacy = await old_store.reserve_notice_ring(
            Principal(older['caller_id'], older['friend_id'], 'Fixture', unified=True), previous_client,
            'Fixture', 'fixture', older_ring, legacy=True)
        older_call = legacy[0]
        self.assertEqual(self.notice_call_state(older_call), ('live', None, None, None, None))

        now += timedelta(seconds=300)
        pending_token = secrets.token_urlsafe(32)
        pending_session = session(self.db, token_hash(pending_token))
        pending_owner = await self.sessions.find_session(pending_token)
        await self.sessions.ensure_profile(pending_owner['friend_id'])
        pending_owner = await self.sessions.find_session(pending_token)
        pending_principal = Principal(pending_owner['caller_id'], pending_owner['friend_id'], 'Fixture', unified=True)
        pending_ring = self.ring(pending_owner, until=3600)
        pending_client = protocol.bound_client(pending_owner['friend_id'], pending_session,
                                               installation_id(self.other_proof), uuid4())
        pending_call, *_ = await old_store.reserve_notice_ring(pending_principal, pending_client, 'Fixture', 'fixture',
                                                               pending_ring, session=pending_session)
        pending_deadline = now + timedelta(seconds=120)
        call_db = self.db.admin_url.replace('postgres:@', 'marong_call@', 1)
        restarted = MemoryStore(call_db, notice_deadlines=True, notice_clock=lambda: now)
        await restarted.open()
        self.addAsyncCleanup(restarted.close)
        now += timedelta(seconds=10)
        await restarted.recover_entrypoint('web')
        deadline = now + timedelta(seconds=120)
        self.assertEqual(self.notice_call_state(call), ('resting', first_connected, deadline, None, None))
        now += timedelta(seconds=30)
        await restarted.recover_entrypoint('web')
        self.assertEqual(self.notice_call_state(call), ('resting', first_connected, deadline, None, None))
        self.assertEqual(self.notice_call_state(pending_call), ('resting', None, pending_deadline, None, None))
        self.assertEqual(self.notice_call_state(older_call), ('resting', None, None, None, None))
        now = deadline
        await restarted.recover_entrypoint('web')
        self.assertEqual(self.notice_call_state(call), ('ended', first_connected, None, now, 'reconnect_limit'))
        self.assertEqual(self.notice_call_state(pending_call), ('ended', None, None, now, 'reconnect_limit'))
        self.assertEqual(self.notice_call_state(older_call), ('resting', None, None, None, None))

    async def test_notice_relay_expiry_leaves_history_and_redial_is_ordinary(self):
        import live_session
        from test_relay import HTTP, Upstream, event

        server, store, protocol, who = await self.call_fixture()
        await self.register_fixture()
        now = self.now
        store.notice_clock = lambda: now
        ring, body, result, _ = await self.notice_reservation(who, protocol)
        call = result['callId']
        initial_deadline = now + timedelta(seconds=120)
        endpoint = self.call_site.make_url('/live/web-notification')
        headers = {'Cookie': f'{COOKIE}={self.token}', 'Origin': str(endpoint.origin())}
        start = {'type': 'start_notified', 'clientId': body['clientId'], 'installationProof': self.proof,
                 'connectToken': result['connectToken']}
        upstreams = []
        recovery_setup, allow_recovery = asyncio.Event(), asyncio.Event()

        async def recover_provider(**kwargs):
            recovery_setup.set()
            await allow_recovery.wait()
            return await Upstream.receive(upstreams[2], **kwargs)

        def upstream(**_):
            model = Upstream()
            if not upstreams:
                model.receive = AsyncMock(side_effect=ConnectionError('fixture setup failed'))
            elif len(upstreams) == 2:
                model.receive = recover_provider
            upstreams.append(model)
            return HTTP(model)

        async def open_notice():
            return await self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=headers)

        with (patch.object(server, 'google_headers', AsyncMock(return_value={})),
              patch.object(live_session, 'ClientSession', side_effect=upstream)):
            async with await open_notice() as failed:
                await failed.send_json(start)
                async with asyncio.timeout(5):
                    async for message in failed:
                        self.assertNotEqual(message.json().get('type'), 'ready')
            self.assertEqual(self.notice_call_state(call), ('resting', None, initial_deadline, None, None))
            now += timedelta(seconds=5)
            async with await open_notice() as current:
                await current.send_json(start)
                ready = await event(current, 'ready')
                self.assertEqual((ready['callId'], ready['resumed']), (call, False))
                self.assertEqual(self.notice_call_state(call), ('live', now, None, None, None))
                slot = server.active_calls[who['friend_id']]
                first_connected = now
                now += timedelta(seconds=10)
            await asyncio.wait_for(slot.released.wait(), 5)
            recovery_deadline = now + timedelta(seconds=120)
            now = recovery_deadline - timedelta(microseconds=1)
            async with await open_notice() as recovered:
                await recovered.send_json(start)
                await asyncio.wait_for(recovery_setup.wait(), 4)
                try:
                    now = recovery_deadline
                    async with await open_notice() as duplicate:
                        await duplicate.send_json(start)
                        self.assertEqual(await duplicate.receive_json(timeout=3), {'type': 'call_busy'})
                    replay = await self.request('POST', ACCEPT, body=body)
                    self.assertEqual((await replay.json())['callId'], call)
                    self.assertEqual(self.notice_call_state(call)[1:3], (first_connected, recovery_deadline))
                finally:
                    allow_recovery.set()
                ready = await event(recovered, 'ready')
                self.assertEqual((ready['callId'], ready['resumed']), (call, True))
                self.assertEqual(self.notice_call_state(call), ('live', first_connected, None, None, None))
                slot = server.active_calls[who['friend_id']]
                now += timedelta(seconds=10)
            await asyncio.wait_for(slot.released.wait(), 5)
            now += timedelta(seconds=120)
            async with await open_notice() as late:
                await late.send_json(start)
                self.assertEqual(await late.receive_json(timeout=3), {'type': 'ring_answered'})
            self.assertEqual(self.notice_call_state(call), ('ended', first_connected, None, now, 'reconnect_limit'))
            self.assertEqual(len(upstreams), 3)
            self.assertEqual(await (await self.request('POST', ACCEPT, body=body)).json(), {'state': 'ring_answered'})

            for android in (False, True):
                query = {'client': str(uuid4()), 'hangup': '1'}
                incoming = headers
                if android:
                    query['ring'] = str(ring)
                    incoming = headers | {'User-Agent': 'MarongApp/0.3.4'}
                ordinary = self.call_site.make_url('/live').with_query(query)
                async with self.client.session.ws_connect(ordinary, headers=incoming) as active:
                    ready = await event(active, 'ready')
                    self.assertNotEqual(ready['callId'], call)
                    self.assertFalse(ready['ring'])
                    slot = server.active_calls[who['friend_id']]
                    await active.send_json({'type': 'stop'})
                    await asyncio.wait_for(slot.released.wait(), 5)
                self.assertEqual(self.notice_call_state(ready['callId'])[:3], ('ended', None, None))
            self.assertEqual(self.db.admin('SELECT status,call_id::text FROM marong.app_rings WHERE id=%s', (ring,)),
                             [('answered', call)])

    async def test_notice_call_requires_issued_document_and_explicit_ordinary_choice(self):
        server, store, _, who = await self.call_fixture()
        await self.register_fixture()
        ring = self.ring(who)
        reference = self.references.seal('call', who['friend_id'], ring, self.now)
        await self.problem(await self.request('POST', ACCEPT, body={
            'targetRef': reference, 'clientId': str(uuid4()),
        }), 403, 'not_allowed')
        answer = await self.answer_body(reference)
        deadline = min(self.now, datetime.now(timezone.utc)) - timedelta(seconds=1)
        set_deadline = 'UPDATE marong.app_rings SET answer_until=%s WHERE id=%s'
        self.db.admin(set_deadline, (deadline, ring))
        result = await self.request('POST', RESOLVE, body={'targetRef': reference})
        self.assertEqual(await result.json(), {'state': 'ring_expired'})
        old_choice = result.headers['X-Marong-Ordinary-Choice']
        form = {'targetRef': reference, 'installationProof': self.proof, 'navigation': uuid4().hex}

        async def document(body, *, status, allowed=False, session=True):
            current = self.token if session is True else session
            headers = {'Cookie': f'{COOKIE}={current}', 'Origin': ORIGIN}
            async with self.client.post('/chat/notice-call', data=body, headers=headers) as reply:
                self.assertEqual(reply.status, status)
                self.assertIn('microphone=(self)' if allowed else 'microphone=()', reply.headers['Permissions-Policy'])
                self.assertEqual(reply.headers['Cache-Control'], 'no-store')
                html = await reply.text()
                for private in (reference, self.proof, current, old_choice):
                    self.assertNotIn(private, html)
                return html

        old_html = await document(form | {'ordinaryChoice': old_choice}, status=200, allowed=True)
        old_client = old_html.split('data-client-id="', 1)[1].split('"', 1)[0]
        await self.problem(await self.request('POST', ACCEPT, body=answer | {'clientId': old_client}),
                           403, 'not_allowed')
        code, _ = await self.sessions.create_device_code(who['friend_id'])
        logged = await self.request('POST', '/chat/api/login/code', body={'code': code})
        token = logged.cookies[COOKIE].value
        await self.state(await self.request('GET', SUB, token=token), 'not_registered')
        await document(form, status=403, session=token)
        await document(form | {'ordinaryChoice': old_choice}, status=403, session=token)
        lookup = await self.request('POST', RESOLVE, body={'targetRef': reference}, token=token)
        chosen = form | {'ordinaryChoice': lookup.headers['X-Marong-Ordinary-Choice']}
        await document(chosen | {'installationProof': self.other_proof}, status=403, session=token)
        await document(chosen, status=403, session=self.alt)
        other_reference = self.references.seal('call', who['friend_id'], ring, self.now)
        await document(chosen | {'targetRef': other_reference}, status=403, session=token)
        self.db.admin('UPDATE call.callers SET enabled=false WHERE id=%s', (who['caller_id'],))
        await document(chosen, status=403, session=token)
        self.db.admin('UPDATE call.callers SET enabled=true WHERE id=%s', (who['caller_id'],))
        html = await document(chosen, status=200, allowed=True, session=token)
        self.assertIn('data-purpose="ordinary"', html)
        self.assertNotIn(chosen['ordinaryChoice'], html)
        client = html.split('data-client-id="', 1)[1].split('"', 1)[0]
        await self.problem(await self.request('POST', ACCEPT, token=token, body=answer | {'clientId': client}),
                           403, 'not_allowed')

        endpoint = self.call_site.make_url('/live/web-notification')
        socket_headers = {'Cookie': f'{COOKIE}={token}', 'Origin': str(endpoint.origin())}
        start = {'type': 'start_ordinary', 'clientId': client, 'installationProof': self.proof,
                 'targetRef': reference}
        with patch.object(server, 'LiveSession') as relay:
            for denied in (start | {'clientId': str(uuid4())}, start | {'clientId': answer['clientId']},
                           start | {'targetRef': other_reference}, start | {'installationProof': self.other_proof}):
                async with self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=socket_headers) as ws:
                    await ws.send_json(denied)
                    self.assertEqual(await ws.receive_json(timeout=3), {'type': 'not_allowed'})
            reserve = store.start_notice_ordinary

            async def changed_target(*args, **kwargs):
                self.db.admin(set_deadline, (datetime.now(timezone.utc) + timedelta(minutes=1), ring))
                return await reserve(*args, **kwargs)

            with patch.object(store, 'start_notice_ordinary', side_effect=changed_target):
                async with self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=socket_headers) as ws:
                    await ws.send_json(start)
                    self.assertEqual(await ws.receive_json(timeout=3), {'type': 'ring_unavailable'})
            relay.assert_not_called()
        await document(chosen, status=403, session=token)
        self.db.admin(set_deadline, (deadline, ring))
        self.assertEqual(self.db.admin('SELECT count(*) FROM call.calls WHERE caller_id=%s', (who['caller_id'],)), [(0,)])

        class OrdinaryCall:
            def __init__(self, websocket, *args, **kwargs):
                self.websocket = websocket
                self.explicit = False
                self.d = {}

            async def run(self):
                call, _, _, notification = self.notified_start
                await self.websocket.send_json({'type': 'ready', 'callId': call, 'ring': bool(notification)})

        with patch.object(server, 'LiveSession', OrdinaryCall):
            for _ in range(2):
                async with self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=socket_headers) as ws:
                    await ws.send_json(start)
                    ready = await ws.receive_json(timeout=3)
                    self.assertEqual((ready['type'], ready['ring']), ('ready', False))
                    call_id = ready['callId']
                self.assertEqual(self.db.admin('SELECT id::text FROM call.calls WHERE caller_id=%s',
                                               (who['caller_id'],)), [(call_id,)])
        self.assertEqual(self.db.admin('SELECT status,call_id,answered_at FROM marong.app_rings WHERE id=%s', (ring,)),
                         [('ringing', None, None)])
        await self.state(await self.request('GET', SUB, token=token), 'not_registered')

    async def test_574_web_first_replay_and_android_first_share_atomic_ring(self):
        server, store, protocol, who = await self.call_fixture()
        await self.register_fixture()
        from call_memory import CallBusy, Principal

        p = Principal(who["caller_id"], who["friend_id"], "Fixture", unified=True)
        ring = self.ring(who)
        reference = self.references.seal("call", who["friend_id"], ring, self.now)
        answer = await self.answer_body(reference)
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
        result = await (await self.request("POST", ACCEPT, body=await self.answer_body(reference))).json()
        self.assertEqual(result, {"state": "ring_answered"})
        await self.problem(await self.request("POST", ACCEPT, body=answer, token=self.alt), 403, "not_allowed")
        await self.problem(await self.request("POST", ACCEPT, body={**answer, "clientId": "bad"}), 400, "invalid_input")
        await self.problem(await self.request("POST", ACCEPT, body=answer, token=None), 401, "login_required")
        await self.problem(await self.request("POST", ACCEPT, body=answer, proof=None), 403, "not_allowed")
        await self.problem(await self.request("POST", ACCEPT, body=answer, headers={"Origin": "https://off.invalid"}),
                           403, "cross_site")

        self.db.admin("""UPDATE call.calls SET status='ended',ended_at=now(),end_reason='hangup',organize_status='pending'
                         WHERE id=%s""", (accepted["callId"],))
        expired = self.ring(who, until=-1)
        expired_ref = self.references.seal("call", who["friend_id"], expired, self.now)
        expired_answer = await self.answer_body(expired_ref)
        self.assertEqual(await (await self.request("POST", ACCEPT, body=expired_answer)).json(), {"state": "ring_expired"})
        self.db.admin("UPDATE marong.app_rings SET status='missed',resolved_at=now() WHERE id=%s", (expired,))
        second = self.ring(who)
        winner = await store.reserve_notice_ring(p, str(uuid4()), "Fixture", "fixture", second, legacy=True)
        second_ref = self.references.seal("call", who["friend_id"], second, self.now)
        self.assertEqual(await (await self.request("POST", ACCEPT, body=await self.answer_body(second_ref))).json(),
                         {"state": "ring_answered"})
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s", (p.caller_id,)), [(2,)])
        self.db.admin("""UPDATE call.calls SET status='ended',ended_at=now(),end_reason='hangup',organize_status='pending'
                         WHERE id=%s""", (winner[0],))
        third = self.ring(who)
        third_ref = self.references.seal("call", who["friend_id"], third, self.now)
        submitted = await asyncio.gather(
            self.request("POST", ACCEPT, body=await self.answer_body(third_ref)),
            self.request("POST", ACCEPT, body=await self.answer_body(third_ref)),
        )
        self.assertEqual(sorted([(await item.json())["state"] for item in submitted]), ["accepted", "ring_answered"])
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s", (p.caller_id,)), [(3,)])
        self.db.admin("""UPDATE call.calls SET status='ended',ended_at=now(),end_reason='hangup',organize_status='pending'
                         WHERE caller_id=%s AND status='live'""", (p.caller_id,))
        contested = self.ring(who)
        contested_ref = self.references.seal("call", who["friend_id"], contested, self.now)
        web_request, android = await asyncio.gather(
            self.request("POST", ACCEPT, body=await self.answer_body(contested_ref)),
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

    async def test_review_reserved_owner_is_protected_without_socket(self):
        server, store, _, who = await self.call_fixture()
        from call_memory import CallBusy, Principal

        await self.register_fixture()
        principal = Principal(who['caller_id'], who['friend_id'], 'Fixture', unified=True)
        ring = self.ring(who)
        ref = self.references.seal('call', who['friend_id'], ring, self.now)
        body = await self.answer_body(ref)
        accepted = await self.request('POST', ACCEPT, body=body)
        self.assertEqual(accepted.status, 200)
        call = (await accepted.json())['callId']
        end = self.call_site.make_url(f'/api/calls/{call}/end')
        headers = {'Cookie': f'{COOKIE}={self.token}', 'Origin': str(end.origin())}
        for state in ('live', 'resting'):
            self.db.admin('UPDATE call.calls SET status=%s WHERE id=%s', (state, call))
            with self.subTest(state=state), self.assertRaises(CallBusy):
                await store.start_call(principal, str(uuid4()), 'Fixture', 'fixture')
            with patch.object(server, 'LiveSession', side_effect=AssertionError) as relay:
                ordinary = self.call_site.make_url('/live').with_query(client=str(uuid4()))
                async with self.client.session.ws_connect(ordinary, headers=headers) as refused:
                    self.assertEqual(await refused.receive_json(timeout=3), {'type': 'call_busy'})
                relay.assert_not_called()
            async with self.client.session.post(end, headers=headers, json={}) as refused:
                self.assertEqual(refused.status, 404)
            self.assertEqual(self.db.admin('SELECT status FROM call.calls WHERE id=%s', (call,)), [(state,)])
        again = await self.request('POST', ACCEPT, body=body)
        self.assertEqual((await again.json())['callId'], call)

    async def test_review_accept_and_result_require_an_active_current_installation(self):
        _, _, _, who = await self.call_fixture()
        ring = self.ring(who)
        ref = self.references.seal('call', who['friend_id'], ring, self.now)
        body = {'targetRef': ref, 'clientId': str(uuid4())}
        await self.problem(await self.request('POST', ACCEPT, body=body), 403, 'not_allowed')
        self.assertEqual(self.db.admin('SELECT status,call_id FROM marong.app_rings WHERE id=%s', (ring,)), [('ringing', None)])
        await self.register_fixture()
        body = await self.answer_body(ref)
        self.db.admin("UPDATE marong.web_push_subscriptions SET subscription_expires_at='10001-01-01' WHERE installation_id=%s",
                      (installation_id(self.proof),))
        accepted = await self.request('POST', ACCEPT, body=body)
        self.assertEqual((await accepted.json())['state'], 'accepted')
        choice = await self.select('revoke')
        await self.state(await self.request('DELETE', SUB, choice=choice), 'revoked')
        await self.problem(await self.request('POST', ACCEPT, body=body), 403, 'not_allowed')

    async def test_review_document_binding_survives_refresh_and_rejects_same_account_relogin(self):
        _, _, _, who = await self.call_fixture()
        await self.register_fixture()
        ring = self.ring(who)
        set_deadline = 'UPDATE marong.app_rings SET answer_until=%s WHERE id=%s'
        before_deadline = self.now + timedelta(microseconds=1)
        self.db.admin(set_deadline, (before_deadline, ring))
        ref = self.references.seal('call', who['friend_id'], ring, self.now)
        ident = installation_id(self.proof)
        async with self.service.pool.connection() as conn:
            consent, _ = await self.service.active_consent(conn, ident, self.sid, self.now)
        document = str(self.chat.web_push_call.document_client(self.sid, ident, ref, consent))
        read = {'targetRef': ref}
        header = {'X-Marong-Notice-Document': document}
        self.assertEqual((await self.request('POST', RESOLVE, body=read, headers=header)).status, 200)
        refresh = await self.select('refresh')
        await self.state(await self.request('PUT', SUB, choice=refresh, body=self.subscription()), 'active')
        self.assertEqual((await self.request('POST', RESOLVE, body=read, headers=header)).status, 200)
        code, _ = await self.sessions.create_device_code(who['friend_id'])
        logged = await self.request('POST', '/chat/api/login/code', body={'code': code})
        self.assertEqual(logged.status, 200)
        changed = logged.cookies[COOKIE].value
        ready = await self.request('POST', RESOLVE, body=read, token=changed)
        self.assertEqual((ready.status, await ready.json()),
                         (200, {'state': 'ring_ready', 'answerUntil': before_deadline.isoformat()}))
        self.db.admin(set_deadline, (self.now, ring))
        expired = await self.request('POST', RESOLVE, body=read, token=changed)
        self.assertEqual((expired.status, await expired.json()), (200, {'state': 'ring_expired'}))
        async with self.client.post('/chat/notice-call',
                                    data=read | {'installationProof': self.proof, 'navigation': uuid4().hex},
                                    headers={'Cookie': f'{COOKIE}={changed}', 'Origin': ORIGIN}) as denied:
            self.assertEqual(denied.status, 403)
            self.assertIn('microphone=()', denied.headers['Permissions-Policy'])
            self.assertEqual(denied.headers['Cache-Control'], 'no-store')
            self.assertIn('약속 전화 시간이 지났어', await denied.text())
        self.db.admin(set_deadline, (before_deadline, ring))
        enable = await self.select('enable', token=changed)
        await self.state(await self.request('PUT', SUB, choice=enable, token=changed, body=self.subscription()), 'active')
        await self.problem(await self.request('POST', RESOLVE, body=read, headers=header, token=changed), 403, 'not_allowed')
        await self.problem(await self.request('POST', ACCEPT, body=read | {'clientId': document}, token=changed),
                           403, 'not_allowed')
        self.assertEqual((await self.request('POST', RESOLVE, body=read, token=changed)).status, 200)
        self.assertEqual(self.db.admin('SELECT status,call_id FROM marong.app_rings WHERE id=%s', (ring,)), [('ringing', None)])

    async def test_review_revocation_before_reservation_and_reservation_before_revocation(self):
        server, store, _, who = await self.call_fixture()
        await self.register_fixture()
        ring = self.ring(who)
        ref = self.references.seal('call', who['friend_id'], ring, self.now)
        body = await self.answer_body(ref)
        ready, proceed = asyncio.Event(), asyncio.Event()
        reserve = store.reserve_notice_ring

        async def delayed_reserve(*args, **kwargs):
            ready.set()
            await proceed.wait()
            return await reserve(*args, **kwargs)

        choice = await self.select('revoke')
        with patch.object(store, 'reserve_notice_ring', side_effect=delayed_reserve):
            request = asyncio.create_task(self.request('POST', ACCEPT, body=body))
            try:
                await asyncio.wait_for(ready.wait(), 2)
                await self.state(await self.request('DELETE', SUB, choice=choice), 'revoked')
            finally:
                proceed.set()
            await self.problem(await request, 403, 'not_allowed')
        self.assertEqual(self.db.admin('SELECT status,call_id FROM marong.app_rings WHERE id=%s', (ring,)), [('ringing', None)])
        await self.register_fixture()
        body = await self.answer_body(ref)
        choice = await self.select('revoke')
        ready.clear()
        proceed.clear()
        validation = server.validate_notice_installation

        async def allowed_before_revocation(*args):
            deadline = await validation(*args)
            ready.set()
            await proceed.wait()
            return deadline

        with patch.object(server, 'validate_notice_installation', side_effect=allowed_before_revocation):
            request = asyncio.create_task(self.request('POST', ACCEPT, body=body))
            try:
                await asyncio.wait_for(ready.wait(), 2)
                revoke = asyncio.create_task(self.request('DELETE', SUB, choice=choice))
                await asyncio.sleep(0.05)
                self.assertFalse(revoke.done())
            finally:
                proceed.set()
            self.assertEqual((await (await request).json())['state'], 'accepted')
            await self.state(await revoke, 'revoked')
        await self.problem(await self.request('POST', ACCEPT, body=body), 403, 'not_allowed')

    async def test_review_expired_subscription_sweep_is_separate_from_read_and_event_ttl(self):
        await self.register_fixture()
        await self.register_fixture(proof=self.other_proof)
        ident = installation_id(self.proof)
        self.db.admin('UPDATE marong.web_push_subscriptions SET subscription_expires_at=%s WHERE installation_id=%s',
                      (self.now, ident))
        old = self.row()[0]
        await self.state(await self.request('GET', SUB), 'expired')
        self.assertEqual(self.row()[0], old)
        self.assertGreaterEqual(await self.service.sweep_expired(), 1)
        state, revision, fingerprint, material, expires = self.row()[0]
        self.assertEqual((state, fingerprint, material, expires), ('expired', None, None, None))
        self.assertNotEqual(revision, old[1])
        self.assertEqual(self.row(self.other_proof)[0][0], 'active')
        self.assertEqual(await self.service.sweep_expired(), 0)

    async def test_review_expiry_sweep_does_not_clear_newer_registration(self):
        await self.register_fixture()
        ident = installation_id(self.proof)
        self.db.admin('UPDATE marong.web_push_subscriptions SET subscription_expires_at=%s WHERE installation_id=%s',
                      (self.now, ident))
        old_revision = self.row()[0][1]
        choice = await self.select('enable')
        locked, proceed = asyncio.Event(), asyncio.Event()

        async def resolve(_):
            locked.set()
            await proceed.wait()
            return ('1.1.1.1',)

        with patch.object(self.service, 'resolve', side_effect=resolve):
            renewed = asyncio.create_task(self.request('PUT', SUB, choice=choice, body=self.subscription()))
            try:
                await asyncio.wait_for(locked.wait(), 2)
                sweep = asyncio.create_task(self.service.sweep_expired())
                await asyncio.sleep(0.05)
                self.assertFalse(sweep.done())
            finally:
                proceed.set()
            await self.state(await renewed, 'active')
            self.assertEqual(await sweep, 0)
        state, revision, fingerprint, material, _ = self.row()[0]
        self.assertEqual(state, 'active')
        self.assertNotEqual(revision, old_revision)
        self.assertIsNotNone(fingerprint)
        self.assertIsNotNone(material)

    async def test_574_session_expires_while_waiting_for_caller_lock(self):
        _, store, _, who = await self.call_fixture()
        from call_memory import NoticeRingState, Principal

        p = Principal(who["caller_id"], who["friend_id"], "Fixture")
        ring = self.ring(who)
        async with store.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT id FROM call.callers WHERE id=%s FOR UPDATE", (p.caller_id,))
            self.db.admin("UPDATE marong.app_sessions SET expires_at=now()+interval '1 second' WHERE id=%s", (self.sid,))
            request = asyncio.create_task(store.reserve_notice_ring(
                p, str(uuid4()), "Fixture", "fixture", ring, session=self.sid))
            await asyncio.sleep(1.25)
        with self.assertRaises(NoticeRingState) as caught:
            await request
        self.assertEqual(caught.exception.state, "login_required")
        self.assertEqual(self.db.admin("SELECT status,call_id FROM marong.app_rings WHERE id=%s", (ring,)),
                         [("ringing", None)])
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s", (p.caller_id,)), [(0,)])

    async def test_575_all_failure_frames_leave_db_and_media_untouched(self):
        from contextlib import nullcontext
        from call_cost import BLOCKED
        from call_memory import NoticeRingState

        server, store, protocol, who = await self.call_fixture()
        await self.register_fixture()
        endpoint = self.call_site.make_url("/live/web-notification")
        headers = {"Cookie": f"{COOKIE}={self.token}", "Origin": str(endpoint.origin())}
        ring = self.ring(who, until=-5)
        reference = self.references.seal("call", who["friend_id"], ring, self.now)
        ident = installation_id(self.proof)
        ordinary = str(protocol.document_client(self.sid, ident, reference, None))
        start = {"type": "start_ordinary", "clientId": ordinary, "installationProof": self.proof, "targetRef": reference}
        client = (await self.answer_body(reference))["clientId"]
        # A once-valid connection credential can outlive a reservation rollback.
        # Use a synthetic signed credential for an expired, unaccepted ring.
        expired = protocol.issue(self.sid, installation_id(self.proof), client_uuid(client), str(uuid4()), ring, self.now)
        notified = {"type": "start_notified", "clientId": client, "installationProof": self.proof,
                    "connectToken": expired}
        before = self.db.admin("SELECT status,call_id,answered_at FROM marong.app_rings WHERE id=%s", (ring,))
        missing = self.references.seal("call", who["friend_id"], uuid4(), self.now)
        seen = set()
        cases = (
            ("invalid_input", '{"type":"ignored",' + json.dumps(start)[1:], nullcontext()),
            ("invalid_input", b"binary-first", nullcontext()),
            ("invalid_input", json.dumps(start).ljust(2049), nullcontext()),
            ("invalid_input", None, nullcontext()),
            ("not_allowed", {**notified, "installationProof": self.other_proof}, nullcontext()),
            ("not_allowed", {**notified, "clientId": str(uuid4())}, nullcontext()),
            ("ring_expired", notified, nullcontext()),
            ("ring_answered", start, patch.object(store, "start_notice_ordinary",
                          side_effect=NoticeRingState("ring_answered"))),
            ("ring_unavailable", {**start, "targetRef": missing,
                                  "clientId": str(protocol.document_client(self.sid, ident, missing, None))}, nullcontext()),
            ("call_busy", start, patch.object(server, "active_calls",
                                             {who["friend_id"]: server.CallSlot(str(uuid4()))})),
            ("calls_full", start, patch.object(server, "CALL_MAX", 0)),
            ("daily_limit", start, patch.object(store.daily_usage, "blocked", return_value=True)),
            ("budget_exhausted", start, patch.object(server, "budget_status", return_value=next(iter(BLOCKED)))),
            ("db_unavailable", start, patch.object(store, "one", side_effect=OperationalError)),
            ("login_required", start, nullcontext()),
        )
        with patch.object(server, "LiveSession") as live_factory:
            for code, frame, fault in cases:
                with self.subTest(code=code, frame_kind=type(frame).__name__), fault:
                    async with self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=headers) as ws:
                        self.assertEqual(ws.protocol, SUBPROTOCOL)
                        if code == "login_required":
                            self.db.admin("UPDATE marong.app_sessions SET revoked_at=now() WHERE id=%s", (self.sid,))
                        if isinstance(frame, dict):
                            await ws.send_json(frame)
                        elif isinstance(frame, str):
                            await ws.send_str(frame)
                        elif isinstance(frame, bytes):
                            await ws.send_bytes(frame)
                        self.assertEqual(await ws.receive_json(timeout=7), {"type": code})
                        seen.add(code)
                        await ws.close()
                    self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s",
                                                   (who["caller_id"],)), [(0,)])
                    self.assertEqual(self.db.admin("SELECT status,call_id,answered_at FROM marong.app_rings WHERE id=%s",
                                                   (ring,)), before)
            live_factory.assert_not_called()
        self.assertEqual(seen, {"login_required", "not_allowed", "invalid_input", "ring_expired", "ring_answered",
                                "ring_unavailable", "call_busy", "calls_full", "daily_limit", "budget_exhausted",
                                "db_unavailable"})

    async def test_575_socket_protocol_first_frame_and_preaccepted_call(self):
        server, store, protocol, who = await self.call_fixture()
        await self.register_fixture()
        import live_session
        from call_memory import MemoryStore
        from test_relay import HTTP, Upstream, event
        origin = str(self.call_site.make_url("/")).rstrip("/")
        ring = self.ring(who)
        reference = self.references.seal("call", who["friend_id"], ring, self.now)
        client = (await self.answer_body(reference))["clientId"]
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
            for incoming, offers, status, code in (
                (headers, (), 400, "invalid_input"),
                ({**headers, "Origin": "https://off.invalid"}, [SUBPROTOCOL], 403, "cross_site"),
                ({"Origin": origin}, [SUBPROTOCOL], 401, "login_required"),
            ):
                with self.assertRaises(WSServerHandshakeError) as caught:
                    await self.client.session.ws_connect(endpoint, protocols=offers, headers=incoming)
                self.assertEqual(caught.exception.status, status)
                protocol_header = {"Sec-WebSocket-Protocol": SUBPROTOCOL} if offers else {}
                async with self.client.session.get(endpoint, headers=incoming | protocol_header) as blocked:
                    self.assertEqual((blocked.status, await blocked.json()), (status, {"code": code}))
            pending = server.CallSlot(client, reconnecting=True)
            previews = (
                (patch.object(server, "active_calls", {who["friend_id"]: pending}), 409, "call_busy"),
                (patch.object(server, "notice_identity", side_effect=OperationalError), 503, "db_unavailable"),
                (patch.object(server, "notice_identity", side_effect=RuntimeError), 500, "internal"),
            )
            for condition, status, code in previews:
                with condition:
                    with self.assertRaises(WSServerHandshakeError) as caught:
                        await self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=headers)
                    self.assertEqual(caught.exception.status, status)
                    async with self.client.session.get(
                            endpoint, headers=headers | {"Sec-WebSocket-Protocol": SUBPROTOCOL}) as blocked:
                        self.assertEqual((blocked.status, await blocked.json()), (status, {"code": code}))
            valid = {"type": "start_notified", "clientId": client, "installationProof": self.proof,
                     "connectToken": accepted["connectToken"]}
            expired_token = protocol.issue(
                self.sid, installation_id(self.proof), client_uuid(client), accepted["callId"], ring,
                self.now - timedelta(seconds=120))
            ordinary_id = str(protocol.document_client(self.sid, installation_id(self.proof), reference, None))
            for body, failure in (({**valid, "extra": "x" * 2048}, "invalid_input"),
                                  ({**valid, "installationProof": self.other_proof}, "not_allowed"),
                                  ({**valid, "clientId": ordinary_id}, "not_allowed"),
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
        original_history = self.db.admin("SELECT status,call_id,answered_at FROM marong.app_rings WHERE id=%s", (ring,))
        original_call = self.notice_call_state(accepted['callId'])
        expired = self.ring(who)
        self.db.admin('UPDATE marong.app_rings SET answer_until=%s WHERE id=%s',
                      (self.now - timedelta(seconds=1), expired))
        reference = self.references.seal("call", who["friend_id"], expired, self.now)
        lookup = await self.request('POST', RESOLVE, body={'targetRef': reference})
        choice = lookup.headers['X-Marong-Ordinary-Choice']
        form = {'targetRef': reference, 'installationProof': self.proof, 'navigation': uuid4().hex,
                'ordinaryChoice': choice}
        async with self.client.post('/chat/notice-call', data=form, headers=headers | {'Origin': ORIGIN}) as document:
            self.assertEqual(document.status, 200)
            ordinary_client = (await document.text()).split('data-client-id="', 1)[1].split('"', 1)[0]
        ordinary = {"type": "start_ordinary", "clientId": ordinary_client, "installationProof": self.proof,
                    "targetRef": reference}
        with (patch.object(server, "google_headers", AsyncMock(return_value={})),
              patch.object(live_session, "ClientSession", side_effect=lambda **_: HTTP(Upstream()))):
            async with self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=headers) as ws:
                await ws.send_json(ordinary)
                ready = await event(ws, 'ready')
                self.assertEqual((ready["type"], ready["ring"]), ("ready", False))
                ordinary_call = ready['callId']
                slot = server.active_calls[who['friend_id']]
                await ws.send_json({'type': 'stop'})
                await asyncio.wait_for(slot.released.wait(), 5)
        status, _, _, _, reason = self.notice_call_state(ordinary_call)
        self.assertEqual((status, reason), ('ended', 'hangup'))
        self.assertEqual(self.db.admin("SELECT status,call_id FROM marong.app_rings WHERE id=%s", (expired,)),
                         [("ringing", None)])
        count = self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s", (who["caller_id"],))
        self.assertEqual(count, [(2,)])
        lookup = await self.request('POST', RESOLVE, body={'targetRef': reference})
        self.assertEqual(lookup.headers['X-Marong-Ordinary-Choice'], choice)

        # Recreate the relay's local state. The target and document are still valid, so rejection
        # has to come from the finished call row rather than an expired credential or an active slot.
        new_store = MemoryStore(self.db.admin_url.replace('postgres:@', 'marong_call@', 1), notice_deadlines=True)
        await new_store.open()
        self.addAsyncCleanup(new_store.close)
        restarted = web.Application()
        restarted.router.add_get('/live/web-notification', server.notice_live)
        relay = TestServer(restarted)
        await relay.start_server()
        self.addAsyncCleanup(relay.close)
        retry = relay.make_url('/live/web-notification')
        with (patch.object(server, 'memory_store', new_store), patch.object(server, 'active_calls', {}),
              patch.object(server, 'resume_state', {}),
              patch.object(new_store.daily_usage, 'blocked', AsyncMock(return_value=False)),
              patch.object(server, 'LiveSession') as unexpected):
            async with self.client.session.ws_connect(retry, protocols=[SUBPROTOCOL],
                                                     headers=headers | {'Origin': str(retry.origin())}) as ws:
                await ws.send_json(ordinary)
                self.assertEqual(await ws.receive_json(timeout=3), {"type": "ring_unavailable"})
            unexpected.assert_not_called()
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s", (who["caller_id"],)), count)
        self.assertEqual(self.db.admin("SELECT status,call_id,answered_at FROM marong.app_rings WHERE id=%s", (ring,)),
                         original_history)
        self.assertEqual(self.notice_call_state(accepted['callId']), original_call)

    async def test_575_relay_webrtc_pcm_reconnect_and_rejected_stop(self):
        server, _, _, who = await self.call_fixture()
        await self.register_fixture()
        import live_session
        from rtc_transport import Bridge
        from test_relay import HTTP, Upstream, event, turn

        endpoint = self.call_site.make_url("/live/web-notification")
        headers = {"Cookie": f"{COOKIE}={self.token}", "Origin": str(endpoint.origin())}
        ring = self.ring(who)
        reference = self.references.seal("call", who["friend_id"], ring, self.now)
        client = (await self.answer_body(reference))["clientId"]
        accepted = await (await self.request("POST", ACCEPT, body={"targetRef": reference, "clientId": client})).json()
        frame = {"type": "start_notified", "clientId": client, "installationProof": self.proof,
                 "connectToken": accepted["connectToken"]}
        call_id = accepted["callId"]
        upstreams = []
        code, _ = await self.sessions.create_device_code(who["friend_id"])
        sibling = await self.sessions.redeem_device_code(code, "192.0.2.5", "Fixture")

        def provider(**_settings):
            upstream = Upstream()
            upstreams.append(upstream)
            return HTTP(upstream)

        bridge = Bridge.__new__(Bridge)
        bridge.owner = f"friend:{who['friend_id']}"
        bridge.client, bridge.name = client, "fixture-room"
        bridge.closed, bridge.session, bridge.task = False, None, None
        bridge.epoch, bridge.turns = 0, deque()
        bridge.source = Mock()
        bridge.close = AsyncMock()
        bridge.token = lambda: "synthetic-media-token"

        async def send_mic(ws, upstream):
            await ws.send_bytes(b"\x01\x02" * 480)
            for _ in range(80):
                if any("realtimeInput" in item and "audio" in item["realtimeInput"] for item in upstream.sent):
                    return
                await asyncio.sleep(.025)
            self.fail("synthetic microphone audio did not reach the relay upstream")

        async def open_socket():
            return await self.client.session.ws_connect(endpoint, protocols=[SUBPROTOCOL], headers=headers)

        async def prepare_media(owner, config_client, *, capacity):
            self.assertEqual((owner, config_client), (bridge.owner, client))
            server.rtc_transport.bridges[client] = bridge
            return bridge

        with (patch.object(server, "google_headers", AsyncMock(return_value={})),
              patch.object(live_session, "ClientSession", provider),
              patch.object(server.rtc_transport, "bridges", {}),
              patch.object(server.rtc_transport, "enabled", return_value=True),
              patch.object(server.rtc_transport, "acquire", side_effect=prepare_media)):
            async with await open_socket() as ws:
                # Exactly 2,048 bytes is a legal JSON frame with whitespace.
                await ws.send_str(json.dumps(frame).ljust(2048))
                ready = await event(ws, "ready")
                self.assertEqual((ready["callId"], ready["ring"], ready["memoryConnected"]),
                                 (call_id, True, True))
                rtc_reply = await self.client.session.post(self.call_site.make_url("/api/rtc"),
                                                           headers=headers, json={"client": client})
                self.assertEqual(rtc_reply.status, 200)
                self.assertEqual((await rtc_reply.json())["room"], bridge.name)
                wrong_install = await self.client.session.post(
                    self.call_site.make_url("/api/rtc"), headers={**headers, "Cookie": f"{COOKIE}={sibling.token}"},
                    json={"client": client})
                self.assertEqual(wrong_install.status, 409)
                await ws.send_json({"type": "audio_ready", "path": "webrtc"})
                await event(ws, "audio_end")
                await event(ws, "turn")
                await send_mic(ws, upstreams[0])
                self.assertEqual(len(bridge.turns), 1)
                self.assertEqual(bytes(bridge.turns[0]["pcm"]), b"\x00\x01" * 240)

                async with await open_socket() as rejected:
                    await rejected.send_json({**frame, "clientId": str(uuid4())})
                    await rejected.send_json({"type": "stop"})
                    self.assertEqual(await rejected.receive_json(timeout=3), {"type": "not_allowed"})
                current = server.active_calls[who["friend_id"]].session
                end = self.call_site.make_url(f'/api/calls/{call_id}/end')
                async with self.client.session.post(end, headers=headers, json={}) as refused:
                    self.assertEqual(refused.status, 404)
                self.assertFalse(current.stop.is_set())
                self.assertEqual(self.db.admin("SELECT status FROM call.calls WHERE id=%s", (call_id,)), [("live",)])

                await ws.send_json({"type": "audio_transport", "mode": "pcm", "reason": "rtc_media_stalled"})
                fallback = await event(ws, "audio_transport")
                self.assertEqual((fallback["callId"], fallback["switched"], fallback["mode"]), (call_id, True, "pcm"))
                pcm = await ws.receive_bytes(timeout=3)
                self.assertEqual(live_session.FRAME.unpack(pcm[:24])[0], b"MRG2")
                self.assertEqual(pcm[24:], b"\x00\x01" * 240)
                await event(ws, "audio_end")
                await ws.send_json({"type": "text", "text": "Synthetic test prompt"})
                await turn(ws)
                self.assertEqual(len(upstreams), 1)

            server.rtc_transport.bridges.clear()
            async with await open_socket() as restored:
                await restored.send_json(frame)
                ready = await event(restored, "ready")
                self.assertEqual((ready["callId"], ready["ring"], ready["audioTransport"], ready["resumed"]),
                                 (call_id, True, "pcm", True))
                await restored.send_json({"type": "audio_ready", "path": "pcm"})
                await send_mic(restored, upstreams[-1])
                await restored.send_json({"type": "text", "text": "Synthetic test after reconnect"})
                await turn(restored)
                await restored.send_json({"type": "stop"})
                await restored.receive(timeout=3)
            async with await open_socket() as ended:
                await ended.send_json(frame)
                self.assertEqual(await ended.receive_json(timeout=3), {"type": "ring_answered"})
        self.assertEqual(self.db.admin("""
            SELECT c.status,r.status,r.call_id::text FROM call.calls c JOIN marong.app_rings r ON r.call_id=c.id
            WHERE c.caller_id=%s AND r.id=%s
        """, (who["caller_id"], ring)), [("ended", "answered", call_id)])
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.calls WHERE caller_id=%s",
                                       (who["caller_id"],)), [(1,)])
        self.assertEqual(self.db.admin("SELECT count(*) FROM call.segments WHERE call_id=%s", (call_id,)), [(2,)])

    async def test_577_existing_routes_and_android_eligibility_with_web_push_on_and_off(self):
        server, _, protocol, who = await self.call_fixture()
        import live_session
        from test_relay import HTTP, Upstream

        fcm = Mock(send=AsyncMock(return_value="ok"))
        self.chat.push = AppPush(self.store, fcm, ring_enabled=True)
        room_lock = asyncio.Lock()
        self.chat.client = Mock(room_lock=Mock(return_value=room_lock))
        await self.store.add_message(who["room_key"], "assistant", "Synthetic saved reply",
                                     meta={"delivered": True})
        device = uuid4()
        device_path = f"/chat/api/devices/{device}"
        granted = {"fid": "fixture" * 3, "notifications": "granted", "appVersion": "0.3.4",
                   "ring": {"channel": "enabled", "fullScreen": "denied"}}
        android_headers = {"User-Agent": "MarongApp/0.3.4"}
        status_url = self.call_site.make_url("/api/me")
        status_headers = {"Cookie": f"{COOKIE}={self.token}", "Origin": str(status_url.origin())}
        flags = []
        for enabled in (False, True):
            self.chat.web_push_subscriptions = self.service if enabled else None
            self.chat.web_push_call = protocol if enabled else None
            app = TestClient(TestServer(self.chat.web_app()))
            await app.start_server()
            self.addAsyncCleanup(app.close)
            self.client = app
            if enabled:
                await self.register_fixture()
            with (patch.object(server, "NOTICE_CALL", protocol if enabled else None),
                  patch.object(server, "google_headers", AsyncMock(return_value={})),
                  patch.object(live_session, "ClientSession", side_effect=lambda **_: HTTP(Upstream())),
                  patch.object(server.rtc_transport, "enabled", return_value=False),
                  patch.object(server.rtc_transport, "bridges", {})):
                before = await self.request("PUT", device_path, body=granted, headers=android_headers)
                self.assertEqual(before.status, 200 if enabled else 201)
                delivery = await before.json()
                self.assertEqual(delivery["delivery"]["to"], "app")
                self.assertEqual(delivery["ring"], {"to": "app", "reason": "app_on", "fullScreen": False})
                self.assertEqual(len(await self.chat.push.ring_devices(who["friend_id"])), 1)
                await self.chat.push.notify(who["friend_id"], "reply", "Synthetic notification")
                self.assertEqual(fcm.send.await_count, len(flags) + 1)
                me = await self.request("GET", "/chat/api/me", proof=None,
                                        headers={"User-Agent": "iPhone Fixture Safari"})
                self.assertEqual(me.status, 200)
                messages = await self.request("GET", "/chat/api/messages", proof=None)
                self.assertEqual(messages.status, 200)
                refused = await self.request("PUT", device_path, body={**granted, "notifications": "denied"},
                                             headers=android_headers)
                self.assertEqual(refused.status, 200)
                self.assertEqual(await self.chat.push.ring_devices(who["friend_id"]), [])
                self.assertEqual(await self.chat.push.notify(who["friend_id"], "reply", "Synthetic notification"),
                                 (0, 0))
                async with self.client.session.get(status_url, headers=status_headers) as reply:
                    self.assertEqual(reply.status, 200)
                    call_status = await reply.json()
                    self.assertTrue(call_status["canCall"])
                async with self.client.session.get(status_url) as unauthorized:
                    self.assertEqual(unauthorized.status, 401)
                with patch.object(server, "budget_status", side_effect=RuntimeError):
                    async with self.client.session.get(status_url, headers=status_headers) as unavailable:
                        self.assertEqual(unavailable.status, 500)
                # Ordinary Safari dials without a notification credential.
                # Android answers the existing explicit ring on the legacy route.
                frames = []
                ring = self.ring(who)
                original = None
                answered_at = None
                for android, taking_ring in ((True, True), (True, False), (False, False)):
                    query = {"client": str(uuid4()), "hangup": "1"}
                    if android:
                        query["ring"] = str(ring)
                    endpoint = self.call_site.make_url("/live").with_query(query)
                    headers = status_headers | (android_headers if android else {"User-Agent": "iPhone Fixture Safari"})
                    with self.assertRaises(WSServerHandshakeError) as origin_error:
                        await self.client.session.ws_connect(endpoint, headers=headers | {"Origin": "https://off.invalid"})
                    self.assertEqual(origin_error.exception.status, 403)
                    async with self.client.session.ws_connect(endpoint, headers=headers) as ws:
                        async with asyncio.timeout(5):
                            while (ready := await ws.receive_json())['type'] not in {'ready', 'call_busy'}:
                                pass
                        self.assertEqual(ready['type'], 'ready', f'Android={android}, enabled={enabled}')
                        self.assertEqual((ready["ring"], ready["memoryConnected"]), (taking_ring, True))
                        frames.append((ready["ring"], ready["memoryConnected"], ready["audioFormat"]))
                        if taking_ring:
                            original = ready['callId']
                            (answered_at,), = self.db.admin('SELECT answered_at FROM marong.app_rings WHERE id=%s',
                                                           (ring,))
                            self.assertIsNotNone(answered_at)
                        else:
                            self.assertNotEqual(ready['callId'], original)
                        competing = endpoint.with_query({**query, "client": str(uuid4())})
                        async with self.client.session.ws_connect(competing, headers=headers) as second:
                            self.assertEqual(await second.receive_json(timeout=3), {"type": "call_busy"})
                        slot = server.active_calls[who['friend_id']]
                        if android:
                            await ws.send_json({"type": "stop"})
                        else:
                            end = self.call_site.make_url(f'/api/calls/{ready["callId"]}/end')
                            async with self.client.session.post(end, headers=headers, json={}) as stopped:
                                self.assertEqual((stopped.status, await stopped.json()), (200, {'ok': True}))
                        await ws.receive(timeout=3)
                    await asyncio.wait_for(slot.released.wait(), 5)
                    self.assertEqual(self.notice_call_state(ready['callId'])[0], 'ended')
                    self.assertEqual(self.db.admin('SELECT status,call_id::text,answered_at FROM marong.app_rings '
                                                   'WHERE id=%s', (ring,)), [('answered', original, answered_at)])
                flags.append((delivery, await me.json(), await messages.json(), await refused.json(), call_status, frames))
        self.assertEqual(flags[0], flags[1])

    async def test_573_notice_document_requires_current_active_installation_and_owned_ring(self):
        server, _, _, who = await self.call_fixture()
        await self.register_fixture()
        path = '/chat/notice-call'
        ring = self.ring(who)
        reference = self.references.seal('call', who['friend_id'], ring, self.now)
        form = {'targetRef': reference, 'installationProof': self.proof, 'navigation': uuid4().hex}
        cookie = {'Cookie': f'{COOKIE}={self.token}'}
        headers = cookie | {'Origin': ORIGIN, 'Sec-Fetch-Site': 'same-origin',
                            'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}

        async def visit(status, *, method='POST', data=form, incoming=headers, url=path, microphone=False,
                        heading=None):
            async with self.client.request(method, url, data=data if method == 'POST' else None,
                                           headers=incoming, allow_redirects=False) as reply:
                self.assertEqual(reply.status, status)
                self.assertEqual(reply.content_type, 'text/html')
                self.assertEqual(reply.headers['Cache-Control'], 'no-store')
                self.assertEqual(reply.headers['Referrer-Policy'], 'no-referrer')
                self.assertEqual(reply.headers['X-Frame-Options'], 'DENY')
                self.assertIn("form-action 'none'", reply.headers['Content-Security-Policy'])
                self.assertEqual(reply.headers['Permissions-Policy'], 'camera=(), microphone=' +
                                 ('(self)' if microphone else '()') + ', geolocation=()')
                body = await reply.text()
                for private in (reference, self.proof, self.token):
                    self.assertNotIn(private, body)
                self.assertEqual(form['navigation'] in body, microphone)
                if heading:
                    self.assertIn(heading, body)
                return body

        entry = await visit(200, microphone=True)
        async with self.client.get('/chat/', headers=cookie) as chat:
            self.assertIn('microphone=()', chat.headers['Permissions-Policy'])
            self.assertEqual(chat.headers['Referrer-Policy'], 'same-origin')
            self.assertTrue(chat.headers['Content-Security-Policy'].endswith(f'form-action {ORIGIN}{path}'))
        await visit(404, method='GET')
        await visit(404, url=path + '?extra=1')
        for wrong in (cookie, headers | {'Origin': 'null'}, headers | {'Origin': 'https://off.invalid'},
                      headers | {'Sec-Fetch-Dest': 'iframe'}, headers | {'Sec-Fetch-Mode': 'cors'}):
            await visit(403, incoming=wrong)
        await visit(400, data=[*form.items(), ('targetRef', reference)])
        await visit(400, data=form | {'navigation': 'x' * 2050})
        await visit(400, data=form | {'targetRef': 'bad'})
        await visit(401, incoming=headers | {'Cookie': 'other=fixture'}, heading='로그인한 뒤 알림을 확인할게')
        await visit(403, data=form | {'installationProof': 'not-valid'})
        await visit(403, data=form | {'installationProof': self.other_proof})
        await visit(403, incoming=headers | {'Cookie': f'{COOKIE}={self.alt}'})
        await visit(404, data=form | {'targetRef': self.references.seal('call', who['friend_id'], uuid4(), self.now)})
        await visit(404, data=form | {'targetRef': self.references.seal('call', who['friend_id'] + 1, ring, self.now)})
        with patch.object(self.service, 'limit', side_effect=server.SessionError('request_limit', retry_after=3)):
            await visit(429, heading='잠시 뒤 다시 확인해 줘')
        with patch.object(self.service, '_row', side_effect=OperationalError):
            await visit(503, heading='지금 전화 상태를 확인할 수 없어')
        with patch.object(self.service, '_row', side_effect=RuntimeError):
            await visit(500, heading='지금 전화 상태를 확인할 수 없어')
        with patch.object(self.chat, 'web_push_call', None):
            await visit(404)
            async with self.client.get('/chat/', headers=cookie) as chat:
                self.assertEqual(chat.headers['Referrer-Policy'], 'no-referrer')
                self.assertTrue(chat.headers['Content-Security-Policy'].endswith("form-action 'none'"))
        self.db.admin('UPDATE marong.app_rings SET answer_until=%s WHERE id=%s', (self.now, ring))
        await visit(200, heading='약속 전화 시간이 지났어')
        self.assertEqual(self.db.admin('SELECT status,call_id FROM marong.app_rings WHERE id=%s', (ring,)), [('ringing', None)])
        self.assertEqual(self.db.admin('SELECT count(*) FROM call.calls WHERE caller_id=%s', (who['caller_id'],)), [(0,)])
        self.db.admin('UPDATE marong.app_rings SET answer_until=now()+interval \'30 seconds\' WHERE id=%s', (ring,))
        client = entry.split('data-client-id="', 1)[1].split('"', 1)[0]
        accepted = await self.request('POST', ACCEPT, body={'targetRef': reference, 'clientId': client})
        self.assertEqual((await accepted.json())['state'], 'accepted')
        await visit(200, heading='이미 받은 전화야')
        self.db.admin('UPDATE marong.app_sessions SET revoked_at=now() WHERE id=%s', (self.sid,))
        await visit(401, heading='로그인한 뒤 알림을 확인할게')


if __name__ == "__main__":
    unittest.main()
