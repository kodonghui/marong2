"""DeepSeek replies (marong/deepseek.py): request/response conversion, web tools delegated to Claude, errors and
fallback, room routing and settings, and a Discord DM through the real Postgres path. The relay is an httpx
MockTransport; Claude is ScriptedLLM. Nothing leaves the machine."""
import asyncio
from dataclasses import replace
import json
import logging
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tools/vertex_live")]
from fakes import FakeEmbeddings, ScriptedLLM, message, text  # noqa: E402
from marong.agent import ASK_OWNER_TOOL, SET_NAME_TOOL  # noqa: E402
from marong.config import load_settings  # noqa: E402
from marong.deepseek import (DOMAIN_TEXT, MODEL, DeepSeekLLM, Route, from_env, read_key, rooms_of,  # noqa: E402
                             to_chat)
from marong.discord_dm import DiscordAgent, DiscordIncoming  # noqa: E402
from marong.shopping import ShopFetch  # noqa: E402
from marong.web_search import WebSearch, sources_of  # noqa: E402
from pg import TestDB  # noqa: E402
from test_discord_dm import DH, DM_DH, Client, prepare  # noqa: E402
from test_dm_help import Logs, dm  # noqa: E402
from test_web_search import WEATHER, cited, searched, usage  # noqa: E402

