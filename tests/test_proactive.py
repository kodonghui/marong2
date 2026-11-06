"""선톡 시험: 진짜 Postgres + 가짜 Claude + 가짜 카카오 전송 API(/v1/bot/send_message).
칸 나누기·방마다 일정·대상 고르기·시간·하루 상한·확률·여러 말 연달아·전송 형식·저장·끄기·횟수 도구·실패 기록·
잠금 뒤 다시 확인·시험 명령(run.py --proactive)·일정 명령(tools/admin.py schedule)·카카오가 1:1 을 막은 뒤
(2026-11-05~) 키 바꿔 보내기·관리자가 켠 단체방 선톡·단체방을 1:1 방에 묶기(admin merge).
실행(윈도우): .venv\\Scripts\\python tests\\test_proactive.py   (리눅스·맥: .venv/bin/python tests/test_proactive.py)"""
import asyncio
import hashlib
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import httpx  # noqa: E402

from fakes import FakeAnthropic, FakeEmbeddings, ScriptedLLM, message, text, tool_use  # noqa: E402
from marong.agent import LINKED_GUARD, PROACTIVE_GROUP_GUIDE, PROACTIVE_GUIDE, PROACTIVE_TRIGGER  # noqa: E402
from pg import TestDB  # noqa: E402

CHECKS = 0
SENT: list[dict] = []
FAIL = {"code": None, "after": 0}  # 다음 전송들을 이 카카오 오류 코드로 실패시킴(after 번은 먼저 성공)
# 가짜 카카오가 키를 받는 방식: ok(어느 키든 감) | blocked(2026-11-05 14:30 KST 뒤: 1:1 방 키 -880, 사람 키 -876, 단체방은 감)
# | user_only(그 전: 1:1 은 사람 키로만 감) | zero(200 인데 sendCount 0·errorCount 1)
KAKAO = {"mode": "ok"}
KAKAO_MSG = {-876: "botGroupKey만 입력되어야 합니다.", -877: "채널 친구가 아닙니다.", -880: "봇이 초대되지 않은 방입니다."}
MODE = {"proactive": "ok"}  # 선톡 말 만들기: ok | multi(말 3개) | fail | refuse
LOGS: list[str] = []


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def situation(body) -> str:
    return body["system"][-1]["text"]


def respond(body):
    """가짜 Claude: 선톡 만들기, 선톡 끄기·켜기·횟수 도구, 보통 답."""
    last = body["messages"][-1]
    if last["role"] == "user" and last["content"] == PROACTIVE_TRIGGER:
        if MODE["proactive"] == "fail":
            return RuntimeError("boom")
        if MODE["proactive"] == "refuse":
            return message([], "refusal", stop_details={"type": "refusal", "category": "general_harms",
                                                        "explanation": None})
        sit = situation(body)
        name = sit.split("- 친구: ")[1].splitlines()[0] if "- 친구: " in sit else "안녕"
        if MODE["proactive"] == "multi":
            return message([text(f"{name} 첫 말\n\n두 번째 말 🌰\n\n\n세 번째 말?")])
        return message([text(f"{name} 선톡 {len(SENT) + 1} 🌰")])
    if isinstance(last["content"], list):  # 도구 결과를 받은 뒤
        return message([text("알겠어 👌")])
    said = last["content"].splitlines()[-1]
    if "선톡 그만" in said:
        return message([tool_use("ask_owner", {"kind": "proactive_off"})], "tool_use")
    if "선톡 다시" in said:
        return message([tool_use("ask_owner", {"kind": "proactive_on"})], "tool_use")
    if "선톡 자주" in said:
        return message([tool_use("ask_owner", {"kind": "proactive_more", "per_day": 5})], "tool_use")
    if "선톡 엄청" in said:
        return message([tool_use("ask_owner", {"kind": "proactive_more", "per_day": 60})], "tool_use")
    return message([text(f"응답:{said}")])


