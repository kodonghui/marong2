"""일정·알림 시험: 진짜 Postgres(pgserver) + 가짜 디스코드 DM + 가짜 Claude.
시각 계산(반복·지난 때·먼 때), 저장·취소·찾기 도구, DM 상황 줄(선톡 상태가 맞고 ask_owner 가 없음), 친구끼리 일정이 안
보임, 때가 된 알림 보내기·기록·한 번만·반복 다음 때·늦은 알림·놓친 알림·전달 실패 다시 하기·디스코드 끊김, 리포트 표시,
봇 계정에 지우기 권한 없음.
실행: .venv/bin/python tests/test_schedules.py"""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tools/vertex_live")]
from fakes import FakeEmbeddings, ScriptedLLM, message, text, tool_use  # noqa: E402
from marong.config import load_settings  # noqa: E402
from marong.discord_dm import DiscordAgent, DiscordReminders  # noqa: E402
from marong.discord_store import DiscordStore  # noqa: E402
from marong.schedules import (LATE_PREFIX, NewSchedule, check_add, describe, occurrence, parse_when,  # noqa: E402
                              reminder_text, schedule_lines)
from pg import TestDB  # noqa: E402
from test_discord_dm import DH, DM_DH, DM_HK, HK, Client, event, prepare as prepare_dm  # noqa: E402
from tools.report import build  # noqa: E402

TZ = ZoneInfo("Asia/Seoul")
CHECKS = 0


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def iso(dt: datetime) -> str:
    return dt.astimezone(TZ).isoformat(timespec="seconds")


