"""인터넷 검색 시험: Claude 서버 도구 web_search 를 디스코드 DM 마롱이에 붙인 것.
도구 정의·횟수 상한(답마다·하루, 한국 날짜)·끄기, 응답 글 잇기, pause_turn 이어 받기, 출처(보내는 글 끝에만, 기록에는 안 넣음),
조직 설정에서 꺼졌을 때 도구 없이 다시 답하기. 진짜 Postgres(pgserver) + 가짜 디스코드 DM + 가짜 Claude.
네트워크·진짜 키·진짜 모델은 쓰지 않는다.
실행: .venv/bin/python tests/test_web_search.py"""
import asyncio
from dataclasses import replace
from datetime import datetime
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tools/vertex_live")]
from fakes import FakeEmbeddings, ScriptedLLM, message, ns, text, thinking, tool_use  # noqa: E402
from marong.agent import FALLBACK_TEXT, Agent  # noqa: E402
from marong.config import load_settings  # noqa: E402
from marong.discord_dm import DiscordAgent, DiscordIncoming  # noqa: E402
from marong.discord_store import DiscordStore  # noqa: E402
from marong.llm import server_tool_counts, text_of  # noqa: E402
from marong.web_search import (GUIDE, OFF_GUIDE, SPENT_GUIDE, TOOL_TYPE, WebSearch, sources_line,  # noqa: E402
                               sources_of, turned_off)
from pg import TestDB  # noqa: E402
from test_discord_dm import DH, DM_DH, Client, prepare  # noqa: E402
from test_dm_help import Logs, dm, situation  # noqa: E402

TZ = ZoneInfo("Asia/Seoul")
CHECKS = 0
WEATHER = "https://www.weather.go.kr/w/index.do"
NEWS = "https://news.example.com/a(1)"


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def kst(*args) -> float:
    return datetime(*args, tzinfo=TZ).timestamp()


def searched(query="서울 날씨", tid="srvtoolu_1", url=WEATHER, title="서울 날씨 - 기상청") -> list[dict]:
    return [{"type": "server_tool_use", "id": tid, "name": "web_search", "input": {"query": query}},
            {"type": "web_search_tool_result", "tool_use_id": tid,
             "content": [{"type": "web_search_result", "url": url, "title": title, "encrypted_content": "enc",
                          "page_age": None}]}]


def cited(t, url=WEATHER, title="서울 날씨 - 기상청") -> dict:
    return {"type": "text", "text": t, "citations": [
        {"type": "web_search_result_location", "url": url, "title": title, "cited_text": "맑음", "encrypted_index": "e"}]}


def usage(searches=0, fetches=0) -> dict:
    out = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0}
    if searches or fetches:
        out["server_tool_use"] = {"web_search_requests": searches, "web_fetch_requests": fetches}
    return out


def tool_names(body) -> list[str]:
    return [t["name"] for t in body.get("tools", [])]


class Refused(Exception):
    status_code = 400


# ── 모듈 단위 ─────────────────────────────────────────

