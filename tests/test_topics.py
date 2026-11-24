"""Calls first and picture topics (docs/04-functional-spec/call-first.md, docs/10-wbs/call-first.md TASK-160~168)
against real Postgres (pgserver) with the migration chain up to 018, a fake FCM, a fake Discord and a fake Claude.
No network, no real key. The picture set is a fixture made here (tiny WebP files).

- TASK-160 store: one topic a day, settings defaults, ring constraints, quiet days (SPEC-264), answers (SPEC-275)
- TASK-161 decisions: topic time, spans, gaps, backoff, picture choice, versions, phrases, the picture list (3.1)
- TASK-162 the topic message: model answer, timeout, refusal, empty, too long, no question
- TASK-163 picture topics in proactive turns: app (preview line), Discord with the picture, failures, second turn
- TASK-164 hello calls: 0.2.2 phones, reason/line in FCM, 0.2.1 only, FCM refusal, 6 hours, live call, window
- TASK-165 missed hello calls: one note with the picture (or a line), never meta.proactive
- TASK-166 the daily maximum counts hello calls; the slot that holds the topic time waits for it
- TASK-167 on/off phrases in the DM and the in-app chat
- TASK-168 API-140 picture route, Message.picture and kind hello
- TASK-172 the admin tool's topics command (SPEC-279): status, call, pictures, window, wrong input changes nothing
Run: .venv/bin/python tests/test_topics.py"""
import asyncio
from datetime import date, datetime, time as clock_time, timedelta
import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid
from zoneinfo import ZoneInfo

import httpx
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tools/vertex_live")]
from fakes import FakeEmbeddings, ScriptedLLM, message, text  # noqa: E402
from marong import topics  # noqa: E402
from marong.access import AccessConfig, AccessVerifier  # noqa: E402
from marong.agent import FALLBACK_TEXT  # noqa: E402
from marong.app_chat import AppChat  # noqa: E402
from marong.app_push import TALK, AppPush  # noqa: E402
from marong.config import load_settings  # noqa: E402
from marong.discord_dm import DiscordAgent, DiscordProactive, DiscordReminders  # noqa: E402
from marong.discord_store import DiscordStore  # noqa: E402
from pg import TestDB  # noqa: E402
from test_app_chat import AUD, HK_EMAIL, DH_EMAIL, ORIGIN, TEAM, Certs, FakeFCM, auth  # noqa: E402
from test_app_chat import fcm_bad_request, fcm_unregistered, mock_fcm  # noqa: E402
from test_app_ring import FID, INSTALL, prepare  # noqa: E402
from test_discord_dm import DM_HK, HK, Channel, Client, event  # noqa: E402

TZ = ZoneInfo("Asia/Seoul")
HK_ROOM = f"discord-dm:{HK}"
TODAY = datetime.now(TZ).date()
CHECKS = 0
PICTURES = [
    {"name": "winter-hat", "title": "털모자", "status": "reviewed", "scene": "Marong wearing a knitted winter hat",
     "line": "나 털모자 샀다! 🧶", "ask": "어때, 잘 어울려?", "preview": "나 털모자 샀다!", "alt": "털모자를 쓰고 웃는 마롱이",
     "months": [11, 12, 1, 2], "hours": [9, 22], "added": "2026-11-17"},
    {"name": "chicken-skewer", "title": "닭꼬치", "status": "reviewed", "scene": "Marong eating a chicken skewer",
     "line": "나 닭꼬치 먹고 있어 🍢", "ask": "넌 뭐 먹었어?", "preview": "나 닭꼬치 먹는 중!", "alt": "닭꼬치를 든 마롱이",
     "months": [], "hours": [17, 22], "added": "2026-11-17"},
    {"name": "all-day", "title": "산책", "status": "reviewed", "scene": "Marong taking a walk",
     "line": "나 산책 나왔어 🌰", "ask": "너는 오늘 뭐 했어?", "preview": "나 산책 나왔어!", "alt": "산책하는 마롱이",
     "months": [], "hours": [0, 24], "added": "2026-11-17"},
    {"name": "old-picture", "title": "옛 그림", "status": "removed", "scene": "Marong waving",
     "line": "안녕!", "ask": "잘 지냈어?", "preview": "안녕!", "alt": "손 흔드는 마롱이",
     "months": [], "hours": [0, 24], "added": "2026-11-17"},
    {"name": "Bad_Name", "title": "틀린 이름", "status": "reviewed", "scene": "x", "line": "x", "ask": "x?",
     "preview": "x", "alt": "x", "months": [], "hours": [0, 24]},
    {"name": "no-question", "title": "물음표 없음", "status": "reviewed", "scene": "x", "line": "x", "ask": "어때",
     "preview": "x", "alt": "x", "months": [], "hours": [0, 24]},
    {"name": "too-big", "title": "큰 그림", "status": "reviewed", "scene": "x", "line": "x", "ask": "x?",
     "preview": "x", "alt": "x", "months": [], "hours": [0, 24]},
    {"name": "no-file", "title": "파일 없음", "status": "reviewed", "scene": "x", "line": "x", "ask": "x?",
     "preview": "x", "alt": "x", "months": [], "hours": [0, 24]},
    {"name": "bad-hours", "title": "시간 틀림", "status": "reviewed", "scene": "x", "line": "x", "ask": "x?",
     "preview": "x", "alt": "x", "months": [], "hours": [22, 9]},
    {"name": "all-day", "title": "같은 이름", "status": "reviewed", "scene": "x", "line": "x", "ask": "x?",
     "preview": "x", "alt": "x", "months": [], "hours": [0, 24]},
]


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def make_set(root: Path) -> Path:
    folder = root / "v1"
    folder.mkdir()
    for i, item in enumerate(PICTURES[:4]):
        Image.new("RGB", (64, 64), (40 * i, 120, 200)).save(folder / f"{item['name']}.webp", "WEBP")
    for name in ("Bad_Name", "no-question", "bad-hours"):
        Image.new("RGB", (8, 8)).save(folder / f"{name}.webp", "WEBP")
    (folder / "too-big.webp").write_bytes(b"RIFF\0\0\0\0WEBP" + b"\0" * (topics.PICTURE_BYTES + 1))
    (folder / "topics.json").write_text(json.dumps({"set": "v1", "pictures": PICTURES}, ensure_ascii=False),
                                        encoding="utf-8")
    return folder


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, clock_time(hour, minute), TZ)


# ── TASK-161: decisions without the DB ─────────────────────────