CHECKS = 0
CLAUDE = "claude-haiku-5-5"
KEY = "hms-test-key-0000"


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def chat(content=None, calls=None, finish="stop", prompt=6000, completion=40, cached=0) -> dict:
    """OpenAI chat completions response JSON."""
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [{"id": f"call_{i}", "type": "function",
                              "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}}
                             for i, (n, a) in enumerate(calls)]
    return {"id": "x", "object": "chat.completion", "model": MODEL,
            "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "prompt_cache_hit_tokens": cached}}


class Relay:
    """Scripted relay: each step is a dict (200 JSON), an (status, body) pair, or an exception to raise."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests: list[dict] = []
        self.headers: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        self.headers.append(dict(request.headers))
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, Exception):
            raise step
        if isinstance(step, tuple):
            return httpx.Response(step[0], text=step[1])
        return httpx.Response(200, json=step)


def llm(relay, claude=None, **kw) -> DeepSeekLLM:
    return DeepSeekLLM(KEY, claude=claude, claude_model=CLAUDE, transport=httpx.MockTransport(relay), **kw)


def body(*messages, tools=None, system="PERSONA") -> dict:
    out = {"model": CLAUDE, "max_tokens": 16000, "output_config": {"effort": "xhigh"},
           "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
                      {"type": "text", "text": "지금 상황"}],
           "messages": list(messages) or [{"role": "user", "content": "안녕"}]}
    if tools:
        out["tools"] = tools
    return out


SEARCH_SPEC = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3,
               "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"}}
FETCH_SPEC = {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 2, "allowed_domains": ["musinsa.com"],
              "max_content_tokens": 10000}


def conversion_checks():
    png = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
    b = body({"role": "user", "content": [png, {"type": "text", "text": "이거 뭐야?"}]},
             {"role": "assistant", "content": [SimpleNamespace(type="thinking", thinking="t"),
                                               SimpleNamespace(type="text", text="잠깐 볼게", citations=None),
                                               SimpleNamespace(type="tool_use", id="t1", name="schedule_list", input={})]},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "일정 없음"}]},
             {"role": "system", "content": "빈 답 말고 답해"},
             tools=[SET_NAME_TOOL, SEARCH_SPEC, FETCH_SPEC])
    messages, functions, delegated = to_chat(b)
    ok(messages[0] == {"role": "system", "content": "PERSONA\n\n지금 상황"}, messages[0])
    ok(messages[1]["content"][0] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
       and messages[1]["content"][1] == {"type": "text", "text": "이거 뭐야?"}, messages[1])
    ok(messages[2] == {"role": "assistant", "content": "잠깐 볼게", "tool_calls": [
        {"id": "t1", "type": "function", "function": {"name": "schedule_list", "arguments": "{}"}}]}, messages[2])
    ok(messages[3] == {"role": "tool", "tool_call_id": "t1", "content": "일정 없음"}, messages[3])
    ok(messages[4] == {"role": "system", "content": "빈 답 말고 답해"} and len(messages) == 5, messages[4:])
    ok([f["function"]["name"] for f in functions] == ["set_name", "web_search", "web_fetch"]
       and functions[0]["function"]["parameters"] == SET_NAME_TOOL["input_schema"]
       and "musinsa.com" in functions[2]["function"]["description"] and set(delegated) == {"web_search", "web_fetch"},
       functions)
    # A search this module delegated goes back as the call plus its digest; Claude's citation-only blocks don't.
    _, _, _ = to_chat(body())
    m2, _, _ = to_chat(body({"role": "user", "content": "날씨"}, {"role": "assistant", "content": [
        SimpleNamespace(type="server_tool_use", id="c0", name="web_search", input={"query": "서울 날씨"}, digest="맑음"),
        SimpleNamespace(type="text", text="", citations=[{"type": "web_search_result_location", "url": WEATHER}]),
        SimpleNamespace(type="tool_use", id="c1", name="schedule_list", input={})]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "없음", "is_error": True}]}))
    ok(m2[2]["tool_calls"][0]["function"]["name"] == "web_search" and m2[2]["tool_calls"][1]["id"] == "c1"
       and m2[3] == {"role": "tool", "tool_call_id": "c0", "content": "맑음"}
       and m2[4] == {"role": "tool", "tool_call_id": "c1", "content": "(오류) 없음"}, m2)
    print("PASS Claude request ↔ chat completions conversion (system, image, tools, results, delegated search)")


async def create_checks():
    # Plain reply: Claude-shaped content, stop reason and usage; the key and a non-default User-Agent are sent.
    relay = Relay(chat("응 안녕 🌰", prompt=6100, completion=12, cached=5000))
    ds = llm(relay)
    resp = await ds.create(body(), 30)
    ok([b.type for b in resp.content] == ["text"] and resp.content[0].text == "응 안녕 🌰"
       and resp.stop_reason == "end_turn" and resp.served_model is None, resp)
    ok(resp.usage.input_tokens == 6100 and resp.usage.output_tokens == 12 and resp.usage.cache_read_input_tokens == 5000
       and resp.usage.server_tool_use is None, resp.usage)
    req = relay.requests[0]
    ok(req["model"] == MODEL and req["max_tokens"] == 16000 and "tools" not in req and "thinking" not in req
       and "reasoning_effort" not in req, req)
    ok(relay.headers[0]["authorization"] == f"Bearer {KEY}" and relay.headers[0]["user-agent"] == "marong-discord/1.0",
       "key header and User-Agent")
    await ds.close()

    # Effort: off turns thinking off, low/medium/high go as reasoning_effort.
    for effort, want in (("off", ("thinking", {"type": "disabled"})), ("high", ("reasoning_effort", "high"))):
        relay = Relay(chat("응"))
        ds = llm(relay, effort=effort)
        await ds.create(body(), 30)
        ok(relay.requests[0][want[0]] == want[1], relay.requests[0])
        await ds.close()

    # Function tools (schedules) come back as tool_use for the agent to run.
    relay = Relay(chat("잠깐만", calls=[("schedule_add", {"when": "2026-11-16 15:00", "what": "병원"})],
                       finish="tool_calls"))
    ds = llm(relay)
    resp = await ds.create(body(tools=[SET_NAME_TOOL, ASK_OWNER_TOOL]), 30)
    ok([b.type for b in resp.content] == ["text", "tool_use"] and resp.stop_reason == "tool_use"
       and resp.content[1].name == "schedule_add" and resp.content[1].input["what"] == "병원"
       and resp.content[1].id == "call_0", resp.content)
    await ds.close()

    # web_search: DeepSeek calls it, Claude searches (query only, its own server tool, once), DeepSeek answers.
    relay = Relay(chat(None, calls=[("web_search", {"query": "서울 날씨"})], finish="tool_calls"),
                  chat("서울은 맑고 18도래"))
    claude = ScriptedLLM(lambda b: message([*searched(), cited("서울은 맑음, 18도")], usage=usage(1)))
    ds = llm(relay, claude)
    resp = await ds.create(body({"role": "user", "content": "PRIVATE_TALK 오늘 날씨 어때?"},
                                tools=[SET_NAME_TOOL, SEARCH_SPEC]), 60)
    sent = claude.bodies[0]
    ok(sent["tools"] == [{**SEARCH_SPEC, "max_uses": 1}] and sent["model"] == CLAUDE
       and "서울 날씨" in sent["messages"][0]["content"] and "PRIVATE_TALK" not in json.dumps(sent, ensure_ascii=False)
       and "PERSONA" not in json.dumps(sent, ensure_ascii=False), sent)
    ok([b.type for b in resp.content] == ["server_tool_use", "text", "text"] and resp.content[-1].text == "서울은 맑고 18도래"
       and resp.stop_reason == "end_turn", [b.type for b in resp.content])
    ok(resp.usage.server_tool_use == {"web_search_requests": 1, "web_fetch_requests": 0}, resp.usage)
    ok(sources_of(resp.content) == [{"url": WEATHER, "title": "서울 날씨 - 기상청"}], sources_of(resp.content))
    second = relay.requests[1]["messages"]
    ok(second[-2]["tool_calls"][0]["function"]["name"] == "web_search" and second[-1]["role"] == "tool"
       and "서울은 맑음" in second[-1]["content"] and WEATHER in second[-1]["content"], second[-2:])
    await ds.close()

    # web_fetch only reads the listed malls; other addresses never reach Claude.
    relay = Relay(chat(None, calls=[("web_fetch", {"url": "https://evil.example/p/1"})], finish="tool_calls"),
                  chat("거긴 못 읽어"))
    claude = ScriptedLLM(lambda b: message([text("x")]))
    ds = llm(relay, claude)
    resp = await ds.create(body(tools=[FETCH_SPEC]), 60)
    ok(not claude.bodies and relay.requests[1]["messages"][-1]["content"] == DOMAIN_TEXT.format(domains="musinsa.com"),
       relay.requests[1]["messages"][-1])
    await ds.close()

    # The first request failing (502, timeout) goes straight to Claude with the same request, no retry.
    for failure in ((502, "upstream request failed"), httpx.ReadTimeout("slow")):
        relay = Relay(failure, chat("늦은 답"))
        claude = ScriptedLLM(lambda b: message([text("클로드가 대신 답함")]))
        ds = llm(relay, claude)
        b = body(tools=[SET_NAME_TOOL])
        resp = await ds.create(b, 60)
        ok(len(relay.requests) == 1 and claude.bodies == [b] and resp.served_model == CLAUDE
           and resp.content[0].text == "클로드가 대신 답함", (failure, len(relay.requests)))
        await ds.close()

    # A slow relay is cut at the DeepSeek time limit, then Claude answers.
    async def slow(request):
        await asyncio.sleep(10)
        return httpx.Response(200, json=chat("너무 늦음"))
    claude = ScriptedLLM(lambda b: message([text("빨리 답함")]))
    ds = DeepSeekLLM(KEY, claude=claude, claude_model=CLAUDE, timeout_s=5, transport=httpx.MockTransport(slow))
    loop = asyncio.get_running_loop()
    t = loop.time()
    resp = await ds.create(body(), 60)
    ok(resp.served_model == CLAUDE and 4.5 < loop.time() - t < 8, loop.time() - t)
    await ds.close()

    # Later rounds (tool results already in the conversation) retry once instead.
    relay = Relay((503, "busy"), chat("일정 저장했어"))
    ds = llm(relay, ScriptedLLM(lambda b: message([text("x")])))
    later = body({"role": "user", "content": "내일 3시 병원"},
                 {"role": "assistant", "content": [SimpleNamespace(type="tool_use", id="t1", name="schedule_add",
                                                                   input={"what": "병원"})]},
                 {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "저장함"}]})
    resp = await ds.create(later, 60)
    ok(len(relay.requests) == 2 and resp.content[0].text == "일정 저장했어" and resp.served_model is None,
       len(relay.requests))
    await ds.close()

    # Without fallback the error goes up (the agent then sends its usual fallback text).
    relay = Relay((500, "down"))
    ds = llm(relay, ScriptedLLM(lambda b: message([text("x")])), fallback=False)
    try:
        await ds.create(body(), 30)
        ok(False, "no error")
    except Exception as e:
        ok(getattr(e, "status_code", None) == 500, e)
    await ds.close()

    # DeepSeek content refusals look like Claude refusals.
    for step in (chat("", finish="content_filter"), (400, '{"error":{"message":"Content Exists Risk"}}')):
        ds = llm(Relay(step), ScriptedLLM(lambda b: message([text("x")])))
        resp = await ds.create(body(), 30)
        ok(resp.stop_reason == "refusal" and resp.served_model is None, step)
        await ds.close()

    # Claude turning the web tool down (400) goes up so DiscordAgent drops the tool and answers again.
    class Off(Exception):
        status_code = 400
    relay = Relay(chat(None, calls=[("web_search", {"query": "뉴스"})], finish="tool_calls"))
    ds = llm(relay, ScriptedLLM(lambda b: Off("web search is not enabled for this organization")))
    try:
        await ds.create(body(tools=[SEARCH_SPEC]), 30)
        ok(False, "no error")
    except Off:
        ok(True, "")
    await ds.close()
    print("PASS replies, effort, function tools, Claude-delegated search/fetch, retry/fallback/time limit, refusals")


def setting_checks():
    ok(rooms_of("*") == ("*",) and rooms_of(" discord-dm:* , discord-ch:123 ") == ("discord-dm:*", "discord-ch:123"),
       "patterns")
    for bad in ("discord-dm", "dm:abc", "*:1", "discord-dm:12*"):
        try:
            rooms_of(bad)
            ok(False, bad)
        except ValueError:
            ok(True, "")
    r = Route(None, rooms_of("discord-dm:*,discord-ch:7"))
    ok(r.answers("discord-dm:1") and r.answers("discord-ch:7") and not r.answers("discord-ch:8")
       and not r.answers("k-room") and not r.answers(None), "matching")
    ok(Route(None, ("*",)).answers("anything"), "*")

    logs = Logs()
    logging.getLogger("marong.deepseek").addHandler(logs)
    logging.getLogger("marong.deepseek").setLevel(logging.INFO)
    with tempfile.TemporaryDirectory() as d:
        creds = Path(d)
        (creds / "deepseek.env").write_text(f"OTHER_URL=https://x\nexport RELAY_KEY=\"{KEY}\"\n", encoding="utf-8")
        ok(read_key(creds / "deepseek.env", "RELAY_KEY") == KEY and read_key(creds / "deepseek.env", "NOPE") == "", "read")
        ok(from_env({}, creds, None, CLAUDE) is None, "off by default")
        route = from_env({"MARONG_DEEPSEEK_ROOMS": "*", "MARONG_DEEPSEEK_KEY_NAME": "RELAY_KEY",
                          "MARONG_DEEPSEEK_EFFORT": "off", "MARONG_DEEPSEEK_TIMEOUT_S": "20"}, creds, None, CLAUDE)
        ok(route is not None and route.rooms == ("*",) and route.model == MODEL and route.llm.effort == "off"
           and route.llm.timeout_s == 20 and route.llm.http.headers["authorization"] == f"Bearer {KEY}", route)
        asyncio.run(route.llm.close())
        for env in ({"MARONG_DEEPSEEK_ROOMS": "*", "MARONG_DEEPSEEK_KEY_NAME": "MISSING"},
                    {"MARONG_DEEPSEEK_ROOMS": "*"},
                    {"MARONG_DEEPSEEK_ROOMS": "dm", "MARONG_DEEPSEEK_KEY_NAME": "RELAY_KEY"},
                    {"MARONG_DEEPSEEK_ROOMS": "*", "MARONG_DEEPSEEK_KEY_NAME": "RELAY_KEY", "MARONG_DEEPSEEK_EFFORT": "x"},
                    {"MARONG_DEEPSEEK_ROOMS": "*", "MARONG_DEEPSEEK_KEY_NAME": "RELAY_KEY",
                     "MARONG_DEEPSEEK_BASE_URL": "http://plain.example/v1"}):
            ok(from_env(env, creds, None, CLAUDE) is None, env)
        ok(from_env({"MARONG_DEEPSEEK_ROOMS": "*", "MARONG_DEEPSEEK_KEY_NAME": "RELAY_KEY"}, None, None, CLAUDE) is None,
           "no credentials directory")
    ok(KEY not in logs.text() and "deepseek off: bad setting" in logs.text() and "deepseek on rooms=*" in logs.text(),
       logs.text())
    print("PASS room patterns, key file reading, settings errors keep Claude (and never log the key)")


class Warmer:
    def __init__(self):
        self.seen_bodies = []

    def seen(self, body, usage):
        self.seen_bodies.append(body)


async def discord_checks(db):
    from marong.discord_store import DiscordStore
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul", reply_wait_s=0, anthropic_model=CLAUDE)
    store = DiscordStore(db.app_url, call_bridge=True)
    await store.open(wait=True)
    try:
        def search_or_answer(request_body):
            return message([*searched(), cited("서울은 맑음, 18도")], usage=usage(1))
        claude = ScriptedLLM(search_or_answer)
        web = WebSearch(per_reply=3, daily=5)
        agent = DiscordAgent(settings, store, FakeEmbeddings(), claude, web=web, shop=ShopFetch(10))
        agent.warmer = Warmer()
        relay = Relay(chat("헐 피곤했구나 오늘은 푹 쉬어 🌰"))
        agent.route = Route(llm(relay, claude), ("*",))
        client = Client(agent, store)
        channel = client.channels[DM_DH]
        room = f"discord-dm:{DH}"

        def last_reply():
            return db.admin("SELECT content, meta FROM marong.messages WHERE room_key=%s AND role='assistant' "
                            "ORDER BY id DESC LIMIT 1", (room,))[0]

        await client.on_message(dm(client, DH, DM_DH, 701, "나 오늘 너무 피곤해"))
        ok(channel.sent[-1] == "헐 피곤했구나 오늘은 푹 쉬어 🌰" and not claude.bodies and not agent.warmer.seen_bodies,
           channel.sent)
        content, meta = last_reply()
        ok(meta["model"] == MODEL and meta["calls"] == 1 and meta["input_tokens"] == 6000 and meta["delivered"] is True
           and "fallback" not in meta, meta)
        req = relay.requests[-1]
        names = [f["function"]["name"] for f in req["tools"]]
        ok(req["messages"][0]["role"] == "system" and "나 오늘 너무 피곤해" in json.dumps(req["messages"][-1], ensure_ascii=False)
           and "web_search" in names and "web_fetch" in names and any(n.startswith("schedule_") for n in names), names)

        # Search through Claude, answer by DeepSeek, the sources line on the sent text only, counts kept.
        relay.steps = [chat(None, calls=[("web_search", {"query": "서울 날씨"})], finish="tool_calls"),
                       chat("오늘 서울은 맑고 18도래")]
        await client.on_message(dm(client, DH, DM_DH, 702, "오늘 서울 날씨 어때?"))
        ok(channel.sent[-1] == "오늘 서울은 맑고 18도래\n\n출처: [서울 날씨 - 기상청](https://www.weather.go.kr/w/index.do)",
           channel.sent[-1])
        content, meta = last_reply()
        ok(content == "오늘 서울은 맑고 18도래" and meta["web_searches"] == 1 and meta["model"] == MODEL
           and meta["sources"] == [{"url": WEATHER, "title": "서울 날씨 - 기상청"}] and web.left() == 4, meta)
        ok(len(claude.bodies) == 1 and claude.bodies[0]["tools"][0]["max_uses"] == 1, claude.bodies)

        # The relay down: Claude answers the same request (cache warmer fed again), meta says so.
        relay.steps = [(502, "upstream request failed")]
        claude.fn = lambda b: message([text("클로드가 대신 답했어")])
        await client.on_message(dm(client, DH, DM_DH, 703, "뭐해?"))
        content, meta = last_reply()
        ok(channel.sent[-1] == "클로드가 대신 답했어" and meta["model"] == CLAUDE and meta["fallback"] == "deepseek"
           and len(agent.warmer.seen_bodies) == 1, meta)

        # Rooms not listed stay on Claude.
        agent.route = Route(agent.route.llm, ("discord-ch:*",))
        claude.fn = lambda b: message([text("클로드 답")])
        n = len(relay.requests)
        await client.on_message(dm(client, DH, DM_DH, 704, "안녕"))
        content, meta = last_reply()
        ok(channel.sent[-1] == "클로드 답" and meta["model"] == CLAUDE and len(relay.requests) == n, meta)

        # Proactive messages go through the same route.
        agent.route = Route(agent.route.llm, ("*",))
        relay.steps = [chat("뭐해~ 저녁 먹었어?")]
        incoming = DiscordIncoming(room, f"discord-user:{DH}", "")
        reply, meta = await agent.ask([{"type": "text", "text": "P"}], [{"role": "user", "content": "선톡"}], incoming,
                                      asyncio.get_running_loop().time() + 30, tools=[])
        ok(reply == "뭐해~ 저녁 먹었어?" and meta["model"] == MODEL and "tools" not in relay.requests[-1], meta)
        await agent.route.llm.close()
    finally:
        await store.close()
    print("PASS Discord DM through DeepSeek: reply, delegated search with sources, Claude fallback, routing, proactive")


if __name__ == "__main__":
    conversion_checks()
    asyncio.run(create_checks())
    setting_checks()
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(discord_checks(db))
    finally:
        db.close()
    print(f"ALL PASS ({CHECKS} checks)")
