"""Channels of the private Discord server (2026-11-15): Marong reads everything linked friends say there, answers only
when called or right after its answer, keeps the channel apart from DMs, Kakao and calls. Real Postgres, fake Discord/LLM."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from zoneinfo import ZoneInfo

import discord
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools/vertex_live")]
from call_memory import MemoryStore, Principal
from fakes import FakeEmbeddings, ScriptedLLM, message, text
from marong.config import load_settings
from marong.discord_dm import (CHANNEL_HEAD, CHANNEL_SYSTEM, DM_SYSTEM, FOLLOW_LINE, HEARD_TITLE, DiscordAgent,
                               DiscordDM, vocative_pattern)
from marong.discord_store import DiscordStore
from marong.memory import MemoryWorker
from marong.store import Store
from pg import TestDB
from psycopg.rows import dict_row
from test_discord_dm import DH, DM_DH, DM_HK, HK, OTHER, Channel as DMChannel, event, prepare
from tools.report import build

GUILD, ROLE, MARONG = 456, 777, 123
TEXT, THREAD, VOICE, OTHER_GUILD_TEXT = 200000000000000001, 200000000000000002, 200000000000000003, 200000000000000004
KLONG = "100000000000000009"  # another bot in the server
ROOM = f"discord-ch:{TEXT}"
TZ = ZoneInfo("Asia/Seoul")


class TextChannel:
    def __init__(self, channel_id, kind=discord.ChannelType.text):
        self.id = channel_id
        self.type = kind
        self.sent = []  # (text, kwargs)
        self.refuse_reference = False

    async def send(self, content, **kwargs):
        assert kwargs["allowed_mentions"].to_dict() == {"parse": []}
        if kwargs.get("reference") is not None and self.refuse_reference:
            raise discord.HTTPException(SimpleNamespace(status=400, reason="fixture"), {"code": 50035, "message": "x"})
        self.sent.append((content, kwargs))


class Msg:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.reacted = []

    def to_reference(self, *, fail_if_not_exists=True):
        return ("ref", self.id, fail_if_not_exists)

    async def add_reaction(self, emoji):
        self.reacted.append(emoji)


class Client(DiscordDM):
    def __init__(self, agent, store, clock, **kwargs):
        super().__init__(agent, store, MARONG, GUILD, clock=clock, **kwargs)
        self.available = True
        self.text, self.thread = TextChannel(TEXT), TextChannel(THREAD, discord.ChannelType.public_thread)
        self.voice = TextChannel(VOICE, discord.ChannelType.voice)
        self.channels = {DM_DH: DMChannel(DM_DH, DH), DM_HK: DMChannel(DM_HK, HK)}

    async def fetch_channel(self, channel_id):
        return self.channels[channel_id]

    def get_partial_messageable(self, channel_id, **kwargs):
        return self.channels[channel_id]


def chat(client, user, mid, content, *, channel=None, bot=False, name=None, mentions=(), roles=(), reply_to=None,
         attachments=(), clean=None, guild=GUILD, webhook=None, everyone=False):
    resolved = None if reply_to is None else SimpleNamespace(author=SimpleNamespace(id=int(reply_to)))
    return Msg(guild=SimpleNamespace(id=guild, self_role=SimpleNamespace(id=ROLE)),
               author=SimpleNamespace(id=int(user), bot=bot, display_name=name or "손님", name="guest"),
               channel=channel or client.text, webhook_id=webhook, id=mid, type=discord.MessageType.default,
               content=content, clean_content=content if clean is None else clean,
               mentions=[SimpleNamespace(id=int(m)) for m in mentions], raw_role_mentions=list(roles),
               role_mentions=[SimpleNamespace(id=r) for r in roles if r != ROLE], mention_everyone=everyone,
               reference=None if resolved is None else SimpleNamespace(resolved=resolved), attachments=list(attachments),
               created_at=datetime.now(timezone.utc))


def rows(db, room=ROOM):
    return db.admin("SELECT role, user_key, content, meta FROM marong.messages WHERE room_key=%s ORDER BY id", (room,))


def body_text(body) -> str:
    return json.dumps(body, ensure_ascii=False)


def situation(body) -> str:
    """The non-cached system block: the situation (the cached one is prompt.md, which mentions DM features)."""
    return body["system"][-1]["text"]


def private_part(body) -> str:
    """What a reply sees besides the persona: the situation and the conversation."""
    return situation(body) + json.dumps(body["messages"], ensure_ascii=False)


class Attachment:
    content_type, size = "application/pdf", 10

    async def read(self):
        raise AssertionError("a non-image attachment is never downloaded")


async def check(db):
    settings = replace(load_settings(), reply_wait_s=0)
    store = DiscordStore(db.app_url, call_bridge=True)
    kakao = Store(db.app_url, call_bridge=True)
    kakao.discord_context_enabled = True
    await store.open(wait=True)
    await kakao.open(wait=True)
    now = [1000.0]
    clock = lambda: now[0]
    replies = []

    def answer(body):
        return message([text(replies.pop(0) if replies else "응 듣고 있어.")])

    try:
        emb = FakeEmbeddings()
        llm = ScriptedLLM(answer)
        agent = DiscordAgent(settings, store, emb, llm, clock=clock)
        client = Client(agent, store, clock, follow_s=120)
        assert client._connection._intents.guild_messages and not client._connection._intents.message_content

        # A friend's own DM first: it must never reach the channel.
        await client.on_message(event(client, HK, DM_HK, 1, "DM_ONLY_SECRET 현경 비밀 얘기"))
        assert len(llm.bodies) == 1 and DM_SYSTEM in body_text(llm.bodies[0])
        assert CHANNEL_SYSTEM not in body_text(llm.bodies[0])

        # Ignored: another server, a webhook, a voice channel's chat, Marong's own message, words the Gateway left
        # empty (no Message Content intent), and a repeated message.
        for msg in (chat(client, HK, 10, "다른 서버", guild=999), chat(client, HK, 11, "웹훅", webhook=5),
                    chat(client, HK, 12, "음성 채널 채팅", channel=client.voice),
                    chat(client, MARONG, 13, "마롱이 자기 말", bot=True), chat(client, HK, 14, "")):
            await client.on_message(msg)
        assert not rows(db) and len(llm.bodies) == 1 and not client.text.sent and not client.heard
        print("PASS other servers, webhooks, voice chats, Marong itself and empty words are ignored")

        # Other bots and people not linked: read for a while only, never stored or answered.
        await client.on_message(chat(client, KLONG, 20, "KLONG_SAID 오늘 서울 비 온대", bot=True, name="클롱이"))
        await client.on_message(chat(client, OTHER, 21, "GUEST_SAID 마롱아 안녕", name="손님"))
        assert not rows(db) and len(llm.bodies) == 1 and not client.text.sent
        assert [line[1:] for line in client._heard_lines(ROOM)] == [
            ("클롱이(봇)", "KLONG_SAID 오늘 서울 비 온대"), ("손님", "GUEST_SAID 마롱아 안녕")]
        print("PASS other bots and unlinked people are only heard, never stored or answered")

        # Linked friends' words are stored even when nobody calls Marong; nothing is answered.
        await client.on_message(chat(client, HK, 30, "CHANNEL_ONLY_TALK 오늘 저녁 뭐 먹을까"))
        await client.on_message(chat(client, DH, 31, "DH_CHANNEL_TALK 마롱이가 그랬는데 떡볶이 맛집 있대"))
        await client.on_message(chat(client, DH, 31, "DH_CHANNEL_TALK 마롱이가 그랬는데 떡볶이 맛집 있대"))  # again
        stored = rows(db)
        assert [(r[0], r[1], r[2]) for r in stored] == [
            ("user", f"discord-user:{HK}", "CHANNEL_ONLY_TALK 오늘 저녁 뭐 먹을까"),
            ("user", f"discord-user:{DH}", "DH_CHANNEL_TALK 마롱이가 그랬는데 떡볶이 맛집 있대")]
        assert len(llm.bodies) == 1 and not client.text.sent
        print("PASS linked friends' channel words are stored without a call and without an answer")

        # A call by name: one answer, as a reply to that message, with everyone's words and their names.
        replies.append("나는 떡볶이 좋아!")
        call = chat(client, DH, 32, "마롱아 너는 뭐 먹고 싶어? 떡볶이 어때")
        await client.on_message(call)
        assert len(llm.bodies) == 2 and client.text.sent == [
            ("나는 떡볶이 좋아!", {"allowed_mentions": client.text.sent[0][1]["allowed_mentions"],
                                  "suppress_embeds": True, "reference": ("ref", 32, False), "mention_author": False})]
        body, said = situation(llm.bodies[-1]), private_part(llm.bodies[-1])
        assert CHANNEL_HEAD in body and CHANNEL_SYSTEM in body and DM_SYSTEM not in body
        assert "현경: CHANNEL_ONLY_TALK" in said and "동희: DH_CHANNEL_TALK" in said
        assert "동희: 마롱아 너는 뭐 먹고 싶어?" in said
        assert HEARD_TITLE in body and "클롱이(봇): KLONG_SAID" in body and "손님: GUEST_SAID" in body
        assert "이어진 친구: 동희, 현경" in body
        for private in ("DM_ONLY_SECRET", "HK_OWN_KAKAO", "DH_OWN_KAKAO", "PRIVATE_GROUP_MARKER",
                        "PRIVATE_MIXED_SUMMARY"):
            assert private not in body_text(llm.bodies[-1]), private
        for dm_only in ("선톡", "schedule_add", "ask_owner", "구글 캘린더 연결", FOLLOW_LINE):
            assert dm_only not in body, dm_only
        assert not [t for t in llm.bodies[-1].get("tools", []) if t.get("name", "").startswith("schedule")]
        last = rows(db)[-1]
        assert last[0] == "assistant" and last[2] == "나는 떡볶이 좋아!" and last[3]["channel"] == "call"
        assert last[3]["memory"]["recall"] == "ok" and last[3]["delivered"] is True
        print("PASS a call is answered as a reply, with every friend's name and no DM, Kakao or schedule context")

        # Right after the answer the same friend goes on without calling: answered as a follow-up.
        n = len(llm.bodies)
        now[0] += 30
        replies.append("오 거기 가자!")
        await client.on_message(chat(client, DH, 33, "그럼 이따 같이 가자"))
        assert len(llm.bodies) == n + 1 and client.text.sent[-1][0] == "오 거기 가자!"
        assert FOLLOW_LINE in situation(llm.bodies[-1]) and rows(db)[-1][3]["channel"] == "follow"
        # ... until they turn to someone else by name: stored, not answered, and the follow-up window is over.
        now[0] += 10
        await client.on_message(chat(client, DH, 34, "현경아 너도 갈 거지?"))
        await client.on_message(chat(client, DH, 35, "그럼 7시에 보자"))
        assert len(llm.bodies) == n + 1 and [r[2] for r in rows(db)[-2:]] == ["현경아 너도 갈 거지?", "그럼 7시에 보자"]
        print("PASS a follow-up right after the answer is answered, and calling another friend by name ends it")

        n = len(llm.bodies)
        replies.append("응응 나도 7시 좋아")
        await client.on_message(chat(client, DH, 36, "마롱이 너도 7시 괜찮아?"))
        assert len(llm.bodies) == n + 1 and client.text.sent[-1][0] == "응응 나도 7시 좋아"
        await client.on_message(chat(client, HK, 37, "나 7시 좋아"))  # another friend joins in
        await client.on_message(chat(client, DH, 38, "오케이 그럼 확정"))
        assert len(llm.bodies) == n + 1, "another friend joined in, so 동희's next word is not for Marong"
        replies.append("확정!")
        await client.on_message(chat(client, DH, 39, "마롱 확인했지?"))
        now[0] += 121
        await client.on_message(chat(client, DH, 40, "근데 비 오면 어쩌지"))
        assert len(llm.bodies) == n + 2, "the follow-up window passed"
        replies.append("우산 챙기자")
        await client.on_message(chat(client, DH, 41, "마롱아"))
        await client.on_message(chat(client, DH, 42, "있대", reply_to=HK))
        assert len(llm.bodies) == n + 3, "a reply to someone else is not a follow-up"
        replies.append("응 챙겨")
        await client.on_message(chat(client, DH, 43, "마롱아 우산 챙겨 줘"))
        await client.on_message(chat(client, DH, 44, "@현경 우산 있어?", mentions=[HK], clean="@현경 우산 있어?"))
        assert len(llm.bodies) == n + 4, "a mention of someone else is not a follow-up"
        assert "마롱이가 그랬는데" in rows(db)[1][2] and len(llm.bodies) == n + 4
        print("PASS another friend joining in, a mention, a reply to someone else and the time limit end follow-ups")

        # Other ways to call: a reply to Marong's message, Marong's role, '@마롱이'.
        replies += ["답장 받았어", "역할로 불렀네", "응 불렀어?"]
        await client.on_message(chat(client, HK, 50, "이거 진짜야?", reply_to=MARONG))
        await client.on_message(chat(client, HK, 51, "@마롱이 안녕", roles=[ROLE], clean="@마롱이 안녕"))
        await client.on_message(chat(client, HK, 52, "<@123>", mentions=[MARONG], clean="@마롱이"))
        assert [s[0] for s in client.text.sent[-3:]] == ["답장 받았어", "역할로 불렀네", "응 불렀어?"]
        assert "현경: @마롱이" in private_part(llm.bodies[-1]) and "<@123>" not in body_text(llm.bodies[-1])
        print("PASS a reply to Marong, Marong's role and an @mention call it, stored as names not raw ids")

        # A quick burst ('마롱아' then the question) gets one answer, at the last message.
        agent.s = replace(settings, reply_wait_s=0.5)
        n = len(llm.bodies)
        now[0] += 500
        replies.append("둘 다 좋아!")
        first = asyncio.create_task(client.on_message(chat(client, DH, 60, "마롱아")))
        await asyncio.sleep(0.1)
        await client.on_message(chat(client, DH, 61, "짜장 짬뽕 뭐가 좋아?"))
        await first
        assert len(llm.bodies) == n + 1 and client.text.sent[-1][0] == "둘 다 좋아!"
        assert client.text.sent[-1][1]["reference"] == ("ref", 61, False)
        said = private_part(llm.bodies[-1])
        assert "동희: 마롱아" in said and "짜장 짬뽕" in said
        # ... while a word to someone else meanwhile does not cancel the waiting answer.
        now[0] += 500
        replies.append("나는 여기 있어")
        first = asyncio.create_task(client.on_message(chat(client, HK, 62, "마롱아 어디 있어?")))
        await asyncio.sleep(0.1)
        await client.on_message(chat(client, HK, 63, "동희야 너는?"))
        await first
        assert len(llm.bodies) == n + 2 and client.text.sent[-1] == (
            "나는 여기 있어", {**client.text.sent[-1][1], "reference": ("ref", 62, False)})
        agent.s = settings
        print("PASS a quick burst gets one answer, and a word to someone else does not cancel it")

        # Reactions work in a channel (here a thread, its own room), the reply still goes out as a reply.
        replies.append("[반응 😂] ㅋㅋㅋ 너무 웃기다")
        joke = chat(client, HK, 70, "마롱아 나 오늘 넘어졌어 ㅋㅋ", channel=client.thread)
        await client.on_message(joke)
        assert joke.reacted == ["😂"] and client.thread.sent[-1][0] == "ㅋㅋㅋ 너무 웃기다"
        assert "반응 달기" in situation(llm.bodies[-1]) and "이 채널에서도 똑같이 써" in situation(llm.bodies[-1])
        thread_rows = rows(db, f"discord-ch:{THREAD}")
        assert [r[2] for r in thread_rows] == ["마롱아 나 오늘 넘어졌어 ㅋㅋ", "ㅋㅋㅋ 너무 웃기다"]
        assert "CHANNEL_ONLY_TALK" not in private_part(llm.bodies[-1]), "a thread is its own room"
        # When Discord refuses the reply link (e.g. no Read Message History), the answer goes out as a plain message.
        client.thread.refuse_reference = True
        replies.append("그래도 보냈어")
        await client.on_message(chat(client, HK, 71, "마롱아 들려?", channel=client.thread))
        assert client.thread.sent[-1] == ("그래도 보냈어", {**client.thread.sent[-1][1]})
        assert "reference" not in client.thread.sent[-1][1]
        print("PASS reactions in a channel, a thread as its own room, and a refused reply link")

        # A file that is not a photo, without a call: stored as such, no answer and no model call.
        calls = len(llm.bodies)
        await client.on_message(chat(client, HK, 80, "", attachments=[Attachment()]))
        assert len(llm.bodies) == calls and rows(db)[-1][2].startswith("[사진]")
        print("PASS a non-photo attachment is stored without an answer or a model call")

        # The channel stays out of DMs, Kakao and calls.
        replies.append("DM 답장")
        await client.on_message(event(client, HK, DM_HK, 90, "DM 에서 하는 말 오늘 저녁 뭐 먹었는지 기억나?"))
        dm = private_part(llm.bodies[-1])
        assert DM_SYSTEM in dm and CHANNEL_SYSTEM not in dm and "DM_ONLY_SECRET" in dm
        for channel_word in ("CHANNEL_ONLY_TALK", "DH_CHANNEL_TALK", "KLONG_SAID", "GUEST_SAID", "짜장 짬뽕"):
            assert channel_word not in dm, channel_word
        hk_user_id = await kakao.add_message("k-hk", "user", "kakao continuity", "p-hk")
        assert "CHANNEL_ONLY_TALK" not in json.dumps(await kakao.discord_context("k-hk", "p-hk", hk_user_id),
                                                     ensure_ascii=False, default=str)
        call_store = MemoryStore(db.admin_url)
        await call_store.pool.open(wait=True)
        try:
            voice = await call_store.seed(Principal(1, 2, "현경"))
            assert "CHANNEL_ONLY_TALK" not in voice and "DH_CHANNEL_TALK" not in voice
        finally:
            await call_store.close()
        worker = MemoryWorker(settings, store, emb, llm)
        assert await worker.embed_pending() > 0
        hits = await store.similar(emb.model, ROOM, emb.vec("떡볶이 맛집"), before_id=10**12, skip_summary_ids=[],
                                   limit=50)
        hit_rooms = {r[0] for r in db.admin("SELECT room_key FROM marong.messages WHERE id = ANY(%s)",
                                            ([h["source_id"] for h in hits if h["source_type"] == "message"],))}
        assert hits and hit_rooms == {ROOM}
        dm_hits = await store.similar(emb.model, f"discord-dm:{HK}", emb.vec("떡볶이 맛집"), before_id=10**12,
                                      skip_summary_ids=[], limit=50)
        dm_rooms = {r[0] for r in db.admin("SELECT room_key FROM marong.messages WHERE id = ANY(%s)",
                                           ([h["source_id"] for h in dm_hits if h["source_type"] == "message"],))}
        assert dm_rooms and not any(r.startswith("discord-ch:") for r in dm_rooms)
        assert {r["content"] for r in await store.recent(ROOM, 100)} >= {"CHANNEL_ONLY_TALK 오늘 저녁 뭐 먹을까"}
        assert not any("DM_ONLY_SECRET" in r["content"] for r in await store.recent(ROOM, 100))
        print("PASS channel words stay out of DMs, Kakao and calls, and recall stays inside each room")

        with psycopg.connect(db.app_url, row_factory=dict_row) as conn:
            ts = datetime.now(TZ)
            tabs, _ = build(conn, ts - timedelta(days=1), ts, TZ, vectors=False)
            data = next(tab for tab in tabs if tab["name"] == "대화")
            row = next(r for r in data["rows"] if r[5] == "CHANNEL_ONLY_TALK 오늘 저녁 뭐 먹을까")
            assert row[2].startswith("Discord 채널")
        print("PASS the research report names the channel room")
    finally:
        await store.close()
        await kakao.close()


async def intents():
    """The Message Content intent is asked for only when the Developer Portal has it on (otherwise Discord closes the
    Gateway with 4014 and DMs stop too). MARONG_DISCORD_CHANNELS=off keeps the bot to DMs as before."""
    settings = load_settings()
    store = DiscordStore("postgresql://unused")
    llm = ScriptedLLM(lambda _: message([text("x")]))
    for flags, expected in ((None, False), (SimpleNamespace(gateway_message_content=False,
                                                           gateway_message_content_limited=False), False),
                            (SimpleNamespace(gateway_message_content=False, gateway_message_content_limited=True), True),
                            (SimpleNamespace(gateway_message_content=True, gateway_message_content_limited=False), True)):
        client = DiscordDM(DiscordAgent(settings, store, FakeEmbeddings(), llm), store, MARONG, GUILD)
        client._application = None if flags is None else SimpleNamespace(flags=flags)
        await client.setup_hook()
        assert client.hears_all is expected and client._connection._intents.message_content is expected
        assert client._connection._intents.guild_messages and client._connection._intents.dm_messages
    off = DiscordDM(DiscordAgent(settings, store, FakeEmbeddings(), llm), store, MARONG, GUILD, channels=False)
    off._application = SimpleNamespace(flags=SimpleNamespace(gateway_message_content=True,
                                                             gateway_message_content_limited=True))
    await off.setup_hook()
    assert not off._connection._intents.guild_messages and not off._connection._intents.message_content
    off.available = True
    await off.on_message(Msg(guild=SimpleNamespace(id=GUILD), author=SimpleNamespace(id=int(DH), bot=False)))
    assert not llm.bodies
    print("PASS Message Content is asked for only when the app has it, and channels can be turned off")

    names = vocative_pattern(["동희", "현경", "고동희", "Kim", ""])
    assert names.search("현경아 뭐해") and names.search("야 동희야!") and names.search("어 현경아")
    assert not names.search("현경아이스크림") and not names.search("동희야말로")
    assert not names.search("현경이 왔어") and not names.search("마롱아") and vocative_pattern([]) is None
    print("PASS calling a friend by name is recognized ('현경아', '동희야')")


if __name__ == "__main__":
    asyncio.run(intents())
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(check(db))
    finally:
        db.close()