def decision_checks(folder: Path, logs):
    d = date(2026, 11, 17)
    m = topics.topic_minute(7, d, 720, 1260)
    ok(720 <= m < 1260 and all(topics.topic_minute(7, d, 720, 1260) == m for _ in range(5)),
       "SPEC-261: the same topic time however often it is worked out")
    ok(len({topics.topic_minute(7, date(2026, 11, k), 720, 1260) for k in range(1, 29)}) > 10, "and it moves by day")
    ok(topics.topic_minute(7, d, 1140, 1140) == 1140, "no span: its start")
    ok(topics.call_span((1140, 1290), (7, 24)) == (1140, 1260) and topics.call_span((1140, 1290), (12, 21))
       == (1140, 1260), "call window but its last 30 minutes, within the proactive hours")
    ok(topics.call_span((1140, 1160), (7, 24)) == (1140, 1141), "a window of 30 minutes or less: its start")
    ok(topics.call_span((1140, 1290), (7, 12)) is None, "proactive hours that miss the window: no call that day")
    ok(topics.text_span((7, 24)) == (720, 1260) and topics.text_span((20, 24)) == (1200, 1260)
       and topics.text_span((7, 12)) is None, "picture topics within 12:00~21:00 of the proactive hours")
    ok([topics.backoff_gap(n) for n in (0, 1, 2, 3, 4, 13, 14, 30)] == [2, 2, 4, 4, 7, 7, None, None], "3.3 table")

    def h(day, status="sent"):
        return {"day": day, "status": status, "picture": "v1/x"}
    ok(topics.gap_reason(date(2026, 11, 16), [h(date(2026, 11, 15))], 0) == "gap"
       and topics.gap_reason(date(2026, 11, 17), [h(date(2026, 11, 15))], 0) is None,
       "SPEC-263 ①: 11/15 topic, not on 11/16, from 11/17")
    ok(topics.gap_reason(d, [h(d, "failed")], 0) == "today", "one row a day, a failed one too")
    ok(topics.gap_reason(date(2026, 11, 16), [h(date(2026, 11, 15), "failed")], 0) is None,
       "a failed topic does not count for the gap")
    week = [h(date(2026, 11, 10)), h(date(2026, 11, 12)), h(date(2026, 11, 14))]
    ok(topics.gap_reason(date(2026, 11, 16), week, 0) == "week" and topics.gap_reason(date(2026, 11, 17), week, 0)
       is None, "three topics in seven days at most")
    ok(topics.gap_reason(d, [h(date(2026, 11, 15))], 2) == "backoff"
       and topics.gap_reason(date(2026, 11, 19), [h(date(2026, 11, 15))], 2) is None
       and topics.gap_reason(d, [h(date(2026, 11, 15))], 0) is None, "SPEC-264 examples: d = 2 waits until 11/19")
    ok(topics.gap_reason(d, [], 14) == "backoff" and topics.gap_reason(d, [h(date(2026, 11, 10))], 5) is None
       and topics.gap_reason(d, [h(date(2026, 11, 11))], 5) == "backoff", "7 days for d = 4~13, stop at 14")

    found = topics.load_set(folder)
    ok(found is not None and sorted(p.name for p in found.pickable) == ["all-day", "chicken-skewer", "winter-hat"],
       [p.name for p in found.pickable] if found else None)
    ok(found.get("v1/old-picture").status == "removed" and found.get("v1/nope") is None and found.get("v2/all-day")
       is None and found.get("../all-day") is None, "removed pictures still have an address, nothing else")
    bad = [line for line in logs.getvalue().splitlines() if "topic_picture_invalid" in line]
    ok(len(bad) == 6 and any("field=name" in line for line in bad) and any("field=ask" in line for line in bad)
       and any("field=file" in line for line in bad) and any("field=hours" in line for line in bad),
       f"SPEC-260: wrong entries left out and logged by index and field: {bad}")
    ok("topics_set set=v1 count=3 removed=1" in logs.getvalue(), "the count in the log")
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "v1"
        empty.mkdir()
        ok(topics.load_set(empty) is None, "no list: topics off")
        (empty / "topics.json").write_text("{not json", encoding="utf-8")
        ok(topics.load_set(empty) is None, "not JSON: topics off")
        (empty / "topics.json").write_text(json.dumps({"set": "v2", "pictures": []}), encoding="utf-8")
        ok(topics.load_set(empty) is None and "topics_set_invalid" in logs.getvalue(), "another set name: off")

    hat, skewer = found.get("v1/winter-hat"), found.get("v1/chicken-skewer")
    now = datetime(2026, 11, 20, 20, 0, tzinfo=TZ)
    ok(topics.pick([hat, skewer], now, {"v1/winter-hat"}, lambda: 0) is skewer, "SPEC-262 example: the skewer")
    ok(topics.pick([hat, skewer], now, {hat.key, skewer.key}) is None, "everything seen in 30 days: none")
    ok(topics.pick([hat], datetime(2026, 6, 1, 20, 0, tzinfo=TZ), set()) is None
       and topics.pick([skewer], datetime(2026, 11, 20, 12, 0, tzinfo=TZ), set()) is None, "months and hours")
    ok({topics.pick([hat, skewer], now, set(), lambda: r).name for r in (0, 0.49, 0.5, 0.99)}
       == {"winter-hat", "chicken-skewer"}, "evenly among the fitting ones")
    ok(hat.src == "/chat/topics/v1/winter-hat.webp" and hat.fallback() == "나 털모자 샀다! 🧶\n\n어때, 잘 어울려?"
       and hat.missed() == "전화했는데 바빴나 봐!\n\n나 털모자 샀다! 🧶\n\n어때, 잘 어울려?", "fixed texts (3.6)")

    ok(all(topics.version_ok(v) for v in ("0.2.2", "0.2.10", "0.10.0", "1.0.0"))
       and not any(topics.version_ok(v) for v in ("0.2.1", "0.1.9", "0.2", "", None, "0.2.2-beta")),
       "SPEC-265 ③: 0.2.2 or later")
    ok(topics.prefs_of(None) == {"hello_call": True, "pictures": True, "window": (1140, 1290)}, "SPEC-278 defaults")
    ok(topics.prefs_of({"hello_call": False, "pictures": True, "call_from": 1300, "call_until": 1200})["window"]
       == (1140, 1290), "a wrong window: the default")
    ok(topics.parse_window("20:00-22:00") == (1200, 1320) and topics.parse_window("19:00-24:00") == (1140, 1440)
       and topics.window_text((1140, 1290)) == "19:00-21:30", "window form")
    ok(all(topics.parse_window(x) is None for x in ("22:00-20:00", "7:00-9:00", "19:00~21:30", "25:00-26:00", "")),
       "wrong window forms")

    said = {"먼저전화하지마": ("hello_call", False), "먼저 전화하지 말아 줘": ("hello_call", False),
            "선 전화 끄기": ("hello_call", False), "먼저 전화 그만": ("hello_call", False),
            "먼저 전화해도 돼": ("hello_call", True), "먼저 전화해 줘": ("hello_call", True),
            "선전화 켜기": ("hello_call", True), "그림 그만 보내": ("pictures", False),
            "그림 보내지 마": ("pictures", False), "그림 화두 끄기": ("pictures", False), "그림 끄기": ("pictures", False),
            "그림 보내 줘": ("pictures", True), "그림 화두 켜기": ("pictures", True), "그림 켜기": ("pictures", True)}
    ok(len({k.replace(" ", "") for k in said}) == 14 and all(topics.phrase(k) == v for k, v in said.items()),
       "3.7: the 14 phrases")
    ok(topics.phrase("마롱아, 먼저 전화하지 마!") == ("hello_call", False) and topics.phrase("마롱아 그림 켜기~~")
       == ("pictures", True) and topics.phrase("  그림   보내  줘 . ") == ("pictures", True), "normalized first")
    ok(all(topics.phrase(x) is None for x in ("먼저 전화하지 마라", "그림 보내 줘서 고마워", "선톡 끄기", "전화해 줘",
                                              "그림 끄기 🎨", "")), "anything else is ordinary conversation")

    ok(topics.topic_text("나 오늘 닭꼬치 먹는 중!\n\n너는 저녁 뭐 먹었어?", skewer)
       == ("나 오늘 닭꼬치 먹는 중!\n\n너는 저녁 뭐 먹었어?", False), "SPEC-271: a good answer as it is")
    ok(topics.topic_text("닭꼬치 먹는 중!\n\n맛있다", skewer) == ("닭꼬치 먹는 중!\n\n맛있다\n\n넌 뭐 먹었어?", False),
       "no question in the last part: the picture's question is added")
    ok(all(topics.topic_text(x, skewer) == (skewer.fallback(), True) for x in (None, "", "  ", "가" * 401)),
       "nothing usable: the fixed text")
    print("PASS TASK-161 topic time, spans, gaps, backoff, picture list and choice, versions, settings, phrases, "
          "topic text checks")