def pure_checks():
    k = lambda *a: datetime(*a, tzinfo=TZ)  # noqa: E731
    ok(parse_when("2026-11-16T15:00:00+09:00", TZ) == (k(2026, 11, 16, 15), False), "ISO with offset")
    ok(parse_when("2026-11-16T15:00", TZ) == (k(2026, 11, 16, 15), False), "naive ISO is Korean time")
    ok(parse_when("2026-11-16T06:00:00Z", TZ) == (k(2026, 11, 16, 15), False), "UTC converts")
    ok(parse_when("2026-11-20", TZ) == (k(2026, 11, 20), True), "date only is all day")
    for bad in ("", "내일 3시", "2026-13-01", "2026-11-16T25:00"):
        try:
            parse_when(bad, TZ)
            ok(False, f"bad time accepted: {bad}")
        except ValueError:
            ok(True, "bad time")

    anchor = k(2026, 11, 13, 8)  # 금요일 08:00
    ok(occurrence(anchor, "daily", k(2026, 11, 15, 9), TZ) == k(2026, 11, 16, 8), "daily after today's time")
    ok(occurrence(anchor, "daily", k(2026, 11, 15, 7), TZ) == k(2026, 11, 15, 8), "daily later today")
    ok(occurrence(anchor, "weekdays", k(2026, 11, 13, 9), TZ) == k(2026, 11, 16, 8), "Friday → Monday")
    ok(occurrence(anchor, "weekly", k(2026, 11, 13, 8), TZ) == k(2026, 11, 20, 8), "weekly strictly after")
    ok(occurrence(anchor, "daily", k(2026, 11, 1), TZ) == anchor, "future anchor is first")
    ok(occurrence(k(2026, 11, 14, 7), "weekdays", k(2026, 11, 1), TZ) == k(2026, 11, 16, 7), "weekend anchor skips")
    jan31 = k(2027, 1, 31, 10)
    ok(occurrence(jan31, "monthly", jan31, TZ) == k(2027, 2, 28, 10), "monthly clamps to Feb 28")
    ok(occurrence(jan31, "monthly", k(2027, 2, 28, 10), TZ) == k(2027, 3, 31, 10), "monthly keeps the 31st")
    ok(occurrence(k(2026, 12, 25, 9), "monthly", k(2026, 12, 25, 10), TZ) == k(2027, 1, 25, 9), "over new year")
    ok(occurrence(k(2020, 1, 1, 8), "daily", k(2026, 11, 15, 9), TZ) == k(2026, 11, 16, 8), "old anchor is quick")

    now = k(2026, 11, 15, 17, 3)
    for inp, why in (({}, "title"), ({"title": "x" * 61, "remind_at": iso(now + timedelta(hours=1))}, "title"),
                     ({"title": "시험"}, "event_at 이나 remind_at"),
                     ({"title": "a", "remind_at": "2026-11-16"}, "시각까지"),
                     ({"title": "a", "remind_at": "내일"}, "remind_at 은"),
                     ({"title": "a", "remind_at": iso(now - timedelta(minutes=10))}, "이미 지난"),
                     ({"title": "a", "remind_at": iso(now + timedelta(days=800))}, "너무 먼"),
                     ({"title": "a", "event_at": "2026-11-14"}, "이미 지난 날"),
                     ({"title": "a", "event_at": "2030-01-01"}, "너무 먼"),
                     ({"title": "a", "repeat": "hourly", "remind_at": iso(now + timedelta(hours=1))}, "repeat"),
                     ({"title": "a", "repeat": "daily"}, "반복 알림은")):
        out = check_add(inp, TZ, now)
        ok(isinstance(out, str) and why in out, f"check_add {inp} → {out}")
    item = check_add({"title": " 토익  원서 접수 ", "remind_at": iso(now - timedelta(seconds=40)), "say": "야 지금!"},
                     TZ, now)
    ok(item.title == "토익 원서 접수" and item.remind_at == now, "just-passed reminder goes now")
    item = check_add({"title": "현경 생일", "event_at": "2026-11-15"}, TZ, now)
    ok(item.all_day and item.remind_at is None, "today's all-day event may be remembered")
    item = check_add({"title": "약", "repeat": "daily", "remind_at": iso(k(2026, 11, 15, 8)),
                      "event_at": "2026-11-20"}, TZ, now)
    ok(item.anchor == k(2026, 11, 15, 8) and item.remind_at == k(2026, 11, 16, 8) and item.event_at is None,
       "repeat starts at the next time and drops the event")
    item = check_add({"title": "a", "remind_at": iso(now + timedelta(hours=1)), "say": "가" * 400}, TZ, now)
    ok(len(item.say) == 300 and item.say.endswith("…"), "long say is cut")

    row = {"id": 12, "title": "토익 시험", "event_at": k(2026, 11, 20, 9), "all_day": False,
           "remind_at": k(2026, 11, 19, 21), "repeat": "none", "repeat_anchor": None, "say": None}
    ok(describe(row, TZ, now) == "#12 11/20(금) 09:00 토익 시험 · 알림 11/19(목) 21:00", describe(row, TZ, now))
    ok(reminder_text(row, TZ, timedelta(0)) == "⏰ 토익 시험 (09:00)", "default text")
    ok(reminder_text({**row, "say": "내일 시험!"}, TZ, timedelta(minutes=30)) == LATE_PREFIX + "내일 시험!", "late")
    row = {**row, "id": 3, "event_at": k(2027, 1, 2), "all_day": True, "remind_at": None}
    ok(describe(row, TZ, now) == "#3 2027/1/2(토) 종일 토익 시험", describe(row, TZ, now))
    row = {**row, "id": 4, "event_at": None, "all_day": False, "repeat": "weekly", "repeat_anchor": k(2026, 11, 17, 19),
           "remind_at": k(2026, 11, 17, 19), "title": "운동"}
    ok(describe(row, TZ, now) == "#4 매주 화요일 19:00 알림: 운동 (다음 11/17(화) 19:00)", describe(row, TZ, now))
    ok("못 읽었어" in "\n".join(schedule_lines(None, 0, TZ, now)), "unreadable list says so")
    print("PASS times, repeats, input checks and wording")


def schedule_reply(name, inp, answer):
    """First Claude call uses the tool, the second writes the reply. Records each tool result."""
    results = []

    def respond(body):
        last = body["messages"][-1]
        if last["role"] == "user" and isinstance(last["content"], list) and last["content"] and \
                isinstance(last["content"][0], dict) and last["content"][0].get("type") == "tool_result":
            results.append(last["content"][0])
            return message([text(answer)])
        return message([tool_use(name, inp)], "tool_use")
    return respond, results


def situation(body) -> str:
    return body["system"][-1]["text"]


