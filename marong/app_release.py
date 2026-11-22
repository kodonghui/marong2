"""The signed Android release advertised by the private app chat (SPEC-284~286)."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import re
import stat
import threading
import time
import unicodedata

log = logging.getLogger("marong.app_release")
PACKAGE = "com.corthexhq.marong"
VERSION_CODE_MAX = 2_100_000_000
APK_MAX = 200 * 1024 * 1024
VERSION_NAME = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}")
APK_NAME = re.compile(r"marong-[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}-([1-9][0-9]{0,9})\.apk")
SHA256 = re.compile(r"[0-9a-f]{64}")
DEFAULT_DIR = "/var/lib/marong/app-releases"
WARNING_INTERVAL = 600


class InvalidRelease(ValueError):
    """A fixed diagnostic code safe to put in logs."""


def release_dir() -> Path:
    return Path(os.environ.get("MARONG_APP_RELEASES_DIR") or DEFAULT_DIR)


def valid_version(code, name) -> bool:
    return (type(code) is int and 1 <= code <= VERSION_CODE_MAX and isinstance(name, str)
            and VERSION_NAME.fullmatch(name) is not None)


def version_parts(name: str) -> tuple[int, ...]:
    return tuple(map(int, name.split(".")))


def normalize_notes(notes) -> str | None:
    if (not isinstance(notes, str) or len(notes.splitlines()) != 1
            or any(unicodedata.category(char) in ("Cc", "Cs", "Zl", "Zp") for char in notes)):
        return None
    trimmed = notes.strip()
    return trimmed if 1 <= len(trimmed) <= 300 else None


def utc_timestamp(value) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise InvalidRelease("published_at") from None
    if parsed.utcoffset() != timedelta(0):
        raise InvalidRelease("published_at")
    return parsed


def parse_history(raw: bytes | None) -> list[dict]:
    if raw is None:
        return []
    try:
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {"format", "entries"}
                or type(data["format"]) is not int or data["format"] != 1
                or not isinstance(data["entries"], list)):
            raise ValueError
        codes = set()
        for entry in data["entries"]:
            utc_timestamp(entry["at"])
            match entry["kind"]:
                case "paused" | "resumed":
                    if set(entry) != {"kind", "at"}:
                        raise ValueError
                case "published":
                    if set(entry) != {"kind", "at", "versionCode", "versionName", "notes",
                                      "size", "sha256", "file", "backfilled"}:
                        raise ValueError
                    code, name = entry["versionCode"], entry["versionName"]
                    notes = entry["notes"]
                    if (not valid_version(code, name) or code in codes or notes is None or normalize_notes(notes) != notes
                            or entry["file"] != f"marong-{name}-{code}.apk"
                            or type(entry["backfilled"]) is not bool):
                        raise ValueError
                    size, digest = entry["size"], entry["sha256"]
                    if not ((entry["backfilled"] and size is None) or type(size) is int and 1 <= size <= APK_MAX):
                        raise ValueError
                    if not ((entry["backfilled"] and digest is None) or isinstance(digest, str) and SHA256.fullmatch(digest)):
                        raise ValueError
                    codes.add(code)
                case _:
                    raise ValueError
        return data["entries"]
    except (KeyError, TypeError, ValueError):
        raise InvalidRelease("history") from None


@dataclass(frozen=True)
class Release:
    code: int
    name: str
    size: int
    sha256: str
    published_at: str

    @property
    def file(self) -> str:
        return f"marong-{self.name}-{self.code}.apk"

    def public(self) -> dict:
        return {"versionCode": self.code, "versionName": self.name, "size": self.size,
                "sha256": self.sha256, "url": f"/chat/app/{self.file}"}

    def manifest(self) -> dict:
        return {"format": 1, "package": PACKAGE, "versionCode": self.code, "versionName": self.name,
                "file": self.file, "size": self.size, "sha256": self.sha256, "publishedAt": self.published_at}

    @classmethod
    def read(cls, data) -> "Release":
        if (not isinstance(data, dict) or type(data.get("format")) is not int or data["format"] != 1
                or data.get("package") != PACKAGE):
            raise InvalidRelease("format")
        code, name, size, digest = (data.get(k) for k in ("versionCode", "versionName", "size", "sha256"))
        if (not valid_version(code, name) or type(size) is not int or not 1 <= size <= APK_MAX
                or not isinstance(digest, str) or not SHA256.fullmatch(digest)):
            raise InvalidRelease("fields")
        published = data.get("publishedAt")
        utc_timestamp(published)
        release = cls(code, name, size, digest, published)
        if data.get("file") != release.file:
            raise InvalidRelease("filename")
        return release


def read_manifest(folder: Path) -> Release | None:
    try:
        with (folder / "release.json").open("rb") as file:
            raw = file.read(4097)
    except FileNotFoundError:
        return None
    if len(raw) > 4096:
        raise InvalidRelease("json")
    try:
        return Release.read(json.loads(raw))
    except (ValueError, UnicodeError) as error:
        if isinstance(error, InvalidRelease):
            raise
        raise InvalidRelease("json") from None


class AppReleases:
    def __init__(self, folder: Path | None = None, clock=time.monotonic):
        self.folder = release_dir() if folder is None else folder
        self.clock = clock
        self.warnings: dict[str, float] = {}
        self.lock = threading.Lock()

    def invalid(self, reason: str):
        with self.lock:
            now = self.clock()
            if now - self.warnings.get(reason, -WARNING_INTERVAL) >= WARNING_INTERVAL:
                self.warnings[reason] = now
                log.warning("app_release invalid reason=%s", reason)

    def paused(self) -> bool:
        try:
            (self.folder / "paused").lstat()
            return True
        except FileNotFoundError:
            return False

    def manifest(self) -> Release | None:
        try:
            return read_manifest(self.folder)
        except InvalidRelease as error:
            self.invalid(str(error))
        except OSError:
            self.invalid("read")
        return None

    def history(self) -> list[dict]:
        try:
            return parse_history((self.folder / "history.json").read_bytes())
        except FileNotFoundError:
            return []
        except (InvalidRelease, OSError):
            self.invalid("history")
            return []

    def latest(self) -> Release | None:
        try:
            if self.paused():
                return None
        except OSError:
            self.invalid("read")
            return None

        try:
            release = read_manifest(self.folder)
            if release is None:
                return None
            info = (self.folder / release.file).lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size != release.size:
                raise InvalidRelease("apk_size")
            return release
        except InvalidRelease as error:
            self.invalid(str(error))
        except FileNotFoundError:
            self.invalid("apk_missing")
        except OSError:
            self.invalid("read")
        return None

    def open(self, name: str):
        """Open one immutable APK snapshot before returning a streaming response."""
        release = self.latest()
        if release is None or release.file != name:
            return None
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            descriptor = os.open(self.folder / name, flags)
        except OSError:
            self.invalid("apk_open")
            return None
        file = os.fdopen(descriptor, "rb")
        try:
            info = os.fstat(descriptor)
            if stat.S_ISREG(info.st_mode) and info.st_size == release.size:
                return release, file
            self.invalid("apk_size")
        except OSError:
            self.invalid("apk_open")
        file.close()
        return None