# ── TASK-160: the store ────────────────────────────────────────

def clear(db):
    db.admin("DELETE FROM marong.topic_sends")
    db.admin("DELETE FROM marong.app_rings WHERE reason = 'hello' OR status <> 'answered'")
    db.admin("UPDATE marong.app_rings SET created_at = now() - interval '2 days'")
    db.admin("UPDATE call.calls SET started_at = now() - interval '2 days'")  # no call within six hours
    db.admin("DELETE FROM marong.topic_prefs")
    # Transport cases represent separate weeks. Keep previous fixture sends outside W2/W3's windows.
    db.admin("UPDATE marong.messages SET created_at = now() - interval '8 days' "
             "WHERE room_key = %s AND created_at > now() - interval '8 days' "
             "AND (meta->>'proactive' = 'true' OR meta->>'hello' = 'true')", (HK_ROOM,))


def say(db, role, content, when, meta=None):
    return db.admin("INSERT INTO marong.messages(room_key, user_key, role, content, meta, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (HK_ROOM, f"discord-user:{HK}" if role == "user" else None, role, content,
                     json.dumps(meta or {}), when))[0][0]


async def store_checks(db, store):
    caller = db.admin("SELECT id FROM call.callers WHERE friend_id = 2")[0][0]
    first = await store.topic_start(2, TODAY, "v1/winter-hat")
    ok(first and await store.topic_start(2, TODAY, "v1/all-day") is None
       and await store.topic_start(1, TODAY, "v1/all-day"), "TBL-125: one topic per friend and day")
    ok(await store.topic_prefs(2) is None, "no settings row")
    await store.topic_pref_set(2, "hello_call", False)
    row = await store.topic_prefs(2)
    ok((row["hello_call"], row["pictures"], row["call_from"], row["call_until"], row["updated_by"])
       == (False, True, 1140, 1290, "friend"), row)
    await store.topic_window_set(2, 1200, 1320)
    await store.topic_pref_set(2, "pictures", False, by="admin")
    row = await store.topic_prefs(2)
    ok((row["hello_call"], row["pictures"], row["call_from"], row["call_until"], row["updated_by"])
       == (False, False, 1200, 1320, "admin"), "each change keeps the other values")
    try:
        await store.topic_pref_set(2, "proactive", False)
        ok(False, "only two settings")
    except ValueError:
        ok(True, "only two settings")

    for sql, why in (
            ("INSERT INTO marong.app_rings(friend_id, caller_id, via, title, answer_until) "
             "VALUES (2, %s, 'app', 'x', now())", "a promise needs its schedule"),
            ("INSERT INTO marong.app_rings(schedule_id, friend_id, caller_id, via, title, answer_until, reason) "
             "SELECT 1, 2, %s, 'app', 'x', now(), 'hello'", "a hello call has none"),
            ("INSERT INTO marong.app_rings(friend_id, caller_id, via, title, answer_until, reason, topic) "
             "VALUES (2, %s, 'app', 'x', now(), 'hello', '../x')", "picture names by form")):
        try:
            db.admin(sql, (caller,))
            ok(False, why)
        except psycopg.errors.CheckViolation:
            ok(True, why)
    ring = await store.hello_add(2, caller, "털모자", "나 털모자 샀다! 어때?", "v1/winter-hat", timedelta(minutes=5))
    ok(ring and ring["status"] == "ringing" and ring["via"] == "app"
       and await store.hello_add(2, caller, "x", "y", None, timedelta(minutes=5)) is None,
       "a hello ring without a schedule; one ringing ring per friend")
    ok(db.admin("SELECT reason, topic, schedule_id, round(extract(epoch FROM answer_until - created_at)) "
                "FROM marong.app_rings WHERE id = %s", (ring["id"],))[0] == ("hello", "v1/winter-hat", None, 300),
       "reason, picture, five minutes")
    await store.topic_call(first, ring["id"])
    ok(db.admin("SELECT kind, status, via, ring_id::text FROM marong.topic_sends WHERE id = %s", (first,))[0]
       == ("call", "sent", "app", ring["id"]), "the topic row names its ring")
    last = await store.hello_last(2)
    ok(last["status"] == "ringing" and await store.rings_recent(2, timedelta(hours=6))
       and not await store.rings_recent(1, timedelta(hours=6)), "the last hello call and recent rings")
    ok(await store.hello_count(timedelta(hours=24)) == 1, "today's hello calls")
    db.admin("UPDATE marong.app_rings SET status = 'failed', resolved_at = now() WHERE id = %s", (ring["id"],))
    ok(await store.hello_last(2) is None and await store.hello_count(timedelta(hours=24)) == 0
       and not await store.rings_recent(2, timedelta(hours=6)), "a ring that failed never rang")
    clear(db)

    ok(await store.topic_quiet_days(2, TODAY, "Asia/Seoul") == 0, "never spoke, nothing sent: 0")
    say(db, "user", "마지막 말", at(TODAY - timedelta(days=3), 22))
    say(db, "assistant", "선톡 1", at(TODAY - timedelta(days=2), 12), {"proactive": True, "delivered": True})
    say(db, "assistant", "선톡 2", at(TODAY - timedelta(days=1), 12), {"proactive": True, "delivered": True})
    say(db, "assistant", "선톡 2-2", at(TODAY - timedelta(days=1), 15), {"proactive": True, "delivered": True})
    say(db, "assistant", "전달 실패", at(TODAY - timedelta(days=1), 18), {"proactive": True, "delivered": False})
    say(db, "assistant", "답", at(TODAY - timedelta(days=4), 12), {})
    ok(await store.topic_quiet_days(2, TODAY, "Asia/Seoul") == 2, "SPEC-264: two days with only proactive messages")
    ok(await store.topic_quiet_days(2, TODAY - timedelta(days=1), "Asia/Seoul") == 1, "days before today only")
    db.admin("INSERT INTO marong.app_rings(friend_id, caller_id, via, title, answer_until, reason, status, "
             "resolved_at, created_at) VALUES (2, %s, 'app', 'x', now(), 'hello', 'missed', now(), %s)",
             (caller, at(TODAY - timedelta(days=3), 23)))
    ok(await store.topic_quiet_days(2, TODAY, "Asia/Seoul") == 3, "a hello call that rang is one of those days")
    say(db, "user", "오늘 말", at(TODAY, 0, 1))
    ok(await store.topic_quiet_days(2, TODAY, "Asia/Seoul") == 0, "the friend spoke: back to 0")
    clear(db)

    # SPEC-275 answers
    opened = lambda n, status, sent: db.admin(  # noqa: E731
        "INSERT INTO marong.topic_sends(friend_id, day, picture, kind, status, sent_at) "
        "VALUES (2, %s, 'v1/all-day', 'text', %s, now() - %s::interval) RETURNING id",
        (TODAY - timedelta(days=n), status, sent))[0][0]
    talked = opened(40, "sent", "30 minutes")
    say(db, "user", "답장", datetime.now(TZ) - timedelta(minutes=10))
    quiet = opened(41, "sent", "30 days")
    failed = opened(42, "failed", "30 days")
    early = opened(43, "sent", "20 minutes")
    rung = opened(44, "sent", "2 hours")
    call = db.admin("INSERT INTO call.calls(caller_id, client_id, prompt_version, voice, started_at) "
                    "VALUES (%s, gen_random_uuid(), 'v', 'Aoede', now() - interval '35 minutes') RETURNING id",
                    (caller,))[0][0]
    hello = db.admin("INSERT INTO marong.app_rings(friend_id, caller_id, via, title, answer_until, reason, status, "
                     "answered_at, call_id, created_at) VALUES (2, %s, 'app', 'x', now(), 'hello', 'answered', "
                     "now() - interval '100 minutes', %s, now() - interval '2 hours') RETURNING id::text",
                     (caller, call))[0][0]
    db.admin("UPDATE marong.topic_sends SET kind = 'call', ring_id = %s WHERE id = %s", (hello, rung))
    db.admin("UPDATE call.calls SET status = 'ended', ended_at = now(), end_reason = 'hangup', "
             "organize_status = 'skipped' WHERE id = %s", (call,))
    answers = await store.topic_answers(topics.ANSWER_WINDOW)
    got = dict(db.admin("SELECT id, answer FROM marong.topic_sends"))
    ok(got == {talked: "answered", quiet: "none", failed: None, early: "answered", rung: "answered"}
       and sorted(answers) == ["answered", "answered", "answered", "none"], got)
    ok(db.admin("SELECT answered_at > now() - interval '11 minutes' FROM marong.topic_sends WHERE id = %s",
                (talked,))[0][0] and db.admin("SELECT answered_at < now() - interval '99 minutes' "
                                               "FROM marong.topic_sends WHERE id = %s", (rung,))[0][0],
       "answered at the friend's word, or when the hello call was taken")
    ok(await store.topic_answers(topics.ANSWER_WINDOW) == [], "decided once")
    clear(db)
    print("PASS TASK-160 one topic a day, settings defaults and changes, ring constraints, quiet days (SPEC-264), "
          "answers (SPEC-275)")


