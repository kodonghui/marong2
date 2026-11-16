"""마롱이 앱 3단계 시험(docs/app-ring.md TC-137~141·144): 진짜 Postgres(pgserver), 가짜 FCM, 가짜 디스코드, 가짜 Claude.
네트워크와 실제 키는 쓰지 않아요.

- TC-137 전화 약속 저장(call 칸, 시각 없음, 통화가 안 되는 친구, 반복, MARONG_APP_RING 없으면 call 칸 없음)
- TC-138 보내기 순서 ①~⑦과 디스코드 실패·끊김, TC-139 벨 메시지에 약속 내용 없음
- TC-140 같은 때 약속 두 개 → 벨 하나, 유니크 색인, 권한(통화 서버는 정한 칸만, 아무도 못 지움)
- TC-141 통화 서버의 약속 전화 확인(claim_ring): ring 있음·없음, 다른 caller, 시간 지남, 같은 통화 다시 연결
- TC-144 못 받은 전화: missed와 한마디 한 번(D18 길), 디스코드 길은 한마디 없음, 받은 벨은 그대로, 받기·놓침 경합은 하나만,
  로그에 벨 id·제목 없음, 기록 시트 표시(SPEC-126 '(앱)', SPEC-142 '(마롱이가 걺)')
실행: .venv/bin/python tests/test_app_ring.py"""
import asyncio
from datetime import datetime, timedelta
import io
import json
import logging
from pathlib import Path
import sys
import uuid
from zoneinfo import ZoneInfo

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tools/vertex_live")]
from call_memory import MemoryStore, Principal  # noqa: E402
from fakes import FakeEmbeddings, ScriptedLLM, message, text  # noqa: E402
from marong.app_delivery import MISSED_LINES, RING_DISCORD_TEXT, RING_LATE_TEXT  # noqa: E402
from marong.app_push import REMINDER, TALK, AppPush  # noqa: E402
from marong.config import load_settings  # noqa: E402
from marong.discord_dm import DiscordAgent, DiscordReminders  # noqa: E402
from marong.discord_store import DiscordStore  # noqa: E402
from marong.schedules import CALL_GUIDE, CALL_UNAVAILABLE, check_add, run_tool, schedule_guide, schedule_tools  # noqa: E402
from pg import TestDB  # noqa: E402
from test_app_chat import FakeFCM, prepare as prepare_app  # noqa: E402
from test_discord_dm import DM_HK, HK, Client, event  # noqa: E402

TZ = ZoneInfo("Asia/Seoul")
ORIGIN = "https://marong.example.test"
HK_ROOM = f"discord-dm:{HK}"
INSTALL = str(uuid.uuid4())
FID = "ringfid" + "z" * 30
CHECKS = 0


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def prepare(db):
    prepare_app(db)
    db.admin("UPDATE marong.discord_dm_links SET channel_id = %s, last_incoming_at = now() WHERE discord_user_id = %s",
             (str(DM_HK), HK))
    db.admin("INSERT INTO marong.app_devices(install_id, friend_id, fid, notifications, app_version, ring_channel, "
             "full_screen) VALUES (%s, 2, %s, 'granted', '0.2.0', 'enabled', 'granted')", (INSTALL, FID))


