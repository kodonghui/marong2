"""Server-side app update tests (TC-599–601, TC-607–613)."""
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx
import psycopg
from aiohttp.test_utils import TestClient, TestServer

from pg import TestDB
from test_app_update import ROOT, apk, fixture
from test_app_chat import AUD, HK_EMAIL, ORIGIN, STRANGER, TEAM, Certs, auth, prepare, problem
from test_app_chat import fcm_bad_request, fcm_unregistered, mock_fcm
from marong import fcm
from marong.access import AccessConfig, AccessVerifier, email_hash
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_release import PACKAGE, AppReleases
from marong.app_update_push import AppUpdatePush
from marong.discord_store import DiscordStore
from tools import app_release


class UpdateMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_tc601_data_only_and_no_inline_retry(self):
        message = fcm.app_update("synthetic-test-fid", 11)
        self.assertEqual(message, {"fid": "synthetic-test-fid", "data": {"kind": "app_update", "v": "11"},
                                   "android": {"priority": "HIGH", "ttl": "86400s", "collapse_key": "app_update"}})
        http = AsyncMock()
        http.post.return_value = httpx.Response(503)
        sender = fcm.FCM(fcm.ServiceAccount("unused", "unused", "unused", "synthetic-project"), http=http)
        with patch.object(sender, "_token", return_value="synthetic-token"):
            self.assertEqual(await sender.send(message), "failed")
        http.post.assert_awaited_once()


def phone(ident):
    return str(UUID(int=ident))


def fid(ident):
    return f"synthetic-fid-{ident:06d}"


class FakeFCM:
    def __init__(self, callback=None):
        self.callback = callback
        self.messages = []
        self.active = 0
        self.peak = 0

    async def send(self, message):
        self.messages.append(message)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.001)
            return await self.callback(message) if self.callback else "ok"
        finally:
            self.active -= 1


class PushWatcherTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = TestDB()
        cls.addClassCleanup(cls.db.close)
        cls.db.apply_sql(ROOT / "marong/call/schema.sql", ROOT / "marong/migrations/012_schedules.sql",
                         ROOT / "marong/migrations/014_app_chat.sql", ROOT / "marong/migrations/015_app_ring.sql",
                         ROOT / "marong/migrations/023_app_update_events.sql")

    async def asyncSetUp(self):
        self.db.admin("TRUNCATE marong.app_devices, marong.app_update_events")
        self.db.admin("INSERT INTO marong.friends(id, name) OVERRIDING SYSTEM VALUE "
                      "SELECT n, 'Fixture ' || n FROM generate_series(1, 10) n "
                      "ON CONFLICT DO NOTHING")
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.releases = AppReleases(self.folder)
        self.store = DiscordStore(self.db.app_url)
        self.addAsyncCleanup(self.store.close)
        await self.store.open(wait=True)
        self.time = 0

    def add_phone(self, ident, friend=1, *, version="0.2.9", days=0, has_fid=True, dropped=False):
        self.db.admin("""INSERT INTO marong.app_devices (install_id, friend_id, fid, notifications, app_version,
                       seen_at, dropped_at) VALUES (%s,%s,%s,'denied',%s,
                       now() - make_interval(days => %s, secs => %s), CASE WHEN %s THEN now() END)""",
                      (phone(ident), friend, fid(ident) if has_fid else None, version, days, ident, dropped))

    def watcher(self, sender):
        return AppUpdatePush(self.store, self.releases, sender, clock=lambda: self.time)

    def events(self):
        return self.db.admin("SELECT kind, attempt, status FROM marong.app_update_events ORDER BY id")

    async def test_tc599_poll_and_select_current_eligible_phones(self):
        self.add_phone(1)
        self.add_phone(2, version="0.2.10")
        self.add_phone(3, version="0.3.0")
        self.add_phone(4, days=31)
        self.add_phone(5, has_fid=False)
        self.add_phone(6, has_fid=False, dropped=True)

        async def existing_claim(_message):
            self.assertEqual(self.events(), [("pushed", 1, None)])
            return "ok"

        sender = FakeFCM(existing_claim)
        watcher = self.watcher(sender)
        sleeps = []

        async def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 1:
                fixture(self.folder, code=13)
                self.time += seconds
            else:
                raise asyncio.CancelledError

        watcher.sleep = sleep
        with self.assertLogs("marong.app_update_push", level="INFO") as logs, self.assertRaises(asyncio.CancelledError):
            await watcher.run()
        self.assertEqual(sleeps, [30, 30])
        self.assertEqual(logs.output, ["INFO:marong.app_update_push:app_update push started",
                                       "INFO:marong.app_update_push:app_update push code=13 sent=1 failed=0 left=0"])
        self.assertEqual(sender.messages, [fcm.app_update(fid(1), 13)])
        await self.watcher(sender).poll()
        self.assertEqual(len(sender.messages), 1)

    async def test_tc599_caps_targets_batch_and_concurrency(self):
        for ident in range(1, 161):
            self.add_phone(ident, 1 if ident <= 30 else (ident - 31) // 20 + 2)
        fixture(self.folder, code=13)
        sender = FakeFCM()
        watcher = self.watcher(sender)
        with self.assertLogs("marong.app_update_push", level="INFO") as logs:
            await watcher.poll()
            self.assertEqual(len(sender.messages), 100)
            self.time += 30
            await watcher.poll()
        self.assertEqual(len(sender.messages), 150)
        self.assertNotIn(fid(21), {message["fid"] for message in sender.messages})
        self.assertIn(fid(20), {message["fid"] for message in sender.messages})
        self.assertEqual(sender.peak, 4)
        self.assertTrue(logs.output[0].endswith("left=50"))
        self.assertTrue(logs.output[1].endswith("left=0"))

    async def test_tc600_unique_claim_pause_resume_and_failed_writes(self):
        self.add_phone(1)
        fixture(self.folder, code=13)
        paused = self.folder / "paused"
        paused.touch()
        sender = FakeFCM()
        watcher = self.watcher(sender)
        await watcher.poll()
        self.assertEqual(sender.messages, [])
        paused.unlink()
        self.time += 30
        with patch.object(self.store, "app_update_claim", side_effect=psycopg.OperationalError):
            with self.assertLogs("marong.app_update_push", level="WARNING"):
                await self.watcher(sender).poll()
        self.assertEqual(self.events(), [])
        await asyncio.gather(watcher.poll(), self.watcher(sender).poll())
        self.assertEqual(len(sender.messages), 1)
        self.assertEqual(self.events(), [("pushed", 1, None)])

        self.add_phone(2)

        async def interrupted(_message):
            raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await self.watcher(FakeFCM(interrupted)).poll()
        await self.watcher(sender).poll()
        self.assertEqual(len(sender.messages), 1)

        self.add_phone(3)
        failing = FakeFCM(AsyncMock(return_value="failed"))
        with patch.object(self.store, "app_update_push_failed", side_effect=psycopg.OperationalError):
            with self.assertLogs("marong.app_update_push", level="WARNING") as logs:
                await self.watcher(failing).poll()
        self.assertIn("app_update record failed kind=push_failed", logs.output[0])
        await self.watcher(failing).poll()
        self.assertEqual(len(failing.messages), 1)
        self.assertEqual(self.events(), [("pushed", 1, None)] * 3)

    async def test_tc600_gone_and_three_attempts_with_ten_minute_gap(self):
        self.add_phone(1)
        self.add_phone(2)
        fixture(self.folder, code=13)

        async def answer(message):
            return "gone" if message["fid"] == fid(1) else "failed"

        sender = FakeFCM(answer)
        watcher = self.watcher(sender)
        self.assertEqual(len(await self.store.app_update_targets(13, (0, 2, 10), 100)), 2)
        await watcher.poll()
        self.assertEqual(len(sender.messages), 2)
        self.assertEqual(self.db.admin("SELECT fid, dropped_at IS NOT NULL FROM marong.app_devices WHERE install_id=%s",
                                       (phone(1),)), [(None, True)])
        self.assertIn(("push_failed", 1, 410), self.events())
        self.time = 599
        await watcher.poll()
        await self.watcher(sender).poll()
        self.assertEqual(len(sender.messages), 2)
        for timepoint in (600, 1200, 1800):
            self.time = timepoint
            self.db.admin("UPDATE marong.app_update_events SET at = now() - interval '11 minutes' "
                          "WHERE kind = 'push_failed'")
            await watcher.poll()
        failures = [n for kind, n, status in self.events() if kind == "push_failed" and status == 500]
        self.assertEqual(failures, [1, 2, 3])
        self.assertEqual(len(sender.messages), 4)

    async def test_tc724_real_sender_retains_fid_and_retries_only_the_400(self):
        self.add_phone(1)
        self.add_phone(2)
        fixture(self.folder, code=13)
        requests = []

        def answer(message):
            phone_one = message["fid"] == fid(1)
            requests.append(1 if phone_one else 2)
            return fcm_bad_request() if phone_one else fcm_unregistered()

        sender = mock_fcm(answer)
        self.addAsyncCleanup(sender.close)
        watcher = self.watcher(sender)
        with self.assertLogs("marong.fcm", level="INFO") as logs:
            await watcher.poll()
            self.assertCountEqual(requests, [1, 2])
            for round_number, timepoint in enumerate((660, 1320, 1980), 2):
                self.time = timepoint
                self.db.admin("UPDATE marong.app_update_events SET at = now() - interval '11 minutes' "
                              "WHERE kind = 'push_failed'")
                await watcher.poll()
                self.assertCountEqual(requests, [1] * min(round_number, 3) + [2])

        def failures(ident):
            return self.db.admin("SELECT attempt, status FROM marong.app_update_events "
                                 "WHERE install_id=%s AND kind='push_failed' ORDER BY attempt", (phone(ident),))

        def state(ident):
            return self.db.admin("SELECT fid IS NOT DISTINCT FROM %s, fid IS NULL, dropped_at IS NOT NULL "
                                 "FROM marong.app_devices WHERE install_id=%s", (fid(ident), phone(ident)))

        self.assertEqual(failures(1), [(1, 500), (2, 500), (3, 500)])
        self.assertEqual(failures(2), [(1, 410)])
        self.assertEqual(state(1), [(True, False, False)])
        self.assertEqual(state(2), [(False, True, True)])
        self.assertEqual(sum("fcm_send_status kind=app_update http=400 " in line for line in logs.output), 3)

    async def test_switch_defaults_on_and_only_zero_disables_it(self):
        sender = FakeFCM()
        for switch, fcm_sender, enabled in ((None, sender, True), ("", sender, True), (" 0 ", sender, False),
                                            ("false", sender, True), ("off", sender, True), (None, None, True)):
            with self.subTest(switch=switch, fcm=bool(fcm_sender)), patch.dict(os.environ), \
                    patch.object(AppUpdatePush, "run", new_callable=AsyncMock) as task, \
                    self.assertLogs("marong.app", level="INFO") as logs:
                if switch is None:
                    os.environ.pop("MARONG_APP_UPDATE_PUSH", None)
                else:
                    os.environ["MARONG_APP_UPDATE_PUSH"] = switch
                chat = AppChat(self.store, None, None, None, AppPush(self.store, fcm_sender), port=0)
                try:
                    await chat.serve()
                    await asyncio.sleep(0)
                    self.assertEqual(task.await_count, int(enabled and fcm_sender is not None))
                    self.assertEqual([message for message in logs.output if "push switch=" in message],
                                     [f"INFO:marong.app:app_update push switch={'on' if enabled else 'off'} "
                                      f"fcm={'on' if fcm_sender else 'off'}"])
                finally:
                    await chat.close()


class UpdateAPITests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = TestDB()
        cls.addClassCleanup(cls.db.close)
        prepare(cls.db)
        cls.db.apply_sql(ROOT / "marong/migrations/023_app_update_events.sql")
        cls.db.admin("UPDATE marong.discord_dm_links SET channel_id = '123456789012345678', last_incoming_at = now() "
                     "WHERE friend_id = 2")

    async def asyncSetUp(self):
        self.db.admin("TRUNCATE marong.app_devices, marong.app_update_events")
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.releases = AppReleases(self.folder)
        self.store = DiscordStore(self.db.app_url, call_bridge=True)
        self.addAsyncCleanup(self.store.close)
        await self.store.open(wait=True)
        httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(Certs()))
        self.addAsyncCleanup(httpx_client.aclose)
        config = AccessConfig(TEAM, AUD, frozenset({HK_EMAIL}))
        self.chat = AppChat(self.store, None, None, AccessVerifier(config, httpx_client),
                            AppPush(self.store, FakeFCM(), ring_enabled=True), origin=ORIGIN, releases=self.releases,
                            admin_email_hash=email_hash(HK_EMAIL))
        self.http = TestClient(TestServer(self.chat.web_app()))
        self.addAsyncCleanup(self.http.close)
        await self.http.start_server()
        app_release.backfill(self.folder)
        self.headers = auth(write=True)

    def report(self, ident=1, headers=None, **changes):
        body = {"fid": fid(ident), "notifications": "granted", "appVersion": "0.3.1",
                "ring": {"channel": "enabled", "fullScreen": "granted"}, **changes}
        return self.http.put(f"/chat/api/devices/{phone(ident)}", json=body,
                             headers=self.headers if headers is None else headers)

    def events(self):
        return self.db.admin("SELECT kind, version_code, app_version, state, status FROM marong.app_update_events ORDER BY id")

    async def test_tc607_native_update_report_payloads(self):
        # Match AppUpdateReport.body and the failure numbers from download, verification and install.
        ring = {"channel": "enabled", "fullScreen": "denied"}
        body = {"fid": fid(1), "notifications": "granted", "appVersion": "0.3.1", "ring": ring}
        updates = [{"versionCode": 10, "state": state} for state in ("downloaded", "waiting_quiet", "needs_confirm")]
        for status in (*range(1, 8), 101, 102, *range(111, 116), 121):
            updates.append({"versionCode": 10, "state": "failed", "status": status})

        expected = []
        for i, update in enumerate(updates):
            with self.subTest(update=update):
                response = await self.report(**body, update=update)
                self.assertEqual(response.status, 201 if i == 0 else 200)
                self.assertEqual((await response.json())["ring"], {"to": "app", "reason": "app_on", "fullScreen": False})
                expected.append(("state", 10, None, update["state"], update.get("status")))

        response = await self.report(**{**body, "appVersion": "0.3.2"}, update={"versionCode": 10, "state": "installed"})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["ring"], {"to": "app", "reason": "app_on", "fullScreen": False})
        self.assertEqual(self.events(), [*expected, ("installed", 10, "0.3.2", None, None)])

    async def test_tc607_validation_and_legacy_api105_responses(self):
        r = await self.report()
        self.assertEqual(r.status, 201)
        self.assertEqual(await r.json(), {"delivery": {"to": "app", "reason": "app_on"},
                                         "ring": {"to": "app", "reason": "app_on", "fullScreen": True}})
        self.assertEqual((await self.report()).status, 200)
        self.assertEqual(self.events(), [])
        original = self.db.admin("SELECT * FROM marong.app_devices")
        for update in (None, {}, {"versionCode": 10, "state": "failed"},
                       {"versionCode": 10, "state": "downloaded", "status": 1},
                       {"versionCode": 10, "state": "unknown"}, {"versionCode": 0, "state": "downloaded"},
                       {"versionCode": 10, "state": "downloaded", "extra": "not allowed"},
                       {"versionCode": True, "state": "downloaded"}, {"versionCode": 10, "state": "failed", "status": True},
                       {"versionCode": 10, "state": "failed", "status": 1000}, {"versionCode": 10.0, "state": []}):
            with self.subTest(update=update):
                await problem(await self.report(update=update), 400, "invalid_request", "update", "bad_format")
                self.assertEqual(self.db.admin("SELECT * FROM marong.app_devices"), original)
        await problem(await self.report(headers={"Origin": ORIGIN}), 401, "unauthenticated")
        await problem(await self.report(headers=auth(STRANGER, write=True)), 403, "not_allowed")
        for error, status, code in ((psycopg.OperationalError, 503, "db_unavailable"), (RuntimeError, 500, "internal")):
            with patch.object(self.store, "app_device_put", side_effect=error):
                await problem(await self.report(), status, code)

    async def test_tc607_deduplicates_limits_and_allows_next_hour(self):
        change = {"versionCode": 10, "state": "failed", "status": 1}
        self.assertEqual((await self.report(update=change)).status, 201)
        for value, reason in ((change, "duplicate"), ({**change, "versionCode": 99}, "unknown_version")):
            with self.assertLogs("marong.app", level="INFO") as logs:
                self.assertEqual((await self.report(update=value)).status, 200)
            self.assertEqual(sum(f"record skipped reason={reason}" in line for line in logs.output), 1)
        for status in range(2, 31):
            ident = 1 if status < 20 else 2
            self.assertIn((await self.report(ident, update={**change, "status": status})).status, (200, 201))
        with self.assertLogs("marong.app", level="INFO") as logs:
            self.assertEqual((await self.report(2, update={**change, "status": 31})).status, 200)
        self.assertEqual(sum("record skipped reason=rate_limit" in line for line in logs.output), 1)
        self.assertEqual([event[-1] for event in self.events()], list(range(1, 31)))
        self.db.admin("UPDATE marong.app_update_events SET at = now() - interval '61 minutes'")
        self.assertEqual((await self.report(2, update={**change, "status": 31})).status, 200)
        self.assertEqual(len(self.events()), 31)

    async def test_tc607_twenty_phone_cap_and_concurrency(self):
        self.db.admin("""INSERT INTO marong.app_devices (install_id, friend_id, fid, notifications, app_version, seen_at)
                       SELECT make_uuid, 2, 'synthetic-old-fid-' || n, 'denied', '0.3.1',
                              CASE WHEN n = 20 THEN now() - interval '31 days' ELSE now() END
                       FROM unnest(%s::uuid[]) WITH ORDINALITY AS u(make_uuid, n)""",
                      ([phone(n) for n in range(1, 21)],))
        responses = await asyncio.gather(self.report(21), self.report(22))
        self.assertEqual(sorted(r.status for r in responses), [201, 409])
        rejected = next(r for r in responses if r.status == 409)
        result = await problem(rejected, 409, "too_many_devices")
        self.assertEqual(result["title"], "이 친구의 30일 안 폰이 이미 20대")
        self.assertEqual((await self.report(1)).status, 200)
        await problem(await self.report(20), 409, "too_many_devices")
        self.db.admin("""INSERT INTO marong.app_devices (install_id, friend_id, fid, notifications, app_version)
                       VALUES (%s, 1, %s, 'granted', '0.3.1')""", (phone(23), fid(23)))
        await problem(await self.report(23), 409, "too_many_devices")
        self.assertEqual(self.db.admin("SELECT friend_id FROM marong.app_devices WHERE install_id=%s", (phone(23),)), [(1,)])
        self.assertEqual(self.db.admin("SELECT count(*) FROM marong.app_devices WHERE friend_id=2 AND "
                                       "seen_at > now() - interval '30 days'"), [(20,)])

    async def test_tc608_installed_only_for_known_upgrades_and_once_per_phone(self):
        self.assertEqual((await self.report()).status, 201)
        installed = {"versionCode": 10, "state": "installed"}
        reports = await asyncio.gather(self.report(appVersion="0.3.2"), self.report(appVersion="0.3.2", update=installed))
        self.assertEqual([r.status for r in reports], [200, 200])
        self.assertEqual(self.events(), [("installed", 10, "0.3.2", None, None)])
        self.assertEqual((await self.report(appVersion="0.9.9", update={**installed, "versionCode": 99})).status, 200)
        self.assertEqual((await self.report()).status, 200)
        self.assertEqual((await self.report(appVersion="0.3.2", update=installed)).status, 200)
        self.assertEqual(len(self.events()), 1)

    async def test_tc608_installed_validates_code_against_reported_version(self):
        entries = self.releases.history()
        release = next(entry for entry in entries if entry.get("versionCode") == 10)
        entries.append({**release, "versionCode": 11, "file": "marong-0.3.2-11.apk"})
        (self.folder / "history.json").write_bytes(app_release.json_bytes({"format": 1, "entries": entries}))

        self.assertEqual((await self.report(1)).status, 201)
        invalid = {"versionCode": 2_000_000_000, "state": "installed"}
        self.assertEqual((await self.report(1, appVersion="0.3.2", update=invalid)).status, 200)
        self.assertEqual(self.events(), [("installed", 11, "0.3.2", None, None)])

        valid = {"versionCode": 10, "state": "installed"}
        self.assertEqual((await self.report(1, appVersion="0.3.2", update=valid)).status, 200)
        self.assertEqual((await self.report(2)).status, 201)
        self.assertEqual((await self.report(2, appVersion="0.3.2", update=valid)).status, 200)
        self.assertEqual(self.events(), [("installed", 11, "0.3.2", None, None), ("installed", 10, "0.3.2", None, None)])

    async def test_tc608_fetched_dedup_and_audit_write_failure(self):
        release = fixture(self.folder, code=10)
        url = f"/chat/app/{release.file}"
        event = asyncio.Event()
        write = self.store.app_update_fetched

        async def fetch(friend_id, code):
            try:
                await write(friend_id, code)
            finally:
                event.set()

        with patch.object(self.store, "app_update_fetched", side_effect=fetch):
            for _ in range(2):
                event.clear()
                r = await self.http.get(url, headers=self.headers)
                self.assertEqual((r.status, await r.read()), (200, b"fixture bytes"))
                await asyncio.wait_for(event.wait(), timeout=2)
        self.assertEqual(self.db.admin("SELECT kind, friend_id, version_code, install_id FROM marong.app_update_events"),
                         [("fetched", 2, 10, None)])

        self.db.admin("REVOKE INSERT ON marong.app_update_events FROM marong")
        try:
            with self.assertLogs("marong.app", level="WARNING") as logs:
                update = {"versionCode": 10, "state": "downloaded"}
                self.assertEqual((await self.report(update=update)).status, 201)
                self.assertEqual((await self.report(appVersion="0.3.2")).status, 200)
                self.db.admin("UPDATE marong.app_update_events SET at = now() - interval '61 minutes'")
                event.clear()
                with patch.object(self.store, "app_update_fetched", side_effect=fetch):
                    r = await self.http.get(url, headers=self.headers)
                    self.assertEqual((r.status, await r.read()), (200, b"fixture bytes"))
                    await asyncio.wait_for(event.wait(), timeout=2)
            self.assertEqual([line.rsplit("=", 1)[-1] for line in logs.output], ["state", "installed", "fetched"])
            self.assertEqual(self.db.admin("SELECT app_version, ring_channel FROM marong.app_devices"), [("0.3.2", "enabled")])
            self.assertEqual(len(self.events()), 1)
        finally:
            self.db.admin("GRANT INSERT ON marong.app_update_events TO marong")

    async def test_tc613_admin_access_empty_response_and_database_failure(self):
        path = "/chat/admin/api/app-versions"
        await problem(await self.http.get(path), 403, "not_allowed")
        await problem(await self.http.get(path, headers=auth(STRANGER)), 403, "not_allowed")
        with patch.object(self.chat.admin, "email_hash", email_hash(STRANGER)):
            await problem(await self.http.get(path, headers=self.headers), 403, "not_allowed")
        (self.folder / "history.json").unlink()
        r = await self.http.get(path, headers=self.headers)
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertIn("script-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(await r.json(), {"latest": None, "paused": False, "releases": [], "devices": [], "fetches": []})
        with patch.object(self.store, "admin_app_devices", side_effect=psycopg.OperationalError):
            await problem(await self.http.get(path, headers=self.headers), 503, "db_unavailable")
        with patch.object(self.store, "admin_app_devices", side_effect=RuntimeError):
            await problem(await self.http.get(path, headers=self.headers), 500, "internal")

    async def test_tc613_admin_limits_and_current_friend_only(self):
        release = fixture(self.folder, code=13)
        (self.folder / "paused").touch()
        self.db.admin("UPDATE marong.friends SET name='Fixture 001' WHERE id IN (1, 2)")
        self.addCleanup(self.db.admin, "UPDATE marong.friends SET name=CASE id WHEN 1 THEN 'Fixture A' "
                                       "ELSE 'Fixture B' END WHERE id IN (1, 2)")
        self.db.admin("""INSERT INTO marong.friends(id, name) OVERRIDING SYSTEM VALUE
                       SELECT n, 'Fixture ' || lpad(n::text, 3, '0') FROM generate_series(3, 103) n
                       ON CONFLICT DO NOTHING""")
        self.db.admin("""INSERT INTO marong.app_devices (install_id, friend_id, fid, notifications, app_version, seen_at, created_at)
                       SELECT md5(n::text)::uuid, 1, 'fixture-device-fid-' || n, 'denied',
                              CASE WHEN n=30 THEN '0.2.9' ELSE '0.2.11' END,
                              now() - make_interval(secs => 30 - n), now() - make_interval(days => 30 - n)
                       FROM generate_series(1, 30) n""")
        self.db.admin("""INSERT INTO marong.app_devices (install_id, friend_id, notifications, app_version, seen_at)
                       VALUES (md5('older-phone')::uuid, 1, 'denied', '0.1.0', now() - interval '91 days')""")
        self.db.admin("""INSERT INTO marong.app_devices (install_id, friend_id, notifications, app_version)
                       SELECT md5((100 * f + n)::text)::uuid, f, 'denied', '0.2.10'
                       FROM generate_series(2, 12) f CROSS JOIN generate_series(1, 20) n""")
        self.db.admin("""INSERT INTO marong.app_update_events(kind, friend_id, install_id, version_code, state, status)
                       SELECT 'state', 1, md5('30')::uuid, 10, 'failed', n FROM generate_series(1, 25) n""")
        self.db.admin("""INSERT INTO marong.app_update_events(kind, friend_id, install_id, version_code, state)
                       VALUES ('state', 2, md5('30')::uuid, 10, 'waiting_quiet')""")
        self.db.admin("""INSERT INTO marong.app_update_events(kind, friend_id, version_code, at)
                       SELECT 'fetched', 1, n, now() - make_interval(secs => 26-n) FROM generate_series(1, 26) n""")
        self.db.admin("""INSERT INTO marong.app_update_events(kind, friend_id, version_code, at)
                       SELECT 'fetched', n, 11, now() FROM generate_series(2, 102) n
                       UNION ALL SELECT 'fetched', 103, 12, now() - interval '91 days'""")
        r = await self.http.get("/chat/admin/api/app-versions", headers=self.headers)
        self.assertEqual(r.status, 200)
        data = await r.json()
        self.assertEqual(data["latest"], {"versionCode": 13, "versionName": "0.2.10", "publishedAt": release.published_at})
        self.assertTrue(data["paused"])
        self.assertEqual([entry["versionCode"] for entry in data["releases"]], list(range(10, 4, -1)))
        self.assertEqual(set(data["releases"][0]), {"kind", "versionCode", "versionName", "at", "notes", "size",
                                                    "sha256", "backfilled"})
        self.assertTrue(data["releases"][0]["backfilled"])
        self.assertEqual(len(data["devices"]), 200)
        first_friend = [row for row in data["devices"] if row["friendId"] == 1]
        self.assertEqual([row["phone"] for row in first_friend], list(range(1, 21)))
        self.assertEqual([row["behind"] for row in first_friend], [False] * 19 + [True])
        self.assertEqual(set(first_friend[0]), {"friend", "friendId", "phone", "appVersion", "seenAt", "notifications",
                                               "events", "behind", "removedAt"})
        self.assertTrue(all(row["removedAt"] is None for row in data["devices"]))
        self.assertEqual([event["status"] for event in first_friend[-1]["events"]], list(range(25, 5, -1)))
        self.assertEqual(data["devices"][20]["friendId"], 2)
        self.assertEqual(data["devices"][20]["friend"], data["devices"][19]["friend"])
        self.assertFalse(any(row["appVersion"] == "0.1.0" for row in data["devices"]))
        self.assertEqual(len(data["fetches"]), 100)
        self.assertEqual([row["friendId"] for row in data["fetches"]], list(range(1, 101)))
        self.assertEqual([item["versionCode"] for item in data["fetches"][0]["items"]], list(range(26, 6, -1)))
        raw = json.dumps(data)
        for secret in ("install_id", "installId", "fid", "email", "waiting_quiet"):
            self.assertNotIn(secret, raw)

    async def test_tc653_admin_removed_phone_recovers_after_report(self):
        release = replace(fixture(self.folder, code=11), name="0.3.3")
        (self.folder / "release.json").write_text(json.dumps(release.manifest()), encoding="utf-8")
        self.db.admin("""
            INSERT INTO marong.friends (id, name) OVERRIDING SYSTEM VALUE VALUES (7, '시험친구 가')
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
        """)
        login = await self.store.app_login(email_hash(HK_EMAIL))
        with patch.object(self.store, "app_login", return_value={**login, "friend_id": 7}):
            for number, version in ((1, "0.3.2"), (2, "0.2.4")):
                self.assertEqual((await self.report(number, appVersion=version)).status, 201)
            await self.store.drop_fid(phone(2), fid(2))
            ((dropped_at,),) = self.db.admin("SELECT dropped_at FROM marong.app_devices WHERE install_id = %s",
                                            (phone(2),))
            targets = await self.store.app_update_targets(11, (0, 3, 3), limit=20)
            self.assertEqual([target["install_id"] for target in targets], [UUID(phone(1))])

            async def devices():
                response = await self.http.get("/chat/admin/api/app-versions", headers=self.headers)
                self.assertEqual(response.status, 200)
                return (await response.json())["devices"]

            first, removed = await devices()
            for row in (first, removed):
                self.assertEqual(set(row), {"friend", "friendId", "phone", "appVersion", "seenAt", "notifications",
                                            "events", "behind", "removedAt"})
                self.assertEqual((row["friendId"], row["friend"]), (7, "시험친구 가"))
            self.assertEqual((first["phone"], first["behind"], first["removedAt"]), (1, True, None))
            self.assertEqual((removed["phone"], removed["behind"]), (2, False))
            removed_at = datetime.fromisoformat(removed["removedAt"])
            self.assertEqual(removed_at, dropped_at)
            self.assertEqual(removed_at.utcoffset(), timedelta(0))

            self.assertEqual((await self.report(2, appVersion="0.2.4")).status, 200)
            self.assertEqual([(row["phone"], row["behind"], row["removedAt"]) for row in await devices()],
                             [(1, True, None), (2, True, None)])


class ReleaseHistoryTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.folder = self.base / "releases"
        self.apk = apk(self.base / "signed.apk")
        self.notes = self.base / "notes.txt"
        self.notes.write_text("시험 릴리스", encoding="utf-8")

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "tools/app_release.py"), *map(str, args)],
                              env={**os.environ, "MARONG_APP_RELEASES_DIR": str(self.folder)},
                              capture_output=True, text=True, check=False)

    def publish_args(self, code=11):
        return ["publish", "--apk", self.apk, "--package", PACKAGE, "--version-code", code,
                "--version-name", f"0.3.{code - 8}", "--notes-file", self.notes]

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.folder.iterdir()}

    def test_tc611_invalid_notes_leave_folder_unchanged(self):
        self.folder.mkdir()
        self.assertEqual(self.cli(*self.publish_args()[:-2]).returncode, 2)
        self.notes.unlink()
        self.assertEqual(self.cli(*self.publish_args()).returncode, 2)
        for invalid in (b"", b"   ", b"a" * 301, b"a\nb", b"a\rb", b"a\tb", b"\x00", b"bad\x7f", b"\xff"):
            with self.subTest(invalid=invalid):
                self.notes.write_bytes(invalid)
                self.assertEqual(self.cli(*self.publish_args()).returncode, 2)
                self.assertEqual(self.snapshot(), {})

    def test_tc611_trims_outer_whitespace_before_validating(self):
        self.notes.write_bytes(" \t시험 릴리스\r\n".encode("utf-8"))
        result = self.cli(*self.publish_args())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(AppReleases(self.folder).history()[0]["notes"], "시험 릴리스")

    def test_tc611_shell_transfers_note_as_a_file(self):
        self.apk.with_name("output-metadata.json").write_text(json.dumps({"applicationId": PACKAGE, "elements": [
            {"versionCode": 11, "versionName": "0.3.3", "outputFile": self.apk.name}]}), encoding="utf-8")
        fake = self.base / "fake_commands"
        fake.mkdir()
        copied = self.base / "copied"
        copied.mkdir()
        (fake / "ssh").write_text("#!/bin/sh\ncase \"$4\" in\n*mktemp*) printf '%s\\n' /var/tmp/marong-app-release.test1234;;\n"
                                 "*' publish '*) printf '%s' \"$4\" > \"$MARONG_COPY_DIR/command\";;\nesac\n")
        (fake / "scp").write_text('#!/bin/sh\ncp -- "$2" "$MARONG_COPY_DIR/${3##*/}"\n')
        (fake / "ssh").chmod(0o700)
        (fake / "scp").chmod(0o700)
        note = "한글 '따옴표' \" test $HOME `literal`"
        result = subprocess.run(["bash", str(ROOT / "deploy/ovh.sh"), "app-release", "publish", str(self.apk),
                                 "--notes", note], capture_output=True, text=True, check=False,
                                env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}",
                                     "MARONG_COPY_DIR": str(copied)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((copied / "notes.txt").read_bytes(), note.encode("utf-8"))
        command = (copied / "command").read_text()
        self.assertIn("--notes-file /var/tmp/marong-app-release.test1234/notes.txt", command)
        self.assertNotIn(note, command)

    def test_tc612_history_and_backfill(self):
        self.assertEqual(self.cli("backfill").stdout.strip(), "backfilled=6")
        before = self.snapshot()
        self.assertEqual(self.cli("backfill").stdout.strip(), "backfilled=0")
        self.assertEqual(self.snapshot(), before)
        self.notes.write_text("  시험 릴리스  ", encoding="utf-8")
        for code in range(11, 15):
            self.assertEqual(self.cli(*self.publish_args(code)).returncode, 0)
        for command in ("pause", "resume"):
            self.assertEqual(self.cli(command).returncode, 0)
        entries = json.loads(self.cli("history").stdout)["entries"]
        self.assertEqual([item["versionCode"] for item in entries[:-2]], list(range(5, 15)))
        self.assertEqual([item["backfilled"] for item in entries[:-2]], [True] * 6 + [False] * 4)
        self.assertEqual([item["kind"] for item in entries[-2:]], ["paused", "resumed"])
        self.assertEqual(entries[-3]["notes"], "시험 릴리스")
        self.assertNotIn("notes", AppReleases(self.folder).latest().public())
        self.assertEqual(len(list(self.folder.glob("*.apk"))), 3)
        self.assertFalse((self.folder / entries[6]["file"]).exists())

    def test_tc612_release_write_failure_restores_exact_history(self):
        self.assertEqual(self.cli("backfill").returncode, 0)
        before = self.snapshot()
        real_write = app_release.atomic_write

        def fail_manifest(path, data):
            if path.name == "release.json":
                raise OSError("synthetic replacement failure")
            real_write(path, data)

        args = [str(arg) for arg in self.publish_args()]
        with patch.object(sys, "argv", ["app_release.py", *args]), \
                patch.dict(os.environ, {"MARONG_APP_RELEASES_DIR": str(self.folder)}), \
                patch.object(app_release, "atomic_write", side_effect=fail_manifest):
            self.assertEqual(app_release.main(), 2)
        self.assertEqual(self.snapshot(), before)

    def test_tc612_corrupt_history_blocks_writes(self):
        self.folder.mkdir()
        (self.folder / "history.json").write_bytes(b'{"format":true,"entries":[]}')
        before = self.snapshot()
        for args in (self.publish_args(), ("pause",), ("resume",), ("backfill",)):
            self.assertEqual(self.cli(*args).returncode, 2)
            self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
