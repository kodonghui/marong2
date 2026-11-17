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
from marong.app_release import APK_MAX, APK_NAME, PACKAGE, InvalidRelease, Release, read_manifest, release_dir, valid_version  # noqa: E402

SIGNATURE = re.compile(r"META-INF/[^/]+\.(RSA|DSA|EC|SF)", re.IGNORECASE)


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


def put_manifest(folder: Path, release: Release):
    with tempfile.NamedTemporaryFile(dir=folder, prefix=".release-", mode="w", encoding="utf-8", delete=False) as file:
        temporary = Path(file.name)
        try:
            json.dump(release.manifest(), file, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
            os.replace(temporary, folder / "release.json")
        finally:
            temporary.unlink(missing_ok=True)


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
    with exclusive(folder):
        current = read_manifest(folder)
        if current and args.version_code <= current.code:
            raise ValueError("버전 코드는 현재 릴리스보다 커야 합니다.")
        staged, size, digest = stage_apk(args.apk, folder)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        release = Release(args.version_code, args.version_name, size, digest, now)
        destination = folder / release.file
        try:
            os.replace(staged, destination)
            try:
                put_manifest(folder, release)
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
        finally:
            staged.unlink(missing_ok=True)
        (folder / "paused").unlink(missing_ok=True)
        prune(folder, release)
    return release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("publish")
    new.add_argument("--apk", type=Path, required=True)
    new.add_argument("--package", required=True)
    new.add_argument("--version-code", type=int, required=True)
    new.add_argument("--version-name", required=True)
    for command in ("status", "pause", "resume"):
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
        else:
            with exclusive(folder):
                paused = folder / "paused"
                if args.command == "pause":
                    paused.touch(exist_ok=True)
                else:
                    paused.unlink(missing_ok=True)
            print("paused" if args.command == "pause" else "resumed")
    except zipfile.BadZipFile:
        print("거절: APK가 ZIP이 아닙니다.", file=sys.stderr)
        return 2
    except InvalidRelease:
        print("거절: 현재 release.json 형식이 틀렸습니다.", file=sys.stderr)
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