def unit_checks():
    now = [kst(2026, 11, 15, 23, 50)]
    web = WebSearch(per_reply=3, daily=4, clock=lambda: now[0])
    tool = web.tool()
    ok(tool == {"type": TOOL_TYPE, "name": "web_search", "max_uses": 3,
                "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"}}, tool)
    ok("allowed_domains" not in tool and "blocked_domains" not in tool, "no domain limits on the shared tool")
    ok(web.guide() == GUIDE, "guide while searches are left")
    web.spend(2)
    ok(web.left() == 2 and web.tool()["max_uses"] == 2, "max_uses never exceeds what is left today")
    web.spend(2)
    ok(web.left() == 0 and web.tool() is None and web.guide() == SPENT_GUIDE, "spent: no tool, say so")
    now[0] = kst(2026, 11, 16, 0, 1)  # 한국 날짜가 바뀌면 다시 셈
    ok(web.left() == 4 and web.tool()["max_uses"] == 3, "a new Korean day starts again")
    web.spend(0)
    web.spend(-1)
    ok(web.left() == 4, "nothing counted without searches")

    ok(turned_off(Refused("Error code: 400 - web search is not enabled for this organization")), "org off")
    ok(turned_off(Refused("tools.3.web_search_20250305.user_location: invalid")), "bad tool config")
    ok(not turned_off(Refused("messages: roles must alternate")), "other 400s are not about search")
    other = Refused("web search unavailable")
    other.status_code = 500
    ok(not turned_off(other), "not a 400")
    ok(web.turn_off(Refused("web search is not enabled")) and web.off, "turn off")
    ok(web.tool() is None and web.guide() == OFF_GUIDE, "off: no tool, say so")
    ok(not web.turn_off(Refused("web search is not enabled")), "only once")
    try:
        WebSearch(per_reply=0)
        ok(False, "per_reply 0 must fail")
    except ValueError:
        ok(True, "per_reply below 1 refused")

    # 글 잇기: 인용으로 쪼개진 글은 그대로 잇고, 검색 블록을 사이에 둔 글만 빈 줄로 나눈다.
    resp = ns(message([thinking(), text("잠깐 "), text("볼게"), *searched(), text("오늘 서울은 "), cited("맑고 18도래"),
                       text(" 겉옷 챙겨!")], usage=usage(1)))
    ok(text_of(resp) == "잠깐 볼게\n\n오늘 서울은 맑고 18도래 겉옷 챙겨!", text_of(resp))
    ok(text_of(ns(message([thinking(), text("안녕 "), text("반가워")]))) == "안녕 반가워", "plain text unchanged")
    ok(server_tool_counts(resp.usage) == (1, 0) and server_tool_counts(ns(message([text("x")])).usage) == (0, 0),
       "search counts from usage")
    ok(server_tool_counts(SimpleNamespace(server_tool_use=SimpleNamespace(web_search_requests=2,
                                                                          web_fetch_requests=None))) == (2, 0),
       "SDK-style usage object")

    # 출처: 인용된 검색 결과와 성공한 web_fetch 결과, 같은 주소는 한 번, 위험한 주소는 뺌.
    blocks = [cited("a"), cited("b"), cited("c", url=NEWS, title="뉴스 [속보] 제목"),
              cited("d", url="javascript:alert(1)"), cited("e", url="https://x.example/a b"),
              {"type": "web_fetch_tool_result", "tool_use_id": "srvtoolu_2",
               "content": {"type": "web_fetch_result", "url": "https://www.musinsa.com/products/1",
                           "content": {"type": "document", "title": "울 코트 | 무신사"}}},
              {"type": "web_fetch_tool_result", "tool_use_id": "srvtoolu_3",
               "content": {"type": "web_fetch_tool_result_error", "error_code": "url_not_accessible"}}]
    found = sources_of([SimpleNamespace(**b) for b in blocks])
    ok([s["url"] for s in found] == [WEATHER, "https://news.example.com/a%281%29", "https://www.musinsa.com/products/1"],
       found)
    line = sources_line(found + [{"url": "https://four.example/", "title": ""}])
    ok(line == "\n\n출처: [서울 날씨 - 기상청](https://www.weather.go.kr/w/index.do) · "
               "[뉴스 (속보) 제목](https://news.example.com/a%281%29) · "
               "[울 코트 | 무신사](https://www.musinsa.com/products/1)", line)
    ok(sources_line([]) == "", "no sources, no line")
    long = sources_line([{"url": "https://four.example/", "title": "가" * 60}, {"url": "https://five.example/x", "title": ""}])
    ok("가" * 39 + "…](https://four.example/)" in long and "[five.example](https://five.example/x)" in long, long)


# ── Agent.ask: 이어 받기·횟수·끄기 (DB 없이) ─────────────────────────

