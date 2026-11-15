"""프롬프트 캐시 시험: 성격 앞부분 캐시 수명(ANTHROPIC_CACHE_TTL), 1시간 쓰기 토큰 기록, 캐시 유지(cache_warm).
캐시 유지: 실제 요청에 쓰인 앞부분만 기억해 조용할 때 max_tokens 0 으로 다시 보냄, 읽으면 유지·새로 쓰면 놓음, 실패하면 조금 뒤,
거절(400)되면 다시 안 보냄, 오래 안 쓰면 놓음, 앞부분 수·하루 상한. 진짜 anthropic SDK 로 가짜 /v1/messages 에 max_tokens 0 이
그대로 가고 빈 답과 1시간 쓰기 수를 읽는지. 네트워크·진짜 키·진짜 모델은 쓰지 않는다.
실행: .venv/bin/python tests/test_cache.py"""
import asyncio
from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from fakes import FakeAnthropic, FakeEmbeddings, ScriptedLLM, message, ns, text, tool_use  # noqa: E402
from marong.agent import Agent, Incoming  # noqa: E402
from marong.cache_warm import (DAILY_MAX, PLACEHOLDER, RETRY_S, WARM_AFTER_S, CacheWarmer, cached_prefix,  # noqa: E402
                               hour_writes, prefix_key)
from marong.config import load_settings  # noqa: E402

CHECKS = 0
TOOL = {"name": "schedule_add", "description": "알림 저장", "input_schema": {"type": "object", "properties": {}}}
SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def usage(read=0, wrote=0, hour=None, **more) -> SimpleNamespace:
    made = None if hour is None else {"ephemeral_1h_input_tokens": hour, "ephemeral_5m_input_tokens": wrote - hour}
    return SimpleNamespace(input_tokens=8, output_tokens=0, cache_read_input_tokens=read,
                           cache_creation_input_tokens=wrote, cache_creation=made, **more)


def body(persona="성격" * 10, situation="# 지금 상황\n- 지금 시각: 비밀 아닌 시각", tools=(TOOL, SEARCH), effort="xhigh",
         ttl="1h") -> dict:
    mark = {"type": "ephemeral", "ttl": ttl} if ttl == "1h" else {"type": "ephemeral"}
    out = {"model": "claude-haiku-5-5", "max_tokens": 16000,
           "system": [{"type": "text", "text": persona, "cache_control": mark}, {"type": "text", "text": situation}],
           "messages": [{"role": "user", "content": "친구가 한 말"}]}
    if tools:
        out["tools"] = [dict(t) for t in tools]
    if effort:
        out["output_config"] = {"effort": effort}
    return out


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.day = date(2026, 11, 15)

    def __call__(self):
        return self.t

    def today(self):
        return self.day


class PingLLM:
    """유지 요청을 기록하고 정한 대로 답한다: ('read', n) · ('write', n) · 예외 객체."""

    def __init__(self):
        self.bodies: list[dict] = []
        self.next: list = []

    async def create(self, b, timeout):
        self.bodies.append(b)
        out = self.next.pop(0) if self.next else ("read", 5000)
        if isinstance(out, Exception):
            raise out
        kind, n = out
        return SimpleNamespace(content=[], stop_reason="max_tokens",
                               usage=usage(read=n if kind == "read" else 0, wrote=n if kind == "write" else 0))


class Status(Exception):
    def __init__(self, status_code, msg):
        super().__init__(msg)
        self.status_code = status_code


