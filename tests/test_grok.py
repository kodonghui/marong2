"""Grok(xAI) 시험: Claude 모양 요청 ↔ xAI chat/completions 모양 바꾸기, Grok 먼저·실패하면 Claude, Grok 거절은 그대로,
도구(set_name) 처리, 친구별로 Grok 쓰기(GROK_FRIENDS), --check 용 모델 목록. 키 값이 오류에 나오지 않는지도 본다.
가짜 서버 하나가 Claude(/v1/messages)와 xAI(/v1/chat/completions) 둘 다 한다(키로 구분). 실행: .venv\\Scripts\\python tests\\test_grok.py"""
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from fakes import FakeAnthropic, ScriptedLLM, message, text  # noqa: E402

XAI_KEY = "xai-testkey123"
GROK = {"mode": "ok", "script": []}  # script: 차례로 돌려줄 xAI 응답(비면 mode 대로)


def chat(content=None, finish="stop", tool_calls=None, **msg) -> dict:
    """xAI chat/completions 응답 JSON."""
    m = {"role": "assistant", "content": content, **msg}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return {"id": "chatcmpl-1", "object": "chat.completion", "model": "grok-test",
            "choices": [{"index": 0, "message": m, "finish_reason": finish}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "prompt_tokens_details": {"cached_tokens": 600}}}


def call(name: str, args: str, cid: str = "call_1") -> dict:
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}


def respond(key, body):
    if key == XAI_KEY:
        if "GET" in body:
            return 200, {"object": "list", "data": [{"id": "grok-test"}, {"id": "grok-other"}]}
        if GROK["script"]:
            return GROK["script"].pop(0)
        mode = GROK["mode"]
        if mode == "stall":
            return "stall"
        if mode == "down":
            return 503, {"error": "Service Unavailable"}
        if mode == "auth":
            return 400, {"code": "Client specified an invalid argument",
                         "error": f"Incorrect API key provided: {XAI_KEY}. You can obtain an API key from https://console.x.ai."}
        if mode == "filter":
            return 200, chat(None, finish="content_filter")
        return 200, chat("그록 답이야")
    if key == "primary":
        return 200, message([text("클로드 답이야")])
    return 401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}


class Names:
    """Agent 가 set_name 도구로 부르는 저장소 대신."""

    def __init__(self):
        self.saved = []

    async def set_name(self, user_key, name, room_key):
        self.saved.append(name)


