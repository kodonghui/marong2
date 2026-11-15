"""디스코드 DM 반응 달기 시험: '[반응 ❤️]' 표시 빼기, 고른 이모지만 달기(한숨 이모티콘 안 됨), 너무 잦지 않게,
답보다 먼저 달기, 실패해도 답은 감, 기록·로그에 표시나 친구 말이 안 남음, 카카오·선톡에는 안내가 없음,
인터넷 검색과 같이(출처 줄은 그대로, 검색이 꺼져 다시 답할 때도 안내와 반응이 남음).
진짜 Postgres(pgserver) + 가짜 디스코드 DM + 가짜 Claude. 네트워크·진짜 키·진짜 모델은 쓰지 않는다.
실행: .venv/bin/python tests/test_reactions.py"""
import asyncio
from dataclasses import replace
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import discord

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tools/vertex_live")]
from fakes import FakeEmbeddings, ScriptedLLM, message, text  # noqa: E402
from marong import reactions  # noqa: E402
from marong.agent import Agent, Incoming  # noqa: E402
from marong.config import load_settings  # noqa: E402
from marong.discord_dm import DiscordAgent, DiscordProactive  # noqa: E402
from marong.discord_store import DiscordStore  # noqa: E402
from marong.reactions import GAP_REPLIES, GAP_S, GUIDE, REACTIONS, pick, split  # noqa: E402
from marong.store import Store  # noqa: E402
from marong.web_search import GUIDE as WEB_GUIDE, OFF_GUIDE as WEB_OFF_GUIDE, WebSearch  # noqa: E402
from pg import TestDB  # noqa: E402
from test_discord_dm import DM_HK, HK, Client, prepare  # noqa: E402
from test_dm_help import Attachment, Logs, is_caption, png, situation  # noqa: E402

TZ = ZoneInfo("Asia/Seoul")
SIGH = "\U0001F62E\u200d\U0001F4A8"
HEART = "❤️"
TITLE = "# 반응 달기 (이 DM에서만)"
CHECKS = 0


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


class Msg:
    """디스코드 메시지 대신: 단 반응과 그때까지 채널에 간 답 수를 적는다."""

    def __init__(self, client, mid, content="", attachments=(), fail=None):
        self.guild, self.webhook_id, self.id = None, None, mid
        self.author = SimpleNamespace(id=int(HK), bot=False)
        self.channel = client.channels[DM_HK]
        self.type = discord.MessageType.default
        self.content, self.attachments, self.fail = content, list(attachments), fail
        self.pressed = []  # (emoji, number of replies already sent when it was pressed)

    async def add_reaction(self, emoji):
        self.pressed.append((emoji, len(self.channel.sent)))
        if self.fail:
            raise self.fail


# ── 표시 읽기 ──────────────────────────────────────────────

def mark_checks():
    ok(split("[반응 ❤️]\n고마워 나도 🥰") == ("고마워 나도 🥰", HEART), "mark on its own first line")
    ok(split("[반응: 😂] ㅋㅋㅋ 미쳤다") == ("ㅋㅋㅋ 미쳤다", "😂"), "colon, same line")
    ok(split("(반응 🎉)\n헐 대박!!\n\n축하해 진짜") == ("헐 대박!!\n\n축하해 진짜", "🎉"), "round brackets; bubbles kept")
    ok(split("고마워 [반응 ❤️] 진짜로") == ("고마워 진짜로", HEART), "mark inside a line")
    ok(split("그거 [반응 ❤️] 좋다\n\n[반응 😂]\n\n끝") == ("그거 좋다\n\n끝", HEART), "every mark goes, the first counts")
    for same in ("그냥 답이야 [괄호] (괄호)", "반응이 좋았대", "", "줄1\n\n\n줄2  끝 ", "[반응형 웹] 공부 중이야",
                 "그 영상 (반응 좋았던 거) 봤어?", "(반응 🤡) 이건 그냥 말"):
        ok(split(same) == (same, None), f"untouched: {same!r}")
    ok(split("[반응]") == ("", "") and split("[반응 ] 응") == ("응", "") and pick("") is None, "empty mark")
    ok(split("(반응 ❤) 고마워 [반응 없음]") == ("고마워", "❤"), "round brackets only around a listed emoji")
    ok(pick("\u2764") == HEART and pick(" \u2764\ufe0f ") == HEART and HEART == "\u2764\ufe0f", "heart in Discord's form")
    for bad in (SIGH, "\U0001F62E", "🤡", "❤️😂", "하트", ":heart:", None):
        ok(pick(bad) is None, f"not allowed: {bad!r}")
    ok(all(pick(e) == e for e in REACTIONS) and len(set(REACTIONS)) == len(REACTIONS), "every listed emoji works")
    ok(SIGH not in GUIDE and all("\U0001F62E" not in e for e in REACTIONS), "no sigh (or its face) anywhere")
    ok(all(e in GUIDE for e in REACTIONS) and "[반응 ❤️]" in GUIDE and "가끔만" in GUIDE, "the guide lists them")


