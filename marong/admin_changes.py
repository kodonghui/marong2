"""Validate and read the public change records shown in the admin page."""

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
import sys
from tempfile import mkstemp
import unicodedata

from .app_release import parse_history, release_dir, utc_timestamp


CHANGELOG_DIR = Path(__file__).resolve().parent / "changelog"
MAX_BYTES = 32 * 1024
SERVER_ID = re.compile(r"[0-9]{8}-[a-z0-9][a-z0-9-]{0,39}")
APP_ID = re.compile(r"app-(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
EVIDENCE = re.compile(r"PR #[1-9][0-9]{0,4}|[0-9a-f]{7,40}")
ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
LOG_NAME = re.compile(r"[A-Za-z0-9._-]{1,80}")
PRIVACY = re.compile(
    r"@|http|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|[a-z0-9_-]{21,}|01[016789]-?[0-9]{3,4}-?[0-9]{4}", re.IGNORECASE | re.ASCII,
)
UNIT_FIELDS = {"format", "id", "kind", "title", "deployedOn", "app", "backfilled", "evidence", "items"}
ITEM_FIELDS = {"type", "area", "title", "before", "after", "evidence"}
TYPES = ("added", "improved", "fixed", "removed")
AREAS = ("app", "web", "call", "chat", "admin", "legacy")
log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


def _valid_text(value, limit):
    return (isinstance(value, str) and 1 <= len(value) <= limit
            and not any("\ud800" <= char <= "\udfff" for char in value))


def _valid_date(value):
    if not isinstance(value, str) or not ISO_DAY.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_evidence(value, minimum, maximum):
    return (isinstance(value, list) and minimum <= len(value) <= maximum
            and all(isinstance(entry, str) and EVIDENCE.fullmatch(entry) for entry in value)
            and len(set(value)) == len(value))


def _valid_item(item, backfilled):
    if not isinstance(item, dict) or item.keys() != ITEM_FIELDS:
        return False
    before, after = item["before"], item["after"]
    return (item["type"] in TYPES and item["area"] in AREAS and _valid_text(item["title"], 40)
            and _valid_text(before, 100) and _valid_text(after, 100)
            and (item["type"] != "added" or before == "없음")
            and (item["type"] != "removed" or after == "없음")
            and (backfilled or "기록 없음" not in (before, after))
            and _valid_evidence(item["evidence"], 0, 5))


def _valid_app(app, ident):
    return (isinstance(app, dict) and app.keys() == {"versionName", "versionCode"}
            and app["versionName"] == ident.removeprefix("app-")
            and type(app["versionCode"]) is int and app["versionCode"] >= 1)


def sort_day(unit):
    if unit["deployedOn"] is not None:
        return unit["deployedOn"]
    prefix = unit["id"][:8]
    return f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:]}"


def validate_unit(path: Path, raw: bytes) -> tuple[dict | None, str | None]:
    if len(raw) > MAX_BYTES:
        return None, "too_big"
    try:
        unit = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return None, "json"
    if not isinstance(unit, dict) or unit.keys() != UNIT_FIELDS:
        return None, "schema"

    ident, kind, app = unit["id"], unit["kind"], unit["app"]
    if (not isinstance(ident, str) or not (SERVER_ID.fullmatch(ident) or APP_ID.fullmatch(ident))
            or path.name != ident + ".json"):
        return None, "name"
    if kind == "app":
        if not APP_ID.fullmatch(ident) or not _valid_app(app, ident):
            return None, "schema"
    elif kind != "server" or app is not None or not SERVER_ID.fullmatch(ident):
        return None, "schema"

    title, backfilled, deployed_on, items = unit["title"], unit["backfilled"], unit["deployedOn"], unit["items"]
    if (type(unit["format"]) is not int or unit["format"] != 1 or type(backfilled) is not bool
            or not _valid_text(title, 40) or title != title.strip()
            or any(unicodedata.category(char) in ("Cc", "Zl", "Zp") for char in title)
            or not _valid_evidence(unit["evidence"], 1, 10) or not isinstance(items, list)
            or not 1 <= len(items) <= 30 or not all(_valid_item(item, backfilled) for item in items)):
        return None, "schema"
    if deployed_on is None and (kind != "server" or not backfilled):
        return None, "schema"
    if not _valid_date(sort_day(unit)):
        return None, "schema"
    if PRIVACY.search(title) or any(PRIVACY.search(item[field]) for item in items for field in ("title", "before", "after")):
        return None, "privacy"
    return unit, None


def _log_invalid(name, reason):
    log.warning("admin_changes file=%s result=invalid reason=%s", name if LOG_NAME.fullmatch(name) else "?", reason)


