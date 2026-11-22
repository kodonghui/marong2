"""Server-side app update tests (TC-599–601, TC-607–613)."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx
import psycopg

from pg import TestDB
from test_app_update import ROOT, apk, fixture
from marong import fcm
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

    async def test_default_off_and_start_requires_fcm(self):
        sender = FakeFCM()
        for switch, fcm_sender, started in (("0", sender, False), ("1", None, False), ("1", sender, True)):
            chat = AppChat(self.store, None, None, None, AppPush(self.store, fcm_sender), port=0)
            with patch.dict(os.environ, {"MARONG_APP_UPDATE_PUSH": switch}), \
                    patch.object(AppUpdatePush, "run", new_callable=AsyncMock) as task:
                try:
                    await chat.serve()
                    await asyncio.sleep(0)
                    self.assertEqual(task.await_count, int(started))
                finally:
                    await chat.close()


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
        for invalid in (b"", b"   ", b"a" * 301, b"a\nb", b"valid\n", b"a\r", b"\x00", b"bad\x7f", b"\xff"):
            with self.subTest(invalid=invalid):
                self.notes.write_bytes(invalid)
                self.assertEqual(self.cli(*self.publish_args()).returncode, 2)
                self.assertEqual(self.snapshot(), {})

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