async def ask_checks():
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul")
    now = [kst(2026, 11, 15, 12, 0)]
    logs = Logs()
    logging.getLogger("marong.web").addHandler(logs)
    logging.getLogger("marong.web").setLevel(logging.INFO)
    msg = lambda: DiscordIncoming("discord-dm:x", "discord-user:x", "오늘 날씨 어때?")  # noqa: E731
    system = [{"type": "text", "text": "persona"}, {"type": "text", "text": "지금 상황\n\n" + GUIDE}]
    messages = [{"role": "user", "content": "오늘 날씨 어때?"}]
    end = lambda: asyncio.get_running_loop().time() + 30  # noqa: E731

    # pause_turn: 받은 블록을 그대로 assistant 로 돌려 보내고(새 user 말 없이) 이어 받은 글을 합친다.
    steps = iter([message([*searched(), text("서울은 맑대.")], stop_reason="pause_turn", usage=usage(1)),
                  message([*searched("서울 미세먼지", "srvtoolu_2", NEWS, "미세먼지 뉴스"), cited("미세먼지는 보통", NEWS, "미세먼지 뉴스")],
                          usage=usage(1))])
    llm = ScriptedLLM(lambda body: next(steps))
    web = WebSearch(daily=10, clock=lambda: now[0])
    agent = DiscordAgent(settings, None, FakeEmbeddings(), llm, web=web)
    m = msg()
    reply, meta = await agent.ask(system, messages, m, end())
    first, second = llm.bodies
    ok(reply == "서울은 맑대.\n\n미세먼지는 보통", reply)
    ok(meta["web_searches"] == 2 and meta["calls"] == 2 and meta["stop_reason"] == "end_turn", meta)
    ok(second["messages"][:-1] == messages and second["messages"][-1]["role"] == "assistant"
       and [b.type for b in second["messages"][-1]["content"]] == ["server_tool_use", "web_search_tool_result", "text"],
       "pause_turn continues with the paused content, no new user message")
    ok(first["tools"] == second["tools"] == [web.tool() | {"max_uses": 3}] and tool_names(first) == ["web_search"],
       "same single web_search tool in every request of the turn")
    ok(web.left() == 8 and [s["url"] for s in m.sources] == [NEWS.replace("(", "%28").replace(")", "%29")], m.sources)
    ok("서울 날씨" not in logs.text() and "web_search n=1 left=8" in logs.text(), "counts logged, queries not")

    # 검색 결과를 보고 쓴 글은 도구(일정) 호출 뒤 마지막 답 앞에 남기고, 그냥 도구 전 말은 버린다.
    steps2 = iter([message([*searched(), cited("내일 서울은 비 온대."), tool_use("schedule_list", {})],
                           stop_reason="tool_use", usage=usage(1)),
                   message([text("우산 챙겨!")])])
    llm2 = ScriptedLLM(lambda body: next(steps2))
    agent2 = DiscordAgent(settings, None, FakeEmbeddings(), llm2, web=WebSearch(clock=lambda: now[0]))
    reply, meta = await agent2.ask(system, messages, msg(), end())
    ok(reply == "내일 서울은 비 온대.\n\n우산 챙겨!", reply)
    steps3 = iter([message([text("잠깐 볼게"), tool_use("schedule_list", {})], stop_reason="tool_use"),
                   message([text("일정은 없어!")])])
    agent3 = DiscordAgent(settings, None, FakeEmbeddings(), ScriptedLLM(lambda body: next(steps3)),
                          web=WebSearch(clock=lambda: now[0]))
    reply, _ = await agent3.ask(system, messages, msg(), end())
    ok(reply == "일정은 없어!", "plain pre-tool words are still dropped")

    # 조직 설정에서 웹 검색이 꺼짐: 400 → 도구와 안내를 빼고 같은 답을 다시 만든다. 그 뒤로는 도구를 넣지 않는다.
    def refuse(body):
        if "web_search" in tool_names(body):
            return Refused("Error code: 400 - web search is not enabled for this organization")
        return message([text("지금은 인터넷을 못 찾아봐서 정확히는 몰라.")])
    llm4 = ScriptedLLM(refuse)
    web4 = WebSearch(clock=lambda: now[0])
    agent4 = DiscordAgent(settings, None, FakeEmbeddings(), llm4, web=web4)
    m4 = msg()
    reply, meta = await agent4.ask(system, messages, m4, end())
    ok(reply.startswith("지금은 인터넷을") and meta["web_search"] == "off" and web4.off, (reply, meta))
    retry = llm4.bodies[-1]
    ok("web_search" not in tool_names(retry) and OFF_GUIDE in situation(retry) and GUIDE not in situation(retry),
       "retry without the tool, and the guide says search is off")
    ok("web_search" not in tool_names(agent4._body(system, messages, agent4._tools(m4))), "stays off")
    ok("web_search off" in logs.text(), "logged once")

    # 다른 오류는 그대로 올린다(대체 문구는 _reply 가 정함). 도구를 직접 준 요청(선톡: tools=[])에는 검색이 없다.
    agent5 = DiscordAgent(settings, None, FakeEmbeddings(), ScriptedLLM(lambda body: Refused("messages: bad")),
                          web=WebSearch(clock=lambda: now[0]))
    try:
        await agent5.ask(system, messages, msg(), end())
        ok(False, "other errors must raise")
    except Refused:
        ok(not agent5.web.off, "other errors keep search on")
    llm6 = ScriptedLLM(lambda body: message([text("심심해서 톡했어")]))
    agent6 = DiscordAgent(settings, None, FakeEmbeddings(), llm6, web=WebSearch(clock=lambda: now[0]))
    await agent6.ask(system, messages, msg(), end(), tools=[])
    ok("tools" not in llm6.bodies[-1], "proactive (tools=[]) never searches")
    kakao = Agent(settings, None, FakeEmbeddings(), llm6)
    ok("web_search" not in tool_names(kakao._body(system, messages, kakao._tools(msg()))), "Kakao has no search")
    logging.getLogger("marong.web").removeHandler(logs)


# ── 디스코드 DM 흐름: 보내는 글의 출처, 기록, 하루 상한 ─────────────────────

