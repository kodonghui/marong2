"""Calls first and picture topics (docs/04-functional-spec/call-first.md, CTX-020): on some days Marong opens with a
picture of its own day ("나 털모자 샀다! 어때, 잘 어울려?") or calls without a promise (a hello call), 2026-11-16
동희님 "왜 선 전화도 하라고", "모자 같은거 쓰고 안녕! 내 모자 어때! … 이벤트성으로 먼저 화두를 던져도 좋고".

- The picture set is a folder in the repository (`marong/topics/v1/`: `<name>.webp` and `topics.json`, SPEC-260).
  The server only chooses from it and never draws (tools/topic_pictures.py draws, people review).
- A topic goes out in a proactive turn (proactive.py, discord_dm.DiscordProactive), never as an extra message: at most
  one a day, two days apart, three in seven days, and less often while the friend does not answer (SPEC-263, 264).
- A hello call rings the friend's app 0.2.2 or later in their call window (19:00~21:30 by default, SPEC-265, 266).
- Everything is decided in Korean time; the stored times are UTC. A day changes at 00:00 KST.
- Logs carry result names, counts and picture names only: no text, ring id, FID or friend name (SPEC-281).
Switch: MARONG_TOPICS=1 (run_discord.py). Without it nothing here runs except the note after a missed hello call."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import re

log = logging.getLogger("marong.topics")

FOLDER = Path(__file__).resolve().with_name("topics")
SET = "v1"                                  # the set new topics come from
SET_NAME = re.compile(r"v[0-9]{1,3}\Z")
NAME = re.compile(r"[a-z0-9-]{1,40}\Z")
KEY = re.compile(r"(v[0-9]{1,3})/([a-z0-9-]{1,40})\Z")   # how a picture is named in the tables: v1/winter-hat
VERSION = re.compile(r"([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\Z")
PICTURE_BYTES = 120 * 1024                  # a picture larger than this is left out (SPEC-260)
REPEAT_DAYS = 30                            # a friend does not see the same picture again within 30 days (REQ-264)
TOPIC_GAP_DAYS = 2                          # two days after the last topic (REQ-261)
WEEK_DAYS, WEEK_MAX = 7, 3                  # three topics in seven days at most
BACKOFF_STOP = 14                           # days with only Marong's own messages after which topics stop (REQ-292)
HELLO_GAP_DAYS, HELLO_MISSED_GAP_DAYS = 3, 7   # after the last hello call, or after a missed one (REQ-275)
RING_QUIET = timedelta(hours=6)             # no hello call within six hours of a ring or a call (REQ-276)
HELLO_ANSWER = timedelta(minutes=5)         # a call started within this after the ring is the hello call
ANSWER_WINDOW = timedelta(hours=3)          # a friend's word within this after a topic is its answer (REQ-291)
APP_MIN = (0, 2, 2)                         # the app that shows a hello call as one (SPEC-267)
WINDOW = (19 * 60, 21 * 60 + 30)            # the default call window, minutes after 00:00 KST (REQ-294)
TEXT_HOURS = (12 * 60, 21 * 60)             # a picture topic message goes out within this
SPAN_MIN = 30                               # minutes: a shorter range has no topic that day
TEXT_MAX = 400                              # a longer model answer gets the fixed text instead (SPEC-271)
LINE_MAX = 30                               # the ring message's preview line (SPEC-267)

MISSED_OPENING = "전화했는데 바빴나 봐!"
MISSED_NOTE = "전화했는데 바빴나 봐! 📞"      # the app notification after a missed hello call with a picture
HELLO_MISSED_LINES = ("전화했는데 바빴나 봐! 편할 때 전화 줘 📞", "방금 전화했었어~ 시간 될 때 걸어 줘 😊")

# What a friend says to turn hello calls and pictures on or off (3.7), compared without spaces.
PHRASES = {
    **dict.fromkeys(("먼저전화하지마", "먼저전화하지말아줘", "선전화끄기", "먼저전화그만"), ("hello_call", False)),
    **dict.fromkeys(("먼저전화해도돼", "먼저전화해줘", "선전화켜기"), ("hello_call", True)),
    **dict.fromkeys(("그림그만보내", "그림보내지마", "그림화두끄기", "그림끄기"), ("pictures", False)),
    **dict.fromkeys(("그림보내줘", "그림화두켜기", "그림켜기"), ("pictures", True)),
}
REPLIES = {
    ("hello_call", False): "알겠어, 이제 먼저 전화는 안 할게. 통화하고 싶으면 언제든 걸어 줘 📞",
    ("hello_call", True): "좋아! 가끔 먼저 전화할게 📞",
    ("pictures", False): "알겠어, 그림은 이제 안 보낼게.",
    ("pictures", True): "좋아, 가끔 그림도 보내 줄게 🎨",
}
PREF_FAILED = "앗, 지금 설정을 못 바꿨어. 조금 뒤에 다시 말해 줘"

# The '# 오늘 꺼낼 화두' part of a proactive turn with a picture (AI-20)
TOPIC_GUIDE = """# 오늘 꺼낼 화두
- 이번 선톡은 마롱이 그림 한 장과 함께 가. 그림: {alt}. 장면: {scene}.
- 마롱이가 지금 그 장면처럼 지내는 것처럼 짧게 나누고, 마지막 말은 친구에게 되묻는 질문 하나로 끝내. 예: '{line}' … '{ask}'.
- 그림을 사진이라고 하지 말고, 그림 설명을 길게 하지 마."""


# ── the picture set (SPEC-260) ─────────────────────────────────

@dataclass(frozen=True)
class Picture:
    set: str
    name: str
    title: str
    status: str
    scene: str
    line: str
    ask: str
    preview: str
    alt: str
    months: tuple[int, ...]
    hours: tuple[int, int]
    path: Path

    @property
    def key(self) -> str:
        return f"{self.set}/{self.name}"

    @property
    def src(self) -> str:
        return f"/chat/topics/{self.set}/{self.name}.webp"

    def fits(self, now: datetime) -> bool:
        return (not self.months or now.month in self.months) and self.hours[0] <= now.hour < self.hours[1]

    def fallback(self) -> str:
        """The topic message without the model: the opening line and the question (SPEC-271)."""
        return f"{self.line}\n\n{self.ask}"

    def missed(self) -> str:
        """After a missed hello call (3.6)."""
        return f"{MISSED_OPENING}\n\n{self.line}\n\n{self.ask}"


def _text(item: dict, field: str, low: int, high: int) -> str:
    value = item.get(field)
    if not isinstance(value, str) or value != value.strip() or not low <= len(value) <= high:
        raise ValueError(field)
    return value


def picture_of(item: dict, set_name: str, folder: Path) -> Picture:
    """One entry of topics.json by the rules of 3.1. ValueError names the field that is wrong."""
    if not isinstance(item, dict):
        raise ValueError("entry")
    name = item.get("name")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("name")
    status = item.get("status")
    if status not in ("reviewed", "removed"):
        raise ValueError("status")
    scene = _text(item, "scene", 1, 300)
    if not scene.isascii():
        raise ValueError("scene")
    ask = _text(item, "ask", 1, 40)
    if not ask.endswith("?"):
        raise ValueError("ask")
    preview = _text(item, "preview", 1, LINE_MAX)
    if "\n" in preview or "\r" in preview:
        raise ValueError("preview")
    months = item.get("months")
    if (not isinstance(months, list) or len(set(months)) != len(months)
            or not all(isinstance(m, int) and not isinstance(m, bool) and 1 <= m <= 12 for m in months)):
        raise ValueError("months")
    hours = item.get("hours")
    if (not isinstance(hours, list) or len(hours) != 2
            or not all(isinstance(h, int) and not isinstance(h, bool) for h in hours)
            or not 0 <= hours[0] < hours[1] <= 24):
        raise ValueError("hours")
    path = folder / f"{name}.webp"
    try:
        head, size = path.read_bytes()[:12], path.stat().st_size
    except OSError:
        raise ValueError("file") from None
    if head[:4] != b"RIFF" or head[8:12] != b"WEBP" or size > PICTURE_BYTES:
        raise ValueError("file")
    return Picture(set_name, name, _text(item, "title", 1, 20), status, scene, _text(item, "line", 1, 40), ask,
                   preview, _text(item, "alt", 1, 60), tuple(months), (hours[0], hours[1]), path)


class PictureSet:
    def __init__(self, set_name: str, pictures: list[Picture]):
        self.set = set_name
        self.by_name = {p.name: p for p in pictures}
        self.pickable = [p for p in pictures if p.status == "reviewed"]

    def get(self, key: str | None) -> Picture | None:
        """A picture of this set by its table name (v1/winter-hat), removed ones too (old messages still show them)."""
        m = KEY.fullmatch(key or "")
        if not m or m.group(1) != self.set:
            return None
        return self.by_name.get(m.group(2))


def load_set(folder: Path | None = None) -> PictureSet | None:
    """Read a picture set. None (topics off) when the list is missing or not JSON (SPEC-260). A wrong entry is left
    out and logged by its index and field."""
    folder = folder or FOLDER / SET
    set_name = folder.name
    try:
        data = json.loads((folder / "topics.json").read_text(encoding="utf-8"))
        if (not SET_NAME.fullmatch(set_name) or data.get("set") != set_name
                or not isinstance(data.get("pictures"), list)):
            raise ValueError("set")
    except (OSError, ValueError, AttributeError) as e:
        log.warning("topics_set_invalid %s", type(e).__name__)
        return None
    pictures, seen = [], set()
    for i, item in enumerate(data["pictures"]):
        try:
            picture = picture_of(item, set_name, folder)
            if picture.name in seen:
                raise ValueError("name")
        except ValueError as e:
            log.warning("topic_picture_invalid index=%d field=%s", i, e)
            continue
        seen.add(picture.name)
        pictures.append(picture)
    found = PictureSet(set_name, pictures)
    log.info("topics_set set=%s count=%d removed=%d", set_name, len(found.pickable),
             len(pictures) - len(found.pickable))
    return found


@lru_cache(maxsize=None)
def picture_set() -> PictureSet | None:
    """The set this process uses, read once."""
    return load_set()


# ── when and which (SPEC-261~265) ─────────────────────────────

def topic_minute(friend_id: int, day: date, start: int, end: int) -> int:
    """The topic time of a friend's Korean day in minutes after 00:00 (3.2): the same however often it is worked out."""
    span = end - start
    if span <= 0:
        return start
    digest = hashlib.sha256(f"{friend_id}:{day.isoformat()}".encode("ascii")).digest()
    return start + int.from_bytes(digest[:8], "big") % span