async def flow_checks(db):
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul")  # as run_discord.py
    store = DiscordStore(db.app_url, call_bridge=True)
    await store.open(wait=True)
    try:
        llm = ScriptedLLM(lambda _: message([text("응!")]))
        agent = DiscordAgent(settings, store, FakeEmbeddings(), llm)
        client = Client(agent, store)
        now = datetime.now(TZ)
        tomorrow3 = (now + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)

        # 1) Asking for a reminder stores it for the asking friend only.
        respond, results = schedule_reply("schedule_add", {
            "title": "토익 원서 접수", "remind_at": iso(tomorrow3), "say": "야 3시야! 토익 원서 접수 잊지 마 📝"},
            "응 내일 3시에 톡할게!")
        llm.fn = respond
        await client.on_message(event(client, HK, DM_HK, 101, "내일 3시에 토익 원서 접수 알려줘"))
        first = llm.bodies[0]
        ok({t["name"] for t in first["tools"]} == {"schedule_add", "schedule_cancel", "schedule_list"}, "DM tools")
        s = situation(first)
        ok("# 일정과 알림" in s and "## 이 친구 일정" in s and "- 아직 없어." in s, "guide and empty list")
        ok("ask_owner" not in s and "선톡 끔" not in s, "no Kakao owner-request lines in DM")
        ok("하루 36번까지 먼저 말을 걸어" in s and "7~24시" in s, "actual DM proactive state")
        ok("선톡과 상관없이" in s, "reminders work regardless of proactive")
        ok("동희에게 대신 전하거나 남길 수 없어" in s and "다른 친구에게 하지 않게" not in s, "no pretend notes to the owner")
        ok(client.channels[DM_HK].sent[-1] == "응 내일 3시에 톡할게!", "reply sent")
        ok(results and "저장했어" in results[0]["content"] and not results[0].get("is_error"), results)
        rows = db.admin("SELECT id, friend_id, room_key, source, title, remind_at, say, status, source_message_id "
                        "FROM marong.schedules")
        ok(len(rows) == 1 and rows[0][1] == 2 and rows[0][2] == f"discord-dm:{HK}" and rows[0][3] == "discord"
           and rows[0][5] == tomorrow3 and rows[0][7] == "active", rows)
        hk_first = rows[0][0]
        asked = db.admin("SELECT id FROM marong.messages WHERE room_key=%s AND content=%s",
                         (f"discord-dm:{HK}", "내일 3시에 토익 원서 접수 알려줘"))
        ok(rows[0][8] == asked[0][0], "source message is the friend's text")
        meta = db.admin("SELECT meta FROM marong.messages WHERE room_key=%s AND role='assistant' ORDER BY id DESC "
                        "LIMIT 1", (f"discord-dm:{HK}",))[0][0]
        ok(meta.get("schedule") == [{"tool": "schedule_add", "result": "ok", "id": hk_first}], meta)

        # 2) The next reply sees the list with its number; the other friend sees nothing of it.
        llm.fn = lambda _: message([text("응 기억하고 있어")])
        await client.on_message(event(client, HK, DM_HK, 102, "내 일정 뭐 있지?"))
        ok(f"- #{hk_first} 알림 " in situation(llm.bodies[-1]) and "토익 원서 접수" in situation(llm.bodies[-1]),
           "own list shown")
        await client.on_message(event(client, DH, DM_DH, 103, "나 일정 있어?"))
        s = situation(llm.bodies[-1])
        ok("토익 원서 접수" not in s and "- 아직 없어." in s, "other friend's schedule is invisible")
        ok("선톡 꺼짐" in s and "먼저 톡해 줘" in s and "ask_owner" not in s, "not-opted-in DM says so without ask_owner")

        # A friend whose sharing is off keeps that fact without the owner-request tool.
        db.admin("UPDATE marong.friends SET share=false WHERE id=1")
        await client.on_message(event(client, DH, DM_DH, 113, "내 얘기 다른 친구한테 해?"))
        s = situation(llm.bodies[-1])
        ok("다른 친구에게 하지 않게 돼 있어(동희가 정함)." in s and "ask_owner" not in s, "sharing fact kept")
        db.admin("UPDATE marong.friends SET share=true WHERE id=1")

        # 3) Mistakes come back to the model and store nothing.
        respond, results = schedule_reply("schedule_add", {
            "title": "회의", "remind_at": iso(now - timedelta(hours=2))}, "앗 다시 말해 줄래?")
        llm.fn = respond
        await client.on_message(event(client, DH, DM_DH, 104, "회의 알려줘"))
        ok(results[0].get("is_error") and "이미 지난" in results[0]["content"], results)
        ok(db.admin("SELECT count(*) FROM marong.schedules WHERE friend_id=1")[0][0] == 0, "nothing stored on error")

        # 4) The same request twice is stored once.
        respond, results = schedule_reply("schedule_add", {
            "title": "토익 원서 접수", "remind_at": iso(tomorrow3)}, "이미 맞춰 놨어!")
        llm.fn = respond
        await client.on_message(event(client, HK, DM_HK, 105, "내일 3시 원서 접수 알려줘~"))
        ok("이미 저장돼 있어" in results[0]["content"], results)
        ok(db.admin("SELECT count(*) FROM marong.schedules WHERE friend_id=2")[0][0] == 1, "no duplicate")

        # 5) A friend cannot cancel someone else's schedule; the owner can.
        respond, results = schedule_reply("schedule_cancel", {"id": hk_first}, "그런 일정은 없는데?")
        llm.fn = respond
        await client.on_message(event(client, DH, DM_DH, 106, f"{hk_first}번 취소해"))
        ok(results[0].get("is_error"), "other friend's cancel refused")
        ok(db.admin("SELECT status FROM marong.schedules WHERE id=%s", (hk_first,))[0][0] == "active", "still active")

        # 6) An event and a repeating reminder; the list tool finds far ones.
        exam = (now + timedelta(days=90)).date().isoformat()
        respond, results = schedule_reply("schedule_add", {"title": "토익 시험", "event_at": exam}, "오 기억할게!")
        llm.fn = respond
        await client.on_message(event(client, HK, DM_HK, 107, f"{exam}에 토익 시험이야"))
        ok("알림 없이 기억만" in results[0]["content"], results)
        pill = (now - timedelta(hours=3)).replace(second=0, microsecond=0)  # first time already passed today
        daily = f"매일 {pill:%H:%M} 알림: 약 먹기"
        respond, results = schedule_reply("schedule_add", {
            "title": "약 먹기", "repeat": "daily", "remind_at": iso(pill), "say": "약 먹을 시간이야 💊"},
            "매일 그때 말해 줄게!")
        llm.fn = respond
        await client.on_message(event(client, HK, DM_HK, 108, "매일 이 시간에 약 먹으라고 해 줘"))
        ok(daily in results[0]["content"], results)
        nxt = db.admin("SELECT remind_at FROM marong.schedules WHERE title='약 먹기'")[0][0]
        ok(nxt - pill == timedelta(days=1), "repeat whose first time passed starts tomorrow")
        llm.fn = lambda _: message([text("응")])
        await client.on_message(event(client, HK, DM_HK, 109, "고마워"))
        s = situation(llm.bodies[-1])
        ok(daily in s and "토익 시험" not in s and "더 먼 일정 1개" in s, "window and count")
        respond, results = schedule_reply("schedule_list", {"start": exam, "end": exam}, "그날 시험이야!")
        llm.fn = respond
        await client.on_message(event(client, HK, DM_HK, 110, "그날 뭐 있었지?"))
        ok("종일 토익 시험" in results[0]["content"] and "약 먹기" in results[0]["content"], results)
        exam_id = db.admin("SELECT id FROM marong.schedules WHERE title='토익 시험'")[0][0]
        respond, results = schedule_reply("schedule_cancel", {"id": exam_id}, "취소했어!")
        llm.fn = respond
        await client.on_message(event(client, HK, DM_HK, 111, "시험 일정 지워 줘"))
        ok("취소했어" in results[0]["content"] and not results[0].get("is_error"), results)
        ok(db.admin("SELECT status FROM marong.schedules WHERE id=%s", (exam_id,))[0][0] == "canceled", "canceled")

        # 7) If the list cannot be read, Marong still answers and says it cannot check right now.
        working = store.upcoming_schedules

        async def broken(*_):
            raise psycopg.OperationalError("fixture")
        store.upcoming_schedules = broken
        llm.fn = lambda _: message([text("지금은 확인이 안 돼 ㅠ")])
        await client.on_message(event(client, HK, DM_HK, 112, "내 일정 뭐야?"))
        store.upcoming_schedules = working
        ok("지금은 일정을 못 읽었어" in situation(llm.bodies[-1]), "unreadable list is said")
        ok(client.channels[DM_HK].sent[-1] == "지금은 확인이 안 돼 ㅠ", "still answers")

        # 8) Proactive greetings never get the schedule tools.
        room = (await store.proactive_rooms())[0]
        llm.fn = lambda _: message([text("뭐 해?")])
        await agent.proactive_message(room)
        ok("tools" not in llm.bodies[-1], "no tools in proactive")
        return hk_first
    finally:
        await store.close()


