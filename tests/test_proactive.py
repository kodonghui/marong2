"""선톡 시험: 진짜 Postgres + 가짜 Claude + 가짜 카카오 전송 API(/v1/bot/send_message).
대상 고르기·시간·하루 상한·확률·전송 형식·저장·끄기 도구·실패 기록·잠금 뒤 다시 확인·시험 명령(run.py --proactive).
실행(윈도우): .venv\\Scripts\\python tests\\test_proactive.py   (리눅스·맥: .venv/bin/python tests/test_proactive.py)"""
import asyncio
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import threading
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import httpx  # noqa: E402

from fakes import FakeAnthropic, FakeEmbeddings, ScriptedLLM, message, text, tool_use  # noqa: E402
from marong.agent import PROACTIVE_GUIDE, PROACTIVE_TRIGGER  # noqa: E402
from pg import TestDB  # noqa: E402

CHECKS = 0
SENT: list[dict] = []
FAIL = {"code": None}      # 다음 전송들을 이 카카오 오류 코드로 실패시킴
MODE = {"proactive": "ok"}  # 선톡 말 만들기: ok | fail | refuse
LOGS: list[str] = []


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def situation(body) -> str:
    return body["system"][-1]["text"]


def respond(body):
    """가짜 Claude: 선톡 만들기, 선톡 끄기·켜기 도구, 보통 답."""
    last = body["messages"][-1]
    if last["role"] == "user" and last["content"] == PROACTIVE_TRIGGER:
        if MODE["proactive"] == "fail":
            return RuntimeError("boom")
        if MODE["proactive"] == "refuse":
            return message([], "refusal", stop_details={"type": "refusal", "category": "general_harms",
                                                        "explanation": None})
        sit = situation(body)
        name = sit.split("- 친구: ")[1].splitlines()[0] if "- 친구: " in sit else "안녕"
        return message([text(f"{name} 선톡 {len(SENT) + 1} 🌰")])
    if isinstance(last["content"], list):  # 도구 결과를 받은 뒤
        return message([text("알겠어 👌")])
    said = last["content"].splitlines()[-1]
    if "선톡 그만" in said:
        return message([tool_use("set_proactive", {"on": False})], "tool_use")
    if "선톡 다시" in said:
        return message([tool_use("set_proactive", {"on": True})], "tool_use")
    return message([text(f"응답:{said}")])