async def tool_checks(db, store, settings):
    names = lambda tools: {t["name"]: t for t in tools}  # noqa: E731
    ok("call" not in names(schedule_tools())["schedule_add"]["input_schema"]["properties"]
       and "call" in names(schedule_tools(True))["schedule_add"]["input_schema"]["properties"],
       "the call field only with MARONG_APP_RING=1")
    ok(CALL_GUIDE not in schedule_guide() and schedule_guide(True).endswith(CALL_GUIDE), "and its guide lines")
    now = datetime.now(TZ)
    at = (now + timedelta(hours=2)).replace(microsecond=0).isoformat()
    ok("언제 전화할지 시각이 필요해" in check_add({"title": "면접 전화", "event_at": at, "call": True}, TZ, now, True),
       "a call needs remind_at")
    ok(check_add({"title": "면접", "remind_at": at, "call": True}, TZ, now).action == "remind",
       "without the ring setting call is ignored")
    out, action = await run_tool(store, "schedule_add", {"title": "밤 전화", "remind_at": at, "call": True,
                                                         "say": "오늘 면접 어땠는지 물어보기"},
                                 friend_id=2, room_key=HK_ROOM, source="discord", source_message_id=None, tz=TZ,
                                 ring=True)
    ok(action["result"] == "ok" and "📞 전화" in out and "그때 마롱이가 전화를 걸어" in out, out)
    ok(db.admin("SELECT action FROM marong.schedules WHERE id = %s", (action["id"],))[0][0] == "call", "saved as call")
    out, action = await run_tool(store, "schedule_add", {"title": "아침 깨우기", "remind_at": at, "call": True,
                                                         "repeat": "daily"},
                                 friend_id=2, room_key=HK_ROOM, source="discord", source_message_id=None, tz=TZ,
                                 ring=True)
    ok(action["result"] == "ok" and "매일" in out and "📞 전화" in out, out)
    out, action = await run_tool(store, "schedule_add", {"title": "전화", "remind_at": at, "call": True},
                                 friend_id=1, room_key=None, source="discord", source_message_id=None, tz=TZ,
                                 ring=True)
    ok(out == CALL_UNAVAILABLE and action == {"tool": "schedule_add", "result": "error", "why": "call_unavailable"},
       "a friend without calls")
    ok(not db.admin("SELECT 1 FROM marong.schedules WHERE friend_id = 1"), "nothing saved for them")

    for ring in (False, True):
        llm = ScriptedLLM(lambda body: message([text("응!")]))
        agent = DiscordAgent(settings, store, FakeEmbeddings(), llm)
        agent.ring = ring
        client = Client(agent, store)
        await client.on_message(event(client, HK, DM_HK, 3000 + ring, "안녕"))
        adds = [t for b in llm.bodies for t in b.get("tools", []) if t.get("name") == "schedule_add"]
        ok(adds and all(("call" in t["input_schema"]["properties"]) == ring for t in adds),
           f"the model sees call only when on ({ring})")
        prompt = json.dumps([[b.get("system"), b.get("messages")] for b in llm.bodies], ensure_ascii=False)
        ok((CALL_GUIDE.strip().splitlines()[0][2:20] in prompt) == ring, f"and the guide ({ring})")
    db.admin("UPDATE marong.schedules SET status = 'canceled' WHERE friend_id = 2")
    print("PASS TC-137 call promises: the call field and guide only when on, a time is needed, friends without calls, "
          "repeats")


def promise(db, title, late="1 minute", say=None, action="call"):
    return db.admin("INSERT INTO marong.schedules(friend_id, room_key, title, remind_at, say, action) "
                    "VALUES (2, %s, %s, now() - %s::interval, %s, %s) RETURNING id",
                    (HK_ROOM, title, late, say, action))[0][0]


def schedule(db, sid):
    return db.admin("SELECT status, failures, claimed_until > now() + interval '50 seconds' FROM marong.schedules "
                    "WHERE id = %s", (sid,))[0]


def rings(db, sid):
    return db.admin("SELECT id::text, via, status, devices, round(extract(epoch FROM answer_until - created_at)) "
                    "FROM marong.app_rings WHERE schedule_id = %s ORDER BY created_at", (sid,))


def clear_rings(db):
    """A fresh start for the next case. Answered rings stay (the record sheet joins calls to them), only older."""
    db.admin("DELETE FROM marong.app_rings WHERE status <> 'answered'")
    db.admin("UPDATE marong.app_rings SET created_at = now() - interval '1 day' WHERE status = 'answered'")


