"""Discord isolation and proactive rules against real Postgres, with fake delivery/LLM."""
import asyncio
from datetime import datetime, timedelta
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
from marong.agent import Agent, Incoming
from marong.config import load_settings
from marong.discord_dm import DiscordAgent, DiscordDM, DiscordProactive
from marong.discord_store import DiscordStore, bind_dm
from marong.store import Store
from pg import TestDB
from psycopg.rows import dict_row
from tools.report import build

DH, HK, OTHER = "100000000000000001", "100000000000000002", "100000000000000003"
DM_DH, DM_HK = 100000000000000011, 100000000000000012
TZ = ZoneInfo("Asia/Seoul")
MODEL = "fixture"


class Channel(discord.DMChannel):
    def __init__(self, channel_id, user_id):
        self.id = channel_id
        self._recipient = SimpleNamespace(id=int(user_id))
        self.sent = []
        self.fail = False

    @property
    def recipient(self):
        return self._recipient

    async def send(self, content, **kwargs):
        assert kwargs["allowed_mentions"].to_dict() == {"parse": []}
        if self.fail:
            raise discord.Forbidden(SimpleNamespace(status=403, reason="fixture"), {"code": 50007, "message": "fixture"})
        self.sent.append(content)


class Client(DiscordDM):
    def __init__(self, agent, store):
        super().__init__(agent, store, 123, 456)
        self.available = True
        self.channels = {DM_DH: Channel(DM_DH, DH), DM_HK: Channel(DM_HK, HK)}

    async def fetch_channel(self, channel_id):
        return self.channels[channel_id]

    def get_partial_messageable(self, channel_id, **kwargs):
        return self.channels[channel_id]


def event(client, user, channel, mid, content, *, group=False, bot=False):
    return SimpleNamespace(guild=object() if group else None, author=SimpleNamespace(id=int(user), bot=bot),
                           channel=client.channels[channel], webhook_id=None, id=mid,
                           type=discord.MessageType.default, content=content)


def prepare(db):
    with psycopg.connect(db.admin_url, autocommit=True) as conn:
        for name in ("marong/call/schema.sql", "marong/call/migrations/002_vertex_memory.sql",
                     "marong/migrations/010_discord_dm.sql"):
            conn.execute((ROOT / name).read_text(encoding="utf-8"))
        conn.execute("INSERT INTO marong.friends(name) VALUES ('동희'),('현경')")
        conn.execute("""INSERT INTO marong.rooms(room_key,is_channel,proactive)
                         VALUES('k-dh',true,false),('k-hk',true,false),('mixed',false,false)""")
        conn.execute("UPDATE marong.rooms SET memory_room='k-hk', group_proactive=true WHERE room_key='mixed'")
        conn.execute("INSERT INTO marong.people(user_key,name,friend_id) VALUES ('p-dh','동희',1),('p-hk','현경',2)")
        conn.execute("""INSERT INTO marong.messages(room_key,user_key,role,content,kakao_id) VALUES
                         ('k-dh','p-dh','user','DH_OWN_KAKAO','k1'),
                         ('k-hk','p-hk','user','HK_OWN_KAKAO','k2'),
                         ('mixed','p-dh','user','PRIVATE_GROUP_MARKER','k3'),
                         ('mixed','p-hk','user','PRIVATE_GROUP_MARKER','k4')""")
        conn.execute("""INSERT INTO marong.summaries(room_key,first_id,last_id,content,meta)
                         SELECT 'k-hk',min(id),max(id),'PRIVATE_MIXED_SUMMARY','{"rooms":["k-hk","mixed"]}'
                           FROM marong.messages WHERE room_key IN('k-hk','mixed')""")
        bind_dm(conn, DH, 1, 2, 12, 21)
        bind_dm(conn, HK, 2, 36, 7, 24)
        bind_dm(conn, HK, 2, 36, 7, 24)
        conn.execute("INSERT INTO call.callers(friend_id) VALUES (2)")


