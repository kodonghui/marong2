"""File, backfill and deployment checks for SPEC-500, SPEC-503 and SPEC-504."""

import ast
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def server_unit(ident="20261124-sihum", **fields):
    return {
        "format": 1, "id": ident, "kind": "server", "title": "시험 반영 가",
        "deployedOn": "2026-11-24", "app": None, "backfilled": False,
        "evidence": ["PR #9001"],
        "items": [{"type": "improved", "area": "admin", "title": "시험 항목",
                   "before": "시험 변경 전", "after": "시험 변경 후", "evidence": []}],
        **fields,
    }


def app_unit(name="9.9.9", code=999, **fields):
    return server_unit(f"app-{name}", kind="app", app={"versionName": name, "versionCode": code}, **fields)


def unit_bytes(unit):
    return json.dumps(unit, ensure_ascii=False).encode("utf-8")


def write_unit(folder, unit, name=None):
    path = folder / (name or f"{unit['id']}.json")
    path.write_bytes(unit_bytes(unit))
    return path


def release_mismatches(units):
    # The publishing CLI imports POSIX-only fcntl. Read its literal table on Windows too.
    release_cli = ast.parse((ROOT / "tools/app_release.py").read_text(encoding="utf-8"))
    table = next(node.value for node in release_cli.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "PAST_RELEASES" for target in node.targets))
    codes = {name: code for code, name, *_ in ast.literal_eval(table)}
    return [unit["id"] for unit in units if unit["app"] and
            codes.get(unit["app"]["versionName"], unit["app"]["versionCode"]) != unit["app"]["versionCode"]]


def backfill_draft():
    draft = (ROOT / "docs/10-wbs/admin-changelog-backfill.md").read_text(encoding="utf-8")
    units = {}
    for line in draft.split("## 1. ", 1)[1].split("## 2. ", 1)[0].splitlines():
        if not re.match(r"^\| [0-9]+ \|", line):
            continue
        _, ident, kind, deployed_on, title, app, evidence, _ = (cell.strip() for cell in line[1:-1].split("|"))
        ident = ident.strip("`")
        unit = server_unit(ident, title=title, deployedOn=None if deployed_on == "기록 없음" else deployed_on,
                           evidence=evidence.split(", "), backfilled=True, items=[])
        if kind == "앱":
            version_name, code = re.fullmatch(r"`?([0-9.]+)`?\s*\((\d+)\)", app).groups()
            unit.update(kind="app", app={"versionName": version_name, "versionCode": int(code)})
        units[ident] = unit
    for line in draft.split("## 2. ", 1)[1].split("## 3. ", 1)[0].splitlines():
        if not line.startswith("| `"):
            continue
        ident, _, type_label, area_label, title, before, after, evidence = (
            cell.strip() for cell in line[1:-1].split("|"))
        units[ident.strip("`")]["items"].append({
            "type": type_label.split("`")[1], "area": area_label.split("`")[1],
            "title": title, "before": before, "after": after, "evidence": evidence.split(", ") if evidence else [],
        })
    return units