async def ring_checks(db, store, settings, logs):
    llm = ScriptedLLM(lambda body: message([text("응!")]))
    agent = DiscordAgent(settings, store, FakeEmbeddings(), llm)
    client = Client(agent, store)
    channel = client.channels[DM_HK]
    sender = FakeFCM()
    push = AppPush(store, sender, ring_enabled=True)
    reminders = DiscordReminders(settings, store, agent, client, app=push, origin=ORIGIN, rng=lambda: 0.5)

    sid = promise(db, "늦은 약속", "4 hours")
    ok(await reminders.step() == 0 and schedule(db, sid)[0] == "missed" and not rings(db, sid), "① 3h late: missed")

    sid = promise(db, "조금 늦은 약속", "6 minutes")
    before = len(sender.sent)
    ok(await reminders.step() == 1 and not rings(db, sid), "② 5 min late: no ring")
    note = sender.sent[before:]
    ok(len(note) == 1 and note[0]["data"] == {"kind": "missed_call", "open": "/"}
       and note[0]["android"]["notification"]["channel_id"] == TALK
       and note[0]["notification"]["body"] == " ".join(RING_LATE_TEXT.split())[:120], note)

    db.admin("UPDATE call.callers SET enabled = false WHERE friend_id = 2")
    sid = promise(db, "통화 꺼진 약속", say="물 마셔!")
    before = len(sender.sent)
    ok(await reminders.step() == 1 and not rings(db, sid), "③ calls off: an ordinary reminder")
    ok(sender.sent[before]["data"]["kind"] == "reminder"
       and sender.sent[before]["android"]["notification"]["channel_id"] == REMINDER
       and sender.sent[before]["notification"]["body"] == "물 마셔!", sender.sent[before])
    db.admin("UPDATE call.callers SET enabled = true WHERE friend_id = 2")

    call = db.admin("INSERT INTO call.calls(caller_id, client_id, prompt_version, voice) SELECT id, gen_random_uuid(), "
                    "'v', 'Aoede' FROM call.callers WHERE friend_id = 2 RETURNING id::text")[0][0]
    sid = promise(db, "통화 중 약속")
    ok(await reminders.step() == 0 and [r[2] for r in rings(db, sid)] == ["busy"] and schedule(db, sid)[0] == "done",
       "④ already in a call: busy")
    db.admin("UPDATE call.calls SET status = 'ended', ended_at = now(), end_reason = 'hangup', "
             "organize_status = 'skipped' WHERE id = %s", (call,))

    sid = promise(db, "벨 약속", say="오늘 면접 어땠는지 물어보기")
    before = len(sender.sent)
    sent = len(channel.sent)
    ok(await reminders.step() == 1, "⑥ a phone rings")
    ring = rings(db, sid)
    ok(len(ring) == 1 and ring[0][1:] == ("app", "ringing", 1, 300), ring)
    bell = sender.sent[before:]
    ok(len(bell) == 1 and bell[0] == {"fid": FID, "data": {"kind": "ring", "ringId": ring[0][0], "v": "1"},
                                      "android": {"priority": "HIGH", "ttl": "45s"}}, bell)
    ok("벨 약속" not in json.dumps(bell, ensure_ascii=False) and "면접" not in json.dumps(bell, ensure_ascii=False),
       "TC-139 the ring carries no title, words or time")
    ok(schedule(db, sid)[0] == "done" and len(channel.sent) == sent, "the promise is done, Discord untouched")

    sid = promise(db, "10분 안 약속")
    ok(await reminders.step() == 0 and [r[2] for r in rings(db, sid)] == ["skipped"], "⑤ a ring in 10 min: skipped")
    clear_rings(db)

    sid = promise(db, "모두 실패 약속", say="약속한 시간이다!")
    sender.answers.append("failed")
    ok(await reminders.step() == 1, "⑦ every phone failed: Discord")
    ring = rings(db, sid)
    ok(ring[0][1:3] == ("discord", "ringing") and ring[0][4] == 600, ring)
    ok(channel.sent[-1] == f"약속한 시간이다!\n여기서 받아 줘: {ORIGIN}/?ring={ring[0][0]}", channel.sent[-1])
    saved = db.admin("SELECT meta FROM marong.messages WHERE room_key = %s ORDER BY id DESC LIMIT 1", (HK_ROOM,))[0][0]
    ok(saved["ring"] == ring[0][0] and saved["transport"] == "discord" and saved["delivered"] is True, saved)
    clear_rings(db)

    db.admin("UPDATE marong.app_devices SET ring_channel = 'disabled' WHERE install_id = %s", (INSTALL,))
    sid = promise(db, "기기 없는 약속")
    before = len(sender.sent)
    ok(await reminders.step() == 1 and rings(db, sid)[0][1:3] == ("discord", "ringing") and len(sender.sent) == before
       and channel.sent[-1].startswith(RING_DISCORD_TEXT + "\n여기서 받아 줘: "), "no phone can ring: Discord")
    clear_rings(db)

    channel.fail = True
    sid = promise(db, "디스코드 실패 약속")
    ok(await reminders.step() == 0 and rings(db, sid)[0][2] == "failed" and schedule(db, sid)[:2] == ("active", 1),
       "the DM failed too: failed, tried again in a minute")
    channel.fail = False
    db.admin("UPDATE marong.schedules SET claimed_until = NULL WHERE id = %s", (sid,))
    ok(await reminders.step() == 1 and [r[2] for r in rings(db, sid)] == ["failed", "ringing"],
       "a failed ring does not count for the 10-minute rule")
    clear_rings(db)

    client.available = False
    sid = promise(db, "디스코드 끊김 약속")
    ok(await reminders.step() == 0 and not rings(db, sid) and schedule(db, sid) == ("active", 0, True),
       "no phone and Discord away: later, without a failure")
    client.available = True
    db.admin("UPDATE marong.schedules SET claimed_until = NULL WHERE id = %s", (sid,))
    ok(await reminders.step() == 1 and rings(db, sid)[0][1] == "discord", "then the invitation")
    clear_rings(db)
    db.admin("UPDATE marong.app_devices SET ring_channel = 'enabled' WHERE install_id = %s", (INSTALL,))

    first, second = promise(db, "같은 때 하나"), promise(db, "같은 때 둘")
    before = len(sender.sent)
    ok(await reminders.step() == 1 and len(sender.sent) == before + 1, "TC-140 two at the same time: one ring")
    ok(sorted(r[2] for r in rings(db, first) + rings(db, second)) == ["ringing", "skipped"], "the other skipped")
    clear_rings(db)

    push.ring_enabled = False
    sid = promise(db, "링 꺼짐 약속", say="일어나!")
    before = len(sender.sent)
    ok(await reminders.step() == 1 and not rings(db, sid) and sender.sent[before]["data"]["kind"] == "reminder",
       "MARONG_APP_RING off: a call promise is an ordinary reminder")
    push.ring_enabled = True
    print("PASS TC-138/139 call promises ①–⑦, every phone failing, no phone, DM failure and retry, Discord away, "
          "two at once, ring off; the ring message carries nothing of the promise")
    return reminders, sender, client