class FakeKakao(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        SENT.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        fail = FAIL["code"]
        if fail and FAIL["after"] > 0:
            FAIL["after"] -= 1
            fail = None
        mode, one = KAKAO["mode"], str(body.get("botGroupKey", "")).startswith("p")  # 시험의 1:1 방 키는 p…
        if not fail and mode in ("blocked", "user_only") and one:
            fail = -880
        elif not fail and mode == "blocked" and "botUserKey" in body:
            fail = -876
        if fail:
            code, resp = 400, {"code": fail, "msg": KAKAO_MSG.get(fail, "오류")}
        elif mode == "zero":
            code, resp = 200, {"totalCount": 1, "sendCount": 0, "errorCount": 1}
        else:
            code, resp = 200, {"totalCount": 1, "sendCount": 1, "errorCount": 0}
        data = json.dumps(resp, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class Collect(logging.Handler):
    def emit(self, record):
        LOGS.append(record.getMessage())


def said_texts(sent: list[dict]) -> list[str]:
    return [x["body"]["skillResponse"]["template"]["outputs"][0]["simpleText"]["text"] for x in sent]


async def main():
    db = TestDB()
    kakao = ThreadingHTTPServer(("127.0.0.1", 0), FakeKakao)
    threading.Thread(target=kakao.serve_forever, daemon=True).start()
    claude = FakeAnthropic(lambda key, body: (200, respond(body)))
    tmp = Path(tempfile.mkdtemp())
    os.environ.update({
        "BOT_TOKEN": "tok-secret", "KAKAO_API_URL": f"http://127.0.0.1:{kakao.server_address[1]}",
        "ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": claude.url, "DATABASE_URL": db.app_url,
        "PROMPT_PATH": str(ROOT / "prompt.md"), "KNOWLEDGE_DIR": str(tmp / "knowledge"), "EMBED_MODEL": "",
        "RECENT_TURNS": "3", "SUMMARY_TURNS": "10", "LLM_TIMEOUT_SECONDS": "30", "PROACTIVE": "on",
    })
    from marong.agent import Agent, Incoming
    from marong.config import load_settings
    from marong.kakao import send_message, skill_text
    from marong.proactive import Proactive, parts, schedule, slot
    from marong.store import Store

    # ── 설정 ──
    s = load_settings()
    ok(s.proactive and s.proactive_per_day == 2 and s.proactive_hours == (12, 21) and s.proactive_daily_max == 60,
       "선톡 기본값: 친구마다 하루 2번, 12~21시, 하루 60번")
    ok(s.problems() == [] and replace(s, proactive_hours=(21, 12)).problems()
       and replace(s, proactive_per_day=0).problems(), "선톡 설정 오류를 알려 줌")
    del os.environ["PROACTIVE"]
    ok(load_settings().proactive is False, "PROACTIVE 가 없으면 꺼짐")
    os.environ["PROACTIVE"] = "on"

    # ── 칸: 일정 시간을 하루 선톡 수만큼 똑같이 나눔 ──
    kst = ZoneInfo("Asia/Seoul")
    day = datetime(2026, 10, 26, tzinfo=kst)

    def at(hour, minute=0):
        return day.replace(hour=hour, minute=minute)

    ok(slot(at(11, 59), (12, 21), 2) is None and slot(at(21), (12, 21), 2) is None, "12~21시 밖은 칸 없음")
    ok(slot(at(12), (12, 21), 2) == slot(at(16, 29), (12, 21), 2) == (at(12), at(16, 30))
       and slot(at(16, 30), (12, 21), 2) == slot(at(20, 59), (12, 21), 2) == (at(16, 30), at(21)),
       "두 칸: 12:00~16:30, 16:30~21:00")
    ok(slot(at(14), (12, 21), 3) == (at(12), at(15)) and slot(at(20, 59), (12, 21), 7)[1] == at(21)
       and slot(at(23), (0, 24), 2) == (at(12), day + timedelta(days=1)), "칸 수가 달라도, 24시까지도")
    ok(slot(at(6, 59), (7, 24), 12) is None and slot(at(7, 30), (7, 24), 12) == (at(7), at(8, 25))
       and slot(at(23, 59), (7, 24), 12) == (at(22, 35), day + timedelta(days=1)), "7~24시 12칸: 85분씩")

    # ── 방마다 일정: 방에 정한 값이 없거나 틀리면 .env 값 ──
    def plan_of(per_day=None, start=None, end=None):
        return schedule({"per_day": per_day, "start_hour": start, "end_hour": end}, s)

    ok(plan_of() == ((12, 21), 2) and plan_of(12, 7, 24) == ((7, 24), 12) and plan_of(5) == ((12, 21), 5)
       and plan_of(3, None, 23) == ((12, 23), 3), "방 일정, 빈 값은 기본값")
    ok(plan_of(4, 22) == ((12, 21), 4) and plan_of(4, 9, 9) == ((12, 21), 4), "시작이 끝보다 늦으면 기본 시간")

    # ── 여러 말: 빈 줄로 나눈 덩어리, 많아야 4개 ──
    ok(parts("야 뭐해") == ["야 뭐해"] and parts("야 뭐해\n\n 나 군밤 샀어 \n \n\n너는?") == ["야 뭐해", "나 군밤 샀어", "너는?"]
       and parts("한 줄\n바로 다음 줄") == ["한 줄\n바로 다음 줄"], "빈 줄로만 나눔")
    ok(parts("1\n\n2\n\n3\n\n4\n\n5") == ["1", "2", "3", "4\n5"], "4개가 넘으면 남은 말을 마지막에 모음")

    store = Store(s.database_url)
    await store.open(wait=True)
    llm = ScriptedLLM(respond)
    agent = Agent(s, store, FakeEmbeddings(), llm)
    planner = Proactive(s, store, agent, None)  # 보낼지 정하기만(plan 은 http 를 안 씀)
    replies: list[str] = []

    async def send(t):
        replies.append(t)
        return True

    async def say(room, user, t, channel=True, kid=None, ag=None):
        return await (ag or agent).handle(Incoming(room, user, t, is_channel=channel, kakao_id=kid), send)

    def age(room, days):
        db.admin("UPDATE marong.messages SET created_at = created_at - make_interval(days => %s) "
                 "WHERE room_key = %s", (days, room))

    def shift(room, minutes):
        db.admin("UPDATE marong.messages SET created_at = created_at - make_interval(mins => %s) "
                 "WHERE room_key = %s", (minutes, room))

    def tick(minutes):  # 시계를 앞으로: 모든 말을 그만큼 예전 일로(선톡의 시각 조건은 DB 시계에서 거꾸로 잼)
        db.admin("UPDATE marong.messages SET created_at = created_at - make_interval(mins => %s)", (minutes,))

    def last_message(room):
        return db.admin("SELECT content, meta FROM marong.messages WHERE room_key = %s ORDER BY id DESC LIMIT 1",
                        (room,))[0]

    async def due_rooms(now):
        return [r["room_key"] for r in await store.proactive_rooms() if planner.plan(r, now)]

    # 방: p1 동희 1:1(4일 조용, 메모·요약 있음), p2 1:1(방금 말함), g1 단체방(4일), terminal(카카오 id 없음, 4일),
    #     p3 1:1(5일, 선톡 끔), p4 1:1(6일, 이름 모름)
    await say("p1", "u1", "나 다음 주 토익 시험 봐", kid="a1")
    await store.set_name("u1", "동희")
    await say("p2", "u2", "안녕", kid="b1")
    await say("g1", "u1g", "다들 안녕", channel=False, kid="c1")
    await say("terminal", "terminal", "터미널에서 한 말")
    await say("p3", "u3", "안녕", kid="d1")
    db.admin("UPDATE marong.rooms SET proactive = false WHERE room_key = 'p3'")  # 관리자가 끈 방
    await say("p4", "u4", "심심해", kid="e1")
    ids = [r[0] for r in db.admin("SELECT id FROM marong.messages WHERE room_key = 'p1' ORDER BY id")]
    sid = await store.add_summary("p1", ids[0], ids[-1], "동희가 다음 주 토익 시험을 본다고 함",
                                  {"u1": "- 토익 시험 준비 중"}, {})
    nid = db.admin("SELECT id FROM marong.notes WHERE room_key = 'p1'")[0][0]
    p4_ids = [r[0] for r in db.admin("SELECT id FROM marong.messages WHERE room_key = 'p4' ORDER BY id")]
    for room, days in (("p1", 4), ("g1", 4), ("terminal", 4), ("p3", 5), ("p4", 6)):
        age(room, days)

    today = datetime.now(kst).replace(hour=0, minute=0, second=0, microsecond=0)
    t = today.replace(hour=13)

    rooms = await store.proactive_rooms()
    ok([r["room_key"] for r in rooms] == ["p4", "p1", "p2"], f"선톡 켠 1:1 방만, 오래 조용한 친구부터: {rooms}")
    p1 = rooms[1]
    ok(rooms[0]["name"] is None and p1["name"] == "동희" and p1["user_key"] == "u1" and p1["per_day"] is None
       and p1["start_hour"] is None and p1["sent_ago"] is None and p1["failures"] == 0
       and p1["quiet_for"] > timedelta(days=4), rooms)
    ok([r["room_key"] for r in await store.proactive_rooms("p1")] == ["p1"]
       and await store.proactive_rooms("p3") == [] and await store.proactive_rooms("g1") == [],
       "방 하나만 다시 확인. 선톡 끈 방·단체방은 없음")
    ok(planner.plan(p1, t) == (today.replace(hour=12), 1 / 210), "13:00 은 12:00~16:30 칸, 남은 확인 210번 → 1/210")
    ok(await due_rooms(t) == ["p4", "p1"], "1시간 넘게 조용한 친구만")
    shift("p2", 50)
    ok("p2" not in await due_rooms(t), "1시간 안에 말한 친구는 대상 아님(이야기 중일 수 있음)")
    shift("p2", 20)
    ok("p2" in await due_rooms(t), "1시간 넘게 조용하면 대상")
    shift("p2", -70)

    async with httpx.AsyncClient() as http:
        pro = Proactive(s, store, agent, http, rng=lambda: 0.0)

        # ── 보내기 ──
        calls = len(llm.bodies)
        ok(await pro.step(t.replace(hour=11)) == 0 and await pro.step(t.replace(hour=21)) == 0
           and not SENT and len(llm.bodies) == calls, "12~21시 밖에서는 보내지 않음")
        ok(await pro.step(t) == 2 and [x["body"]["botGroupKey"] for x in SENT] == ["p4", "p1"],
           "대상 친구 모두에게, 오래 조용한 친구부터")
        b = llm.bodies[-2]
        ok("tools" not in b and b["messages"] == [{"role": "user", "content": PROACTIVE_TRIGGER}]
           and b["output_config"] == {"effort": "xhigh"} and b["system"][0]["cache_control"] == {"type": "ephemeral"},
           "선톡은 도구 없이, 같은 말투 지시문(캐시)과 effort")
        sit = situation(b)
        ok(PROACTIVE_GUIDE.format(per_day=2) in sit and "이름 없이 말해" in sit and "# 최근 대화" in sit
           and "심심해" in sit and "친구가 마지막으로 말한 때" in sit, "이름 모르는 친구: 그 방 최근 대화를 보고 말 검")
        ok("토익" not in sit and "다들 안녕" not in sit, "다른 방 기억은 안 섞임")
        first = SENT[0]
        ok(first["path"] == "/v1/bot/send_message" and first["auth"] == "KakaoAK tok-secret", first)
        ok(first["body"]["botGroupKey"] == "p4" and "botUserKey" not in first["body"],
           "1:1 도 방 키(botGroupKey)로 먼저 보냄(키 하나만)")
        outputs = first["body"]["skillResponse"]["template"]["outputs"]
        ok(outputs == [{"simpleText": {"text": "안녕 선톡 1 🌰"}}] and first["body"]["skillResponse"]["version"] == "2.0",
           first)
        role, content, reply_to, meta = db.admin(
            "SELECT role, content, reply_to, meta FROM marong.messages WHERE room_key = 'p4' ORDER BY id DESC LIMIT 1")[0]
        ok(role == "assistant" and content == "안녕 선톡 1 🌰" and reply_to is None and meta["proactive"] is True
           and meta["delivered"] is True and meta["send_code"] is None and meta["send_key"] == "room"
           and meta["calls"] == 1 and meta["parts"] == [1, 1], meta)
        ok(meta["memory"] == {"recent": [p4_ids[0], p4_ids[-1]], "summaries": [], "notes": []},
           f"선톡에 넣은 기억(최근 대화 구간)도 기록: {meta['memory']}")
        sit = situation(llm.bodies[-1])
        ok("- 친구: 동희" in sit and "토익 시험 준비 중" in sit and "다음 주 토익 시험을 본다고" in sit,
           "그 방의 메모·요약을 보고 말 검")
        ok(last_message("p1")[1]["memory"] == {"recent": [ids[0], ids[-1]], "summaries": [sid], "notes": [nid]},
           "넣은 요약·메모 id 도 기록")
        ok(await pro.step(t) == 0 and len(SENT) == 2,
           "같은 칸에 다시 안 보냄. 방금 말한 친구·단체방·터미널·선톡 끈 방은 대상 아님")

        # ── 친구가 답하면 선톡이 앞 문맥 ──
        await say("p1", "u1", "시험 망했어 ㅠ", kid="a2")
        convo = json.dumps(llm.bodies[-1]["messages"], ensure_ascii=False)
        ok("동희 선톡 2 🌰" in convo and convo.index("동희 선톡 2") < convo.index("시험 망했어"), "선톡에 답하면 선톡이 앞 문맥")

        # ── 하루 두 칸: 칸마다 한 번, 답이 없어도 다음 칸에 또 ──
        tick(209)  # 16:29, 오후 칸 마지막 확인
        sure = Proactive(s, store, agent, http, rng=lambda: 0.99)
        ok(await sure.step(t.replace(hour=16, minute=29)) == 1 and SENT[-1]["body"]["botGroupKey"] == "p2",
           "같은 칸엔 한 번만(p4·p1). 그사이 조용해진 친구(p2)는 칸 마지막 확인이라 꼭 받음")
        tick(16)  # 16:45, 저녁 칸
        evening = t.replace(hour=16, minute=45)
        shy = Proactive(s, store, agent, http, rng=lambda: 0.2)
        ok(await shy.step(evening) == 0 and len(SENT) == 3, "칸에 남은 확인이 255번이면 1/255 확률: 이번엔 안 보냄")
        ok(await pro.step(evening) == 2 and [x["body"]["botGroupKey"] for x in SENT[-2:]] == ["p4", "p1"],
           "저녁 칸: 답이 없는 친구(p4)에게도 또. 오후 칸 끝에 받은 친구(p2)는 칸 반 길이(2시간 15분)가 지나야")
        tick(135)  # 19:00
        ok(await pro.step(t.replace(hour=19)) == 1 and SENT[-1]["body"]["botGroupKey"] == "p2"
           and await pro.step(t.replace(hour=19)) == 0, "칸 반 길이가 지나면 받고, 칸마다 한 번")

        # ── 하루 상한(모든 친구 합) ──
        tick(18 * 60)  # 다음 날 13:00
        capped = Proactive(replace(s, proactive_daily_max=1), store, agent, http, rng=lambda: 0.0)
        ok(await capped.step(t) == 1 and len(SENT) == 7 and await capped.step(t) == 0, "하루 상한(1번)에 닿으면 거기까지")

        # ── 전송 실패: 전달 안 됨으로 남기고 그 칸엔 다시 안 보냄. 친구가 말한 뒤로 두 번이면 쉼 ──
        FAIL["code"] = -877
        ok(await pro.step(t) == 2 and len(SENT) == 9, "전송 실패도 보낸 것으로 셈. 키 문제가 아닌 오류는 다른 키로 안 보냄")
        FAIL["code"] = None
        content, meta = last_message("p1")
        ok(meta["proactive"] is True and meta["delivered"] is False and meta["send_code"] == -877
           and meta["send_key"] == "room" and meta["parts"] == [0, 1], meta)
        ok(await pro.step(t) == 0 and len(SENT) == 9, "실패한 방에도 그 칸엔 다시 안 보냄")
        ok(all(r["content"] != content for r in await store.recent("p1", 20)), "전달 안 된 선톡은 다음 대화에서 뺌")
        tick(225)  # 16:45
        FAIL["code"] = -877
        ok(await pro.step(evening) == 3 and len(SENT) == 12, "실패한 방도 다음 칸엔 다시 해 봄")
        FAIL["code"] = None
        tick(20 * 60 + 15)  # 다음 날 13:00
        ok(await due_rooms(t) == ["p4"],
           "친구가 마지막으로 말한 뒤로 전달 실패가 두 번이면 친구가 다시 말할 때까지 쉼(차단 등). 한 번이면 계속")
        await say("p1", "u1", "나 왔어", kid="a3")
        shift("p1", 90)
        ok(await due_rooms(t) == ["p4", "p1"], "친구가 다시 말하면 다시 대상")

        # ── 말을 못 만들면 안 보내고 저장도 안 함, 그 방은 그 칸엔 건너뜀 ──
        await say("p4", "u4", "ㅎㅇ", kid="e2")  # p4 는 방금 말해서 대상 아님 → p1 만 대상
        stored = db.admin("SELECT count(*) FROM marong.messages WHERE meta->>'proactive' = 'true'")[0][0]
        MODE["proactive"] = "fail"
        calls, n = len(llm.bodies), len(SENT)
        ok(await pro.step(t) == 0 and len(SENT) == n and len(llm.bodies) == calls + 1, "오류면 안 보냄")
        ok(await pro.step(t) == 0 and len(llm.bodies) == calls + 1, "그 방은 그 칸엔 다시 안 함")
        MODE["proactive"] = "refuse"
        ok(await Proactive(s, store, agent, http, rng=lambda: 0.0).step(t) == 0 and len(SENT) == n, "거절이면 안 보냄")
        MODE["proactive"] = "ok"
        ok(db.admin("SELECT count(*) FROM marong.messages WHERE meta->>'proactive' = 'true'")[0][0] == stored,
           "못 만든 선톡은 저장하지 않음")

        # ── 잠금을 기다리는 동안 친구가 말하면 보내지 않음 ──
        lock = asyncio.Lock()
        waiting = Proactive(s, store, agent, http, room_lock=lambda key: lock, rng=lambda: 0.0)
        await lock.acquire()
        task = asyncio.create_task(waiting.step(t))
        await asyncio.sleep(0.3)
        await store.add_message("p1", "user", "나 또 왔어", user_key="u1", kakao_id="a9")
        lock.release()
        ok(await task == 0 and len(SENT) == n, "잠금을 얻은 뒤 다시 확인: 친구가 먼저 말했으면 안 보냄")

        # ── 한 번 말 걸 때 짧은 말 여러 개를 몇 초 간격으로 따로 ──
        gaps: list[float] = []

        async def nap(seconds):
            gaps.append(seconds)

        chatty = Proactive(s, store, agent, http, rng=lambda: 0.5, sleep=nap)
        MODE["proactive"] = "multi"
        room4 = (await store.proactive_rooms("p4"))[0]
        n = len(SENT)
        r = await chatty.deliver(room4, dry=True)
        ok(r["parts"] == [0, 3] and r["ok"] is None and len(SENT) == n and not gaps, f"미리 보기는 안 보냄: {r}")
        stored = db.admin("SELECT count(*) FROM marong.messages WHERE meta->>'proactive' = 'true'")[0][0]
        r = await chatty.deliver(room4)
        ok(r["ok"] is True and r["parts"] == [3, 3] and said_texts(SENT[n:]) == ["안녕 첫 말", "두 번째 말 🌰", "세 번째 말?"]
           and all(x["body"].get("botGroupKey") == "p4" and "botUserKey" not in x["body"] for x in SENT[n:]),
           f"빈 줄로 나눈 말 3개를 따로 보냄: {r}")
        ok(gaps == [4.0, 4.0], f"말 사이 2~6초 쉼(rng 0.5 → 4초): {gaps}")
        content, meta = last_message("p4")
        ok(content == "안녕 첫 말\n\n두 번째 말 🌰\n\n세 번째 말?" and meta["parts"] == [3, 3] and meta["delivered"] is True
           and db.admin("SELECT count(*) FROM marong.messages WHERE meta->>'proactive' = 'true'")[0][0] == stored + 1,
           "기록은 한 번(하루 상한도 한 번으로 셈)")
        FAIL.update(code=-877, after=1)
        n = len(SENT)
        r = await chatty.deliver(room4)
        FAIL.update(code=None, after=0)
        content, meta = last_message("p4")
        ok(r["ok"] is True and r["code"] == -877 and r["parts"] == [1, 3] and len(SENT) == n + 2
           and content == "안녕 첫 말" and meta["delivered"] is True and meta["send_code"] == -877
           and meta["parts"] == [1, 3], f"중간에 끊기면 거기서 멈추고 친구가 받은 말까지만 남김: {r} {meta}")
        FAIL["code"] = -877
        r = await chatty.deliver(room4)
        FAIL["code"] = None
        content, meta = last_message("p4")
        ok(r["ok"] is False and r["parts"] == [0, 3] and "세 번째 말?" in content and meta["delivered"] is False,
           "첫 말부터 실패하면 만든 말 전부를 전달 안 됨으로")
        MODE["proactive"] = "ok"

        # ── 친구가 선톡을 그만·다시·더 해 달라고 해도 설정은 안 바뀌고 관리자에게 요청으로만 남음 ──
        def requests_of(room):
            return db.admin("SELECT kind, detail FROM marong.requests WHERE room_key = %s ORDER BY id", (room,))

        def room5_state():
            return db.admin("SELECT proactive, proactive_per_day FROM marong.rooms WHERE room_key = 'p5'")

        def last_result():
            return llm.bodies[-1]["messages"][-1]["content"][0]

        await say("p5", "u5", "안녕", kid="f1")
        b = llm.bodies[-1]
        ok([x["name"] for x in b["tools"]] == ["set_name", "ask_owner"]
           and "하루 2번쯤 먼저 카톡을 보내(선톡, 동희가 정함)" in situation(b), "설정을 바꾸는 도구는 없고 1:1 에 선톡 안내")
        props = next(x for x in b["tools"] if x["name"] == "ask_owner")["input_schema"]["properties"]
        ok(props["per_day"] == {**props["per_day"], "type": "integer", "minimum": 1, "maximum": 48}, props)
        ok(await say("p5", "u5", "선톡 그만 보내", kid="f2") == "알겠어 👌" and room5_state() == [(True, None)]
           and requests_of("p5") == [("proactive_off", {})], "그만하라고 해도 끄지 않고 요청으로 남김")
        ok("동희가 정해서" in last_result()["content"] and "바꾼 척하지 말고" in last_result()["content"], last_result())
        await say("p5", "u5", "선톡 그만 보내", kid="f2b")
        ok(len(requests_of("p5")) == 1, "같은 말을 또 하면 다시 남기지 않음")
        db.admin("UPDATE marong.rooms SET proactive = false WHERE room_key = 'p5'")  # 관리자가 끔(admin schedule … off)
        age("p5", 5)
        ok("p5" not in await due_rooms(t), "끈 방은 대상 아님")
        await say("p5", "u5", "선톡 다시 해줘", kid="f3")
        ok("마롱이가 먼저 말 걸지 않아(선톡 끔, 동희가 정함)" in situation(llm.bodies[-2]) and room5_state() == [(False, None)]
           and requests_of("p5")[-1] == ("proactive_on", {}), "다시 해 달라고 해도 켜지 않고 요청만")
        await say("p5", "u5", "선톡 그만 보내", kid="f3b")
        ok("이미 그렇게 돼 있어" in last_result()["content"] and requests_of("p5")[-1] == ("proactive_on", {}),
           "이미 꺼져 있으면 남기지 않음")
        db.admin("UPDATE marong.rooms SET proactive = true WHERE room_key = 'p5'")  # 관리자가 다시 켬
        ok(await say("p5", "u5", "선톡 자주 해줘", kid="f5") == "알겠어 👌" and room5_state() == [(True, None)]
           and requests_of("p5")[-1] == ("proactive_more", {"per_day": 5}), "더 자주 해 달라고 해도 횟수는 그대로, 말한 횟수만 남김")
        await say("p5", "u5", "선톡 엄청 많이 해줘", kid="f6")
        ok(last_result().get("is_error") is True and "1~48" in last_result()["content"] and len(requests_of("p5")) == 3,
           "1~48 밖이면 남기지 않음")
        await say("p5", "u5", "고마워", kid="f7")
        ok("하루 2번쯤 먼저 카톡을 보내(선톡, 동희가 정함)" in situation(llm.bodies[-1]), "횟수는 관리자가 정한 그대로")
        room5 = (await store.proactive_rooms("p5"))[0]
        r = await pro.deliver(room5, dry=True)
        ok(room5["per_day"] is None and r["parts"] == [0, 1] and PROACTIVE_GUIDE.format(per_day=2) in situation(llm.bodies[-1]),
           "선톡 만들 때도 관리자가 정한 횟수")
        await say("g1", "u1g", "마롱아", channel=False, kid="c2")
        ok([x["name"] for x in llm.bodies[-1]["tools"]] == ["set_name", "ask_owner"]
           and "선톡" not in situation(llm.bodies[-1]), "단체방에서는 선톡 안내 없음")
        await say("g1", "u1g", "선톡 그만 보내", channel=False, kid="c3")
        ok("이미 그렇게 돼 있어(선톡이 꺼져 있음)" in last_result()["content"] and requests_of("g1") == [],
           "단체방 선톡은 기본 꺼짐이라 그만하라고 해도 남기지 않음")
        off = Agent(replace(s, proactive=False), store, FakeEmbeddings(), llm)
        await say("p5", "u5", "안녕 또", kid="f4", ag=off)
        ok([x["name"] for x in llm.bodies[-1]["tools"]] == ["set_name", "ask_owner"]
           and "선톡" not in situation(llm.bodies[-1]), "PROACTIVE=off 면 선톡 안내 없음")
        await say("p5", "u5", "선톡 그만 보내", kid="f4b", ag=off)
        ok("선톡 꺼짐" in last_result()["content"] and len(requests_of("p5")) == 3, "PROACTIVE=off 면 요청도 안 남김")

        # ── 단체방 전송 형식(관리자가 켠 단체방 선톡) ──
        sent_ok, code = await send_message(http, s, skill_text("단체방 시험"), group_key="g1")
        ok(sent_ok and code is None and SENT[-1]["body"]["botGroupKey"] == "g1" and "botUserKey" not in SENT[-1]["body"],
           "단체방은 botGroupKey 로")

        # ── 시험 명령(run.py --proactive): 선톡 일정·시간과 상관없이 그 친구 1:1 방(또는 #방키의 방)에 한 번 ──
        import run

        async def cli(*args):
            out = io.StringIO()
            with redirect_stdout(out):
                code = await run.main("proactive", list(args))
            return code, out.getvalue()

        n = len(SENT)
        code, out = await cli("동희", "--dry")
        ok(code == 0 and "미리 보기(보내지 않음, 말 1개):\n동희 선톡" in out and len(SENT) == n, out)
        code, out = await cli("#" + hashlib.sha1(b"u5").hexdigest()[:8])
        ok(code == 0 and out.startswith("보냄(말 1/1개):\n") and SENT[-1]["body"]["botGroupKey"] == "p5", out)
        ok(db.admin("SELECT meta->>'proactive' FROM marong.messages WHERE room_key = 'p5' ORDER BY id DESC LIMIT 1")
           == [("true",)], "시험 선톡도 기록에 남음")
        code, out = await cli("#" + hashlib.sha1(b"u3").hexdigest()[:8])
        ok(code == 1 and "선톡이 꺼져 있어요" in out and "schedule <친구> on" in out, out)
        code, out = await cli("#" + hashlib.sha1(b"u3").hexdigest()[:8], "--dry")
        ok(code == 0 and "미리 보기(보내지 않음" in out, f"끈 방도 미리 보기는 됨: {out}")
        code, out = await cli("없는친구")
        ok(code == 1 and "방을 하나로 못 정함" in out, out)
        FAIL["code"] = -877
        code, out = await cli("동희")
        FAIL["code"] = None
        ok(code == 1 and "카카오 코드 -877" in out, out)

        # ── 표 버전 5 에서 올리기: 하루 횟수 CHECK 가 1~24 였던 표도 schema.sql 을 다시 돌리면 1~48 하나만 남음 ──
        def per_day_checks():
            return db.admin("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conrelid = 'marong.rooms'::regclass AND pg_get_constraintdef(oid) LIKE %s",
                            ("%proactive_per_day%",))

        db.admin("UPDATE marong.rooms SET proactive_per_day = 5 WHERE room_key = 'p5'")  # 관리자가 정한 횟수
        checks = per_day_checks()
        ok(len(checks) == 1 and ">= 1" in checks[0][1] and "<= 48" in checks[0][1], checks)
        db.admin("ALTER TABLE marong.rooms DROP CONSTRAINT rooms_proactive_per_day_check")
        for _ in range(2):  # 표 버전 5 처럼 이름은 Postgres 가 붙임(같은 CHECK 가 두 번 붙은 표까지)
            db.admin("ALTER TABLE marong.rooms ADD CHECK (proactive_per_day BETWEEN 1 AND 24)")
        ok(len(per_day_checks()) == 2, per_day_checks())
        db.apply_schema()
        checks = per_day_checks()
        ok(len(checks) == 1 and checks[0][0] == "rooms_proactive_per_day_check" and "<= 48" in checks[0][1]
           and await store.schema_version() == 9
           and db.admin("SELECT proactive_per_day FROM marong.rooms WHERE room_key = 'p5'") == [(5,)],
           f"옛 CHECK 를 지우고 1~48 하나만, 표 버전 9, 정해 둔 횟수는 그대로: {checks}")

        # ── 방마다 일정(tools/admin.py schedule): 현경이에게는 7~24시에 하루 12번 ──
        def admin(*args):
            env = {**os.environ, "DATABASE_URL": db.app_url, "PYTHONIOENCODING": "utf-8"}
            p = subprocess.run([sys.executable, str(ROOT / "tools" / "admin.py"), *args],
                               capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
            return p.returncode, p.stdout + p.stderr

        def plan_row():
            return db.admin("SELECT proactive_per_day, proactive_start, proactive_end FROM marong.rooms "
                            "WHERE room_key = 'p6'")

        await say("p6", "u6", "안녕 나 현경이야", kid="g1")
        await store.set_name("u6", "현경")
        code, out = admin("schedule", "현경", "12", "7-24")
        ok(code == 0 and "선톡 일정 하루 12번, 7~24시" in out and plan_row() == [(12, 7, 24)], out)
        code, out = admin("rooms")
        ok(code == 0 and "(선톡 일정 하루 12번, 7~24시)" in out, out)
        for bad in (("현경", "49"), ("현경", "0"), ("현경", "많이"), ("현경", "5", "9-8"), ("현경", "5", "7-25"),
                    ("현경",)):
            code, out = admin("schedule", *bad)
            ok(code != 0 and plan_row() == [(12, 7, 24)], f"잘못된 일정은 안 바꿈: {bad} {out}")
        code, out = admin("schedule", "없는친구", "3")
        ok(code != 0 and "찾지 못함" in out, out)
        code, out = admin("schedule", "현경", "default")
        ok(code == 0 and ".env 기본값" in out and plan_row() == [(None, None, None)], out)
        code, out = admin("schedule", "현경", "36", "7-24")  # 2026-10-27 동희님 "ㅇㅇ36번"
        ok(code == 0 and "선톡 일정 하루 36번, 7~24시" in out and plan_row() == [(36, 7, 24)], out)
        code, out = admin("schedule", "현경", "48")
        ok(code == 0 and plan_row() == [(48, 7, 24)], f"상한 48번까지(시간은 그대로): {out}")
        code, out = admin("schedule", "현경", "12", "7-24")
        ok(code == 0 and plan_row() == [(12, 7, 24)], out)

        shift("p6", 120)
        morning = today.replace(hour=7, minute=30)
        room6 = (await store.proactive_rooms("p6"))[0]
        ok(room6["per_day"] == 12 and room6["start_hour"] == 7 and room6["end_hour"] == 24, room6)
        ok(planner.plan(room6, morning) == (today.replace(hour=7), 1 / 55), "7:30 은 07:00~08:25 칸, 남은 확인 55번")
        ok(await due_rooms(morning) == ["p6"], "다른 친구는 12~21시, 현경이는 7시부터")
        ok(await pro.step(morning) == 1 and SENT[-1]["body"]["botGroupKey"] == "p6", "현경이에게 아침 선톡")
        sit = situation(llm.bodies[-1])
        ok("- 친구: 현경" in sit and PROACTIVE_GUIDE.format(per_day=12) in sit, "선톡 안내에도 하루 12번")
        tick(20)  # 07:50 친구가 답함
        await say("p6", "u6", "ㅋㅋ 아침부터 웬일", kid="g2")
        ok("하루 12번쯤 먼저 카톡을 보내(선톡, 동희가 정함)" in situation(llm.bodies[-1]), "답할 때 안내에도 이 방 횟수")
        tick(40)  # 08:30, 다음 칸(08:25~09:50)
        ok(await due_rooms(today.replace(hour=8, minute=30)) == [], "칸 반 길이(42분 30초)만큼은 조용해야")
        tick(10)  # 08:40
        later = today.replace(hour=8, minute=40)
        ok(await due_rooms(later) == ["p6"] and await pro.step(later) == 1 and SENT[-1]["body"]["botGroupKey"] == "p6",
           "칸이 짧으면 1시간까지 안 기다리고 칸 반 길이만 조용하면 보냄")

        # ── 카카오가 1:1 먼저 보내기를 막은 뒤(2026-11-05 14:30 KST~): 방 키 -880 → 사람 키로 한 번만 더(-876) ──
        def keys_of(sent):
            return [(k, v) for x in sent for k, v in x["body"].items() if k != "skillResponse"]

        KAKAO["mode"] = "blocked"
        room1 = (await store.proactive_rooms("p1"))[0]
        n = len(SENT)
        r = await pro.deliver(room1)
        content, meta = last_message("p1")
        ok(r["ok"] is False and r["code"] == -876 and keys_of(SENT[n:]) == [("botGroupKey", "p1"), ("botUserKey", "u1")]
           and meta["delivered"] is False and meta["send_code"] == -876 and meta["send_key"] == "user",
           f"1:1 은 방 키, 안 되면 사람 키로 한 번씩만 해 보고 전달 실패로 남김: {r} {meta}")
        ok(any("send_message_retry key=user after=-880" in x for x in LOGS), "다른 키로 다시 보낸 것은 로그에")

        # 카카오가 1:1 을 사람 키로 다시 열면(11-05 전처럼) 코드를 고치지 않아도 감. 첫 말에서 키를 바꾸고 다음 말은 바로 그 키로
        KAKAO["mode"] = "user_only"
        MODE["proactive"] = "multi"
        n = len(SENT)
        r = await chatty.deliver(room4)
        content, meta = last_message("p4")
        ok(r["ok"] is True and r["parts"] == [3, 3] and r["code"] is None
           and keys_of(SENT[n:]) == [("botGroupKey", "p4")] + [("botUserKey", "u4")] * 3
           and said_texts(SENT[n + 1:]) == ["안녕 첫 말", "두 번째 말 🌰", "세 번째 말?"]
           and meta["delivered"] is True and meta["send_key"] == "user", f"사람 키로만 가는 1:1: {r} {meta}")
        MODE["proactive"] = "ok"

        # 200 이어도 sendCount 0·errorCount 가 있으면 받는 사람에게 못 간 것(키 문제인지 몰라 다른 키로 다시 안 보냄)
        KAKAO["mode"] = "zero"
        n = len(SENT)
        r = await pro.deliver(room4)
        content, meta = last_message("p4")
        ok(r["ok"] is False and r["code"] is None and len(SENT) == n + 1 and meta["delivered"] is False
           and any("send_message_not_delivered sendCount=0 errorCount=1" in x for x in LOGS), f"sendCount 0: {r} {meta}")

        # ── 관리자가 켠 단체방에도 선톡(봇을 초대한 단체방은 카카오가 1:1 을 막은 뒤에도 방 키로 감) ──
        KAKAO["mode"] = "blocked"
        g1 = "#" + hashlib.sha1(b"g1").hexdigest()[:8]

        def room_line(out, k):
            return next((line for line in out.splitlines() if line.startswith(k)), "")

        code, out = admin("rooms")
        ok(await store.proactive_rooms("g1") == [] and "단체" in room_line(out, g1) and "선톡" not in room_line(out, g1),
           f"단체방 선톡은 기본 꺼짐: {out}")
        code, out = await cli(g1)
        ok(code == 1 and "이 단체방은 선톡이 꺼져 있어요" in out and "schedule <#방키> on" in out, out)
        code, out = admin("schedule", g1, "on")
        ok(code == 0 and f"단체방 {g1}: 선톡 일정 .env 기본값 (선톡 켜짐: 이 방에 먼저 말 걸어요)" in out, out)
        code, out = admin("rooms")
        ok(code == 0 and "(선톡 켬)" in room_line(out, g1), out)
        room_g = (await store.proactive_rooms("g1"))[0]
        ok(room_g["is_channel"] is False and room_g["group_proactive"] is True and room_g["user_key"] == "u1g"
           and room_g["sent_ago"] is None and room_g["failures"] == 0, room_g)

        due = await due_rooms(t)
        ok("g1" in due and "p3" not in due, f"켠 단체방은 1:1 과 같은 일정·조건으로 대상: {due}")
        fresh = Proactive(s, store, agent, http, rng=lambda: 0.0)
        n, calls = len(SENT), len(llm.bodies)
        ok(await fresh.step(t) == len(due), due)
        to_g = [x for x in SENT[n:] if "botUserKey" not in x["body"] and x["body"].get("botGroupKey") == "g1"]
        ok(len(to_g) == 1 and ("botUserKey", "u1g") not in keys_of(SENT[n:]), f"단체방은 방 키로만: {keys_of(SENT[n:])}")
        ok(keys_of(SENT[n:]).count(("botGroupKey", "g1")) == 1
           and len(SENT) - n == 1 + 2 * (len(due) - 1), "1:1 방은 지금 두 키 모두 막혀 방마다 두 번씩 해 보고 실패")
        content, meta = last_message("g1")
        ok(meta["proactive"] is True and meta["delivered"] is True and meta["send_key"] == "room"
           and meta["send_code"] is None and content == said_texts(to_g)[0], meta)
        gsit = next(situation(b) for b in llm.bodies[calls:] if "# 단체방에 먼저 말 걸기" in situation(b))
        speaker = "친구-" + hashlib.sha1(b"u1g").hexdigest()[:4]
        ok("- 단체 채팅방이야." in gsit and f"- 이 방에서 마롱이에게 말한 친구: {speaker}" in gsit
           and "- 이 방에서 누가 마지막으로 마롱이에게 말한 때:" in gsit and "다들 안녕" in gsit
           and PROACTIVE_GROUP_GUIDE.format(per_day=2) in gsit, gsit)
        ok("- 1:1 채팅이야." not in gsit and "# 먼저 말 걸기" not in gsit and "토익" not in gsit and "- 친구: " not in gsit,
           "단체방 선톡에는 1:1 안내·다른 방 기억이 없음")
        for room in due:
            if room != "g1":
                content, meta = last_message(room)
                ok(meta["delivered"] is False and meta["send_code"] == -876 and meta["send_key"] == "user", (room, meta))

        code, out = await cli(g1)
        ok(code == 0 and out.startswith("보냄(말 1/1개):\n") and keys_of(SENT[-1:]) == [("botGroupKey", "g1")], out)
        code, out = admin("schedule", g1, "3", "9-22")
        ok(code == 0 and f"단체방 {g1}: 선톡 일정 하루 3번, 9~22시 (선톡 켜짐" in out
           and db.admin("SELECT group_proactive, proactive_per_day, proactive_start, proactive_end FROM marong.rooms "
                        "WHERE room_key = 'g1'") == [(True, 3, 9, 22)], out)
        ok((await store.proactive_rooms("g1"))[0]["per_day"] == 3, "단체방도 방마다 일정")
        code, out = admin("schedule", g1, "off")
        ok(code == 0 and "(선톡 꺼짐: on 으로 켜야 보냄)" in out and await store.proactive_rooms("g1") == []
           and db.admin("SELECT proactive FROM marong.rooms WHERE room_key = 'g1'") == [(True,)]
           and [r["room_key"] for r in await store.proactive_rooms("p1")] == ["p1"], f"끄면 그 단체방만 빠짐: {out}")
        code, out = await cli(g1[1:], "--dry")
        ok(code == 0 and "미리 보기(보내지 않음" in out, f"# 을 빼도 되고, 끈 단체방도 미리 보기는 됨: {out}")

        # ── 기억 묶기(표 버전 9, admin merge): 1:1 이 막혀 현경이와 마롱이가 있는 단체방 g2 를 현경이 1:1 방 p6 에 묶음.
        #    기록은 옮기지 않고 두 방이 기억을 같이 쓰며, g2 선톡은 1:1 처럼 현경이에게(2026-11-06 동희님 "데이터베이스 각각 합쳐주고")
        g2, p6_room = ("#" + hashlib.sha1(k).hexdigest()[:8] for k in (b"g2", b"p6"))
        await say("g2", "u1g2", "마롱아 여기 현경이 방이야", channel=False, kid="h1")
        await say("p6", "u6", "나 귤 좋아해", kid="g3")
        p6_ids = [r[0] for r in db.admin("SELECT id FROM marong.messages WHERE room_key = 'p6' ORDER BY id")]
        sid6 = await store.add_summary("p6", p6_ids[0], p6_ids[-1], "현경이는 귤을 좋아한다고 함", {"u6": "- 귤 좋아함"}, {})
        ok("귤" not in json.dumps([r["content"] for r in await store.recent("g2", 50)], ensure_ascii=False)
           and await store.notes("g2") == [], "묶기 전에는 방마다 기억이 따로")
        for bad, why in (((g2,), "사용: merge"), ((p6_room, "현경"), "1:1 방이에요"), ((g2, "없는친구"), "하나로 못 정함"),
                         ((g2, g1), "단체방이에요")):
            code, out = admin("merge", *bad)
            ok(code != 0 and why in out and db.admin("SELECT memory_room FROM marong.rooms WHERE room_key = 'g2'")
               == [(None,)], f"잘못된 묶기는 안 바꿈: {bad} {out}")
        code, out = admin("merge", g2, "현경")
        ok(code == 0 and f"단체방 {g2} → 현경 1:1 방 {p6_room}: 기억(최근 대화·요약·메모)을 같이 써요" in out
           and db.admin("SELECT memory_room FROM marong.rooms WHERE room_key = 'g2'") == [("p6",)], out)
        code, out = admin("rooms")
        ok(f"(기억 묶음: 1:1 방 {p6_room})" in room_line(out, g2) and "(기억 묶음: 단체방 1개)" in room_line(out, p6_room)
           and "기억 묶음" not in room_line(out, g1), out)

        both = await store.recent("g2", 50)
        ok({"나 귤 좋아해", "마롱아 여기 현경이 방이야"} <= {r["content"] for r in both}
           and [r["id"] for r in both] == sorted(r["id"] for r in both)
           and [r["id"] for r in await store.recent("p6", 50)] == [r["id"] for r in both],
           "묶은 두 방은 서로의 대화를 시간 순으로 함께 읽음")
        ok([x["id"] for x in await store.summaries("g2", 3)] == [sid6]
           and [(n["user_key"], n["content"]) for n in await store.notes("g2")] == [("u6", "- 귤 좋아함")],
           "1:1 에서 정리한 요약·메모를 묶인 단체방에서도 씀")
        ok(db.admin("SELECT count(*) FROM marong.messages WHERE room_key = 'g2'") == [(2,)],
           "기록은 옮기지 않음(단체방 말은 단체방에 그대로)")

        ok(await store.proactive_rooms("g2") == [], "묶어도 단체방 선톡은 따로 켬")
        admin("schedule", g2, "on")
        code, out = admin("schedule", g2, "36", "7-24")
        room_g2 = (await store.proactive_rooms("g2"))[0]
        ok(code == 0 and room_g2["memory_room"] == "p6" and room_g2["is_channel"] is False and room_g2["user_key"] == "u6"
           and room_g2["name"] == "현경" and room_g2["per_day"] == 36 and room_g2["quiet_for"] < timedelta(minutes=5),
           f"묶인 단체방 선톡 대상은 1:1 친구, 조용한 시간은 두 방을 함께 봄: {room_g2}")
        evening = today.replace(hour=20, minute=5)  # 19:45~20:13 칸(36칸이면 28분 20초씩)
        ok(planner.plan(room_g2, evening) is None, "1:1 에서 방금 말했으면 묶인 단체방에도 끼어들지 않음")
        shift("p6", 30)
        shift("g2", 30)
        room_g2 = (await store.proactive_rooms("g2"))[0]
        ok(planner.plan(room_g2, evening) is not None, room_g2)
        n, calls = len(SENT), len(llm.bodies)
        r = await pro.deliver(room_g2)
        content, meta = last_message("g2")
        ok(r["ok"] is True and keys_of(SENT[n:]) == [("botGroupKey", "g2")] and content == f"현경 선톡 {n + 1} 🌰"
           and meta["proactive"] is True and meta["delivered"] is True and meta["send_key"] == "room",
           f"묶인 단체방 선톡은 방 키로, 1:1 친구 이름을 불러 말 걺: {r} {meta}")
        lsit = situation(llm.bodies[-1])
        ok("- 이 친구와 1:1 로 하던 대화를 이어 가는 단체 채팅방이야(동희가 묶음)" in lsit and "- 친구: 현경" in lsit
           and PROACTIVE_GUIDE.format(per_day=36) in lsit and lsit.endswith(LINKED_GUARD)
           and "현경: 나 귤 좋아해" in lsit and "## 현경\n- 귤 좋아함" in lsit and "현경이는 귤을 좋아한다고 함" in lsit
           and "# 단체방에 먼저 말 걸기" not in lsit and "토익" not in lsit, lsit)
        ok((await store.proactive_rooms("p6"))[0]["sent_ago"] < timedelta(minutes=1)
           and planner.plan((await store.proactive_rooms("g2"))[0], evening) is None,
           "묶인 방들은 지난 선톡도 함께 셈(같은 친구에게 두 방으로 연달아 안 감)")

        await say("g2", "u1g2", "현경이 뭐 좋아해?", channel=False, kid="h2")
        b = llm.bodies[-1]
        rsit = situation(b)
        ok("- 이 방은 한 친구와 1:1 로 하던 대화를 이어 가는 방이야(1:1 친구: 현경, 동희가 묶음)." in rsit
           and LINKED_GUARD in rsit and "- 마롱이는 이 방에 하루 36번쯤 먼저 카톡을 보내(선톡, 동희가 정함)" in rsit
           and "## 현경\n- 귤 좋아함" in rsit and "현경: 나 귤 좋아해" in json.dumps(b["messages"], ensure_ascii=False),
           f"묶인 단체방 답에는 1:1 대화·메모와 선톡 안내: {rsit}")
        await say("p6", "u6", "응 귤", kid="g4")
        b = llm.bodies[-1]
        speaker = "친구-" + hashlib.sha1(b"u1g2").hexdigest()[:4]
        ok("- 이 1:1 방은 동희가 묶은 단체방과 기억을 같이 써." in situation(b)
           and "하루 12번쯤 먼저 카톡을 보내" in situation(b)
           and f"{speaker}: 현경이 뭐 좋아해?" in json.dumps(b["messages"], ensure_ascii=False),
           "1:1 방에서도 묶인 단체방에서 오간 말을 이름을 붙여 읽음")
        await say("g2", "u1g2", "선톡 그만 보내", channel=False, kid="h3")
        ok(requests_of("g2") == [("proactive_off", {})], "선톡을 켠 묶인 단체방에서 한 선톡 요청은 남김")
        code, out = await cli(g2, "--dry")
        ok(code == 0 and "미리 보기(보내지 않음, 말 1개):\n현경 선톡" in out, out)

        code, out = admin("merge", g2, "off")
        room_g2 = (await store.proactive_rooms("g2"))[0]
        ok(code == 0 and "묶음 풂" in out and room_g2["memory_room"] is None and room_g2["user_key"] == "u1g2"
           and "나 귤 좋아해" not in {r["content"] for r in await store.recent("g2", 50)} and await store.notes("g2") == [],
           f"묶음을 풀면 그 방 기억만: {out} {room_g2}")
        code, out = admin("merge", g2, p6_room)
        ok(code == 0 and f"→ 현경 1:1 방 {p6_room}" in out and (await store.proactive_rooms("g2"))[0]["user_key"] == "u6",
           f"1:1 #방키로도 묶음: {out}")

        # 요약: 방마다 어디까지 요약했는지 세서, 묶기 전에 1:1 만 따로 요약한 말은 다시 요약하지 않고 그 요약보다 먼저 단체방에서
        # 한 말도 빠뜨리지 않음. 묶음 뿌리(1:1 방) 하나로 요약하고 meta.rooms 에 두 방을 적음
        g2_ids = [r[0] for r in db.admin("SELECT id FROM marong.messages WHERE room_key = 'g2' ORDER BY id")]
        p6_new = [r[0] for r in db.admin("SELECT id FROM marong.messages WHERE room_key = 'p6' AND id > %s ORDER BY id",
                                         (p6_ids[-1],))]
        rows = await store.unsummarized("g2", 100)
        ok([r["id"] for r in rows] == sorted(g2_ids + p6_new) and g2_ids[0] < p6_ids[-1]
           and [r["id"] for r in await store.unsummarized("p6", 100)] == [r["id"] for r in rows],
           "묶기 전 1:1 요약 뒤의 말과 단체방 말 전부(단체방 첫 말은 그 요약보다 먼저)")
        due, to_note = await store.rooms_due(1), await store.rooms_to_note()
        ok("p6" in due and "g2" not in due and "p6" in to_note and "g2" not in to_note, f"묶음 뿌리 하나로: {due} {to_note}")
        sid_m = await store.add_summary("p6", rows[0]["id"], rows[-1]["id"], "묶은 뒤 첫 요약", {"u6": "- 귤과 감 좋아함"}, {})
        await store.add_notes("p6", {}, rows[-1]["id"])
        ok(db.admin("SELECT meta->'rooms' FROM marong.summaries WHERE id = %s", (sid_m,)) == [(["g2", "p6"],)]
           and await store.unsummarized("g2", 100) == [] and "p6" not in await store.rooms_due(1)
           and "p6" not in await store.rooms_to_note()
           and db.admin("SELECT noted_id FROM marong.rooms WHERE room_key IN ('g2', 'p6')") == [(rows[-1]["id"],)] * 2,
           "묶음 요약은 두 방 말을 함께 덮고, 메모를 고친 위치도 두 방 함께")
        ok([(n["user_key"], n["content"]) for n in await store.notes("g2")] == [("u6", "- 귤과 감 좋아함")]
           and [x["id"] for x in await store.summaries("g2", 3)] == [sid6, sid_m],
           "새 요약·메모는 1:1 방 쪽에 쌓여 두 방이 같이 씀")
        admin("merge", g2, "off")
        ok(await store.unsummarized("g2", 100) == [], "풀어도 묶음 요약으로 덮은 단체방 말은 다시 요약하지 않음")
        admin("merge", g2, p6_room)
        KAKAO["mode"] = "ok"

    # ── 로그에 대화 내용·토큰·카카오 키 원문이 없음 ──
    joined = "\n".join(LOGS)
    for secret in ("tok-secret", "선톡 1 🌰", "동희 선톡", "토익", "심심해", "botUserKey", "첫 말", "현경이야", "웬일",
                   "귤", "현경이 방"):
        ok(secret not in joined, f"로그에 '{secret}'이(가) 남음")
    ok("선톡 room=" in joined and "parts=3/3" in joined and "ask_owner user=" in joined, "로그 자체는 남음")

    await store.close()
    claude.close()
    kakao.shutdown()
    db.close()
    print(f"proactive: all {CHECKS} checks passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    root = logging.getLogger()
    root.setLevel(logging.INFO)  # 서버와 같은 INFO 로그까지 모아서 내용이 새지 않는지 봄
    for h in root.handlers:
        h.setLevel(logging.WARNING)
    root.addHandler(Collect())
    options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    asyncio.run(main(), **options)