async def delivery_checks(db, hk_first):
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul")  # as run_discord.py
    store = DiscordStore(db.app_url, call_bridge=True)
    await store.open(wait=True)
    try:
        llm = ScriptedLLM(lambda _: message([text("응!")]))
        agent = DiscordAgent(settings, store, FakeEmbeddings(), llm)
        client = Client(agent, store)
        hk = client.channels[DM_HK]
        reminders = DiscordReminders(settings, store, agent, client)

        def due(schedule_id, ago):
            db.admin("UPDATE marong.schedules SET remind_at=now()-%s WHERE id=%s", (ago, schedule_id))

        # A due one-off reminder goes once, is recorded and finishes.
        due(hk_first, timedelta(seconds=5))
        before = len(hk.sent)
        ok(await reminders.step() == 1 and hk.sent[before:] == ["야 3시야! 토익 원서 접수 잊지 마 📝"], hk.sent)
        ok(await reminders.step() == 0 and len(hk.sent) == before + 1, "sent only once")
        status, count = db.admin("SELECT status, sent_count FROM marong.schedules WHERE id=%s", (hk_first,))[0]
        ok(status == "done" and count == 1, (status, count))
        saved = db.admin("SELECT content, meta FROM marong.messages WHERE room_key=%s ORDER BY id DESC LIMIT 1",
                         (f"discord-dm:{HK}",))[0]
        ok(saved[0] == hk.sent[-1] and saved[1]["reminder"] == hk_first and saved[1]["delivered"] is True, saved)

        async def insert(friend, title, remind_ago=None, event_in=None, repeat="none", say=None):
            now = datetime.now(TZ)
            remind = now - remind_ago if remind_ago is not None else None
            item = NewSchedule(title, now + event_in if event_in else None, False, remind, repeat,
                               remind if repeat != "none" else None, say)
            outcome, row = await store.add_schedule(friend, None, "discord", None, item)
            assert outcome == "ok", outcome
            return row["id"]

        # An event keeps living after its reminder; a daily reminder moves to tomorrow.
        event_id = await insert(2, "치과", timedelta(seconds=1), timedelta(hours=2), say="2시간 뒤 치과야!")
        daily_id = await insert(2, "물 마시기", timedelta(seconds=1), repeat="daily", say="물 마셔 💧")
        ok(await reminders.step() == 2, "two due")
        remind, status = db.admin("SELECT remind_at, status FROM marong.schedules WHERE id=%s", (event_id,))[0]
        ok(remind is None and status == "active", "event stays without reminder")
        remind, anchor = db.admin("SELECT remind_at, repeat_anchor FROM marong.schedules WHERE id=%s", (daily_id,))[0]
        ok(remind - anchor == timedelta(days=1), (remind, anchor))

        # Late reminders: a little late says sorry, very late is not sent.
        late_id = await insert(2, "빨래", timedelta(minutes=20), say="빨래 꺼내!")
        missed_id = await insert(2, "택배", timedelta(hours=4), say="택배 와!")
        before = len(hk.sent)
        ok(await reminders.step() == 1 and hk.sent[before:] == [LATE_PREFIX + "빨래 꺼내!"], hk.sent[before:])
        ok(db.admin("SELECT status, sent_count FROM marong.schedules WHERE id=%s", (missed_id,))[0] == ("missed", 0),
           "very late one-off is missed")
        late_daily = await insert(2, "스트레칭", timedelta(hours=5), repeat="daily", say="스트레칭!")
        ok(await reminders.step() == 0, "very late repeat is skipped")
        ok(db.admin("SELECT status, remind_at > now() FROM marong.schedules WHERE id=%s", (late_daily,))[0]
           == ("active", True), "and moves on")

        # Delivery failures retry a minute later, then give up with one record.
        failing = await insert(2, "전화", timedelta(seconds=1), say="엄마한테 전화!")
        hk.fail = True
        for attempt in range(3):
            ok(await reminders.step() == 0, "failed send")
            if attempt < 2:
                ok(await reminders.step() == 0, "waits before retry")
                db.admin("UPDATE marong.schedules SET claimed_until=now()-interval '1 second' WHERE id=%s", (failing,))
        hk.fail = False
        ok(db.admin("SELECT status FROM marong.schedules WHERE id=%s", (failing,))[0][0] == "missed", "gave up")
        records = db.admin("SELECT meta->>'delivered' FROM marong.messages WHERE meta->>'reminder'=%s", (str(failing),))
        ok(records == [("false",)], records)

        # No channel yet (the friend never opened the DM) → missed; disconnected Discord → nothing is claimed.
        db.admin("UPDATE marong.discord_dm_links SET channel_id=NULL, last_incoming_at=NULL, opted_in_at=NULL "
                 "WHERE discord_user_id=%s", (DH,))
        no_dm = await insert(1, "동희 알림", timedelta(seconds=1), say="동희!")
        client.available = False
        waiting = await insert(2, "기다림", timedelta(seconds=1), say="기다렸지!")
        ok(await reminders.step() == 0, "offline")
        ok(db.admin("SELECT claimed_until FROM marong.schedules WHERE id=%s", (waiting,))[0][0] is None, "not claimed")
        client.available = True
        before = len(hk.sent)
        ok(await reminders.step() == 1 and hk.sent[before:] == ["기다렸지!"], "sent after reconnect")
        ok(db.admin("SELECT status FROM marong.schedules WHERE id=%s", (no_dm,))[0][0] == "missed", "no DM → missed")

        # A claimed reminder is not taken again while its lease runs.
        leased = await insert(2, "임대", timedelta(seconds=1), say="임대!")
        db.admin("UPDATE marong.schedules SET claimed_until=now()+interval '4 minutes' WHERE id=%s", (leased,))
        ok(await reminders.step() == 0, "leased")

        # Past events close; the bot account cannot delete schedules.
        db.admin("UPDATE marong.schedules SET event_at=now()-interval '2 days' WHERE id=%s", (event_id,))
        ok(await store.close_past_events() == 1, "past event closed")
        with psycopg.connect(db.app_url) as conn:
            can = conn.execute("SELECT has_table_privilege('marong.schedules','DELETE') OR "
                               "has_table_privilege('marong.schedules','TRUNCATE')").fetchone()[0]
        ok(not can, "no delete for the bot")

        # The research sheet labels reminders.
        with psycopg.connect(db.app_url, row_factory=dict_row) as conn:
            ts = datetime.now(TZ)
            tabs, _ = build(conn, ts - timedelta(days=1), ts + timedelta(minutes=1), TZ, vectors=False)
            talk = next(tab for tab in tabs if tab["name"] == "대화")
            kinds = {row[5]: row[4] for row in talk["rows"]}
            ok(kinds.get("물 마셔 💧") == "알림(부탁한 일정)", kinds.get("물 마셔 💧"))
        print("PASS delivery once, records, repeats, late and missed reminders, retries, offline, lease, report")
    finally:
        await store.close()


if __name__ == "__main__":
    pure_checks()
    db = TestDB()
    try:
        prepare_dm(db)  # includes 012_schedules.sql
        first = asyncio.run(flow_checks(db))
        print("PASS tools, DM situation, isolation, duplicates, cancel rights, list, proactive without tools")
        asyncio.run(delivery_checks(db, first))
    finally:
        db.close()
    print(f"OK {CHECKS} checks")