async def permission_checks(db):
    ring = db.admin("INSERT INTO marong.app_rings(schedule_id, friend_id, caller_id, via, title, answer_until) "
                    "SELECT s.id, 2, c.id, 'app', 'x', now() + interval '5 minutes' FROM marong.schedules s, "
                    "call.callers c WHERE c.friend_id = 2 ORDER BY s.id LIMIT 1 RETURNING id::text")[0][0]
    try:
        db.admin("INSERT INTO marong.app_rings(schedule_id, friend_id, caller_id, via, title, answer_until) "
                 "SELECT s.id, 2, c.id, 'app', 'y', now() + interval '5 minutes' FROM marong.schedules s, "
                 "call.callers c WHERE c.friend_id = 2 ORDER BY s.id LIMIT 1")
        ok(False, "two ringing rows for one friend")
    except psycopg.errors.UniqueViolation:
        ok(True, "one ringing row per friend")
    bot = db.app_url
    call = db.admin_url.replace("postgres:@", "marong_call@", 1)
    for url, sql, why in ((bot, "DELETE FROM marong.app_rings", "the bot cannot delete rings"),
                          (call, "DELETE FROM marong.app_rings", "the call server cannot delete rings"),
                          (call, f"UPDATE marong.app_rings SET title = 'z' WHERE id = '{ring}'",
                           "the call server cannot change the promise"),
                          (call, "UPDATE marong.app_rings SET devices = 3", "nor the devices"),
                          (call, "INSERT INTO marong.app_rings(schedule_id, friend_id, caller_id, via, title, "
                                 "answer_until) VALUES (1, 2, 1, 'app', 'z', now())", "nor add rings"),
                          (call, "SELECT friend_id FROM marong.app_rings", "nor read who the friend is")):
        with psycopg.connect(url, autocommit=True) as conn:
            try:
                conn.execute(sql)
                ok(False, why)
            except psycopg.errors.InsufficientPrivilege:
                ok(True, why)
    with psycopg.connect(call, autocommit=True) as conn:
        n = conn.execute("UPDATE marong.app_rings SET status = 'ringing' WHERE id = %s RETURNING id", (ring,)).rowcount
        ok(n == 1, "the call server may change the status")
    clear_rings(db)
    print("PASS TC-140 unique ringing row, no DELETE for anyone, the call server changes only status/answer columns")