async def dm_checks(db):
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul")  # as run_discord.py
    store = DiscordStore(db.app_url, call_bridge=True)
    await store.open(wait=True)
    try:
        now = [kst(2026, 11, 15, 20, 0)]

        def respond(body):
            if "web_search" in tool_names(body):
                return message([thinking(), *searched(), text("오늘 서울은 "), cited("맑고 18도래"), text(" 저녁엔 쌀쌀해.")],
                               usage=usage(1))
            return message([text("오늘은 검색을 다 써서 못 찾아봐 🥲")])
        llm = ScriptedLLM(respond)
        web = WebSearch(per_reply=3, daily=2, clock=lambda: now[0])
        agent = DiscordAgent(settings, store, FakeEmbeddings(), llm, web=web)
        client = Client(agent, store)
        channel = client.channels[DM_DH]
        room = f"discord-dm:{DH}"

        def last_reply():
            return db.admin("SELECT content, meta FROM marong.messages WHERE room_key=%s AND role='assistant' "
                            "ORDER BY id DESC LIMIT 1", (room,))[0]

        await client.on_message(dm(client, DH, DM_DH, 501, "오늘 서울 날씨 어때?"))
        body = llm.bodies[-1]
        ok(body["tools"][-1] == {"type": TOOL_TYPE, "name": "web_search", "max_uses": 2,
                                 "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"}},
           body["tools"])
        ok(tool_names(body).count("web_search") == 1 and GUIDE in situation(body), "one search tool and its guide")
        ok(channel.sent[-1] == "오늘 서울은 맑고 18도래 저녁엔 쌀쌀해.\n\n출처: [서울 날씨 - 기상청](https://www.weather.go.kr/w/index.do)",
           channel.sent[-1])
        content, meta = last_reply()
        ok(content == "오늘 서울은 맑고 18도래 저녁엔 쌀쌀해.", "the history keeps the answer without the source line")
        ok(meta["web_searches"] == 1 and meta["sources"] == [{"url": WEATHER, "title": "서울 날씨 - 기상청"}]
           and meta["delivered"] is True, meta)
        history = [m for m in llm.bodies[-1]["messages"]]
        ok(all("출처:" not in str(m["content"]) for m in history), "sources never go back to the model")

        await client.on_message(dm(client, DH, DM_DH, 502, "내일은?"))
        ok(web.left() == 0, "two searches spent today")
        await client.on_message(dm(client, DH, DM_DH, 503, "그럼 부산 날씨도 찾아 줘"))
        body = llm.bodies[-1]
        ok("web_search" not in tool_names(body) and SPENT_GUIDE in situation(body), "daily cap: no tool, say so")
        ok(channel.sent[-1] == "오늘은 검색을 다 써서 못 찾아봐 🥲", "no source line without a search")
        ok("sources" not in last_reply()[1], "no sources in the meta either")

        now[0] = kst(2026, 11, 16, 8, 0)
        await client.on_message(dm(client, DH, DM_DH, 504, "오늘 날씨는?"))
        ok("web_search" in tool_names(llm.bodies[-1]) and channel.sent[-1].endswith("index.do)"), "next day: back on")

        # 답이 실패해 대체 문구가 나가면 그 앞에 찾은 출처도 붙이지 않는다.
        calls = [0]

        def flaky(body):
            calls[0] += 1
            if calls[0] == 1:
                return message([*searched(), text("찾는 중")], stop_reason="pause_turn", usage=usage(1))
            return TimeoutError("fixture")
        agent.llm = ScriptedLLM(flaky)
        await client.on_message(dm(client, DH, DM_DH, 505, "환율 알려 줘"))
        ok(channel.sent[-1] == FALLBACK_TEXT and "sources" not in last_reply()[1], channel.sent[-1])

        # 긴 답이면 출처는 따로 한 메시지로 보낸다(링크가 2,000자에서 잘리지 않게).
        agent.llm = ScriptedLLM(lambda body: message([*searched(), cited("가" * 1790)], usage=usage(1)))
        before = len(channel.sent)
        await client.on_message(dm(client, DH, DM_DH, 506, "길게 알려 줘"))
        ok(len(channel.sent) == before + 2 and channel.sent[-1].startswith("출처: [서울 날씨"), channel.sent[before:])
    finally:
        await store.close()


if __name__ == "__main__":
    unit_checks()
    print("PASS web_search tool, limits (per reply, per Korean day), off switch, text joining, sources")
    asyncio.run(ask_checks())
    print("PASS ask loop: pause_turn, counts, kept search text, organization off → retry without the tool")
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(dm_checks(db))
        print("PASS DM flow: source line only in the sent DM, history and meta, daily cap, next day, fallback, long reply")
    finally:
        db.close()
    print(f"OK {CHECKS} checks")