# ── 디스코드 DM ────────────────────────────────────────────

async def dm_checks(db):
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul")  # as run_discord.py
    store = DiscordStore(db.app_url, call_bridge=True)
    kakao = Store(db.app_url, call_bridge=True)
    await store.open(wait=True)
    await kakao.open(wait=True)
    logs = Logs()
    for name in ("marong.discord", "agent"):
        logging.getLogger(name).addHandler(logs)
        logging.getLogger(name).setLevel(logging.INFO)
    try:
        replies = [""]

        def respond(body):
            if is_caption(body):
                return message([text("떡볶이 사진. 국물 떡볶이와 튀김")])
            return message([text(replies[0])])

        llm = ScriptedLLM(respond)
        clock = [1000.0]
        agent = DiscordAgent(settings, store, FakeEmbeddings(), llm, clock=lambda: clock[0])
        client = Client(agent, store)
        hk = client.channels[DM_HK]
        room = f"discord-dm:{HK}"
        mid = [700]

        async def say(content, reply, **kw):
            replies[0] = reply
            mid[0] += 1
            m = Msg(client, mid[0], content, **kw)
            before = len(hk.sent)
            await client.on_message(m)
            return m, before

        def last_reply():
            return db.admin("SELECT content, meta FROM marong.messages WHERE room_key=%s AND role='assistant' "
                            "ORDER BY id DESC LIMIT 1", (room,))[0]

        # 1) Good news: the emoji goes on the friend's message before the answer; the mark never shows.
        m, before = await say("나 오늘 면접 붙었어!!!", "[반응 🎉]\n헐 대박!! 축하해 진짜")
        ok(TITLE in situation(llm.bodies[-1]), "guide shown")
        ok(m.pressed == [("🎉", before)] and hk.sent[before:] == ["헐 대박!! 축하해 진짜"], (m.pressed, hk.sent[before:]))
        content, meta = last_reply()
        ok(content == "헐 대박!! 축하해 진짜" and meta["reaction"] == {"emoji": "🎉", "ok": True}, (content, meta))

        # 2) Not too often: the next GAP_REPLIES replies get no guide, and a stray mark is only removed.
        for i in range(GAP_REPLIES):
            m, before = await say(f"고마워 {i}", "[반응 ❤️] 응응 나도 좋아")
            ok(TITLE not in situation(llm.bodies[-1]), f"no guide right after a reaction ({i})")
            ok(m.pressed == [] and hk.sent[-1] == "응응 나도 좋아" and "reaction" not in last_reply()[1], i)
        m, before = await say("ㅋㅋㅋ 아까 팀장님 넘어졌어", "[반응 😂]\nㅋㅋㅋㅋ 미쳤다 괜찮으셔?")
        ok(TITLE in situation(llm.bodies[-1]) and m.pressed == [("😂", before)], "back after GAP_REPLIES replies")

        # ...or after GAP_S, even with fewer replies in between.
        await say("그치", "웅웅")
        ok(TITLE not in situation(llm.bodies[-1]), "still in the gap")
        clock[0] += GAP_S
        m, _ = await say("나 오늘 운동 2시간 했다", "와 진짜 열심히 했네")
        ok(TITLE in situation(llm.bodies[-1]) and m.pressed == [], "back after GAP_S; no mark, no reaction")

        # 3) Only listed emoji: the sigh face and unknown emoji are never pressed, and the text stays clean.
        for mark in (SIGH, "🤡", "❤️😂"):
            m, _ = await say("오늘 너무 힘들었어", f"[반응 {mark}]\n아이고 진짜 고생했다 " + SIGH)
            ok(m.pressed == [] and hk.sent[-1] == "아이고 진짜 고생했다", (mark, hk.sent[-1]))
            ok(TITLE in situation(llm.bodies[-1]), "a refused mark does not start the gap")
        ok(all(SIGH not in s and "[반응" not in s for s in hk.sent), "nothing leaks into sent text")

        # 4) A reply that is only a mark: the emoji is sent as the message, not pressed.
        m, before = await say("사랑해 마롱아", "[반응 \u2764]")
        ok(m.pressed == [] and hk.sent[before:] == [HEART] and last_reply()[0] == HEART, hk.sent[before:])
        m, before = await say("ㅎㅎ", "[반응 🤡]")
        ok(m.pressed == [] and hk.sent[before:] == [reactions.ALONE_TEXT], hk.sent[before:])

        # 5) Discord refuses the reaction: the answer still goes, the record says it failed, logs stay quiet.
        unknown = discord.HTTPException(SimpleNamespace(status=400, reason="fixture"),
                                        {"code": 10014, "message": "Unknown Emoji"})
        m, before = await say("나 자격증 땄어", "[반응 👏]\n오 대박 고생했다", fail=unknown)
        ok(m.pressed == [("👏", before)] and hk.sent[before:] == ["오 대박 고생했다"], hk.sent[before:])
        ok(last_reply()[1]["reaction"] == {"emoji": "👏", "ok": False}, last_reply()[1])
        ok("discord_reaction_failed HTTPException status=400 code=10014" in logs.text(), logs.text())

        # 6) A photo: the reaction goes on the photo message itself.
        clock[0] += GAP_S
        m, before = await say("", "[반응 😋]\n와 국물 떡볶이 최고지", attachments=[Attachment(png())])
        ok(m.pressed == [("😋", before)] and hk.sent[-1] == "와 국물 떡볶이 최고지", (m.pressed, hk.sent[-1]))

        # 7) The heart reaches Discord as U+2764 U+FE0F even when Marong writes it without the selector.
        clock[0] += GAP_S
        m, _ = await say("고마워 진짜", "[반응 \u2764]\n나도 고마워")
        ok(m.pressed[0][0] == "\u2764\ufe0f", m.pressed)

        stored = db.admin("SELECT content FROM marong.messages WHERE room_key=%s", (room,))
        ok(not any("[반응" in r[0] for r in stored), "no mark in the history")
        ok("면접" not in logs.text() and "떡볶이" not in logs.text(), "no friend or Marong text in logs")
        ok("discord_reaction emoji=🎉" in logs.text() and "discord_reaction_skipped why=gap" in logs.text(),
           "reactions and skips are logged")

        # 8) Proactive messages and Kakao get no reaction guide.
        db.admin("UPDATE marong.discord_dm_links SET last_incoming_at=now()-interval '2 hours', "
                 "opted_in_at=now()-interval '2 hours' WHERE room_key=%s", (room,))
        now = datetime(2026, 11, 13, 12, 0, tzinfo=TZ)

        async def no_sleep(_):
            return None
        replies[0] = "뭐 해?\n\n나 방금 군밤 샀어"
        plan = DiscordProactive(settings, store, agent, client, clock=lambda: now, rng=lambda: 0, sleep=no_sleep)
        ok(await plan.step(now) == 1 and TITLE not in json.dumps(llm.bodies[-1], ensure_ascii=False), "proactive")
        kakao_llm = ScriptedLLM(lambda _: message([text("응응")]))

        async def deliver(_):
            return True
        await Agent(settings, kakao, FakeEmbeddings(), kakao_llm).handle(Incoming("k-hk", "p-hk", "안녕"), deliver)
        ok(TITLE not in json.dumps(kakao_llm.bodies[-1], ensure_ascii=False), "Kakao")
    finally:
        for name in ("marong.discord", "agent"):
            logging.getLogger(name).removeHandler(logs)
        await store.close()
        await kakao.close()