async def claim_checks(db, reminders, sender):
    call_url = db.admin_url.replace("postgres:@", "marong_call@", 1)
    calls = MemoryStore(call_url)
    await calls.pool.open(wait=True)
    caller = db.admin("SELECT id FROM call.callers WHERE friend_id = 2")[0][0]
    p = Principal(caller, 2, "현경")
    other = Principal(caller + 100, 1, "동희")

    def new_call():
        return db.admin("INSERT INTO call.calls(caller_id, client_id, prompt_version, voice) VALUES "
                        "(%s, gen_random_uuid(), 'v', 'Aoede') RETURNING id::text", (caller,))[0][0]

    def end(call_id):
        db.admin("UPDATE call.calls SET status = 'ended', ended_at = now(), end_reason = 'hangup', "
                 "organize_status = 'skipped' WHERE id = %s", (call_id,))

    try:
        sid = promise(db, "받을 약속", say="잘 잤어?")
        await reminders.step()
        ring = rings(db, sid)[0][0]
        call_a = new_call()
        ok(await calls.claim_ring(other, call_a, ring) is None, "another caller cannot take it")
        got = await calls.claim_ring(p, call_a, ring)
        ok(got and got["fresh"] and str(got["id"]) == ring and got["title"] == "받을 약속" and got["say"] == "잘 잤어?",
           got)
        segment = await calls.start_segment(p, call_a, str(uuid.uuid4()), "gemini-fixture")
        turn = await calls.save_turn(p, call_a, segment, "answer", "assistant", "약속한 전화야! 잘 잤어?", True, False)
        again = await calls.claim_ring(p, call_a, ring)
        ok(again and again["fresh"] is False and str(again["id"]) == ring, "the same call reconnecting gets it again")
        end(call_a)
        call_b = new_call()
        ok(await calls.claim_ring(p, call_b, ring) is None, "an answered ring is not answered twice")
        ok(db.admin("SELECT status, call_id::text FROM marong.app_rings WHERE id = %s", (ring,))[0]
           == ("answered", call_a), "answered by the first call")
        end(call_b)
        clear_rings(db)

        sid = promise(db, "링 id 없는 약속")
        await reminders.step()
        ring = rings(db, sid)[0][0]
        call_c = new_call()
        got = await calls.claim_ring(p, call_c)
        ok(got and got["fresh"] and str(got["id"]) == ring, "without a ring id: the caller's latest ringing row")
        end(call_c)
        db.admin("UPDATE marong.app_rings SET answer_until = now() - interval '1 second' WHERE id = %s", (ring,))
        before = len(sender.sent)
        ok(await reminders.sweep_rings() == 0 and len(sender.sent) == before
           and db.admin("SELECT status FROM marong.app_rings WHERE id = %s", (ring,))[0][0] == "answered",
           "TC-144 a call in the window answered it: never missed, no note")
        clear_rings(db)

        outcomes = set()
        for i, edge in enumerate((1, 2, 3, 5, 8, 12)):  # TC-144 answer and miss racing at the window's edge: one wins
            sid = promise(db, f"경합 약속 {i}")
            await reminders.step()
            ring = rings(db, sid)[0][0]
            call_e = new_call()
            before = len(sender.sent)
            db.admin("UPDATE marong.app_rings SET answer_until = clock_timestamp() + %s * interval '1 millisecond' "
                     "WHERE id = %s", (edge, ring))
            got, noted = await asyncio.gather(calls.claim_ring(p, call_e, ring), reminders.sweep_rings())
            status = db.admin("SELECT status FROM marong.app_rings WHERE id = %s", (ring,))[0][0]
            ok((status, bool(got), noted, len(sender.sent) - before) in {("answered", True, 0, 0),
                                                                          ("missed", False, 1, 1)},
               (status, got, noted))
            outcomes.add(status)
            end(call_e)
            clear_rings(db)

        sid = promise(db, "시간 지난 약속")
        await reminders.step()
        ring = rings(db, sid)[0][0]
        db.admin("UPDATE marong.app_rings SET answer_until = now() - interval '1 second' WHERE id = %s", (ring,))
        call_d = new_call()
        ok(await calls.claim_ring(p, call_d, ring) is None, "after the answer window it is an ordinary call")
        end(call_d)
        print("PASS TC-141 claim_ring as the call server: ring id or latest, other caller, once, reconnect, window; "
              f"TC-144 answered rings never missed, answer/miss race has one winner ({', '.join(sorted(outcomes))})")
        return ring, turn
    finally:
        await calls.pool.close()