# ── TASK-162~166: proactive turns ──────────────────────────────

class FileChannel(Channel):
    """The DM channel, keeping the attachment's file name next to each message."""

    def __init__(self, channel_id, user_id):
        super().__init__(channel_id, user_id)
        self.files = []

    async def send(self, content, **kwargs):
        await super().send(content, **kwargs)
        self.files.append(kwargs["file"].filename if kwargs.get("file") else None)


async def no_sleep(_):
    return None


def reset(db, per_day=36, start=7, end=24):
    db.admin("UPDATE marong.discord_dm_links SET last_slot = NULL, last_attempt_at = NULL, failures = 0, "
             "last_incoming_at = now() - interval '2 hours', opted_in_at = now() - interval '2 hours', "
             "per_day = %s, start_hour = %s, end_hour = %s WHERE discord_user_id = %s", (per_day, start, end, HK))


def topic_rows(db):
    return db.admin("SELECT day, picture, kind, status, via, ring_id::text FROM marong.topic_sends ORDER BY id")


def last_message(db):
    return db.admin("SELECT content, meta FROM marong.messages WHERE room_key = %s ORDER BY id DESC LIMIT 1",
                    (HK_ROOM,))[0]


async def proactive_checks(db, store, settings, folder, logs):
    answers = []
    llm = ScriptedLLM(lambda body: answers.pop(0) if answers else message([text("오늘 뭐 했어?")]))
    agent = DiscordAgent(settings, store, FakeEmbeddings(), llm)
    client = Client(agent, store)
    channel = client.channels[DM_HK] = FileChannel(DM_HK, HK)
    sender = FakeFCM()
    async def name_for(friend_id):
        return "합성밤이" if friend_id == 2 else None

    push = AppPush(store, sender, ring_enabled=True, title_for=name_for)
    pictures = topics.load_set(folder)
    chooser = topics.Topics(settings, store, push, pictures=pictures, rng=lambda: 0)

    def turn_plan(now):
        return DiscordProactive(settings, store, agent, client, clock=lambda: now, rng=lambda: 0, app=push,
                                topics=chooser, sleep=no_sleep)

    async def topic_time(callable_day):
        reset(db)
        room = (await store.proactive_rooms(HK_ROOM))[0]
        today = await chooser.today(room, at(TODAY, 8))
        ok(not isinstance(today, str) and (today.call is not None) == callable_day
           and (time_ok := (19 * 60 <= today.at.hour * 60 + today.at.minute < 21 * 60 if callable_day
                            else 12 * 60 <= today.at.hour * 60 + today.at.minute < 21 * 60)), (today, callable_day))
        return today.at

    async def turn(now):
        reset(db)
        room = (await store.proactive_rooms(HK_ROOM))[0]
        return await turn_plan(now).deliver(room)

    # TASK-163 a picture topic through the app: the phone shows only the preview line (0.2.0 phone: no hello call)
    t = await topic_time(False)
    now = t + timedelta(minutes=1)
    before, sent, calls = len(sender.sent), len(channel.sent), len(llm.bodies)
    answers.append(message([text("나 산책 나왔어!\n\n오늘 날씨 좋다\n\n너는 오늘 뭐 했어?")]))
    result = await turn(now)
    rows = topic_rows(db)
    ok(result["ok"] and result["via"] == "app" and len(rows) == 1 and rows[0][2:5] == ("text", "sent", "app"), rows)
    picture = pictures.get(rows[0][1])
    note = sender.sent[before:]
    ok(len(note) == 1 and note[0]["data"]["kind"] == "proactive" and note[0]["notification"]["body"]
       == picture.preview and note[0]["android"]["notification"]["channel_id"] == TALK
       and len(channel.sent) == sent, note)
    content, meta = last_message(db)
    ok(content == "나 산책 나왔어!\n\n오늘 날씨 좋다\n\n너는 오늘 뭐 했어?" and meta["topic"] == picture.key
       and meta["proactive"] and meta["transport"] == "app" and meta["delivered"], meta)
    prompt = json.dumps(llm.bodies[calls:], ensure_ascii=False)
    ok(len(llm.bodies) == calls + 1 and "# 오늘 꺼낼 화두" in prompt and picture.scene in prompt
       and picture.alt in prompt, "AI-20: the topic part with the set's own words")

    # A second turn the same day waits for a reply even if the next slot has arrived.
    later = min(now + timedelta(hours=4), at(TODAY, 21, 59))
    sent, before, calls = len(channel.sent), len(sender.sent), len(llm.bodies)
    result = await turn(later)
    ok(not result["ok"] and len(topic_rows(db)) == 1 and len(channel.sent) == sent
       and len(sender.sent) == before and len(llm.bodies) == calls, "W2 applies to picture and call selection")
    # Simulate a reply after the first send, with enough quiet time for the next turn.
    db.admin("UPDATE marong.messages SET created_at=now()-interval '6 hours' WHERE room_key=%s "
             "AND meta->>'proactive'='true' AND created_at>now()-interval '2 hours'", (HK_ROOM,))
    before = len(sender.sent)
    result = await turn(later)
    content, meta = last_message(db)
    ok(result["ok"] and "topic" not in meta and len(topic_rows(db)) == 1
       and sender.sent[-1]["notification"]["body"] == "오늘 뭐 했어?", "SPEC-263: one topic a day")
    clear(db)

    # every phone fails: Discord, with the picture on the first message only
    sender.answers.append("failed")
    sent = len(channel.sent)
    say(db, "assistant", "나 산책 나왔어!\n\n너는 오늘 뭐 했어?", datetime.now(TZ) - timedelta(hours=6),
        {"proactive": True, "delivered": True})
    answers.append(message([text("나 산책 나왔어!\n\n너는 오늘 뭐 했어?")]))
    result = await turn(now)
    rows = topic_rows(db)
    ok(result["ok"] and rows[0][2:5] == ("text", "sent", "discord")
       and channel.sent[sent:] == ["나 산책 나왔어!", "너는 오늘 뭐 했어?"]
       and channel.files[sent:] == [f"marong-{rows[0][1].split('/')[1]}.webp", None],
       "picture topics still send their reviewed topic even if the text overlaps")
    content, meta = last_message(db)
    ok(meta["transport"] == "discord" and meta["topic"] == rows[0][1] and meta["parts"] == [2, 2], meta)
    clear(db)

    # the message with the picture fails: stop, keep it as not delivered, the topic failed
    sender.answers.append("failed")
    channel.fail = True
    result = await turn(now)
    channel.fail = False
    content, meta = last_message(db)
    ok(not result["ok"] and topic_rows(db)[0][3] == "failed" and meta["delivered"] is False and meta["topic"],
       "SPEC-273: the first message failed")
    clear(db)

    # neither path: the app fails and Discord is away
    sender.answers.append("failed")
    client.available = False
    result = await turn(now)
    client.available = True
    ok(result["text"] is None and topic_rows(db)[0][3] == "failed", "nothing went: the topic failed")
    clear(db)

    # TASK-162 the model times out, refuses, says nothing, too much: the picture's fixed text
    for answer in ([TimeoutError("fixture")], [message([text("못 해")], stop_reason="refusal")],
                   [message([text("")])] * 2, [message([text("가" * 401 + "?")])],
                   [message([text("(조용히 기다립니다)")])]):
        answers.extend(answer)  # an empty answer is asked once more (Agent.ask)
        before = len(sender.sent)
        result = await turn(now)
        rows = topic_rows(db)
        content, meta = last_message(db)
        picture = pictures.get(rows[0][1])
        ok(result["ok"] and content == picture.fallback() and meta.get("topic_fallback") and meta["topic"]
           == picture.key and sender.sent[before]["notification"]["body"] == picture.preview, (answer, content))
        clear(db)
    ok("topic_text fallback=1" in logs.getvalue(), "fallback logged")
    # a picture topic is never repeated within 30 days: with every fitting picture used, an ordinary message
    used = [p.key for p in pictures.pickable]
    for i, key in enumerate(used):
        db.admin("INSERT INTO marong.topic_sends(friend_id, day, picture, kind, status) VALUES (2, %s, %s, 'text', "
                 "'sent')", (TODAY - timedelta(days=3 + i * 3), key))
    result = await turn(now)
    content, meta = last_message(db)
    ok(result["ok"] and "topic" not in meta and "topic_skipped reason=no_picture" in logs.getvalue(),
       "SPEC-262: no picture left")
    clear(db)

    # TASK-164 a hello call to a 0.2.2 phone
    db.admin("UPDATE marong.app_devices SET app_version = '0.2.2' WHERE install_id = %s", (INSTALL,))
    t = await topic_time(True)
    now = t + timedelta(minutes=1)
    db.admin("UPDATE marong.discord_dm_links SET last_incoming_at=now()-interval '1 day', "
             "opted_in_at=now()-interval '1 day' WHERE discord_user_id=%s", (HK,))
    waiting = say(db, "assistant", "답을 기다리는 시험 선톡", datetime.now(TZ) - timedelta(hours=12),
                  {"proactive": True, "delivered": True})
    before = len(sender.sent)
    ok(await turn_plan(now).step(now) == 0 and len(sender.sent) == before and not topic_rows(db)
       and not db.admin("SELECT 1 FROM marong.app_rings WHERE reason = 'hello'"),
       "W2 neither the picture nor the scheduled hello call is sent before 21 hours")
    db.admin("UPDATE marong.messages SET created_at=now()-interval '8 days' WHERE id=%s", (waiting,))
    before, sent = len(sender.sent), len(channel.sent)
    result = await turn(now)
    rows = topic_rows(db)
    ring = db.admin("SELECT id::text, reason, status, via, schedule_id, topic, title, say, devices FROM marong.app_rings "
                    "WHERE reason = 'hello'")
    picture = pictures.get(rows[0][1])
    ok(result["ok"] and result["via"] == "call" and len(ring) == 1
       and ring[0][1:] == ("hello", "ringing", "app", None, picture.key, picture.title,
                           f"{picture.line} {picture.ask}", 1), ring)
    ok(rows[0][2:6] == ("call", "sent", "app", ring[0][0]), rows)
    bell = sender.sent[before:]
    ok(len(bell) == 1 and bell[0]["data"] == {"kind": "ring", "ringId": ring[0][0], "v": "1", "reason": "hello",
                                              "line": picture.preview, "title": "합성밤이"} and "notification" not in bell[0]
       and len(channel.sent) == sent, bell)
    ok(await turn_plan(now).daily_count(timedelta(hours=24)) == await store.proactive_count(timedelta(hours=24)) + 1,
       "SPEC-276: the hello call is one turn of the daily maximum")
    ok(f"hello_ring devices=1 picture={picture.key}" in logs.getvalue(), "logged by count and picture")

    # TASK-165 nobody took it: one note with the picture by the D18 path, never meta.proactive
    reminders = DiscordReminders(settings, store, agent, client, app=push, origin=ORIGIN, rng=lambda: 0)
    db.admin("UPDATE marong.app_rings SET answer_until = now() - interval '1 second' WHERE id = %s", (ring[0][0],))
    before = len(sender.sent)
    ok(await reminders.sweep_rings() == 1, "one note")
    note = sender.sent[before:]
    ok(len(note) == 1 and note[0]["notification"]["body"] == topics.MISSED_NOTE
       and note[0]["data"] == {"kind": "missed_call", "open": "/chat/"}, note)
    content, meta = last_message(db)
    ok(content == picture.missed() and meta["hello"] and meta["missed"] and meta["ring"] == ring[0][0]
       and meta["topic"] == picture.key and "proactive" not in meta and meta["transport"] == "app", meta)
    ok(await reminders.sweep_rings() == 0, "once")
    ok((await store.proactive_rooms(HK_ROOM))[0]["unanswered"] == 1, "W2 the missed hello note counts once")
    ok(db.admin("SELECT status FROM marong.app_rings WHERE id = %s", (ring[0][0],))[0][0] == "missed"
       and await store.hello_last(2) is not None, "the ring is missed")
    clear(db)

    # without a picture (pictures off): a short line; Discord when the phone fails, then nothing attached
    db.admin("INSERT INTO marong.topic_prefs(friend_id, pictures) VALUES (2, false)")
    result = await turn(now)
    ring = db.admin("SELECT id::text, topic FROM marong.app_rings WHERE reason = 'hello'")
    ok(result["via"] == "call" and ring[0][1] is None, "pictures off: the call has no picture")
    db.admin("UPDATE marong.app_rings SET answer_until = now() - interval '1 second' WHERE id = %s", (ring[0][0],))
    sender.answers.append("failed")
    sent = len(channel.sent)
    ok(await reminders.sweep_rings() == 1 and channel.sent[sent:] == [topics.HELLO_MISSED_LINES[0]]
       and channel.files[sent:] == [None], channel.sent[sent:])
    content, meta = last_message(db)
    ok(meta["hello"] and "topic" not in meta and meta["transport"] == "discord"
       and topic_rows(db)[0][4] == "discord", "the note's path on the topic row")
    clear(db)

    # with the picture, by Discord: the picture is attached
    result = await turn(now)
    ring = db.admin("SELECT id::text, topic FROM marong.app_rings WHERE reason = 'hello'")
    db.admin("UPDATE marong.app_rings SET answer_until = now() - interval '1 second' WHERE id = %s", (ring[0][0],))
    sender.answers.append("failed")
    sent = len(channel.sent)
    ok(await reminders.sweep_rings() == 1 and channel.sent[sent:] == [pictures.get(ring[0][1]).missed()]
       and channel.files[sent:] == [f"marong-{ring[0][1].split('/')[1]}.webp"], channel.files[sent:])
    clear(db)

    # TC-723: both bell failures fall back to the picture topic; only unregistration drops the FID.
    def phone_state():
        return db.admin("SELECT fid IS NOT DISTINCT FROM %s, fid IS NULL, dropped_at IS NOT NULL "
                        "FROM marong.app_devices WHERE install_id = %s", (FID, INSTALL))[0]

    kinds = []
    for response, via, expected_state, expected_kinds in (
        (fcm_bad_request(), "app", (True, False, False), ["ring", "proactive"]),
        (fcm_unregistered(), "discord", (False, True, True), ["ring"]),
    ):
        def answer(msg):
            kind = msg["data"]["kind"]
            kinds.append(kind)
            return response if kind == "ring" else httpx.Response(200)

        push.fcm = mock_fcm(answer)
        try:
            if response.status_code == 400:
                ok(await push.ring(await push.ring_devices(2), str(uuid.uuid4())) == 0
                   and phone_state() == expected_state, "TC-723 promise ring 400 preserves its FID")
            kinds.clear()
            result = await turn(now)
            rows = topic_rows(db)
            ok(result["ok"] and result["via"] == via and rows[0][2:5] == ("text", "sent", via)
               and db.admin("SELECT status FROM marong.app_rings WHERE reason = 'hello'") == [("failed",)]
               and kinds == expected_kinds and phone_state() == expected_state,
               f"TC-723 hello ring HTTP {response.status_code} falls back to a picture topic")
        finally:
            await push.fcm.close()
            push.fcm = sender
        clear(db)
    db.admin("UPDATE marong.app_devices SET fid = %s, dropped_at = NULL WHERE install_id = %s", (FID, INSTALL))
    print("PASS TC-723 3 bell and hello-call failure scenarios against PostgreSQL")

    # FCM refuses and pictures are off: an ordinary proactive message, the topic failed
    db.admin("INSERT INTO marong.topic_prefs(friend_id, pictures) VALUES (2, false)")
    sender.answers.append("failed")
    result = await turn(now)
    content, meta = last_message(db)
    ok(result["ok"] and "topic" not in meta and topic_rows(db)[0][3] == "failed", "SPEC-266 with pictures off")
    clear(db)

    # a ring that rang within six hours, or a live call: a picture topic message instead
    caller = db.admin("SELECT id FROM call.callers WHERE friend_id = 2")[0][0]
    db.admin("INSERT INTO marong.app_rings(friend_id, caller_id, via, title, answer_until, reason, status, "
             "resolved_at, created_at) VALUES (2, %s, 'app', 'x', now(), 'hello', 'missed', now(), "
             "now() - interval '5 hours')", (caller,))
    t2 = await chooser.today((await store.proactive_rooms(HK_ROOM))[0], at(TODAY, 8))
    ok(t2.call is None, "SPEC-265 ⑤: the last hello call was missed today: not callable for seven days")
    clear(db)
    live = db.admin("INSERT INTO call.calls(caller_id, client_id, prompt_version, voice) "
                    "VALUES (%s, gen_random_uuid(), 'v', 'Aoede') RETURNING id", (caller,))[0][0]
    result = await turn(now)
    ok(result["via"] == "app" and topic_rows(db)[0][2] == "text"
       and not db.admin("SELECT 1 FROM marong.app_rings WHERE reason = 'hello'"), "SPEC-265 ⑥⑦: a live call")
    db.admin("UPDATE call.calls SET status = 'ended', ended_at = now(), end_reason = 'hangup', "
             "organize_status = 'skipped' WHERE id = %s", (live,))
    clear(db)
    db.admin("UPDATE call.calls SET started_at = now() - interval '5 hours' WHERE id = %s", (live,))
    result = await turn(now)
    ok(result["via"] == "app" and topic_rows(db)[0][2] == "text", "a call started within six hours")
    db.admin("UPDATE call.calls SET started_at = now() - interval '7 hours' WHERE id = %s", (live,))
    clear(db)

    # before the call window: wait for a later slot; after it: a picture topic message
    room = (reset(db), (await store.proactive_rooms(HK_ROOM))[0])[1]
    ok(await chooser.choose(room, at(TODAY, 18, 30), at(TODAY, 23)) is None and not topic_rows(db),
       "SPEC-263 ⑥: before the window nothing is taken")
    choice = await chooser.choose(room, at(TODAY, 21, 40), at(TODAY, 22))
    ok(choice.kind == "text" and topic_rows(db)[0][2] == "text", "after the window: a picture topic message")
    clear(db)

    # a 0.2.1 phone only: no hello call
    db.admin("UPDATE marong.app_devices SET app_version = '0.2.1' WHERE install_id = %s", (INSTALL,))
    t = await topic_time(False)
    db.admin("UPDATE marong.app_devices SET app_version = '0.2.2' WHERE install_id = %s", (INSTALL,))

    # TASK-166 the slot that holds the topic time waits for it, then goes at the first check after it
    t = await topic_time(True)
    reset(db, per_day=1, start=7, end=24)
    plan = turn_plan(t - timedelta(minutes=5))
    room = (await store.proactive_rooms(HK_ROOM))[0]
    await plan._topic_round(t - timedelta(minutes=5))
    ok(plan.plan(room, t - timedelta(minutes=5)) is None and plan.plan(room, t) == (at(TODAY, 8), 1.0)
       and plan.plan(room, t + timedelta(minutes=9)) == (at(TODAY, 8), 1.0), "SPEC-263 ②: wait in the capped slot")
    plain = DiscordProactive(settings, store, agent, client, clock=lambda: t, rng=lambda: 0, app=push)
    ok(plain.plan(room, t - timedelta(minutes=5))[1] < 1, "without topics: as before")
    db.admin("INSERT INTO marong.topic_sends(friend_id, day, picture, kind, status) VALUES (2, %s, 'v1/all-day', "
             "'text', 'sent')", (TODAY,))
    plan._due.clear()
    await plan._topic_round(t - timedelta(minutes=5))
    ok(plan.plan(room, t - timedelta(minutes=5))[1] < 1, "today's topic went: no more waiting")
    clear(db)
    reset(db)
    logged = logs.getvalue()
    ok(not any(x in logged for x in (picture.line, picture.ask, "나 산책 나왔어", ring[0][0] if ring else "-", HK)),
       "SPEC-281: no text, ring id or Discord id in the logs")
    print("PASS TASK-162~166 picture topics by app and Discord, failures, fixed text, hello calls with reason/line, "
          "missed notes, refusals, six hours, live calls, window, daily maximum, the slot waits for the topic time")
    return agent, client, llm