class FakeKakao(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        SENT.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if FAIL["code"]:
            code, resp = 400, {"code": FAIL["code"], "msg": "봇이 초대되지 않은 방입니다."}
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
    from marong.proactive import Proactive
    from marong.store import Store

    # ── 설정 ──
    s = load_settings()
    ok(s.proactive and s.proactive_quiet_days == 3 and s.proactive_hours == (12, 21) and s.proactive_daily_max == 10,
       "선톡 기본값: 사흘, 12~21시, 하루 10개")
    ok(s.problems() == [] and replace(s, proactive_hours=(21, 12)).problems()
       and replace(s, proactive_quiet_days=0).problems(), "선톡 설정 오류를 알려 줌")
    del os.environ["PROACTIVE"]
    ok(load_settings().proactive is False, "PROACTIVE 가 없으면 꺼짐")
    os.environ["PROACTIVE"] = "on"

    store = Store(s.database_url)
    await store.open(wait=True)
    llm = ScriptedLLM(respond)
    agent = Agent(s, store, FakeEmbeddings(), llm)
    replies: list[str] = []

    async def send(t):
        replies.append(t)
        return True

    async def say(room, user, t, channel=True, kid=None, ag=None):
        return await (ag or agent).handle(Incoming(room, user, t, is_channel=channel, kakao_id=kid), send)

    def age(room, days):
        db.admin("UPDATE marong.messages SET created_at = created_at - make_interval(days => %s) "
                 "WHERE room_key = %s", (days, room))

    # 방: p1 동희 1:1(4일 조용, 메모·요약 있음), p2 1:1(1일), g1 단체방(4일), terminal(카카오 id 없음, 4일),
    #     p3 1:1(5일, 선톡 끔), p4 1:1(6일, 이름 모름)
    await say("p1", "u1", "나 다음 주 토익 시험 봐", kid="a1")
    await store.set_name("u1", "동희")
    await say("p2", "u2", "안녕", kid="b1")
    await say("g1", "u1g", "다들 안녕", channel=False, kid="c1")
    await say("terminal", "terminal", "터미널에서 한 말")
    await say("p3", "u3", "안녕", kid="d1")
    await store.set_proactive("p3", False)
    await say("p4", "u4", "심심해", kid="e1")
    ids = [r[0] for r in db.admin("SELECT id FROM marong.messages WHERE room_key = 'p1' ORDER BY id")]
    await store.add_summary("p1", ids[0], ids[-1], "동희가 다음 주 토익 시험을 본다고 함", {"u1": "- 토익 시험 준비 중"}, {})
    for room, days in (("p1", 4), ("p2", 1), ("g1", 4), ("terminal", 4), ("p3", 5), ("p4", 6)):
        age(room, days)

    due = await store.proactive_due(3, 10)
    ok([r["room_key"] for r in due] == ["p4", "p1"], f"대상은 오래 조용한 1:1 방만, 오래된 순: {due}")
    ok(due[0]["name"] is None and due[1]["name"] == "동희" and due[1]["user_key"] == "u1", due)
    ok(await store.proactive_due(3, 10, room_key="p1") == [due[1]] and not await store.proactive_due(3, 10, room_key="p2"),
       "방 하나만 다시 확인")

    async with httpx.AsyncClient() as http:
        pro = Proactive(s, store, agent, http, chance=1.0)
        kst = ZoneInfo("Asia/Seoul")
        noon = datetime.now(kst).replace(hour=13, minute=0, second=0, microsecond=0)

        # ── 보내기 ──
        calls = len(llm.bodies)
        ok(await pro.step(noon.replace(hour=9)) == 0 and await pro.step(noon.replace(hour=21)) == 0
           and not SENT and len(llm.bodies) == calls, "12~21시 밖에서는 보내지 않음")
        ok(await pro.step(noon) == 1 and len(SENT) == 1, "한 번에 한 명, 오래 조용한 친구부터")
        b = llm.bodies[-1]
        ok("tools" not in b and b["messages"] == [{"role": "user", "content": PROACTIVE_TRIGGER}]
           and b["output_config"] == {"effort": "xhigh"} and b["system"][0]["cache_control"] == {"type": "ephemeral"},
           "선톡은 도구 없이, 같은 말투 지시문(캐시)과 effort")
        sit = situation(b)
        ok(PROACTIVE_GUIDE in sit and "이름 없이 말해" in sit and "# 최근 대화" in sit and "심심해" in sit
           and "친구가 마지막으로 말한 때" in sit, "이름 모르는 친구: 그 방 최근 대화를 보고 말 검")
        ok("토익" not in sit and "다들 안녕" not in sit, "다른 방 기억은 안 섞임")
        first = SENT[0]
        ok(first["path"] == "/v1/bot/send_message" and first["auth"] == "KakaoAK tok-secret", first)
        ok(first["body"]["botUserKey"] == "u4" and "botGroupKey" not in first["body"], "1:1 은 botUserKey 로 보냄")
        outputs = first["body"]["skillResponse"]["template"]["outputs"]
        ok(outputs == [{"simpleText": {"text": "안녕 선톡 1 🌰"}}] and first["body"]["skillResponse"]["version"] == "2.0",
           first)
        role, content, reply_to, meta = db.admin(
            "SELECT role, content, reply_to, meta FROM marong.messages WHERE room_key = 'p4' ORDER BY id DESC LIMIT 1")[0]
        ok(role == "assistant" and content == "안녕 선톡 1 🌰" and reply_to is None and meta["proactive"] is True
           and meta["delivered"] is True and meta["send_code"] is None and meta["calls"] == 1, meta)

        ok(await pro.step(noon) == 1 and SENT[-1]["body"]["botUserKey"] == "u1", "다음 친구")
        sit = situation(llm.bodies[-1])
        ok("- 친구: 동희" in sit and "토익 시험 준비 중" in sit and "다음 주 토익 시험을 본다고" in sit,
           "그 방의 메모·요약을 보고 말 검")
        ok(await pro.step(noon) == 0 and len(SENT) == 2,
           "답이 오기 전엔 다시 안 보냄. 최근 대화·단체방·터미널·선톡 끈 방은 대상 아님")

        # ── 친구가 답하면 선톡이 앞 문맥, 다시 조용해지면 또 한 번 ──
        await say("p1", "u1", "시험 망했어 ㅠ", kid="a2")
        convo = json.dumps(llm.bodies[-1]["messages"], ensure_ascii=False)
        ok("동희 선톡 2 🌰" in convo and convo.index("동희 선톡 2") < convo.index("시험 망했어"), "선톡에 답하면 선톡이 앞 문맥")
        ok(await store.proactive_due(3, 10) == [], "답한 친구는 다시 조용해질 때까지 대상 아님")
        age("p1", 4)
        ok([r["room_key"] for r in await store.proactive_due(3, 10)] == ["p1"], "다시 사흘 조용하면 또 대상")

        # ── 하루 상한·확률 ──
        capped = Proactive(replace(s, proactive_daily_max=1), store, agent, http, chance=1.0)
        ok(await capped.step(noon) == 0 and len(SENT) == 2, "하루 상한에 닿으면 안 보냄(오늘 1개)")
        shy = Proactive(s, store, agent, http, rng=lambda: 0.5)
        ok(await shy.step(noon) == 0 and len(SENT) == 2, "확률(0.3)에 안 걸리면 이번엔 안 보냄")

        # ── 전송 실패: 전달 안 됨으로 남기고 다시 안 보냄 ──
        FAIL["code"] = -880
        ok(await pro.step(noon) == 1 and len(SENT) == 3, "전송 실패도 한 번 보낸 것으로 셈")
        FAIL["code"] = None
        meta = db.admin("SELECT meta FROM marong.messages WHERE room_key = 'p1' ORDER BY id DESC LIMIT 1")[0][0]
        ok(meta["proactive"] is True and meta["delivered"] is False and meta["send_code"] == -880, meta)
        ok(await store.proactive_due(3, 10) == [], "실패한 방에도 다시 안 보냄")
        ok(all("선톡 3" not in r["content"] for r in await store.recent("p1", 20)), "전달 안 된 선톡은 다음 대화에서 뺌")

        # ── 말을 못 만들면 안 보내고 저장도 안 함, 그 방은 그날 건너뜀 ──
        age("p2", 3)
        MODE["proactive"] = "fail"
        calls = len(llm.bodies)
        ok(await pro.step(noon) == 0 and len(SENT) == 3 and len(llm.bodies) == calls + 1, "오류면 안 보냄")
        ok(await pro.step(noon) == 0 and len(llm.bodies) == calls + 1, "그 방은 그날 다시 안 함")
        MODE["proactive"] = "refuse"
        ok(await Proactive(s, store, agent, http, chance=1.0).step(noon) == 0 and len(SENT) == 3, "거절이면 안 보냄")
        MODE["proactive"] = "ok"
        ok(not db.admin("SELECT 1 FROM marong.messages WHERE room_key = 'p2' AND meta->>'proactive' = 'true'"),
           "못 만든 선톡은 저장하지 않음")

        # ── 잠금을 기다리는 동안 친구가 말하면 보내지 않음 ──
        lock = asyncio.Lock()
        waiting = Proactive(s, store, agent, http, room_lock=lambda key: lock, chance=1.0)
        await lock.acquire()
        task = asyncio.create_task(waiting.step(noon))
        await asyncio.sleep(0.3)
        await store.add_message("p2", "user", "나 왔어", user_key="u2", kakao_id="b9")
        lock.release()
        ok(await task == 0 and len(SENT) == 3, "잠금을 얻은 뒤 다시 확인: 친구가 먼저 말했으면 안 보냄")

        # ── 친구가 그만하라면 끄고, 다시 해 달라면 켬(1:1 에서만 도구) ──
        await say("p5", "u5", "안녕", kid="f1")
        b = llm.bodies[-1]
        ok([t["name"] for t in b["tools"]] == ["set_name", "set_proactive"] and "가끔 먼저 카톡을 보내(선톡)" in situation(b),
           "선톡이 켜져 있으면 1:1 에서 끄기 도구와 안내")
        ok(await say("p5", "u5", "선톡 그만 보내", kid="f2") == "알겠어 👌"
           and db.admin("SELECT proactive FROM marong.rooms WHERE room_key = 'p5'") == [(False,)], "그만하라면 끔")
        age("p5", 5)
        ok("p5" not in [r["room_key"] for r in await store.proactive_due(3, 10)], "끈 방은 대상 아님")
        await say("p5", "u5", "선톡 다시 해줘", kid="f3")
        ok("선톡을 꺼 뒀어" in situation(llm.bodies[-2])
           and db.admin("SELECT proactive FROM marong.rooms WHERE room_key = 'p5'") == [(True,)], "다시 켜기")
        await say("g1", "u1g", "마롱아", channel=False, kid="c2")
        ok([t["name"] for t in llm.bodies[-1]["tools"]] == ["set_name"] and "선톡" not in situation(llm.bodies[-1]),
           "단체방에서는 선톡 도구·안내 없음")
        off = Agent(replace(s, proactive=False), store, FakeEmbeddings(), llm)
        await say("p5", "u5", "안녕 또", kid="f4", ag=off)
        ok([t["name"] for t in llm.bodies[-1]["tools"]] == ["set_name"] and "선톡" not in situation(llm.bodies[-1]),
           "PROACTIVE=off 면 도구·안내 없음")

        # ── 단체방 전송 형식(지금은 안 씀) ──
        sent_ok, code = await send_message(http, s, skill_text("단체방 시험"), group_key="g1")
        ok(sent_ok and code is None and SENT[-1]["body"]["botGroupKey"] == "g1" and "botUserKey" not in SENT[-1]["body"],
           "단체방은 botGroupKey 로")

        # ── 시험 명령(run.py --proactive): 조용한 날수·시간과 상관없이 그 친구 1:1 방에 한 개 ──
        import run

        async def cli(*args):
            out = io.StringIO()
            with redirect_stdout(out):
                code = await run.main("proactive", list(args))
            return code, out.getvalue()

        n = len(SENT)
        code, out = await cli("동희", "--dry")
        ok(code == 0 and "미리 보기(보내지 않음): 동희 선톡" in out and len(SENT) == n, out)
        code, out = await cli("#" + hashlib.sha1(b"u5").hexdigest()[:8])
        ok(code == 0 and out.startswith("보냄: ") and SENT[-1]["body"]["botUserKey"] == "u5", out)
        ok(db.admin("SELECT meta->>'proactive' FROM marong.messages WHERE room_key = 'p5' ORDER BY id DESC LIMIT 1")
           == [("true",)], "시험 선톡도 기록에 남음")
        code, out = await cli("#" + hashlib.sha1(b"u3").hexdigest()[:8])
        ok(code == 1 and "선톡을 꺼 뒀어요" in out, out)
        code, out = await cli("없는친구")
        ok(code == 1 and "1:1 방을 하나로 못 정함" in out, out)
        FAIL["code"] = -877
        code, out = await cli("동희")
        FAIL["code"] = None
        ok(code == 1 and "카카오 코드 -877" in out, out)

    # ── 로그에 대화 내용·토큰·카카오 키 원문이 없음 ──
    joined = "\n".join(LOGS)
    for secret in ("tok-secret", "선톡 1 🌰", "동희 선톡", "토익", "심심해", "botUserKey"):
        ok(secret not in joined, f"로그에 '{secret}'이(가) 남음")
    ok("선톡 room=" in joined and "set_proactive room=" in joined, "로그 자체는 남음")

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