def unit_checks():
    # 설정: 기본 1시간, 5m 로 되돌리기, 그 밖의 값은 실행 전 점검에서 걸림
    old = os.environ.pop("ANTHROPIC_CACHE_TTL", None)
    try:
        ok(load_settings().cache_ttl == "1h", "default ttl")
        os.environ["ANTHROPIC_CACHE_TTL"] = "5M"
        ok(load_settings().cache_ttl == "5m", "5m")
        os.environ["ANTHROPIC_CACHE_TTL"] = "24h"
        ok(any("ANTHROPIC_CACHE_TTL" in p for p in load_settings().problems()), "24h is not a Claude ttl")
    finally:
        os.environ.pop("ANTHROPIC_CACHE_TTL", None)
        if old is not None:
            os.environ["ANTHROPIC_CACHE_TTL"] = old

    # 1시간 쓰기 토큰: SDK 객체(속성)·dict·없음
    ok(hour_writes(SimpleNamespace(cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=7, ephemeral_5m_input_tokens=1))) == 7,
       "attr")
    ok(hour_writes(usage(wrote=9, hour=9)) == 9 and hour_writes(usage(wrote=9)) == 0, "dict / none")
    ok(hour_writes(SimpleNamespace()) == 0, "older usage without cache_creation")

    # 앞부분: 도구 전부 + 캐시 표시까지의 system + 모델 + effort. 지금 상황·대화·max_tokens 는 빠짐
    b = body()
    p = cached_prefix(b)
    ok(p["model"] == "claude-haiku-5-5" and p["tools"] == [TOOL, SEARCH] and len(p["system"]) == 1
       and p["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"} and p["output_config"] == {"effort": "xhigh"}
       and "messages" not in p and "max_tokens" not in p, p)
    ok("지금 상황" not in json.dumps(p, ensure_ascii=False), "situation is not part of the prefix")
    b["system"][0]["text"] = "바뀜"
    ok(p["system"][0]["text"] == "성격" * 10, "prefix is a copy")
    ok(cached_prefix({**body(), "output_config": {"effort": "low", "format": {"type": "json_schema"}}})["output_config"]
       == {"effort": "low"}, "format dropped (max_tokens 0 refuses it)")
    ok(cached_prefix({**body(), "thinking": {"type": "enabled", "budget_tokens": 2000}}) is None, "extended thinking")
    ok(cached_prefix({**body(), "thinking": {"type": "adaptive"}})["thinking"] == {"type": "adaptive"}, "adaptive kept")
    no_mark = body()
    del no_mark["system"][0]["cache_control"]
    ok(cached_prefix(no_mark) is None and cached_prefix({"model": "m", "system": "글"}) is None, "nothing cached")
    ok("tools" not in cached_prefix(body(tools=())), "greeting without tools")

    # 키: 같은 앞부분은 같고, 대화·지금 상황이 달라도 같고, 도구(검색 횟수)·성격·effort 가 바뀌면 달라짐
    k = prefix_key(cached_prefix(body()))
    ok(k == prefix_key(cached_prefix(body(situation="다른 상황"))), "same prefix, other situation")
    ok(k != prefix_key(cached_prefix(body(tools=(TOOL, {**SEARCH, "max_uses": 2})))), "max_uses change")
    ok(k != prefix_key(cached_prefix(body(persona="새 성격" * 10))), "persona change")
    ok(k != prefix_key(cached_prefix(body(effort="high"))), "effort change")