class ChangelogTest(unittest.TestCase):
    def test_tc700_repository_files(self):
        from marong.admin_changes import CHANGELOG_DIR, load_units, validate_unit

        files = sorted(CHANGELOG_DIR.glob("*.json"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(file=path.name):
                unit, reason = validate_unit(path, path.read_bytes())
                self.assertIsNone(reason)
                self.assertEqual(path.stem, unit["id"])
        units, skipped = load_units(CHANGELOG_DIR)
        self.assertEqual(skipped, 0)
        self.assertEqual(len({unit["id"] for unit in units}), len(files))
        self.assertEqual(release_mismatches(units), [])
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "README.md").write_bytes(b"not a release unit")
            self.assertEqual(load_units(folder), ([], 0))

    def test_tc701_validator_reasons(self):
        from marong.admin_changes import validate_unit

        normal = server_unit()
        path = Path(f"{normal['id']}.json")
        self.assertEqual(validate_unit(path, unit_bytes(normal)), (normal, None))

        cases = [
            (Path("20261124-other.json"), normal, "name"),
            (path, server_unit(format=2), "schema"),
            (Path("app-9.9.9.json"), server_unit("app-9.9.9", kind="app"), "schema"),
            (Path("app-9.9.9.json"), app_unit() | {"app": {"versionName": "9.9.8", "versionCode": 999}}, "schema"),
            (path, server_unit(title="가" * 41), "schema"),
            (path, server_unit(deployedOn=None), "schema"),
            (path, server_unit(evidence=[]), "schema"),
            (path, server_unit(format=True), "schema"),
            (path, server_unit(deployedOn="2026-02-30"), "schema"),
            (path, server_unit(title="시험\n반영"), "schema"),
            (path, server_unit(unknown=True), "schema"),
        ]
        for item_fields in ({"before": "가" * 101}, {"type": "added"}, {"type": "removed"}, {"before": "기록 없음"}):
            unit = deepcopy(normal)
            unit["items"][0].update(item_fields)
            cases.append((path, unit, "schema"))
        for index, (file, unit, reason) in enumerate(cases):
            with self.subTest(case=index):
                self.assertEqual(validate_unit(file, unit_bytes(unit)), (None, reason))
        for raw, reason in ((b"{", "json"), (b"\xff", "json"), (b" " * 32769, "too_big")):
            self.assertEqual(validate_unit(path, raw), (None, reason))

    def test_tc702_app_releases(self):
        from marong.admin_changes import load_units

        for fixtures, skipped, mismatches in (
            ([app_unit("0.3.2", 11)], 0, ["app-0.3.2"]),
            ([app_unit("9.9.8"), app_unit()], 2, []),
            ([app_unit()], 0, []),
        ):
            with self.subTest(skipped=skipped, mismatches=mismatches), TemporaryDirectory() as temporary:
                folder = Path(temporary)
                for unit in fixtures:
                    write_unit(folder, unit)
                if skipped:
                    with self.assertLogs("marong.admin_changes", "WARNING") as log:
                        self.assertEqual(load_units(folder), ([], skipped))
                    self.assertEqual(sum(line.endswith("reason=duplicate") for line in log.output), 2)
                else:
                    self.assertEqual(load_units(folder), (fixtures, 0))
                    self.assertEqual(release_mismatches(fixtures), mismatches)

    def test_tc703_privacy_patterns(self):
        from marong.admin_changes import validate_unit

        for pattern in ("friend@example.com", "00000000-0000-4000-8000-000000000000",
                        "a" * 22, "010-1234-5678", "http://"):
            with self.subTest(pattern=pattern):
                unit = server_unit()
                unit["items"][0]["after"] = pattern
                self.assertEqual(validate_unit(Path(f"{unit['id']}.json"), unit_bytes(unit)), (None, "privacy"))

    def test_tc712_backfill_matches_the_approved_draft(self):
        from marong.admin_changes import CHANGELOG_DIR, load_units

        units, skipped = load_units(CHANGELOG_DIR)
        self.assertEqual(skipped, 0)
        actual = {unit["id"]: unit for unit in units if unit["backfilled"]}
        self.assertEqual(len(actual), 47)
        self.assertEqual(sum(len(unit["items"]) for unit in actual.values()), 79)
        self.assertEqual(sum(unit["kind"] == "app" for unit in actual.values()), 8)
        self.assertEqual(sum(unit["deployedOn"] is None for unit in actual.values()), 6)
        self.assertTrue(all(unit["evidence"] for unit in actual.values()))
        self.assertFalse(any({"PR #7", "PR #8"}.intersection(unit["evidence"]) for unit in actual.values()))
        self.assertEqual(actual, backfill_draft())

    def test_tc711_deployment_put_check_and_rollback(self):
        from marong.admin_changes import deployment_main

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            changes = root / "changelog"
            release_history = root / "history.json"
            deployments = root / "deployments"
            deployments.mkdir()
            server = server_unit("20261201-sihum", deployedOn="2026-12-01")
            ident = server["id"]
            archive = deployments / f"{ident}.Ab3dEf7h"
            archive.mkdir()
            app = app_unit(deployedOn="2026-12-01")
            raw = unit_bytes(server)
            same_day = datetime(2026, 11, 30, 15, 10, tzinfo=timezone.utc)
            previous_day = datetime(2026, 11, 30, 14, 50, tzinfo=timezone.utc)

            def run(action, unit=server, *, content=None, at=same_day):
                return deployment_main([action, unit["id"], str(deployments)], changes=changes,
                                       history=release_history, raw=unit_bytes(unit) if content is None else content,
                                       now=lambda: at)

            with patch("builtins.print") as printed:
                self.assertEqual(run("put"), 0)
                self.assertEqual((changes / f"{ident}.json").read_bytes(), raw)
                if sys.platform != "win32":
                    self.assertEqual((changes / f"{ident}.json").stat().st_mode & 0o777, 0o644)
                self.assertEqual((archive / "changelog.json").read_bytes(), raw)
                self.assertEqual((archive / "changelog.sha256").read_text().strip(), sha256(raw).hexdigest())
                self.assertEqual((archive / "changelog.copied-at").read_text().strip(), "2026-11-30T15:10:00Z")
                self.assertEqual(run("check"), 0)
                printed.assert_called_with(f"ok {ident}")
                self.assertNotEqual(run("check", content=raw + b" "), 0)
                printed.assert_called_with("mismatch sha256")
                self.assertEqual(run("put", at=previous_day), 0)
                self.assertNotEqual(run("check"), 0)
                printed.assert_called_with("mismatch deployedOn")
                self.assertEqual(run("put", at=same_day), 0)
                self.assertEqual(run("check"), 0)

                def publish(code):
                    published = {"kind": "published", "at": "2026-11-30T16:00:00Z", "versionName": "9.9.9",
                                 "versionCode": code, "notes": "시험 릴리스", "file": f"marong-9.9.9-{code}.apk",
                                 "backfilled": True, "size": None, "sha256": None}
                    release_history.write_bytes(unit_bytes({"format": 1, "entries": [published]}))

                publish(999)
                self.assertEqual(run("put", app), 0)
                self.assertTrue((deployments / app["id"] / "changelog.json").is_file())
                self.assertEqual(run("check", app), 0)
                publish(1000)
                self.assertNotEqual(run("check", app), 0)
                printed.assert_called_with("mismatch versionCode")

                self.assertNotEqual(run("put", content=b"{"), 0)
                missing = server_unit("20261201-missing", deployedOn="2026-12-01")
                self.assertNotEqual(run("put", missing), 0)
                duplicate = deployments / ident
                duplicate.mkdir()
                self.assertNotEqual(run("put", content=raw + b" "), 0)
                self.assertEqual(list(duplicate.iterdir()), [])
                duplicate.rename(deployments / "unrelated")

                (archive / "changelog.json").write_bytes(unit_bytes(missing))
                self.assertNotEqual(run("put", content=raw + b" "), 0)
                self.assertEqual((changes / f"{ident}.json").read_bytes(), raw)
                self.assertEqual(sorted(path.stem for path in changes.iterdir()), [ident, app["id"]])
                (archive / "changelog.json").write_bytes(raw)
                self.assertEqual(run("rollback"), 0)
                self.assertEqual([path.stem for path in changes.iterdir()], [app["id"]])
                self.assertTrue((archive / "changelog.json").is_file())


if __name__ == "__main__":
    unittest.main()
