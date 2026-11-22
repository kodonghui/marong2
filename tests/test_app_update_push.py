"""Server-side app update tests (TC-599–601, TC-607–613)."""
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from test_app_update import ROOT, apk
from marong import fcm
from marong.app_release import PACKAGE, AppReleases
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