async def agent_checks():
    base = replace(load_settings(), prompt_path=str(ROOT / "prompt.md"), knowledge_dir=str(ROOT / "knowledge"))

    # system: 성격 블록에만 캐시 표시. 1시간이면 ttl, 5m 이면 예전 그대로({"type": "ephemeral"})
    hour = Agent(base, None, FakeEmbeddings(), ScriptedLLM(lambda b: message([text("응")])))
    five = Agent(replace(base, cache_ttl="5m"), None, FakeEmbeddings(), ScriptedLLM(lambda b: message([text("응")])))
    s1, s5 = hour._system("상황"), five._system("상황")
    ok(s1[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"} and "cache_control" not in s1[1], s1[0].get("cache_control"))
    ok(s5[0]["cache_control"] == {"type": "ephemeral"}, s5[0].get("cache_control"))

    # ask: 1시간 쓰기를 meta 에 따로 세고(도구를 쓴 두 번 합), 요청마다 캐시 유지에 앞부분을 알림
    steps = iter([
        message([tool_use("set_name", {"name": "동희"})], stop_reason="tool_use",
                usage={"input_tokens": 300, "output_tokens": 10, "cache_read_input_tokens": 0,
                       "cache_creation_input_tokens": 6000,
                       "cache_creation": {"ephemeral_1h_input_tokens": 6000, "ephemeral_5m_input_tokens": 0}}),
        message([text("반가워 동희야")],
                usage={"input_tokens": 340, "output_tokens": 12, "cache_read_input_tokens": 6000,
                       "cache_creation_input_tokens": 0,
                       "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0}}),
    ])
    llm = ScriptedLLM(lambda b: next(steps))
    agent = Agent(base, None, FakeEmbeddings(), llm)
    seen = []
    agent.warmer = SimpleNamespace(seen=lambda b, u: seen.append((b, u)))

    async def no_tool(block, msg):
        return {"type": "tool_result", "tool_use_id": block.id, "content": "저장했어"}
    agent._run_tool = no_tool
    msg = Incoming(room_key="r1", user_key="u1", text="나 동희야")
    reply, meta = await agent.ask(agent._system("# 지금 상황"), [{"role": "user", "content": "나 동희야"}], msg,
                                  asyncio.get_running_loop().time() + 30)
    ok(reply == "반가워 동희야" and meta["calls"] == 2, (reply, meta))
    ok(meta["cache_write_tokens"] == 6000 and meta["cache_write_1h_tokens"] == 6000 and meta["cache_read_tokens"] == 6000,
       meta)
    ok(len(seen) == 2 and seen[0][0] is llm.bodies[0] and seen[1][0] is llm.bodies[1], "warmer sees every request")
    ok(llm.bodies[0]["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}, llm.bodies[0]["system"][0])

    # 1시간 쓰기가 없으면 칸을 만들지 않음(예전 기록과 같은 모양)
    plain = Agent(base, None, FakeEmbeddings(), ScriptedLLM(lambda b: message([text("응")])))
    _, meta = await plain.ask(plain._system("상황"), [{"role": "user", "content": "응?"}], msg,
                              asyncio.get_running_loop().time() + 30)
    ok("cache_write_1h_tokens" not in meta and plain.warmer is None, meta)


async def warm_checks():
    clock = Clock()
    llm = PingLLM()
    w = CacheWarmer(llm, clock=clock, today=clock.today)

    # 캐시를 안 쓴 요청(짧음)은 기억하지 않음
    w.seen(body(), usage())
    ok(not w.entries, "nothing to keep warm")

    # 답장 앞부분 등록 → 45분 전에는 안 보냄 → 지나면 같은 앞부분 + max_tokens 0 + 자리 말
    w.seen(body(), usage(wrote=6000, hour=6000))
    ok(len(w.entries) == 1, w.entries)
    clock.t += WARM_AFTER_S - 61
    ok(await w.step() == 0 and not llm.bodies, "too early")
    clock.t += 61
    ok(await w.step() == 1 and len(llm.bodies) == 1, llm.bodies)
    ping = llm.bodies[0]
    ok(ping["max_tokens"] == 0 and ping["messages"] == [{"role": "user", "content": PLACEHOLDER}]
       and ping["tools"] == [TOOL, SEARCH] and len(ping["system"]) == 1 and ping["output_config"] == {"effort": "xhigh"}
       and "stream" not in ping and "tool_choice" not in ping, ping)
    ok("지금 상황" not in json.dumps(ping, ensure_ascii=False) and "친구가 한 말" not in json.dumps(ping, ensure_ascii=False),
       "no situation or conversation in the ping")

    # 읽으면 다시 45분 뒤. 그 사이 실제 요청이 오면 그때부터 다시 셈
    clock.t += 60
    ok(await w.step() == 0 and len(llm.bodies) == 1, "just refreshed")
    clock.t += WARM_AFTER_S - 600
    w.seen(body(situation="다음 말"), usage(read=6000))
    clock.t += 600
    ok(await w.step() == 0 and len(llm.bodies) == 1, "a real request refreshed it")
    clock.t += WARM_AFTER_S
    ok(await w.step() == 1 and len(llm.bodies) == 2, "warm again")

    # 선톡(도구 없음)은 다른 앞부분: 따로 유지
    w.seen(body(tools=()), usage(wrote=5500, hour=5500))
    ok(len(w.entries) == 2, list(w.entries))
    clock.t += WARM_AFTER_S
    ok(await w.step() == 2 and len(llm.bodies) == 4, len(llm.bodies))
    ok({("tools" in b) for b in llm.bodies[2:]} == {True, False}, "both prefixes pinged")

    # 실패(과부하) → 5분 뒤 다시. 크레딧 400 도 다시 시도(요청이 틀린 게 아님)
    clock.t += WARM_AFTER_S
    llm.next = [Status(529, "overloaded"), Status(400, "Your credit balance is too low")]
    ok(await w.step() == 0 and len(llm.bodies) == 6 and len(w.entries) == 2, "both failed, both kept")
    clock.t += 60
    ok(await w.step() == 0 and len(llm.bodies) == 6, "wait before retry")
    clock.t += RETRY_S
    ok(await w.step() == 2 and len(llm.bodies) == 8, "retried")

    # 유지 요청이 새로 썼으면(이미 식음) 놓음: 쓰기 값을 또 내지 않음
    clock.t += WARM_AFTER_S
    llm.next = [("write", 6000), ("read", 5500)]
    ok(await w.step() == 1 and len(w.entries) == 1, list(w.entries))
    clock.t += WARM_AFTER_S
    ok(await w.step() == 1 and len(llm.bodies) == 11 and "tools" not in llm.bodies[-1], "only the greeting stays")

    # 요청 자체가 거절되면(400) 그 앞부분은 다시 등록하지 않음
    w.seen(body(persona="거절될 앞부분" * 5), usage(wrote=6000))
    clock.t += WARM_AFTER_S
    llm.next = [("read", 5500), Status(400, "max_tokens: bad")]
    await w.step()
    ok(len(w.entries) == 1 and len(w.refused) == 1, (list(w.entries), w.refused))
    w.seen(body(persona="거절될 앞부분" * 5), usage(read=6000))
    ok(len(w.entries) == 1, "refused prefix is not tracked again")

    # 실제 요청이 24시간 없으면 놓음(보내지 않고)
    before = len(llm.bodies)
    for _ in range(40):
        clock.t += WARM_AFTER_S
        await w.step()
    ok(not w.entries and len(llm.bodies) - before <= 32, (len(llm.bodies) - before, list(w.entries)))

    # 앞부분은 3개까지(가장 오래 안 쓴 것부터 놓음)
    for i in range(4):
        w.seen(body(persona=f"성격 {i} " * 10), usage(read=6000))
    ok(len(w.entries) == 3 and prefix_key(cached_prefix(body(persona="성격 0 " * 10))) not in w.entries, list(w.entries))

    # 하루 상한: 상한에 닿으면 그날은 더 안 보내고, 다음 날(한국 날짜) 다시
    capped = CacheWarmer(PingLLM(), clock=clock, today=clock.today, daily_max=2)
    for i in range(3):
        capped.seen(body(persona=f"상한 {i} " * 10), usage(read=6000))
    clock.t += WARM_AFTER_S
    ok(await capped.step() == 2 and len(capped.llm.bodies) == 2, len(capped.llm.bodies))
    ok(await capped.step() == 0 and len(capped.llm.bodies) == 2, "capped today")
    clock.day = date(2026, 11, 16)
    ok(await capped.step() == 1 and len(capped.llm.bodies) == 3, "next day")
    ok(DAILY_MAX >= 3 * 24 * 3600 // WARM_AFTER_S, "default cap covers three prefixes all day")


async def sdk_checks():
    """진짜 anthropic SDK: max_tokens 0 이 그대로 가고, 빈 content·1시간 쓰기 수를 SDK 객체로 읽는다."""
    got = []

    def respond(key, b):
        got.append(b)
        return 200, message([], stop_reason="max_tokens", usage={
            "input_tokens": 8, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 6000,
            "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 6000}})

    fake = FakeAnthropic(respond)
    os.environ.update({"ANTHROPIC_API_KEY": "primary", "ANTHROPIC_API_KEY_BACKUP": "", "ANTHROPIC_BASE_URL": fake.url,
                       "BOT_TOKEN": "t"})
    from marong.llm import LLM
    llm = LLM(load_settings())
    try:
        prefix = cached_prefix(body())
        resp = await llm.create({**prefix, "max_tokens": 0, "messages": [{"role": "user", "content": PLACEHOLDER}]}, 10)
        ok(got and got[0]["max_tokens"] == 0 and got[0]["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"},
           got)
        ok(resp.content == [] and resp.stop_reason == "max_tokens" and hour_writes(resp.usage) == 6000, resp)
        # 캐시 유지가 SDK 응답을 그대로 읽음: 새로 썼으므로 놓음
        clock = Clock()
        w = CacheWarmer(llm, clock=clock, today=clock.today)
        w.seen(body(), ns(message([text("응")], usage={"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 6000})).usage)
        clock.t += WARM_AFTER_S
        ok(await w.step() == 0 and not w.entries and w.count["write"] == 6000, w.count)
    finally:
        await llm.close()
        fake.close()


if __name__ == "__main__":
    unit_checks()
    print("PASS settings, 1-hour write count, cached prefix and key")
    asyncio.run(agent_checks())
    print("PASS agent: persona mark with ttl, 1-hour writes in meta, every request reported to the warmer")
    asyncio.run(warm_checks())
    print("PASS warmer: only real prefixes, timing, read keeps, write drops, retry, refused, idle, keep 3, daily cap")
    asyncio.run(sdk_checks())
    print("PASS real SDK: max_tokens 0 sent as is, empty reply and 1-hour writes read")
    print(f"OK {CHECKS} checks")