async def check(db):
    settings = load_settings()
    store = DiscordStore(db.app_url, call_bridge=True)
    kakao = Store(db.app_url, call_bridge=True)
    kakao.discord_context_enabled = True
    await store.open(wait=True)
    await kakao.open(wait=True)
    try:
        emb = FakeEmbeddings()
        llm = ScriptedLLM(lambda _: message([text("테스트 답장이야.")]))
        agent = DiscordAgent(settings, store, emb, llm)
        client = Client(agent, store)
        for incoming in (
            event(client, OTHER, DM_HK, 1, "third party"),
            event(client, HK, DM_HK, 2, "server message", group=True),
            event(client, HK, DM_HK, 3, "bot message", bot=True),
            event(client, HK, DM_DH, 4, "wrong recipient"),
        ):
            await client.on_message(incoming)
        assert not llm.bodies and not any(ch.sent for ch in client.channels.values())
        print("PASS third-party, server, bot and wrong-recipient events are ignored")

        h = event(client, HK, DM_HK, 5, "HK_DISCORD_MESSAGE")
        await client.on_message(h)
        await client.on_message(h)
        await client.on_message(event(client, DH, DM_DH, 6, "DH_DISCORD_MESSAGE"))
        assert len(llm.bodies) == 2
        a, b = (json.dumps(req, ensure_ascii=False) for req in llm.bodies)
        assert "HK_OWN_KAKAO" in a and "DH_OWN_KAKAO" in b
        assert all(x not in a for x in ("DH_OWN_KAKAO", "PRIVATE_GROUP_MARKER", "PRIVATE_MIXED_SUMMARY"))
        assert all(x not in b for x in ("HK_OWN_KAKAO", "HK_DISCORD_MESSAGE"))
        assert len(client.channels[DM_HK].sent) == len(client.channels[DM_DH].sent) == 2
        print("PASS untagged replies, duplicate protection and isolated per-person context")

        assert not await store.proactive_rooms()
        assert any(r["room_key"] == "mixed" for r in await kakao.proactive_rooms())
        await client.on_message(event(client, HK, DM_HK, 7, "선톡 켜기"))
        rooms = await store.proactive_rooms()
        assert len(rooms) == 1 and rooms[0]["per_day"] == 36 and rooms[0]["start_hour"] == 7
        assert "하루 최대 36번" in client.channels[DM_HK].sent[-1]
        room = rooms[0]["room_key"]
        db.admin("UPDATE marong.discord_dm_links SET last_incoming_at=now()-interval '2 hours', opted_in_at=now()-interval '2 hours' WHERE room_key=%s", (room,))
        now = datetime(2026, 11, 13, 12, 0, tzinfo=TZ)
        plan = DiscordProactive(settings, store, agent, client, clock=lambda: now, rng=lambda: 0)
        assert await plan.step(now) == 1
        restarted = DiscordProactive(settings, store, agent, client, clock=lambda: now, rng=lambda: 0)
        assert await restarted.step(now) == 0
        assert not any(r["room_key"] == "mixed" for r in await kakao.proactive_rooms())
        assert client.channels[DM_HK].sent[-1] == "테스트 답장이야."
        await client.on_message(event(client, HK, DM_HK, 8, "선톡 끄기"))
        assert not await store.proactive_rooms()
        assert await restarted.step(now) == 0
        print("PASS consent gate, scheduled DM, persistent deduplication and immediate opt-out")

        assert not any(r["room_key"].startswith("discord-dm:") for r in await kakao.proactive_rooms())
        hk_user_id = await kakao.add_message("k-hk", "user", "kakao continuity", "p-hk")
        assert "HK_DISCORD_MESSAGE" in json.dumps(await kakao.discord_context("k-hk", "p-hk", hk_user_id))
        assert not await kakao.discord_context("k-hk", "p-dh", hk_user_id)
        assert not await kakao.discord_context("mixed", "p-hk", hk_user_id)
        assert "HK_DISCORD_MESSAGE" not in json.dumps(await kakao.recent("k-dh", 100), default=str)
        kakao_llm = ScriptedLLM(lambda _: message([text("HK_KAKAO_PRIVATE_REPLY")]))
        kakao_agent = Agent(settings, kakao, emb, kakao_llm)
        async def deliver_kakao(_):
            return True
        await kakao_agent.handle(Incoming("k-hk", "p-hk", "kakao memory continuity"), deliver_kakao)
        assert "HK_DISCORD_MESSAGE" in json.dumps(kakao_llm.bodies[-1], ensure_ascii=False)
        assert "DH_DISCORD_MESSAGE" not in json.dumps(kakao_llm.bodies[-1], ensure_ascii=False)
        assert "HK_KAKAO_PRIVATE_REPLY" not in json.dumps(await kakao.recent("mixed", 100), default=str)
        call = MemoryStore(db.admin_url)
        await call.pool.open(wait=True)
        try:
            voice = await call.seed(Principal(1, 2, "현경"))
            assert "HK_DISCORD_MESSAGE" in voice and "DH_DISCORD_MESSAGE" not in voice
        finally:
            await call.close()
        print("PASS same-account Kakao/voice context and no group or other-account access")

        with psycopg.connect(db.app_url, row_factory=dict_row) as conn:
            ts = datetime.now(TZ)
            tabs, _ = build(conn, ts-timedelta(days=1), ts, TZ, vectors=False)
            data = next(tab for tab in tabs if tab["name"] == "대화")
            index = next(i for i,row in enumerate(data["rows"]) if row[5] == "HK_DISCORD_MESSAGE")
            assert data["rows"][index][2].startswith("Discord DM") and data["colors"][index] == "#fff2cc"
        print("PASS research report contains Discord DM text with existing speaker color")
    finally:
        await store.close()
        await kakao.close()


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(check(db))
    finally:
        db.close()
