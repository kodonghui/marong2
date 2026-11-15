"""DM 도우미 시험: 보내기 전 말 다듬기('야'로 부르기·한숨 이모티콘), 디스코드 DM 사진 받기, 쇼핑몰 상품 페이지
읽기(web_fetch 설정·하루 상한·안내), 공부·쇼핑 지시문. 진짜 Postgres(pgserver) + 가짜 디스코드 DM + 가짜 Claude
(서버 도구 응답 블록도 가짜). 네트워크·진짜 키·진짜 모델은 쓰지 않는다.
실행: .venv/bin/python tests/test_dm_help.py"""
import asyncio
from dataclasses import replace
from datetime import datetime
import io
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import discord
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tools/vertex_live")]
from fakes import FakeEmbeddings, ScriptedLLM, message, text  # noqa: E402
from marong.agent import ASK_OWNER_TOOL, PROACTIVE_GROUP_GUIDE, PROACTIVE_GUIDE, SET_NAME_TOOL, Agent, Incoming  # noqa: E402
from marong.config import load_settings  # noqa: E402
from marong.discord_dm import (FOLLOW_UP_S, PHOTOS_PER_MESSAGE, DiscordAgent, DiscordProactive,  # noqa: E402
                               DiscordReminders)
from marong.discord_store import DiscordStore  # noqa: E402
from marong.google_calendar import CONNECT_TEXT, LINK_MARK  # noqa: E402
from marong.photo import MAX_DOWNLOAD  # noqa: E402
from marong.schedules import SCHEDULE_TOOLS  # noqa: E402
from marong.shopping import FETCH_TOOL, MALL_NAMES, MALLS, ShopFetch, guide as shop_guide  # noqa: E402
from marong.store import Store  # noqa: E402
from marong.style import tidy, vocative  # noqa: E402
from pg import TestDB  # noqa: E402
from test_discord_dm import DH, DM_DH, DM_HK, HK, Client, prepare  # noqa: E402

TZ = ZoneInfo("Asia/Seoul")
SIGH = "\U0001F62E‍\U0001F4A8"
CHECKS = 0
CDN = "https://cdn.discordapp.com/attachments/1/2/page.png?ex=SIGNATURE-FIXTURE"


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


class Logs(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())

    def text(self):
        return "\n".join(self.lines)