async def missed_checks(db, reminders, sender, client, logs, expired):
    before = len(sender.sent)
    ok(await reminders.sweep_rings() == 1, "the expired ring becomes missed with one note")
    ok(db.admin("SELECT status, resolved_at IS NOT NULL FROM marong.app_rings WHERE id = %s", (expired,))[0]
       == ("missed", True), "missed")
    note = sender.sent[before:]
    ok(len(note) == 1 and note[0]["data"] == {"kind": "missed_call", "open": "/"} and note[0]["android"]["ttl"] == "3600s"
       and note[0]["notification"]["body"] == MISSED_LINES[1], note)
    saved = db.admin("SELECT content, meta FROM marong.messages WHERE meta->>'ring' = %s", (expired,))[0]
    ok(saved[0] == MISSED_LINES[1] and saved[1]["missed"] is True and saved[1]["transport"] == "app", saved)
    ok(await reminders.sweep_rings() == 0 and len(sender.sent) == before + 1, "only once")
    clear_rings(db)

    sid = promise(db, "디스코드로 간 약속")
    sender.answers.append("failed")
    await reminders.step()
    ring = rings(db, sid)[0][0]
    db.admin("UPDATE marong.app_rings SET answer_until = now() - interval '1 second' WHERE id = %s", (ring,))
    sent, before = len(client.channels[DM_HK].sent), len(sender.sent)
    ok(await reminders.sweep_rings() == 0 and rings(db, sid)[0][2] == "missed"
       and len(client.channels[DM_HK].sent) == sent and len(sender.sent) == before,
       "the Discord invitation already said it: no note")
    clear_rings(db)

    sid = promise(db, "앱 실패 한마디 약속")
    await reminders.step()
    ring = rings(db, sid)[0][0]
    db.admin("UPDATE marong.app_rings SET answer_until = now() - interval '1 second' WHERE id = %s", (ring,))
    sender.answers.append("failed")
    sent = len(client.channels[DM_HK].sent)
    ok(await reminders.sweep_rings() == 1 and client.channels[DM_HK].sent[sent:] == [MISSED_LINES[1]],
       "the app note failed: the Discord DM gets it (D18)")
    clear_rings(db)

    secrets = ["받을 약속", "잘 잤어?", "시간 지난 약속", "벨 약속", expired, ring, FID, INSTALL]
    leaked = [line[:160] for line in logs.getvalue().splitlines() if any(s in line for s in secrets)]
    ok(not leaked, f"no ring id, title, words, FID or install id in the logs: {leaked}")
    ok("ring_sent devices=1" in logs.getvalue() and "ring_missed via=app" in logs.getvalue(), "result names logged")
    print("PASS TC-144 missed rings: one note by the D18 path, none after a Discord invitation, no secrets in logs")


