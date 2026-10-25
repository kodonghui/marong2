"""카카오·Claude 없이 전체 흐름을 확인하는 시험(Postgres 는 진짜).
가짜 게이트웨이(웹소켓)와 가짜 HTTP 서버(카카오 콜백 API + Claude /v1/messages)를 띄우고 run.main 을 돌린다.
Claude 호출은 진짜 anthropic SDK 가 가짜 서버로 보낸다.
실행(윈도우): .venv\\Scripts\\python tests\\test_e2e.py   (리눅스·맥: .venv/bin/python tests/test_e2e.py)"""
import asyncio
import json
import logging
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import websockets  # noqa: E402

from fakes import api_key, message, text, thinking, tool_use  # noqa: E402
from pg import TestDB  # noqa: E402

CALLBACKS: list[dict] = []
CLAUDE: list[dict] = []
SLOW: set[str] = set()  # 이 콜백 토큰의 답장은 1초 늦게 받음(카카오 API 가 느린 경우)
LOGS: list[str] = []


def claude(key: str, body: dict):
    if "format" in body.get("output_config", {}):  # 뒤에서 하는 요약
        tags = body["output_config"]["format"]["schema"]["properties"]["notes"]["items"]["properties"]["who"]["enum"]
        return 200, message([text(json.dumps({"summary": "동희가 마라탕을 좋아한다고 함",
                                              "notes": [{"who": tags[0], "note": "- 마라탕 좋아함"}]},
                                             ensure_ascii=False))])
    last = body["messages"][-1]
    if isinstance(last["content"], list) and last["content"][0].get("type") == "tool_result":
        return 200, message([text("동희야 반가워 😆")])
    said = last["content"] if isinstance(last["content"], str) else ""
    sit = body["system"][-1]["text"]
    if "PRIMARY_DOWN" in said and key == "primary":
        return 529, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
    if "FAIL" in said:
        return 500, {"type": "error", "error": {"type": "api_error", "message": "boom"}}
    if "REFUSE" in said:
        return 200, message([], "refusal", stop_details={"type": "refusal", "category": "general_harms",
                                                         "explanation": None})
    if "내 이름은 동희" in said:
        return 200, message([thinking("이름 저장"), tool_use("set_name", {"name": "동희"})], "tool_use")
    if "BUBBLES" in said:
        return 200, message([thinking(), text("하나\n\n둘\n\n셋\n\n넷")])
    if "이름을 아직 몰라" in sit:
        return 200, message([text("안녕! 너 이름이 뭐야? 🙂")])
    name = sit.split("지금 말 건 친구: ")[1].splitlines()[0] if "지금 말 건 친구: " in sit else "?"
    flags = f"이름={name} 요약={'있음' if '# 예전 대화 요약' in sit else '없음'} 메모={'있음' if '# 기억 메모' in sit else '없음'}"
    return 200, message([text(f"답({key}): {said.splitlines()[-1]} | {flags}")])


class FakeHTTP(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        if self.path == "/v1/bot/callback":
            if self.headers.get("X-Bot-Callback-Token") in SLOW:
                time.sleep(1)
            CALLBACKS.append({"auth": self.headers.get("Authorization"),
                              "cb": self.headers.get("X-Bot-Callback-Token"), "body": body})
            code, resp = 200, {"totalCount": 1, "sendCount": 1, "errorCount": 0}
        elif self.path == "/v1/messages":
            key = api_key(self.headers)
            CLAUDE.append({"key": key, "version": self.headers.get("anthropic-version"), "body": body})
            code, resp = claude(key, body)
        else:
            code, resp = 404, {}
        data = json.dumps(resp, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


CONNS: asyncio.Queue = None
ACK = {"on": True}


async def gw_handler(ws):
    conn = {"ws": ws, "frames": asyncio.Queue()}
    await CONNS.put(conn)
    await ws.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 400}}))
    try:
        async for raw in ws:
            f = json.loads(raw)
            if f.get("op") == 1:
                if ACK["on"]:
                    await ws.send(json.dumps({"op": 11}))
                conn["heartbeats"] = conn.get("heartbeats", 0) + 1
                continue
            await conn["frames"].put(f)
    except websockets.ConnectionClosed:
        pass


async def wait_for(pred, timeout=10.0, what=""):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if pred():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"시간 초과: {what}")