# ── TASK-167: phrases ──────────────────────────────────────────

async def phrase_checks(db, store, agent, client, llm):
    channel = client.channels[DM_HK]
    agent.topics = True
    calls = len(llm.bodies)
    mid = 9000

    async def dm(words):
        nonlocal mid
        mid += 1
        await client.on_message(event(client, HK, DM_HK, mid, words))
        return channel.sent[-1]

    ok(await dm("마롱아, 먼저 전화하지 마!") == topics.REPLIES[("hello_call", False)]
       and (await store.topic_prefs(2))["hello_call"] is False and len(llm.bodies) == calls,
       "SPEC-277 example: hello calls off without the model")
    ok(await dm("먼저 전화 그만") == topics.REPLIES[("hello_call", False)], "the same again: the same answer")
    ok(await dm("그림 끄기") == topics.REPLIES[("pictures", False)]
       and (await store.topic_prefs(2))["pictures"] is False, "pictures off")
    ok(await dm("먼저 전화해 줘") == topics.REPLIES[("hello_call", True)]
       and await dm("그림 화두 켜기") == topics.REPLIES[("pictures", True)]
       and (await store.topic_prefs(2))["hello_call"] is True and (await store.topic_prefs(2))["pictures"] is True,
       "back on")
    content, meta = last_message(db)
    ok(meta["topic_pref"] == {"pictures": True}, meta)
    calls = len(llm.bodies)
    await dm("먼저 전화하지 마라")
    ok(len(llm.bodies) == calls + 1, "a near phrase is ordinary conversation")
    agent.topics = False
    await dm("그림 끄기")
    ok(len(llm.bodies) == calls + 2 and (await store.topic_prefs(2))["pictures"] is True,
       "MARONG_TOPICS off: the phrases are ordinary conversation")
    agent.topics = True
    real = store.topic_pref_set

    async def broken(*args, **kwargs):
        raise psycopg.OperationalError("fixture")
    store.topic_pref_set = broken
    ok(await dm("그림 끄기") == topics.PREF_FAILED, "a failed save says so")
    store.topic_pref_set = real
    db.admin("DELETE FROM marong.topic_prefs")
    print("PASS TASK-167 the 3.7 phrases change settings with fixed answers, near phrases and the switch off go to "
          "the model, a failed save says so")