def call_span(window: tuple[int, int], hours: tuple[int, int]) -> tuple[int, int] | None:
    """Where a hello call's topic time may fall: the call window but its last 30 minutes, within the friend's proactive
    hours (their turns only come then). None: the two do not meet."""
    start, end = window
    end = end - SPAN_MIN if end - start > SPAN_MIN else start + 1
    start, end = max(start, hours[0] * 60), min(end, hours[1] * 60)
    return (start, end) if end > start else None


def text_span(hours: tuple[int, int]) -> tuple[int, int] | None:
    """Where a picture topic message's time may fall: the proactive hours within 12:00~21:00, at least 30 minutes."""
    start, end = max(TEXT_HOURS[0], hours[0] * 60), min(TEXT_HOURS[1], hours[1] * 60)
    return (start, end) if end - start >= SPAN_MIN else None


def backoff_gap(days: int) -> int | None:
    """Days after the last topic before the next one, by the days with only Marong's own messages (3.3). None: stop."""
    if days <= 1:
        return TOPIC_GAP_DAYS
    if days <= 3:
        return 4
    if days < BACKOFF_STOP:
        return 7
    return None


def gap_reason(today: date, history: list[dict], days: int) -> str | None:
    """Why no topic may go out today (SPEC-263 ①, ③), or None. history: the friend's topic rows of the last 30 days."""
    if any(h["day"] == today for h in history):
        return "today"
    gap = backoff_gap(days)
    if gap is None:
        return "backoff"
    kept = [h["day"] for h in history if h["status"] != "failed"]
    if kept and (today - max(kept)).days < gap:
        return "backoff" if gap > TOPIC_GAP_DAYS else "gap"
    if sum(1 for d in kept if (today - d).days < WEEK_DAYS) >= WEEK_MAX:
        return "week"
    return None


