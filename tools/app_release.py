#!/usr/bin/env python3
"""Publish or pause Marong Android releases on the server (SPEC-287~288)."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.app_release import (  # noqa: E402
    APK_MAX, APK_NAME, PACKAGE, InvalidRelease, Release, normalize_notes, parse_history, read_manifest, release_dir,
    valid_version,
)

SIGNATURE = re.compile(r"META-INF/[^/]+\.(RSA|DSA|EC|SF)", re.IGNORECASE)

# Release manifests (including deployment backups) and WBS TASK-176, 185, 192, 408, 468, 473.
# The archived WBS records the 0.2.2 publication to the minute.
PAST_RELEASES = (
    (5, "0.2.2", 5_097_697, "98daee99f828ecc484b558d7073a613e7a3dcf1d9ae0a17c1764ddf209e703b7",
     "2026-11-17T08:57:00Z", "앱 자동 업데이트와 마롱이가 먼저 거는 전화"),
    (6, "0.2.3", 5_097_662, "5203708a1d55d53ecb932606913c2abd768674d4ebc785d1a0314b6bf644c3b9",
     "2026-11-17T13:00:41Z", "기존 앱의 자동 업데이트 확인"),
    (7, "0.2.4", 5_097_674, "4cc22a40da9b686091d7dd3637e7960c5e13e11be1de4fbb28eafdf9b61641e0",
     "2026-11-18T14:55:10Z", "설치를 미뤄 둔 조건이 끝나면 빠르게 재시도"),
    (8, "0.3.0", 5_097_769, "b868d61ab8c3a64b4e9e59cd7d807036775ea565e3b1eebf9787f5c63ca156aa",
     "2026-11-19T10:14:02Z", "앱 로그인과 글 대화 통합"),
    (9, "0.3.1", 5_114_152, "dc0d05a315fb0e1ae8ea203699e94a22046a8a546ae56a35a780a0d580c5f91e",
     "2026-11-21T09:31:24Z", "스피커 전환과 통화 볼륨 조절"),
    (10, "0.3.2", 5_114_156, "205876d61f4fb1de284733ad4d5e621063e65d5d067579b33db7ae2a35e16356",
     "2026-11-22T07:21:02Z", "통화 화면을 다시 열지 않고 벨 받기"),
)


@contextmanager
def exclusive(folder: Path):
    """Serialize writers without a persistent lock file."""
    folder.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def stage_apk(apk: Path, folder: Path) -> tuple[Path, int, str]:
    digest = hashlib.sha256()
    size = 0
    with apk.open("rb") as source, tempfile.NamedTemporaryFile(dir=folder, prefix=".apk-", delete=False) as output:
        staged = Path(output.name)
        try:
            while chunk := source.read(65536):
                size += len(chunk)
                if size > APK_MAX:
                    raise ValueError("APK가 200MB를 넘습니다.")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            with zipfile.ZipFile(staged) as archive:
                names = archive.namelist()
                if "AndroidManifest.xml" not in names or not any(SIGNATURE.fullmatch(name) for name in names):
                    raise ValueError("APK 매니페스트나 META-INF 서명 파일이 없습니다.")
            os.fsync(output.fileno())
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
    return staged, size, digest.hexdigest()


def atomic_write(path: Path, content: bytes):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.stem}-", delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def json_bytes(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")


def history_bytes(folder: Path) -> bytes | None:
    try:
        return (folder / "history.json").read_bytes()
    except FileNotFoundError:
        return None


@contextmanager
def append_history(folder: Path, previous: bytes | None, entries: list[dict]):
    path = folder / "history.json"
    atomic_write(path, json_bytes({"format": 1, "entries": entries}))
    try:
        yield
    except BaseException:
        if previous is None:
            path.unlink()
        else:
            atomic_write(path, previous)
        raise


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def published_entry(release: Release, notes: str) -> dict:
    return {"kind": "published", "versionCode": release.code, "versionName": release.name,
            "at": release.published_at, "notes": notes, "size": release.size, "sha256": release.sha256,
            "file": release.file, "backfilled": False}


def prune(folder: Path, current: Release):
    older = []
    for path in folder.iterdir():
        match = APK_NAME.fullmatch(path.name)
        if match and path.name != current.file and path.is_file() and not path.is_symlink():
            older.append((int(match[1]), path))
    for _, path in sorted(older, reverse=True)[2:]:
        path.unlink()


def publish(args, folder: Path) -> Release:
    if args.package != PACKAGE:
        raise ValueError("마롱이 패키지가 아닙니다.")
    if not valid_version(args.version_code, args.version_name):
        raise ValueError("버전 코드나 버전 이름 형식이 틀렸습니다.")
    notes = normalize_notes(args.notes_file.read_bytes().decode("utf-8"))
    if notes is None:
        raise ValueError("릴리스 노트는 제어 문자가 없는 한 줄(1~300자)이어야 합니다.")
    with exclusive(folder):
        current = read_manifest(folder)
        previous = history_bytes(folder)
        entries = parse_history(previous)
        if ((current and args.version_code <= current.code)
                or any(args.version_code <= entry.get("versionCode", 0) for entry in entries)):
            raise ValueError("버전 코드는 현재 릴리스보다 커야 합니다.")
        staged, size, digest = stage_apk(args.apk, folder)
        release = Release(args.version_code, args.version_name, size, digest, now_utc())
        destination = folder / release.file
        try:
            os.replace(staged, destination)
            try:
                with append_history(folder, previous, entries + [published_entry(release, notes)]):
                    atomic_write(folder / "release.json", json_bytes(release.manifest()))
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
        finally:
            staged.unlink(missing_ok=True)
        (folder / "paused").unlink(missing_ok=True)
        prune(folder, release)
    return release


def set_paused(folder: Path, paused: bool):
    with exclusive(folder):
        previous = history_bytes(folder)
        entries = parse_history(previous)
        entry = {"kind": "paused" if paused else "resumed", "at": now_utc()}
        with append_history(folder, previous, entries + [entry]):
            marker = folder / "paused"
            if paused:
                marker.touch(exist_ok=True)
            else:
                marker.unlink(missing_ok=True)


def backfill(folder: Path) -> int:
    with exclusive(folder):
        entries = parse_history(history_bytes(folder))
        existing = {entry.get("versionCode") for entry in entries}
        additions = [dict(published_entry(Release(code, name, size, digest, at), notes), backfilled=True)
                     for code, name, size, digest, at, notes in PAST_RELEASES if code not in existing]
        if additions:
            atomic_write(folder / "history.json", json_bytes({"format": 1, "entries": entries + additions}))
        return len(additions)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("publish")
    new.add_argument("--apk", type=Path, required=True)
    new.add_argument("--package", required=True)
    new.add_argument("--version-code", type=int, required=True)
    new.add_argument("--version-name", required=True)
    new.add_argument("--notes-file", type=Path, required=True)
    for command in ("status", "pause", "resume", "history", "backfill"):
        sub.add_parser(command)
    args = parser.parse_args()
    folder = release_dir()
    try:
        if args.command == "publish":
            release = publish(args, folder)
            print(f"{release.name} ({release.code}) {release.size} bytes sha256={release.sha256}")
        elif args.command == "status":
            release = read_manifest(folder)
            state = "paused" if (folder / "paused").exists() else "active"
            print(f"{state}: {release.name} ({release.code}) {release.size} bytes "
                  f"sha256={release.sha256[:16]} published_at={release.published_at}" if release else f"{state}: none")
        elif args.command == "history":
            print(json_bytes({"format": 1, "entries": parse_history(history_bytes(folder))}).decode("utf-8"), end="")
        elif args.command == "backfill":
            print(f"backfilled={backfill(folder)}")
        else:
            set_paused(folder, args.command == "pause")
            print("paused" if args.command == "pause" else "resumed")
    except zipfile.BadZipFile:
        print("거절: APK가 ZIP이 아닙니다.", file=sys.stderr)
        return 2
    except InvalidRelease as error:
        filename = "history.json" if str(error) == "history" else "release.json"
        print(f"거절: 현재 {filename} 형식이 틀렸습니다.", file=sys.stderr)
        return 2
    except UnicodeError:
        print("거절: 릴리스 노트는 UTF-8이어야 합니다.", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"거절: 릴리스 파일 오류({type(error).__name__}).", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"거절: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