# ── TASK-168: the in-app chat ──────────────────────────────────

async def chat_checks(db, store, settings, agent, client, folder):
    certs = Certs()
    access = AccessVerifier(AccessConfig(TEAM, AUD, frozenset({HK_EMAIL, DH_EMAIL})),
                            httpx.AsyncClient(transport=httpx.MockTransport(certs)))
    chat = AppChat(store, agent, client, access, AppPush(store, FakeFCM()), origin=ORIGIN)
    async with TestClient(TestServer(chat.web_app())) as http:
        r = await http.get("/chat/topics/v1/winter-hat.webp")
        body = await r.read()
        ok(r.status == 200 and r.headers["Content-Type"] == "image/webp"
           and r.headers["Cache-Control"] == "public, max-age=31536000, immutable"
           and body == (folder / "winter-hat.webp").read_bytes() and r.headers["X-Content-Type-Options"] == "nosniff",
           "API-140 200")
        r = await http.get("/chat/topics/v1/old-picture.webp")
        ok(r.status == 200, "a removed picture still shows in old messages")
        for path in ("/chat/topics/v1/nope.webp", "/chat/topics/v1/Winter-Hat.webp", "/chat/topics/v2/winter-hat.webp",
                     "/chat/topics/v1/winter-hat.png", "/chat/topics/v1/too-big.webp", "/chat/topics/x/all-day.webp",
                     "/chat/topics/v1/..%2Ftopics.json"):
            r = await http.get(path)
            problem = await r.json(content_type=None)
            ok(r.status == 404 and problem["code"] == "no_picture" and r.headers["Cache-Control"] == "no-store"
               and r.headers["Content-Type"].startswith("application/problem+json"), (path, r.status, problem))
        (folder / "chicken-skewer.webp").rename(folder / "moved.webp")
        r = await http.get("/chat/topics/v1/chicken-skewer.webp")
        problem = await r.json(content_type=None)
        ok(r.status == 500 and problem["code"] == "internal" and r.headers["Cache-Control"] == "no-store",
           "API-140 default: an unreadable file")
        (folder / "moved.webp").rename(folder / "chicken-skewer.webp")

        say(db, "assistant", "나 털모자 샀다!\n\n어때?", datetime.now(TZ),
            {"proactive": True, "topic": "v1/winter-hat", "transport": "app", "delivered": True})
        say(db, "assistant", "전화했는데 바빴나 봐!", datetime.now(TZ),
            {"ring": "x", "hello": True, "missed": True, "topic": "v1/old-picture", "transport": "app",
             "delivered": True})
        say(db, "assistant", "모르는 그림", datetime.now(TZ),
            {"proactive": True, "topic": "v1/nope", "transport": "app", "delivered": True})
        say(db, "user", "내 말", datetime.now(TZ), {"topic": "v1/winter-hat"})
        r = await http.get("/chat/api/messages?limit=4", headers=auth())
        page = await r.json()
        got = {m["text"]: m for m in page["messages"]}
        ok(r.status == 200 and got["나 털모자 샀다!\n\n어때?"]["picture"]
           == {"src": "/chat/topics/v1/winter-hat.webp", "alt": "털모자를 쓰고 웃는 마롱이"}
           and got["나 털모자 샀다!\n\n어때?"]["kind"] == "proactive", got)
        ok(got["전화했는데 바빴나 봐!"]["kind"] == "hello" and got["전화했는데 바빴나 봐!"]["picture"]["src"]
           == "/chat/topics/v1/old-picture.webp", "API-102: kind hello, a removed picture still shown")
        ok("picture" not in got["모르는 그림"] and "picture" not in got["내 말"], "unknown pictures and friends' words")
    await chat.close()
    print("PASS TASK-168 API-140 200/404/500 with immutable caching only for pictures, Message.picture and kind hello")