def pick(pictures: list[Picture], now: datetime, used: set[str], rng=random.random) -> Picture | None:
    """A picture for this month and hour that the friend has not seen in 30 days, evenly at random (SPEC-262)."""
    fits = [p for p in pictures if p.fits(now) and p.key not in used]
    return fits[int(rng() * len(fits)) % len(fits)] if fits else None


def version_ok(version: str | None) -> bool:
    m = VERSION.fullmatch(version or "")
    return bool(m) and tuple(int(x) for x in m.groups()) >= APP_MIN


def prefs_of(row: dict | None) -> dict:
    """A friend's settings: no row means both on and 19:00~21:30 (SPEC-278)."""
    if row is None:
        return {"hello_call": True, "pictures": True, "window": WINDOW}
    window = (row["call_from"], row["call_until"])
    if not 0 <= window[0] < window[1] <= 24 * 60:
        window = WINDOW
    return {"hello_call": row["hello_call"], "pictures": row["pictures"], "window": window}


def phrase(text: str) -> tuple[str, bool] | None:
    """('hello_call' | 'pictures', on) when the whole message is one of the phrases of 3.7."""
    flat = " ".join((text or "").split()).rstrip(".!?~").removeprefix("마롱아").lstrip(", ")
    return PHRASES.get(flat.replace(" ", ""))