# ── 인터넷 검색과 같이 ─────────────────────────────────────

class Refused(Exception):
    status_code = 400


def searches(body) -> bool:
    return any(t.get("name") == "web_search" for t in body.get("tools", []))


async def search_checks(db):
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul")  # as run_discord.py
    store = DiscordStore(db.app_url, call_bridge=True)
    await store.open(wait=True)
    try:
        url, title = "https://www.weather.go.kr/w/index.do", "서울 날씨 - 기상청"
        found = [{"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "서울 날씨"}},
                 {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
                  "content": [{"type": "web_search_result", "url": url, "title": title, "encrypted_content": "enc",
                               "page_age": None}]}]
        cited = {"type": "text", "text": "맑고 18도래", "citations": [
            {"type": "web_search_result_location", "url": url, "title": title, "cited_text": "맑음",
             "encrypted_index": "e"}]}
        used = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0,
                "server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0}}
        refuse = [False]

        def respond(body):
            if searches(body) and refuse[0]:
                return Refused("Error code: 400 - web search is not enabled for this organization")
            if searches(body):  # the mark comes before the search; the answer is written after it
                return message([text("[반응 👀] "), *found, text("오늘 서울은 "), cited, text(" 저녁엔 쌀쌀해.")], usage=used)
            return message([text("[반응 👀]\n지금은 인터넷을 못 찾아봐서 정확히는 몰라")])

        llm = ScriptedLLM(respond)
        clock = [1000.0]
        agent = DiscordAgent(settings, store, FakeEmbeddings(), llm, web=WebSearch(per_reply=3, daily=5),
                             clock=lambda: clock[0])
        client = Client(agent, store)
        hk = client.channels[DM_HK]
        room = f"discord-dm:{HK}"

        def last_reply():
            return db.admin("SELECT content, meta FROM marong.messages WHERE room_key=%s AND role='assistant' "
                            "ORDER BY id DESC LIMIT 1", (room,))[0]

        # 9) A searched answer with a reaction: the mark goes, the sources line stays under the answer (DM only).
        m = Msg(client, 901, "오늘 서울 날씨 어때?")
        before = len(hk.sent)
        await client.on_message(m)
        ok(WEB_GUIDE in situation(llm.bodies[-1]) and TITLE in situation(llm.bodies[-1]), "both guides")
        answer = "오늘 서울은 맑고 18도래 저녁엔 쌀쌀해."
        ok(m.pressed == [("👀", before)] and hk.sent[before:] == [f"{answer}\n\n출처: [{title}]({url})"],
           (m.pressed, hk.sent[before:]))
        content, meta = last_reply()
        ok(content == answer and meta["reaction"] == {"emoji": "👀", "ok": True}
           and meta["sources"] == [{"url": url, "title": title}], (content, meta))

        # 10) The API refuses web search: the retry without it keeps the reaction guide, and the reaction still goes.
        clock[0] += GAP_S
        refuse[0] = True
        m = Msg(client, 902, "내일 날씨는?")
        before = len(hk.sent)
        await client.on_message(m)
        retry = llm.bodies[-1]
        ok(not searches(retry) and WEB_OFF_GUIDE in situation(retry) and TITLE in situation(retry), "retry guides")
        ok(m.pressed == [("👀", before)] and hk.sent[before:] == ["지금은 인터넷을 못 찾아봐서 정확히는 몰라"],
           (m.pressed, hk.sent[before:]))
        meta = last_reply()[1]
        ok(meta["reaction"] == {"emoji": "👀", "ok": True} and meta["web_search"] == "off" and "sources" not in meta,
           meta)
    finally:
        await store.close()


if __name__ == "__main__":
    mark_checks()
    print("PASS reaction marks: removed from text, only listed emoji (no sigh), Discord's heart form")
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(dm_checks(db))
        print("PASS DM reactions: before the reply, not too often, refused emoji, failures, photos, no guide elsewhere")
        asyncio.run(search_checks(db))
        print("PASS reactions with web search: sources line kept, guide and reaction survive a refused-search retry")
    finally:
        db.close()
    print(f"OK {CHECKS} checks")