def admin_checks(db):
    """tools/admin.py topics, as 동희님 runs it (bash deploy/ovh.sh admin topics …), against the bot's own account."""
    def admin(*args):
        env = {**os.environ, "DATABASE_URL": db.app_url, "PYTHONIOENCODING": "utf-8"}
        p = subprocess.run([sys.executable, str(ROOT / "tools" / "admin.py"), "topics", *args],
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        return p.returncode, p.stdout + p.stderr

    def prefs():
        return db.admin("SELECT hello_call, pictures, call_from, call_until, updated_by FROM marong.topic_prefs "
                        "WHERE friend_id = 2")

    db.admin("DELETE FROM marong.topic_prefs")
    db.admin("DELETE FROM marong.topic_sends WHERE friend_id = 2")
    db.admin("INSERT INTO marong.topic_sends (friend_id, day, picture, kind, status, via, sent_at, answer, answered_at) "
             "VALUES (2, current_date - 2, 'v1/winter-hat', 'text', 'sent', 'app', now() - interval '2 days', "
             "'answered', now() - interval '2 days'), (2, current_date, 'v1/chicken-skewer', 'text', 'failed', NULL, "
             "now(), NULL, NULL)")
    code, out = admin("status")
    ok(code == 0 and "현경  선 전화 켬 · 그림 화두 켬 · 선 전화 시간대 19:00-21:30 (기본값)" in out, out)
    lines = [line for line in out.splitlines() if line.startswith("  ") and "v1/" in line]
    ok(len(lines) == 2 and re.fullmatch(r"  \d\d/\d\d  v1/chicken-skewer  그림 글 → 실패 · 답 기다림", lines[0])
       and re.fullmatch(r"  \d\d/\d\d  v1/winter-hat  그림 글 → 보냄\(앱\) · 답 있음", lines[1]), out)
    ok(not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", out), "no ring id in the status")
    ok(prefs() == [], "status changes nothing")
    code, out = admin("현경", "window", "20:00-22:00")
    ok(code == 0 and "현경: 선 전화 시간대 20:00-22:00" in out, out)
    ok(prefs() == [(True, True, 1200, 1320, "admin")], prefs())
    code, out = admin("현경", "call", "off")
    ok(code == 0 and "현경: 선 전화 끔" in out and prefs() == [(False, True, 1200, 1320, "admin")], (out, prefs()))
    code, out = admin("현경", "pictures", "off")
    ok(code == 0 and "현경: 그림 화두 끔" in out and prefs() == [(False, False, 1200, 1320, "admin")], (out, prefs()))
    code, out = admin("status")
    ok("현경  선 전화 끔 · 그림 화두 끔 · 선 전화 시간대 20:00-22:00 (바꾼 때 " in out and "관리자)" in out, out)
    for args, why in ((("없는친구", "call", "on"), "없음"), (("현경", "window", "22:00-20:00"), "HH:MM-HH:MM"),
                      (("현경", "window", "7-9"), "HH:MM-HH:MM"), (("현경", "window", "19:00-24:30"), "HH:MM-HH:MM"),
                      (("현경", "call", "maybe"), "사용:"), (("현경", "ring", "on"), "사용:"), ((), "사용:")):
        code, out = admin(*args)
        ok(code != 0 and why in out, (args, out))
    ok(prefs() == [(False, False, 1200, 1320, "admin")], "wrong input changed nothing")
    code, out = admin("현경", "call", "on")
    code, out = admin("현경", "pictures", "on")
    code, out = admin("현경", "window", "19:00-21:30")
    ok(prefs() == [(True, True, 1140, 1290, "admin")], prefs())
    print("PASS TASK-172 admin topics: status (defaults, recent topics, no ring id), call/pictures on|off and window by "
          "admin, unknown friend and wrong times change nothing")


def log_checks(logs):
    """TASK-173, SPEC-281: every log line of topics, hello calls and pictures is result names, counts and picture names:
    plain ASCII, so no topic text, friend's words or name, and no ring id, FID or Discord id."""
    lines = [line for line in logs.getvalue().splitlines()
             if re.search(r"topic|hello|picture|ring_missed|ring_answered", line)]
    ok(len(lines) > 20, f"{len(lines)} lines read")
    bad = [line for line in lines if not line.isascii() or re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-|ringfid|fidA|fidB|\d{15,}", line)]
    ok(not bad, bad[:5])
    print(f"PASS TASK-173 {len(lines)} log lines of topics, hello calls and pictures: names and counts only")


async def main(db, folder, logs):
    settings = load_settings()
    store = DiscordStore(db.app_url, call_bridge=True)
    await store.open(wait=True)
    topics.FOLDER = folder.parent  # the process-wide set (missed notes, the chat server) is the fixture too
    topics.picture_set.cache_clear()
    try:
        decision_checks(folder, logs)
        await store_checks(db, store)
        agent, client, llm = await proactive_checks(db, store, settings, folder, logs)
        await phrase_checks(db, store, agent, client, llm)
        await chat_checks(db, store, settings, agent, client, folder)
        admin_checks(db)
        log_checks(logs)
    finally:
        await store.close()


if __name__ == "__main__":
    logs = io.StringIO()
    capture = logging.StreamHandler(logs)
    capture.setFormatter(logging.Formatter("%(name)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(capture)
    root.setLevel(logging.INFO)
    db = TestDB()
    try:
        prepare(db)
        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(main(db, make_set(Path(tmp)), logs))
    finally:
        db.close()
    print(f"OK {CHECKS} checks")