def load_units(folder: Path = CHANGELOG_DIR) -> tuple[list[dict], int]:
    try:
        paths = list(folder.iterdir())
    except FileNotFoundError:
        log.warning("admin_changes result=missing_dir")
        return [], 0

    loaded = []
    skipped = 0
    codes = Counter()
    for path in paths:
        if not path.name.endswith(".json"):
            continue
        try:
            unit, reason = validate_unit(path, _read_unit(path))
        except OSError:
            unit, reason = None, "json"
        if reason is not None:
            _log_invalid(path.name, reason)
            skipped += 1
            continue
        loaded.append(unit)
        if unit["app"] is not None:
            codes[unit["app"]["versionCode"]] += 1

    units = []
    for unit in loaded:
        if unit["app"] is not None and codes[unit["app"]["versionCode"]] > 1:
            _log_invalid(unit["id"] + ".json", "duplicate")
            skipped += 1
        else:
            units.append(unit)
    return units, skipped


class ChangelogOperationError(ValueError):
    """Fixed CLI diagnostics that can be reported without printing records."""


def _read_unit(path):
    with path.open("rb") as file:
        return file.read(MAX_BYTES + 1)


def _atomic_write(path, content, mode=0o600):
    fd, name = mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _deployment_folder(root, ident, *, create):
    if create:
        root.mkdir(parents=True, exist_ok=True)
    variant = re.compile(re.escape(ident) + r"\.[a-zA-Z0-9]{8}")
    matches = [path for path in root.iterdir()
               if (path.name == ident or variant.fullmatch(path.name)) and path.is_dir() and not path.is_symlink()]
    if not matches and create:
        folder = root / ident
        folder.mkdir()
        return folder
    if len(matches) != 1:
        raise ChangelogOperationError("invalid deployment_folder")
    return matches[0]


def _archive_unit(archive, target):
    archived = _read_unit(archive / "changelog.json")
    unit, reason = validate_unit(target, archived)
    if reason:
        raise ChangelogOperationError("invalid archived_unit")
    return unit, archived


def put_unit(archive, target, raw, now):
    try:
        _archive_unit(archive, target)
    except FileNotFoundError:
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(archive / "changelog.json", raw)
    _atomic_write(archive / "changelog.sha256", sha256(raw).hexdigest().encode("ascii") + b"\n")
    _atomic_write(target, raw, mode=0o644)
    copied_at = now().astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    _atomic_write(archive / "changelog.copied-at", copied_at.encode("ascii") + b"\n")


def check_unit(archive, target, raw, history):
    unit, archived = _archive_unit(archive, target)
    digest = (archive / "changelog.sha256").read_text(encoding="ascii").strip()
    if any(sha256(content).hexdigest() != digest for content in (raw, archived, _read_unit(target))):
        raise ChangelogOperationError("mismatch sha256")

    if unit["app"] is None:
        actual = (archive / "changelog.copied-at").read_text(encoding="ascii").strip()
    else:
        app = unit["app"]
        entries = parse_history(history.read_bytes())
        published = [entry for entry in entries if entry["kind"] == "published" and entry["versionName"] == app["versionName"]]
        if len(published) != 1:
            raise ChangelogOperationError("mismatch versionName")
        if published[0]["versionCode"] != app["versionCode"]:
            raise ChangelogOperationError("mismatch versionCode")
        actual = published[0]["at"]
    if utc_timestamp(actual).astimezone(KST).date().isoformat() != unit["deployedOn"]:
        raise ChangelogOperationError("mismatch deployedOn")


def deployment_main(argv=None, *, changes=CHANGELOG_DIR, history=None, raw=None, now=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("put", "check", "rollback"))
    parser.add_argument("id")
    parser.add_argument("deployment_root", type=Path)
    args = parser.parse_args(argv)
    if not (SERVER_ID.fullmatch(args.id) or APP_ID.fullmatch(args.id)):
        print("invalid name")
        return 1
    target = changes / (args.id + ".json")
    try:
        if args.action != "rollback":
            if raw is None:
                raw = sys.stdin.buffer.read(MAX_BYTES + 1)
            _, reason = validate_unit(target, raw)
            if reason:
                raise ChangelogOperationError(f"invalid {reason}")
        archive = _deployment_folder(args.deployment_root, args.id, create=args.action == "put" and args.id.startswith("app-"))
        if args.action == "put":
            put_unit(archive, target, raw, now or (lambda: datetime.now(timezone.utc)))
        elif args.action == "check":
            check_unit(archive, target, raw, history or release_dir() / "history.json")
        else:
            _archive_unit(archive, target)
            target.unlink(missing_ok=True)
    except ChangelogOperationError as error:
        print(str(error))
        return 1
    except (OSError, ValueError):
        print("invalid deployment_record")
        return 1
    print(f"ok {args.id}")
    return 0


if __name__ == "__main__":
    sys.exit(deployment_main())