def bubbles(cb):
    return [o["simpleText"]["text"] for o in cb["body"]["skillResponse"]["template"]["outputs"]]


def text_of(cb):
    return "\n\n".join(bubbles(cb))


async def dispatch(ws, s, t, d):
    await ws.send(json.dumps({"op": 0, "s": s, "t": t, "d": d}))


def msg(i, content, cb, room="room_1", user="user_1", channel=True):
    return {"id": i, "content": content, "timestamp": "2026-10-25T12:00:00Z", "isChannelChatroom": channel,
            "botGroupKey": room, "botUserKey": user, "callbackToken": cb}


class Collect(logging.Handler):
    def emit(self, record):
        LOGS.append(record.getMessage())


async def main():
    global CONNS
    CONNS = asyncio.Queue()
    db = TestDB()
    http = ThreadingHTTPServer(("127.0.0.1", 0), FakeHTTP)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    hport = http.server_address[1]
    server = await websockets.serve(gw_handler, "127.0.0.1", 0)
    wport = server.sockets[0].getsockname()[1]
    tmp = Path(tempfile.mkdtemp())
    os.environ.update({
        "BOT_TOKEN": "tok-secret", "KAKAO_GATEWAY_URL": f"ws://127.0.0.1:{wport}",
        "KAKAO_API_URL": f"http://127.0.0.1:{hport}", "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{hport}",
        "ANTHROPIC_API_KEY": "primary", "ANTHROPIC_API_KEY_BACKUP": "backup", "DATABASE_URL": db.app_url,
        "EMBED_MODEL": "", "PROMPT_PATH": str(ROOT / "prompt.md"), "WELCOME_PATH": str(ROOT / "welcome.txt"),
        "KNOWLEDGE_DIR": str(tmp / "knowledge"), "RECENT_TURNS": "2", "SUMMARY_TURNS": "2",
        "LLM_TIMEOUT_SECONDS": "10",
    })
    import run  # noqa: E402
    bot = asyncio.create_task(run.main("run"))
    checks = 0

    def count(sql):
        return db.admin(sql)[0][0]

    # 1) 최초 연결: IDENTIFY 에 봇 토큰
    c1 = await asyncio.wait_for(CONNS.get(), 10)
    f = await asyncio.wait_for(c1["frames"].get(), 5)
    assert f == {"op": 2, "d": {"token": "tok-secret"}}, f
    await c1["ws"].send(json.dumps({"op": 3, "d": {"session_id": "S1", "bot": {"id": "B"}}}))
    checks += 1

    # 2) 첫 메시지 → 이름을 물음. 콜백 헤더 2개, Claude 요청에 모델·effort·도구·캐시
    await dispatch(c1["ws"], 1, "MESSAGE_CREATE", msg(1, "안녕", "cb1"))
    await wait_for(lambda: len(CALLBACKS) == 1, what="첫 답장")
    assert CALLBACKS[0]["auth"] == "KakaoAK tok-secret" and CALLBACKS[0]["cb"] == "cb1"
    assert text_of(CALLBACKS[0]) == "안녕! 너 이름이 뭐야? 🙂", text_of(CALLBACKS[0])
    b = CLAUDE[-1]["body"]
    assert b["model"] == "claude-haiku-5-5" and b["output_config"] == {"effort": "xhigh"} and b["max_tokens"] == 16000, b
    assert b["tools"][0]["name"] == "set_name" and b["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert CLAUDE[-1]["version"], "anthropic-version 헤더"
    checks += 1

    # 3) HEARTBEAT
    await wait_for(lambda: c1.get("heartbeats", 0) >= 1, what="heartbeat")
    checks += 1

    # 4) 같은 메시지 id 가 다시 와도 한 번만 답함
    await dispatch(c1["ws"], 2, "MESSAGE_CREATE", msg(1, "안녕", "cb1-again"))
    await asyncio.sleep(0.5)
    assert len(CALLBACKS) == 1
    checks += 1

    # 5) 이름을 알려 주면 set_name → 생각 블록·도구 호출을 그대로 돌려주고 이름으로 부름
    n = len(CLAUDE)
    await dispatch(c1["ws"], 3, "MESSAGE_CREATE", msg(2, "내 이름은 동희야", "cb2"))
    await wait_for(lambda: len(CALLBACKS) == 2, what="이름 답장")
    assert text_of(CALLBACKS[1]) == "동희야 반가워 😆", text_of(CALLBACKS[1])
    asst = CLAUDE[n + 1]["body"]["messages"][-2]
    th, tu = asst["content"]
    assert asst["role"] == "assistant" and th["type"] == "thinking" and th["thinking"] == "이름 저장", asst
    assert th["signature"] == thinking("이름 저장")["signature"], "생각 블록 서명을 그대로 돌려줌"
    assert tu["type"] == "tool_use" and tu["id"] == "toolu_1" and tu["input"] == {"name": "동희"}, tu
    assert CLAUDE[n + 1]["body"]["messages"][-1]["content"][0]["tool_use_id"] == "toolu_1"
    assert db.admin("SELECT name FROM marong.people WHERE user_key = 'user_1'") == [("동희",)]
    checks += 1

    # 6) 다음 말부터 이름을 앎
    await dispatch(c1["ws"], 4, "MESSAGE_CREATE", msg(3, "나 마라탕 좋아해", "cb3"))
    await wait_for(lambda: len(CALLBACKS) == 3, what="이름 아는 답장")
    assert "이름=동희" in text_of(CALLBACKS[2]), text_of(CALLBACKS[2])
    checks += 1

    # 7) 뒤에서 요약·메모가 만들어지고(4개 메시지마다), 다음 답에 들어감
    await wait_for(lambda: count("SELECT count(*) FROM marong.summaries") >= 1, what="요약")
    assert db.admin("SELECT content FROM marong.notes") == [("- 마라탕 좋아함",)]
    await dispatch(c1["ws"], 5, "MESSAGE_CREATE", msg(4, "오늘 뭐 먹지", "cb4"))
    await wait_for(lambda: len(CALLBACKS) == 4, what="기억 쓰는 답장")
    assert "요약=있음 메모=있음" in text_of(CALLBACKS[3]), text_of(CALLBACKS[3])
    checks += 1

    # 8) 빈 줄로 나눈 답 → 말풍선 3개까지(남는 건 셋째에 모음)
    await dispatch(c1["ws"], 6, "MESSAGE_CREATE", msg(5, "BUBBLES", "cb5"))
    await wait_for(lambda: len(CALLBACKS) == 5, what="말풍선")
    assert bubbles(CALLBACKS[4]) == ["하나", "둘", "셋\n\n넷"], bubbles(CALLBACKS[4])
    checks += 1

    # 9) '초기화'·'처음부터'는 그냥 대화. 기록은 늘기만 함
    before = count("SELECT count(*) FROM marong.messages")
    await dispatch(c1["ws"], 7, "MESSAGE_CREATE", msg(6, "초기화", "cb6"))
    await dispatch(c1["ws"], 8, "MESSAGE_CREATE", msg(7, "처음부터", "cb7"))
    await wait_for(lambda: len(CALLBACKS) == 7, what="초기화 답장")
    assert "답(primary): 초기화" in text_of(CALLBACKS[5]) and "답(primary): 처음부터" in text_of(CALLBACKS[6]), (text_of(CALLBACKS[5]), text_of(CALLBACKS[6]))
    assert count("SELECT count(*) FROM marong.messages") == before + 4
    assert count("SELECT min(id) FROM marong.messages") == 1, "첫 메시지가 그대로 있음"
    checks += 1

    # 10) 주 키가 실패하면 백업 키로, 둘 다 실패하면 대체 문구, 거절이면 거절 문구
    from marong.agent import FALLBACK_TEXT, REFUSAL_TEXT
    await dispatch(c1["ws"], 9, "MESSAGE_CREATE", msg(8, "PRIMARY_DOWN 시험", "cb8"))
    await wait_for(lambda: len(CALLBACKS) == 8, what="백업 키")
    assert text_of(CALLBACKS[7]).startswith("답(backup): PRIMARY_DOWN"), text_of(CALLBACKS[7])
    await dispatch(c1["ws"], 10, "MESSAGE_CREATE", msg(9, "FAIL 시험", "cb9"))
    await wait_for(lambda: len(CALLBACKS) == 9, what="대체 문구")
    assert text_of(CALLBACKS[8]) == FALLBACK_TEXT
    await dispatch(c1["ws"], 11, "MESSAGE_CREATE", msg(10, "REFUSE 시험", "cb10"))
    await wait_for(lambda: len(CALLBACKS) == 10, what="거절 문구")
    assert text_of(CALLBACKS[9]) == REFUSAL_TEXT
    checks += 1

    # 11) 단체방: 말한 친구 표시
    await dispatch(c1["ws"], 12, "MESSAGE_CREATE", msg(11, "다들 안녕", "cb11", room="group_1", channel=False))
    await wait_for(lambda: len(CALLBACKS) == 11, what="단체방 답장")
    convo = json.dumps(CLAUDE[-1]["body"]["messages"], ensure_ascii=False)
    assert "동희: 다들 안녕" in convo and "단체 채팅방" in CLAUDE[-1]["body"]["system"][-1]["text"], convo
    checks += 1

    # 12) 채팅방 입장(CHAT_JOIN) → welcome.txt 인사
    await dispatch(c1["ws"], 13, "CHAT_JOIN", {"botGroupKey": "group_2", "user": {"botUserKey": "user_2"},
                                                "timestamp": "t", "callbackToken": "cb12"})
    await wait_for(lambda: len(CALLBACKS) == 12, what="인사말")
    assert text_of(CALLBACKS[11]).startswith("안녕! 나는 마롱이야"), text_of(CALLBACKS[11])
    checks += 1

    # 13) 같은 방에서는 앞 답장이 늦게 가도 받은 순서대로 답함
    SLOW.add("cb13")
    await dispatch(c1["ws"], 14, "MESSAGE_CREATE", msg(12, "느린 질문", "cb13"))
    await dispatch(c1["ws"], 15, "MESSAGE_CREATE", msg(13, "다음 질문", "cb14"))
    await wait_for(lambda: len(CALLBACKS) == 14, what="순서대로 답장")
    assert [c["cb"] for c in CALLBACKS[12:]] == ["cb13", "cb14"], [c["cb"] for c in CALLBACKS[12:]]
    checks += 1

    # 14) 서버 재시작(1001) → RESUME(session_id, 마지막 seq)
    await c1["ws"].close(1001)
    c2 = await asyncio.wait_for(CONNS.get(), 5)
    f = await asyncio.wait_for(c2["frames"].get(), 5)
    assert f == {"op": 6, "d": {"token": "tok-secret", "session_id": "S1", "seq": 15}}, f
    checks += 1

    # 15) 세션 만료(4009) → 새 IDENTIFY
    await c2["ws"].close(4009)
    c3 = await asyncio.wait_for(CONNS.get(), 6)
    f = await asyncio.wait_for(c3["frames"].get(), 5)
    assert f["op"] == 2, f
    await c3["ws"].send(json.dumps({"op": 3, "d": {"session_id": "S2", "bot": {"id": "B"}}}))
    checks += 1

    # 16) HEARTBEAT_ACK 가 안 오면 스스로 끊고 RESUME
    ACK["on"] = False
    c4 = await asyncio.wait_for(CONNS.get(), 6)
    ACK["on"] = True
    f = await asyncio.wait_for(c4["frames"].get(), 5)
    assert f["op"] == 6 and f["d"]["session_id"] == "S2", f
    checks += 1

    # 17) 다른 연결로 대체됨(4004) → 다시 연결하지 않고 정상 종료(0)
    await c4["ws"].close(4004)
    code = await asyncio.wait_for(bot, 10)
    assert code == 0
    await asyncio.sleep(1.5)
    assert CONNS.empty(), "4004 뒤에 다시 연결하면 안 됨"
    checks += 1

    # 18) 로그에 대화 내용·토큰·카카오 키 원문이 없음
    joined = "\n".join(LOGS)
    for secret in ("마라탕", "내 이름은", "다들 안녕", "tok-secret", "cb1", "user_1", "room_1", "group_1"):
        assert secret not in joined, f"로그에 '{secret}'이(가) 남음"
    assert "MESSAGE_CREATE id=" in joined and "set_name user=" in joined, "로그 자체는 남음"
    checks += 1

    server.close()
    http.shutdown()
    db.close()
    print(f"e2e: all {checks} checks passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    root = logging.getLogger()
    root.setLevel(logging.INFO)  # 서버와 같은 INFO 로그까지 모아서 내용이 새지 않는지 봄
    for h in root.handlers:
        h.setLevel(logging.WARNING)
    root.addHandler(Collect())
    options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    asyncio.run(main(), **options)