def window_text(window: tuple[int, int]) -> str:
    return "{:02d}:{:02d}-{:02d}:{:02d}".format(*divmod(window[0], 60), *divmod(window[1], 60))


def parse_window(text: str) -> tuple[int, int] | None:
    """'19:00-21:30' → (1140, 1290). None when the form or the order is wrong (SPEC-279)."""
    m = re.fullmatch(r"([01][0-9]|2[0-3]):([0-5][0-9])-([01][0-9]|2[0-4]):([0-5][0-9])", text or "")
    if not m:
        return None
    start, end = int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))
    return (start, end) if start < end <= 24 * 60 else None


# ── the decision in a proactive turn (SPEC-263) ───────────────

@dataclass
class Today:
    prefs: dict
    used: set
    call: dict | None    # {"caller", "devices"} when the friend can get a hello call today
    at: datetime         # the topic time (SPEC-261)


@dataclass
class Choice:
    kind: str            # text | call
    picture: Picture
    topic_id: int
    prefs: dict
    call: dict | None


class Topics:
    def __init__(self, settings, store, app=None, *, pictures: PictureSet | None = None, rng=random.random):
        from zoneinfo import ZoneInfo
        self.s = settings
        self.store = store
        self.app = app                       # app_push.AppPush or None (no app on this server)
        self.pictures = pictures if pictures is not None else picture_set()
        self.rng = rng
        self.tz = ZoneInfo(settings.timezone)

    @property
    def on(self) -> bool:
        return self.pictures is not None and bool(self.pictures.pickable)

    async def today(self, room: dict, now: datetime) -> Today | str:
        """What today allows for this friend, or why no topic goes out today."""
        from .proactive import schedule  # proactive imports agent, which imports this module
        if not self.on:
            return "no_set"
        friend, day = room["friend_id"], now.date()
        prefs = prefs_of(await self.store.topic_prefs(friend))
        if not (prefs["hello_call"] or prefs["pictures"]):
            return "off"
        history = await self.store.topic_history(friend, day - timedelta(days=REPEAT_DAYS - 1))
        days = await self.store.topic_quiet_days(friend, day, self.s.timezone)
        why = gap_reason(day, history, days)
        if why:
            return why
        hours = schedule(room, self.s)[0]
        call = await self._callable(friend, day) if prefs["hello_call"] else None
        span = call_span(prefs["window"], hours) if call else None
        if span is None:
            call = None
            if not prefs["pictures"]:
                return "no_call"
            span = text_span(hours)
            if span is None:
                return "no_time"
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        at = midnight + timedelta(minutes=topic_minute(friend, day, *span))
        return Today(prefs, {h["picture"] for h in history if h["status"] != "failed"}, call, at)

    async def _callable(self, friend: int, day: date) -> dict | None:
        """SPEC-265 ①~③, ⑤: what holds all day. The moment's conditions are in choose()."""
        if self.app is None or not self.app.enabled or not self.app.ring_enabled:
            return None
        caller = await self.store.call_friend(friend)
        if caller is None:
            return None
        devices = [d for d in await self.app.ring_devices(friend) if version_ok(d["app_version"])]
        if not devices:
            return None
        last = await self.store.hello_last(friend)
        if last:
            gap = HELLO_MISSED_GAP_DAYS if last["status"] == "missed" else HELLO_GAP_DAYS
            if (day - last["created_at"].astimezone(self.tz).date()).days < gap:
                return None
        return {"caller": caller, "devices": devices}

    async def choose(self, room: dict, now: datetime, slot_end: datetime) -> Choice | None:
        """In a proactive turn whose slot was claimed: a topic for it, recorded before anything is sent, or None for
        an ordinary proactive message."""
        today = await self.today(room, now)
        if isinstance(today, str):
            if today != "today":
                log.info("topic_skipped reason=%s", today)
            return None
        if slot_end <= today.at:  # a later slot holds the topic time
            return None
        pictures = self.pictures.pickable
        if os.getenv("MARONG_FRIEND_CARD") == "on":
            rules = await self.store._all("""SELECT text FROM marong.friend_rules
                WHERE friend_id=%s AND kind='avoid_topic' AND removed_at IS NULL""", (room["friend_id"],))
            pictures = tuple(picture for picture in pictures if not any(
                rule["text"] in " ".join((picture.title, picture.scene, picture.line, picture.ask, picture.alt))
                for rule in rules))
        picture = pick(pictures, now, today.used, self.rng)
        if picture is None:
            log.info("topic_skipped reason=no_picture")
            return None
        kind = "text" if today.prefs["pictures"] else None
        if today.call:
            minute = now.hour * 60 + now.minute
            start, end = today.prefs["window"]
            if minute < start:  # the call window comes later today: wait for its slot
                return None
            if minute < end and not await self.store.rings_recent(room["friend_id"], RING_QUIET) \
                    and not await self.store.call_live(today.call["caller"]):
                kind = "call"
        if kind is None:
            log.info("topic_skipped reason=no_call")
            return None
        topic_id = await self.store.topic_start(room["friend_id"], now.date(), picture.key)
        if topic_id is None:  # another turn took today's topic first
            return None
        log.info("topic_chosen kind=%s picture=%s", kind, picture.key)
        return Choice(kind, picture, topic_id, today.prefs, today.call)


def topic_text(text: str | None, picture: Picture) -> tuple[str, bool]:
    """The model's topic message as it may go, or the fixed text: (text, fixed) (SPEC-271). The caller has already
    turned errors, refusals and the fallback answer into None."""
    from .proactive import parts
    if not text or not text.strip() or len(text) > TEXT_MAX:
        return picture.fallback(), True
    text = text.strip()
    if "?" not in parts(text)[-1] and "？" not in parts(text)[-1]:
        text = f"{text}\n\n{picture.ask}"
    return text, False