def report_checks(db, turn):
    """SPEC-126/142 markers in the record sheet (tools/report.py), read as the bot's own account."""
    from psycopg.rows import dict_row
    from tools.report import build
    db.admin("INSERT INTO marong.messages(room_key, user_key, role, content, kakao_id, meta) VALUES "
             "(%s, %s, 'user', '앱에서 한 말', %s, '{\"transport\": \"app\"}')",
             (HK_ROOM, f"discord-user:{HK}", f"app:{uuid.uuid4()}"))
    now = datetime.now(TZ)
    with psycopg.connect(db.app_url, row_factory=dict_row) as c:
        c.read_only = True
        tabs, _ = build(c, now - timedelta(hours=1), now + timedelta(minutes=1), TZ, now=now, vectors=False)
    talk = next(t for t in tabs if t["name"] == "대화")
    kinds = {row[0]: row[4] for row in talk["rows"]}
    ok(kinds[f"V{turn}"] == "통화(응답)(마롱이가 걺)", kinds.get(f"V{turn}"))
    expected = {}
    for mid, meta in db.admin("SELECT id, meta FROM marong.messages WHERE room_key = %s AND meta IS NOT NULL",
                              (HK_ROOM,)):
        app = "(앱)" if meta.get("transport") == "app" else ""
        if meta.get("missed"):
            expected[mid] = "알림(못 받은 전화)" + app
        elif meta.get("ring") == "late":
            expected[mid] = "알림(늦은 전화 약속)" + app
        elif meta.get("reminder") and meta.get("ring"):
            expected[mid] = "알림(전화 약속)" + app
        elif meta.get("reminder"):
            expected[mid] = "알림(부탁한 일정)" + app
    app_user = db.admin("SELECT id FROM marong.messages WHERE content = '앱에서 한 말'")[0][0]
    expected[app_user] = "친구 말(앱)"
    seen = {kinds.get(mid) for mid in expected}
    ok(all(kinds.get(mid) == want for mid, want in expected.items()),
       [(mid, kinds.get(mid), want) for mid, want in expected.items() if kinds.get(mid) != want])
    ok({"알림(못 받은 전화)(앱)", "알림(못 받은 전화)", "알림(늦은 전화 약속)(앱)", "알림(전화 약속)",
        "알림(부탁한 일정)(앱)", "친구 말(앱)"} <= seen, seen)
    guide = " ".join(row[0] for row in next(t for t in tabs if t["name"] == "읽는 법")["rows"])
    ok("'(앱)'" in guide and "'(마롱이가 걺)'" in guide, "the sheet explains the markers")
    print("PASS SPEC-126/142 record sheet: '(앱)' on app messages and notes, call promise notes by kind, "
          "'(마롱이가 걺)' on the call that answered a ring")


async def main(db):
    logs = io.StringIO()
    capture = logging.StreamHandler(logs)
    capture.setFormatter(logging.Formatter("%(name)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(capture)
    root.setLevel(logging.INFO)
    settings = load_settings()
    store = DiscordStore(db.app_url, call_bridge=True)
    await store.open(wait=True)
    try:
        await tool_checks(db, store, settings)
        reminders, sender, client = await ring_checks(db, store, settings, logs)
        await permission_checks(db)
        expired, turn = await claim_checks(db, reminders, sender)
        await missed_checks(db, reminders, sender, client, logs, expired)
        report_checks(db, turn)
    finally:
        root.removeHandler(capture)
        await store.close()


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(main(db))
    finally:
        db.close()
    print(f"OK {CHECKS} checks")