def png(color=(200, 30, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (12, 8), color).save(out, "PNG")
    return out.getvalue()


class Attachment:
    def __init__(self, data=b"", content_type="image/png", size=None, fail=False):
        self.data, self.content_type, self.fail = data, content_type, fail
        self.size = len(data) if size is None else size
        self.filename, self.url, self.reads = "page.png", CDN, 0

    async def read(self):
        self.reads += 1
        if self.fail:
            raise discord.HTTPException(SimpleNamespace(status=404, reason="fixture"), "gone")
        return self.data


def dm(client, user, channel, mid, content="", attachments=()):
    return SimpleNamespace(guild=None, author=SimpleNamespace(id=int(user), bot=False), channel=client.channels[channel],
                           webhook_id=None, id=mid, type=discord.MessageType.default, content=content,
                           attachments=list(attachments))


def images(body) -> int:
    return sum(1 for m in body["messages"] if isinstance(m["content"], list)
               for b in m["content"] if isinstance(b, dict) and b.get("type") == "image")


def situation(body) -> str:
    return body["system"][-1]["text"]


def is_caption(body) -> bool:
    return "tools" not in body and "system" not in body


# ── 말 다듬기 ──────────────────────────────────────────────

def style_checks():
    ok(tidy("야 뭐해", "현경") == ("현경아 뭐해", ["ya"]), "leading 야 becomes the name")
    ok(tidy("야! 뭐해", "동희") == ("동희야! 뭐해", ["ya"]), "name without final consonant")
    ok(tidy("야ㅋㅋ 뭐해") == ("ㅋㅋ 뭐해", ["ya"]), "without a name it is dropped")
    ok(tidy("야 뭐해\n\n야 근데 나 군밤 샀어 " + SIGH, "현경") == ("현경아 뭐해\n\n근데 나 군밤 샀어", ["sigh", "ya"]),
       "only the first call becomes the name; sigh removed")
    for same in ("야식 먹을래?", "야호 😆", "3시야! 잊지 마", "이제 야라고 안 할게", "그 얘기 진짜야?", "동희야 뭐해"):
        ok(tidy(same, "현경") == (same, []), f"untouched: {same}")
    ok(tidy("헐 " + SIGH + " 진짜?") == ("헐 진짜?", ["sigh"]), "sigh in the middle")
    ok(tidy(SIGH)[0] and tidy(SIGH)[0] != SIGH, "never empty")
    ok(tidy("앗 좀 늦었다 미안 🙏\n야 3시야!") == ("앗 좀 늦었다 미안 🙏\n3시야!", ["ya"]), "line start too")
    ok(vocative("현경이") == "현경아" and vocative("Jay") is None and vocative("") is None, "vocative")

    prompt = (ROOT / "prompt.md").read_text(encoding="utf-8")
    ok(SIGH not in prompt and "한숨 쉬는 이모티콘은 쓰지 마" in prompt, "prompt: no sigh example, rule present")
    ok("이름 없이 '야'라고 부르지 마" in prompt, "prompt: no bare 야")
    ok("'야 뭐해'" not in PROACTIVE_GUIDE.split("하지도")[0] and "'야', '야!'로 부르거나" in PROACTIVE_GUIDE
       and "'야', '야!'로 부르거나" in PROACTIVE_GROUP_GUIDE, "proactive guides")
    say = SCHEDULE_TOOLS[0]["input_schema"]["properties"]["say"]["description"]
    ok("'야 " not in say and "'야'로 시작하지 마" in say, "reminder example")
    ok("# 공부 같이 하기" in prompt and "# 같이 고르기" in prompt, "study and shopping sections")
    ok("물건 가격은 '지금 상황'에 쇼핑 검색 안내가 있을 때만" in prompt, "prices only with the tool")


# ── 쇼핑몰 상품 페이지 읽기 ──────────────────────────────────

def shop_checks():
    ok(FETCH_TOOL["type"] == "web_fetch_20250910" and FETCH_TOOL["name"] == "web_fetch", FETCH_TOOL)
    ok(FETCH_TOOL["allowed_domains"] == list(MALLS) and "blocked_domains" not in FETCH_TOOL, "mall domains only")
    ok(FETCH_TOOL["max_uses"] == 2 and 0 < FETCH_TOOL["max_content_tokens"] <= 20000, FETCH_TOOL)
    ok(all(d.isascii() and d == d.lower() and d.count(".") >= 1 and not any(c in d for c in "/*: ")
           and not d.startswith("www.") for d in MALLS), "bare ASCII domains (web_fetch matches domains, not paths)")
    ok({"musinsa.com", "29cm.co.kr", "wconcept.co.kr", "zigzag.kr", "oliveyoung.co.kr"} <= set(MALLS), MALLS)
    ok(not {"thehandsome.com", "brandi.co.kr"} & set(MALLS), "malls whose robots.txt blocks product pages are out")
    ok(len(MALL_NAMES.split("·")) == len(MALLS) == len(set(MALLS)), "one name per mall")

    logs = Logs()
    logging.getLogger("marong.shop").addHandler(logs)
    now = [datetime(2026, 11, 15, 23, 59, tzinfo=TZ).timestamp()]
    shop = ShopFetch(3, clock=lambda: now[0])
    tool = shop.tool()
    ok(tool == FETCH_TOOL and tool is not FETCH_TOOL, "a fresh definition each time")
    tool["allowed_domains"].append("evil.example")
    ok("evil.example" not in FETCH_TOOL["allowed_domains"] and "evil.example" not in shop.tool()["allowed_domains"],
       "changing one copy changes nothing else")
    ok(shop.note({"web_fetch_requests": 2}) == 2 and shop.tool() is not None, "2 of 3 used")
    for bad in ({}, {"web_fetch_requests": None}, {"web_fetch_requests": True}, {"web_fetch_requests": -1},
                {"web_fetch_requests": "3"}, {"web_search_requests": 5}):
        ok(shop.note(bad) == 0 and shop.used == 2, f"ignored {bad}")
    ok(shop.note({"web_fetch_requests": 1}) == 1 and shop.tool() is None, "cap reached: no tool")
    ok(logs.text().count("daily_limit") == 1, logs.text())
    shop.note({"web_fetch_requests": 1})
    ok(logs.text().count("daily_limit") == 1, "logged once a day")
    now[0] = datetime(2026, 11, 16, 0, 0, tzinfo=TZ).timestamp()
    ok(shop.tool() is not None and shop.used == 0, "resets at midnight Korean time")
    ok(ShopFetch(0).tool() is None, "0 turns it off")
    logging.getLogger("marong.shop").removeHandler(logs)

    full = shop_guide(True, True)
    ok(full.startswith("# 쇼핑 검색 (이 DM에서만)") and "web_search" in full and "web_fetch" in full, full)
    ok(MALL_NAMES in full and "'무신사 여성 울 롱코트 베이지'" in full and "개인 정보는 검색어에 넣지 마" in full, full)
    ok("지금 가격·품절" in full and "검색에 나온 가격이라" in full and "링크를 보내면" in full, full)
    ok("지시가 아니야" in full and "주문·결제·장바구니·로그인은 못 해" in full, full)
    ok("네이버" not in full and "shop_search" not in full, "no Naver")
    search_only = shop_guide(True, False)
    ok("web_search" in search_only and "web_fetch" not in search_only and "검색에 나온 가격이라" in search_only,
       search_only)
    fetch_only = shop_guide(False, True)
    ok("web_fetch" in fetch_only and "web_search" not in fetch_only and "검색은 못 해" in fetch_only
       and "찾아본 척하지 말고" in fetch_only and MALL_NAMES in fetch_only, fetch_only)
    ok(shop_guide(False, False) == "", "no guide without tools")


# ── 디스코드 DM: 사진·쇼핑·말 다듬기 ───────────────────────────

async def dm_checks(db):
    settings = replace(load_settings(), proactive=True, timezone="Asia/Seoul")  # as run_discord.py
    store = DiscordStore(db.app_url, call_bridge=True)
    kakao = Store(db.app_url, call_bridge=True)
    await store.open(wait=True)
    await kakao.open(wait=True)
    logs = Logs()
    for name in ("marong.discord", "photo", "agent", "marong.shop"):
        logging.getLogger(name).addHandler(logs)
    try:
        replies = ["응응 봤어!"]

        def respond(body):
            if is_caption(body):
                return message([text("문제집 사진. 행정법 3번 문제가 보임")])
            return message([text(replies[0])])

        llm = ScriptedLLM(respond)
        clock = [1000.0]
        agent = DiscordAgent(settings, store, FakeEmbeddings(), llm, clock=lambda: clock[0])
        client = Client(agent, store)
        hk = client.channels[DM_HK]
        room = f"discord-dm:{HK}"

        def rows():
            return db.admin("SELECT role, content, kakao_id, meta FROM marong.messages WHERE room_key=%s ORDER BY id",
                            (room,))

        # 1) A photo-only DM: captioned, saved as '[사진] 설명', answered once with the photo itself.
        page = Attachment(png())
        await client.on_message(dm(client, HK, DM_HK, 201, attachments=[page]))
        cap, answer = llm.bodies[-2], llm.bodies[-1]
        ok(is_caption(cap) and "디스코드 DM으로 보낸 사진" in json.dumps(cap, ensure_ascii=False), "caption prompt")
        ok(images(answer) == 1 and hk.sent == ["응응 봤어!"], "the reply sees the photo")
        user = [r for r in rows() if r[0] == "user"]
        ok(user[-1][1] == "[사진] 문제집 사진. 행정법 3번 문제가 보임" and user[-1][2] == "discord:201", user[-1])
        ok(page.reads == 1 and "SIGNATURE-FIXTURE" not in logs.text(), "read once, address never logged")

        # 2) The same page stays visible for a follow-up question, then expires.
        await client.on_message(dm(client, HK, DM_HK, 202, "그럼 5번은?"))
        ok(images(llm.bodies[-1]) == 1, "follow-up still sees the page")
        clock[0] += FOLLOW_UP_S + 1
        await client.on_message(dm(client, HK, DM_HK, 203, "7번도"))
        ok(images(llm.bodies[-1]) == 0, "after the follow-up window only the caption remains")

        # 3) Two photos and text in one message: three saved lines, one reply that sees both photos.
        n = len(llm.bodies)
        await client.on_message(dm(client, HK, DM_HK, 204, "둘 중 뭐가 나아?",
                                   [Attachment(png()), Attachment(png((0, 0, 200)))]))
        ok(len(llm.bodies) == n + 3 and images(llm.bodies[-1]) == 2, "two captions, one reply with both photos")
        tail = rows()[-4:]
        ok([r[2] for r in tail[:3]] == ["discord:204:1", "discord:204:2", "discord:204"]
           and tail[2][1] == "둘 중 뭐가 나아?" and tail[3][0] == "assistant", tail)
        ok(len(hk.sent) == 4, "one reply per Discord message")

        # 3b) A photo sent with the exact '구글 캘린더 연결' phrase: the photo is kept, the command still answers,
        #     and the one-time link goes out only in the DM while the history keeps the mark.
        class LinkOnly:  # just enough of GoogleCalendar for the connect phrase
            def new_link(self, friend_id):
                self.friend_id = friend_id
                return "https://calendar-link.test/ONE-TIME"
        agent.google = LinkOnly()
        try:
            await client.on_message(dm(client, HK, DM_HK, 209, "구글 캘린더 연결", [Attachment(png())]))
        finally:
            agent.google = None
        ok(hk.sent[-1] == CONNECT_TEXT.replace(LINK_MARK, "https://calendar-link.test/ONE-TIME"), hk.sent[-1])
        tail = rows()[-3:]
        ok([r[2] for r in tail[:2]] == ["discord:209:1", "discord:209"] and tail[0][1].startswith("[사진] ")
           and LINK_MARK in tail[2][1] and "ONE-TIME" not in tail[2][1], tail)

        # 4) Files that are not photos, too big, unreadable, or too many: no download, honest notes.
        pdf, big, broken = Attachment(b"%PDF-1.7", "application/pdf"), Attachment(png(), size=MAX_DOWNLOAD + 1), \
            Attachment(png(), fail=True)
        await client.on_message(dm(client, HK, DM_HK, 205, "이거 봐 줘", [pdf, big, broken]))
        notes = [r[1] for r in rows()[-5:-2]]  # three notes, then the text, then the reply
        ok(notes == ["[사진] (사진이 아닌 파일이라 못 열었어)", "[사진] (사진이 너무 커서 못 열었어)", "[사진] (사진이 안 열렸어)"],
           notes)
        ok(pdf.reads == 0 and big.reads == 0 and broken.reads == 1, "no download for non-photos or huge files")
        many = [Attachment(png()) for _ in range(PHOTOS_PER_MESSAGE + 2)]
        await client.on_message(dm(client, HK, DM_HK, 206, attachments=many))
        ok(sum(a.reads for a in many) == PHOTOS_PER_MESSAGE and rows()[-2][1].endswith("나머지는 못 열었어)"),
           "only the first photos open; the rest is noted")
        ok("SIGNATURE-FIXTURE" not in logs.text(), "attachment addresses stay out of logs")

        # 5) Replies and proactive messages: no bare '야', no sigh emoji, in what is sent and stored.
        replies[0] = "야! 그거 완전 좋다 " + SIGH
        await client.on_message(dm(client, HK, DM_HK, 207, "나 오늘 공부 6시간 했어"))
        ok(hk.sent[-1] == "현경아! 그거 완전 좋다", hk.sent[-1])
        last = rows()[-1]
        ok(last[1] == hk.sent[-1] and last[3]["tidy"] == ["sigh", "ya"], last)
        replies[0] = "야 뭐해\n\n나 방금 군밤 샀어 " + SIGH
        db.admin("UPDATE marong.discord_dm_links SET last_incoming_at=now()-interval '2 hours', "
                 "opted_in_at=now()-interval '2 hours' WHERE room_key=%s", (room,))
        now = datetime(2026, 11, 13, 12, 0, tzinfo=TZ)

        async def no_sleep(_):
            return None
        plan = DiscordProactive(settings, store, agent, client, clock=lambda: now, rng=lambda: 0, sleep=no_sleep)
        before = len(hk.sent)
        ok(await plan.step(now) == 1 and hk.sent[before:] == ["현경아 뭐해", "나 방금 군밤 샀어"], hk.sent[before:])
        ok(rows()[-1][3]["tidy"] == ["sigh", "ya"], "proactive meta notes the fix")

        # 6) Kakao 1:1 replies get the same treatment; Kakao tools are unchanged.
        kakao_llm = ScriptedLLM(lambda _: message([text("야 반가워 " + SIGH)]))
        kakao_agent = Agent(settings, kakao, FakeEmbeddings(), kakao_llm)
        sent = []

        async def deliver(body):
            sent.append(body)
            return True
        await kakao_agent.handle(Incoming("k-hk", "p-hk", "안녕"), deliver)
        ok(sent == ["현경아 반가워"], sent)
        ok(kakao_agent._tools(Incoming("k-hk", "p-hk", "x")) == [SET_NAME_TOOL, ASK_OWNER_TOOL], "Kakao tools")

        # 7) Shopping: page reads (web_fetch, malls only) come with a ShopFetch, the guide follows the tools this reply
        #    gets, reads are counted per Korean day from usage and stop at the cap. Search is the shared web_search.
        names = {t["name"] for t in agent._tools(SimpleNamespace(friend_id=2))}
        ok("web_fetch" not in names, "no ShopFetch, no page reads")
        ok(shop_guide("web_search" in names, False) in situation(llm.bodies[-1]), "guide without page reads")
        day = [datetime(2026, 11, 15, 20, 0, tzinfo=TZ).timestamp()]
        shop = ShopFetch(2, clock=lambda: day[0])
        page = "https://www.musinsa.com/products/1234567"

        def shopping(body):
            if is_caption(body):
                return message([text("코트 사진")])
            if not any(t["name"] == "web_fetch" for t in body.get("tools", [])):
                return message([text("지금은 페이지를 못 읽어서 고르는 기준만 얘기할게")])
            return message(
                [{"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_fetch", "input": {"url": page}},
                 {"type": "web_fetch_tool_result", "tool_use_id": "srvtoolu_1",
                  "content": {"type": "web_fetch_result", "url": page, "retrieved_at": "2026-11-15T11:00:00Z",
                              "content": {"type": "document", "title": "울 롱코트",
                                          "source": {"type": "text", "media_type": "text/plain",
                                                     "data": "울 롱코트 89,000원 재고 있음"}}}},
                 text("이거 어때? 지금 89,000원이고 울이야 " + page)],
                usage={"input_tokens": 900, "output_tokens": 40, "cache_read_input_tokens": 0,
                       "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 1}})
        shop_llm = ScriptedLLM(shopping)
        shop_agent = DiscordAgent(settings, store, FakeEmbeddings(), shop_llm, shop=shop)
        shop_client = Client(shop_agent, store)
        dh = shop_client.channels[DM_DH]
        await shop_client.on_message(dm(shop_client, DH, DM_DH, 301, "10만 원 안쪽 울 코트 찾아 줘"))
        first = shop_llm.bodies[-1]
        names = {t["name"] for t in first["tools"]}
        ok(next(t for t in first["tools"] if t["name"] == "web_fetch") == FETCH_TOOL, first["tools"])
        ok({"schedule_add", "schedule_cancel", "schedule_list", "web_fetch"} <= names, names)
        ok(shop_guide("web_search" in names, True) in situation(first), "guide matches the tools")
        ok(dh.sent and dh.sent[0].startswith("이거 어때? 지금 89,000원"), dh.sent)
        ok(shop.used == 1, "one page read counted")
        saved = db.admin("SELECT meta FROM marong.messages WHERE room_key=%s AND role='assistant' ORDER BY id DESC "
                         "LIMIT 1", (f"discord-dm:{DH}",))[0][0]
        ok(saved.get("web_fetch_requests") == 1 and "shop" not in saved, saved)
        ok(page not in logs.text() and "1234567" not in logs.text(), "no page address in logs")

        await shop_client.on_message(dm(shop_client, DH, DM_DH, 302, "그럼 니트도"))
        ok(shop.used == 2 and shop.tool() is None, "the second read reaches today's cap")
        await shop_client.on_message(dm(shop_client, DH, DM_DH, 303, "하나만 더 봐 줘"))
        last = shop_llm.bodies[-1]
        names = {t["name"] for t in last["tools"]}
        ok("web_fetch" not in names and shop_guide("web_search" in names, False) in situation(last), "capped reply")
        ok(dh.sent[-1].startswith("지금은 페이지를 못 읽어서"), dh.sent[-1])
        day[0] = datetime(2026, 11, 16, 0, 1, tzinfo=TZ).timestamp()
        await shop_client.on_message(dm(shop_client, DH, DM_DH, 304, "오늘 다시 찾아 줘"))
        ok(any(t["name"] == "web_fetch" for t in shop_llm.bodies[-1]["tools"]) and shop.used == 1, "back the next day")

        # 8) Reminders sent later drop a leading '야' too.
        reminders = DiscordReminders(settings, store, agent, client)
        sid = db.admin("INSERT INTO marong.schedules(friend_id, room_key, source, title, remind_at, say) VALUES "
                       "(2, %s, 'discord', '토익', now() - interval '5 seconds', '야 3시야! 토익 잊지 마') RETURNING id",
                       (room,))[0][0]
        before = len(hk.sent)
        ok(await reminders.step() == 1 and hk.sent[before:] == ["3시야! 토익 잊지 마"], (sid, hk.sent[before:]))
    finally:
        for name in ("marong.discord", "photo", "agent", "marong.shop"):
            logging.getLogger(name).removeHandler(logs)
        await store.close()
        await kakao.close()


if __name__ == "__main__":
    style_checks()
    print("PASS outgoing text: no bare '야', no sigh emoji; prompts say the same")
    shop_checks()
    print("PASS mall page reads: web_fetch definition, mall domains, daily cap in Korean time, guide follows the tools")
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(dm_checks(db))
        print("PASS DM photos, follow-up window, file limits, tidy replies/proactive/reminders, mall page reads")
    finally:
        db.close()
    print(f"OK {CHECKS} checks")