async def main():
    fake = FakeAnthropic(respond)
    os.environ.update({"ANTHROPIC_API_KEY": "primary", "ANTHROPIC_API_KEY_BACKUP": "", "ANTHROPIC_BASE_URL": fake.url,
                       "BOT_TOKEN": "t", "XAI_API_KEY": XAI_KEY, "XAI_MODEL": "grok-test",
                       "XAI_BASE_URL": fake.url + "/v1", "GROK_FRIENDS": "3", "PROMPT_PATH": str(ROOT / "prompt.md"),
                       "KNOWLEDGE_DIR": str(ROOT / "tests" / "no-knowledge"), "EMBED_MODEL": ""})
    from anthropic.types import TextBlock, ToolUseBlock

    from marong.agent import REFUSAL_TEXT, Agent, Incoming
    from marong.config import load_settings
    from marong.grok import GrokError, from_chat, to_chat
    from marong.llm import LLM, brief, text_of
    checks = 0

    # 1) 요청 바꾸기: system 블록은 하나로(캐시 표시·effort 는 뺌), 사진은 data URL, 도구 호출·결과는 tool_calls·tool 메시지
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}
    body = {"model": "claude-haiku-5-5", "max_tokens": 16000, "output_config": {"effort": "xhigh"},
            "system": [{"type": "text", "text": "너는 마롱이", "cache_control": {"type": "ephemeral"}},
                       {"type": "text", "text": "# 지금 상황"}],
            "tools": [{"name": "set_name", "description": "이름 저장", "input_schema": {"type": "object"}}],
            "messages": [{"role": "user", "content": "안녕"},
                         {"role": "assistant", "content": "안녕! 이름이 뭐야?"},
                         {"role": "user", "content": [image, {"type": "text", "text": "나 동희야"}]},
                         {"role": "assistant", "content": [TextBlock(type="text", text="잠깐만"),
                                                           ToolUseBlock(type="tool_use", id="call_9", name="set_name",
                                                                        input={"name": "동희"})]},
                         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_9", "content": "저장했어"},
                                                      {"type": "tool_result", "tool_use_id": "call_8", "content": "없음",
                                                       "is_error": True}]},
                         {"role": "system", "content": "글로 써"}]}
    out = to_chat(body, "grok-test")
    m = out["messages"]
    assert out["model"] == "grok-test" and out["max_completion_tokens"] == 16000, out
    assert "output_config" not in out and "max_tokens" not in out and "system" not in out, out
    assert m[0] == {"role": "system", "content": "너는 마롱이\n\n# 지금 상황"}, m[0]
    assert m[1] == {"role": "user", "content": "안녕"} and m[2] == {"role": "assistant", "content": "안녕! 이름이 뭐야?"}
    assert m[3] == {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}},
                                                {"type": "text", "text": "나 동희야"}]}, m[3]
    assert m[4] == {"role": "assistant", "content": "잠깐만", "tool_calls": [
        {"id": "call_9", "type": "function", "function": {"name": "set_name", "arguments": '{"name": "동희"}'}}]}, m[4]
    assert m[5] == {"role": "tool", "tool_call_id": "call_9", "content": "저장했어"}, m[5]
    assert m[6] == {"role": "tool", "tool_call_id": "call_8", "content": "(오류) 없음"}, m[6]
    assert m[7] == {"role": "system", "content": "글로 써"} and len(m) == 8, m
    assert out["tools"] == [{"type": "function", "function": {"name": "set_name", "description": "이름 저장",
                                                              "parameters": {"type": "object"}}}], out["tools"]
    checks += 1

    # 2) 답 바꾸기: 글·도구 호출·멈춘 이유·토큰(캐시는 따로). 인자가 깨졌으면 빈 인자
    r = from_chat(chat("응 반가워"), "grok-test")
    assert text_of(r) == "응 반가워" and r.stop_reason == "end_turn" and r.stop_details is None and r.model == "grok-test"
    assert (r.usage.input_tokens, r.usage.cache_read_input_tokens, r.usage.output_tokens) == (400, 600, 50), r.usage
    r = from_chat(chat("", tool_calls=[call("set_name", '{"name": "동희"}'), call("set_name", "{깨짐", "call_2")]), "g")
    assert r.stop_reason == "tool_use" and [b.input for b in r.content] == [{"name": "동희"}, {}], r.content
    assert from_chat(chat("길어", finish="length"), "g").stop_reason == "max_tokens"
    for refused in (chat(None, finish="content_filter"), chat(None, refusal="그건 못 해")):
        r = from_chat(refused, "g")
        assert r.stop_reason == "refusal" and r.stop_details.category == "grok" and not r.content, r
    checks += 1

    # 3) Grok 먼저: 정상이면 Grok 답만. grok=False 면 Claude 만
    llm = LLM(load_settings())
    claude_body = {"model": "claude-haiku-5-5", "max_tokens": 100, "messages": [{"role": "user", "content": "안녕"}]}

    async def ask(grok=True, timeout=6.0):
        fake.calls.clear()
        resp = await llm.create(claude_body, timeout, grok=grok)
        return text_of(resp), [c["path"] for c in fake.calls]

    assert await ask() == ("그록 답이야", ["/v1/chat/completions"]), "Grok 정상"
    sent = fake.calls[0]["body"]
    assert sent["model"] == "grok-test" and fake.calls[0]["key"] == XAI_KEY and "output_config" not in sent, sent
    assert await ask(grok=False) == ("클로드 답이야", ["/v1/messages"]), "Grok 안 씀"
    checks += 1

    # 4) Grok 이 실패(장애·키 오류)하면 같은 요청을 Claude 로. 오류 설명에 키 값은 안 나옴
    for mode in ("down", "auth"):
        GROK["mode"] = mode
        assert await ask() == ("클로드 답이야", ["/v1/chat/completions", "/v1/messages"]), mode
    assert fake.calls[1]["body"]["model"] == "claude-haiku-5-5", "Claude 로는 Claude 요청 그대로"
    try:
        await llm.grok.create(claude_body, 5)
        raise AssertionError("키 오류는 GrokError")
    except GrokError as e:
        assert e.status_code == 400 and XAI_KEY not in brief(e) and "xai-…" in brief(e), brief(e)
    checks += 1

    # 5) Grok 이 멈추면 시간의 절반만 기다리고 Claude 로(전체 시간 안에서)
    GROK["mode"] = "stall"
    start = time.monotonic()
    got = await ask(timeout=4.0)
    took = time.monotonic() - start
    assert got == ("클로드 답이야", ["/v1/chat/completions", "/v1/messages"]) and 1.5 < took < 4.5, (got, took)
    checks += 1

    # 6) Grok 이 거절하면 Claude 로 다시 보내지 않고 거절 그대로
    GROK["mode"] = "filter"
    fake.calls.clear()
    resp = await llm.create(claude_body, 6.0, grok=True)
    assert resp.stop_reason == "refusal" and [c["path"] for c in fake.calls] == ["/v1/chat/completions"]
    GROK["mode"] = "ok"
    checks += 1

    # 7) 도구: Grok 이 set_name 을 부르면 저장하고 결과를 tool 메시지로 돌려줌 → 다음 답. meta 는 Grok 모델, effort 없음
    names = Names()
    agent = Agent(load_settings(), names, None, llm)
    msg = Incoming(room_key="r1", user_key="u1", text="나 동희야")
    system = [{"type": "text", "text": "너는 마롱이"}]
    GROK["script"] = [(200, chat("", tool_calls=[call("set_name", '{"name": "동희"}')])), (200, chat("반가워 동희!"))]
    fake.calls.clear()
    loop = asyncio.get_running_loop()
    reply, meta = await agent.ask(system, [{"role": "user", "content": "나 동희야"}], msg, loop.time() + 10, grok=True)
    assert reply == "반가워 동희!" and names.saved == ["동희"], (reply, names.saved)
    assert meta["model"] == "grok-test" and meta["effort"] is None and meta["calls"] == 2, meta
    assert meta["grok_tokens"] == [800, 100, 1200] and meta["input_tokens"] == 800, meta
    second = fake.calls[1]["body"]["messages"]
    assert second[-2]["tool_calls"][0]["id"] == "call_1" and second[-1]["role"] == "tool", second
    assert second[-1]["tool_call_id"] == "call_1" and "동희" in second[-1]["content"], second[-1]
    checks += 1

    # 8) 도구를 부른 뒤 Grok 이 실패하면 Claude 가 이어 받음(Grok 의 도구 호출 블록을 Claude 모양 그대로 보냄)
    names.saved.clear()
    GROK["script"] = [(200, chat("", tool_calls=[call("set_name", '{"name": "동희"}')])),
                      (503, {"error": "Service Unavailable"})]
    fake.calls.clear()
    reply, meta = await agent.ask(system, [{"role": "user", "content": "나 동희야"}], msg, loop.time() + 10, grok=True)
    assert reply == "클로드 답이야" and meta["model"] == "claude-haiku-5-5" and meta["effort"] == "xhigh", (reply, meta)
    # 토큰 합계에는 두 회사 몫이 다 들고, Grok 몫은 따로(admin stats 가 Claude 금액에서 뺌)
    assert meta["grok_tokens"] == [400, 50, 600] and (meta["input_tokens"], meta["output_tokens"]) == (500, 70), meta
    sent = fake.calls[-1]["body"]["messages"]
    assert [c["path"] for c in fake.calls] == ["/v1/chat/completions", "/v1/chat/completions", "/v1/messages"]
    assert sent[1] == {"role": "assistant", "content": [{"type": "tool_use", "id": "call_1", "name": "set_name",
                                                         "input": {"name": "동희"}}]}, sent[1]
    assert sent[2]["content"][0]["type"] == "tool_result" and sent[2]["content"][0]["tool_use_id"] == "call_1", sent[2]
    checks += 1

    # 9) 어느 방에서 Grok 이 답하나: GROK_FRIENDS 의 친구 1:1 방만(단체방·다른 친구·친구에 안 묶인 키는 Claude). all 이면 모든 방.
    #    키나 모델이 비면 늘 Claude
    s = load_settings()
    assert s.grok_for(3, True) and not s.grok_for(3, False) and not s.grok_for(4, True) and not s.grok_for(None, True)
    os.environ["GROK_FRIENDS"] = "all"
    assert load_settings().grok_for(None, False)
    for name in ("XAI_API_KEY", "XAI_MODEL"):
        os.environ.update({"GROK_FRIENDS": "3", name: ""})
        assert not load_settings().grok_for(3, True), name
        os.environ.update({"XAI_API_KEY": XAI_KEY, "XAI_MODEL": "grok-test"})
    checks += 1

    # 10) 답장(_reply)이 친구 번호로 Grok 을 고름
    scripted = ScriptedLLM(lambda body: message([text("응")]))
    agent = Agent(load_settings(), names, None, scripted)
    for friend_id, is_channel, want in ((3, True, True), (4, True, False), (3, False, False)):
        person = {"user_key": "u1", "name": "동희", "friend_id": friend_id, "share": True, "proactive": True,
                  "per_day": None}
        one = Incoming(room_key="r1", user_key="u1", text="안녕", is_channel=is_channel)
        await agent._reply(one, person, None, "안녕", 5, use_memory=False)
        assert scripted.grok[-1] is want, (friend_id, is_channel, scripted.grok)
    checks += 1

    # 11) --check: 쓸 수 있는 모델 목록과 짧은 답. 키가 없으면 빈 값
    status, models = await llm.check_grok()
    assert status.startswith("정상") and models == ["grok-other", "grok-test"], (status, models)
    os.environ["XAI_API_KEY"] = ""
    plain = LLM(load_settings())
    assert plain.grok is None and await plain.check_grok() == ("", [])
    fake.calls.clear()
    await plain.create(claude_body, 5, grok=True)
    assert [c["path"] for c in fake.calls] == ["/v1/messages"], "키가 없으면 grok=True 여도 Claude"
    assert REFUSAL_TEXT  # 거절 문구는 agent 가 그대로 씀(위 6 의 refusal)
    checks += 1

    await plain.close()
    await llm.close()
    fake.close()
    print(f"grok: all {checks} checks passed")


if __name__ == "__main__":
    options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    asyncio.run(main(), **options)
