"""TC-671/672: real PostgreSQL, synthetic conversations, existing DB roles."""

import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from psycopg import AsyncConnection, connect
from psycopg.rows import dict_row

from call_memory import MemoryStore, Principal, memory_scope
from fixture_database import BOT_DSN, CALL_DSN, database
from fakes import ScriptedLLM, message, text
from marong import continuity
from marong.agent import Agent, Incoming
from marong.config import load_settings
from marong.continuity import SIGNAL_TEXTS
from marong.continuity_db import read_previous
from marong.store import Store


NOW = datetime(2026, 11, 24, 5, 5, tzinfo=timezone.utc)


def admin(sql, params=()):
    with connect(database.admin_url, autocommit=True) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else []


class ContinuityStoreTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        suffix = uuid4().hex
        self.user, self.other = f"fixture-{suffix}-a", f"fixture-{suffix}-b"
        self.root, self.group, self.bound = f"fixture-{suffix}-root", f"fixture-{suffix}-group", f"fixture-{suffix}-bound"
        [(friend,)] = admin("INSERT INTO marong.friends(name) VALUES ('시험친구 가') RETURNING id")
        [(other,)] = admin("INSERT INTO marong.friends(name) VALUES ('시험친구 나') RETURNING id")
        [(caller,)] = admin("INSERT INTO call.callers(friend_id) VALUES (%s) RETURNING id", (friend,))
        admin("INSERT INTO marong.people(user_key,friend_id) VALUES (%s,%s),(%s,%s)",
              (self.user, friend, self.other, other))
        admin("INSERT INTO marong.rooms(room_key,is_channel,memory_room) VALUES "
              "(%s,true,NULL),(%s,false,NULL),(%s,true,%s)", (self.root, self.group, self.bound, self.root))
        return Principal(caller, friend, "시험친구 가")

    def message(self, at, text, *, user=None, role="user", room=None, delivered=True):
        [(mid,)] = admin(
            "INSERT INTO marong.messages(room_key,user_key,role,content,created_at,meta) "
            "VALUES(%s,%s,%s,%s,%s,jsonb_build_object('delivered',%s::bool)) RETURNING id",
            (room or self.root, (user or self.user) if role == "user" else None, role, text, at, delivered),
        )
        return mid

    def call(self, principal, at, *, status="ended", count=8, last_after=4, deleted=False):
        call_id, segment, client = uuid4(), uuid4(), uuid4()
        end = at + timedelta(minutes=last_after)
        admin(
            "INSERT INTO call.calls(id,caller_id,status,client_id,prompt_version,voice,started_at,ended_at,end_reason,"
            "organize_status,deleted_at) VALUES "
            "(%s,%s,%s,%s,'fixture','fixture',%s,%s,%s,%s,%s)",
            (call_id, principal.caller_id, status, client, at, end if status == "ended" else None,
             "hangup" if status == "ended" else None, "done" if status == "ended" else "none", end if deleted else None),
        )
        admin(
            "INSERT INTO call.segments(id,call_id,mode,client_id,state,opened_at,closed_at,close_reason) "
            "VALUES(%s,%s,'start',%s,'closed',%s,%s,'user_hangup')", (segment, call_id, client, at, end),
        )
        admin(
            "INSERT INTO call.turns(call_id,segment_id,seq,role,content,started_at,ended_at) "
            "SELECT %s,%s,i,CASE WHEN i %% 2 = 0 THEN 'assistant' ELSE 'user' END,"
            "'합성 통화 ' || i,%s::timestamptz+%s::interval*(i-1)/greatest(%s-1,1),"
            "%s::timestamptz+%s::interval*(i-1)/greatest(%s-1,1) FROM generate_series(1,%s) i",
            (call_id, segment, at, end-at, count, at, end-at, count, count),
        )
        return call_id

    async def test_recent_and_older_with_existing_roles(self):
        person = self.fixture()
        self.message(NOW - timedelta(minutes=26), "합성 글 대화")
        self.message(NOW - timedelta(minutes=25), "시험 준비는 잘 돼?", role="assistant")
        call = self.call(person, NOW - timedelta(minutes=5))
        older_call = self.call(person, NOW - timedelta(days=1), last_after=6)
        admin("INSERT INTO call.cards(call_id,summary,model,prompt_version) VALUES(%s,'합성 요약','fixture','fixture')",
              (older_call,))
        self.message(NOW - timedelta(days=4), "합성 글 회고")
        self.message(NOW - timedelta(days=9), "합성 제외")
        for room in (self.group, self.bound):
            self.message(NOW, "범위 밖", room=room)
        self.message(NOW, "전달 실패", delivered=False)
        self.message(NOW, "[알림] 서버 신호")
        for signal in SIGNAL_TEXTS:
            self.message(NOW, signal)
        hidden = self.message(NOW, "숨김 표시")
        admin("INSERT INTO call.kakao_guards(room_key,friend_id,message_floor,note_floor,summary_floor,"
              "message_forgotten_through) VALUES(%s,%s,%s,0,0,%s)",
              (self.root, person.friend_id, hidden - 1, hidden))
        excluded = self.message(NOW, "제외 표시")
        admin("INSERT INTO call.source_exclusions(caller_id,source_type,source_id) VALUES (%s,'kakao_message',%s)",
              (person.caller_id, str(excluded)))
        self.call(person, NOW - timedelta(minutes=1), count=1, last_after=0, deleted=True)
        live = self.call(person, NOW - timedelta(seconds=30), count=1, last_after=0, status="live")
        admin("UPDATE call.turns SET finalized=false WHERE call_id=%s AND seq=2", (call,))
        admin("UPDATE call.turns SET forgotten_at=now() WHERE call_id=%s AND seq=3", (call,))
        identity = {**MemoryStore.params(person), "name": person.name}
        for dsn, voice in ((CALL_DSN, True), (BOT_DSN, False)):
            async with await AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
                recent, older = await read_previous(conn, memory_scope(person), identity,
                                                    NOW, live, voice=voice, marks=True)
                self.assertEqual([row.origin for row in recent], ["text"] * 2 + ["call"] * 6)
                self.assertEqual([row.text for row in recent if row.origin == "call"],
                                 [f"합성 통화 {seq}" for seq in (1, 4, 5, 6, 7, 8)])
                self.assertEqual([row["channel"] for row in older], ["통화", "글"])
                recent, older = await read_previous(conn, memory_scope(person), identity,
                                                    NOW + timedelta(minutes=30), live, voice=voice, marks=True)
                self.assertFalse(recent)
                self.assertEqual([row["channel"] for row in older], ["글·통화", "통화", "글"])

    async def test_long_and_resting_calls_do_not_hide_older_conversations(self):
        person = self.fixture()
        self.call(person, NOW - timedelta(days=1))
        self.call(person, NOW - timedelta(minutes=80), count=150, last_after=25)
        resting = self.call(person, NOW - timedelta(minutes=10), status="resting", last_after=1)
        store = MemoryStore(CALL_DSN)
        await store.open()
        try:
            recent, older, report = await store.previous_conversation(person, None, NOW, "start")
            self.assertEqual(len(recent), 8)
            self.assertEqual([row["channel"] for row in older], ["통화", "통화"])
            self.assertEqual(report["result"], "ok")
            recent, older, report = await store.previous_conversation(person, resting, NOW, "reconnect")
            self.assertFalse(recent)
            self.assertEqual(len(older), 2)
        finally:
            await store.close()

    async def test_timeout_keeps_output_empty(self):
        person = self.fixture()

        async def slow(*args, **kwargs):
            await asyncio.sleep(1.2)

        store = MemoryStore(CALL_DSN)
        await store.open()
        try:
            with patch("call_memory.read_previous", slow), redirect_stdout(StringIO()) as output:
                recent, older, report = await store.previous_conversation(person, None, NOW, "start")
            self.assertFalse(recent or older)
            self.assertEqual(report["result"], "timeout")
            self.assertEqual(len(output.getvalue().splitlines()), 1)
        finally:
            await store.close()

    async def test_timed_seed_uses_call_start_and_names_turn_speakers(self):
        person = self.fixture()
        now = NOW.replace(hour=7, minute=0)
        yesterday = datetime(2026, 11, 23, 12, 5, tzinfo=timezone.utc)
        self.message(now - timedelta(minutes=2), "합성 최근 글")
        current = self.call(person, now - timedelta(minutes=3), count=2, last_after=1)
        older = self.call(person, yesterday, last_after=6)
        admin("INSERT INTO call.cards(call_id,summary,model,prompt_version) VALUES(%s,'합성 요약','fixture','fixture')",
              (older,))
        store = MemoryStore(CALL_DSN)
        await store.open()
        try:
            original = json.loads(await store.seed(person, current))
            self.assertIn("kakao_recent", original)
            self.assertNotIn("as_of", original)
            self.assertIn("created_at", original["call_cards"][0])
            seeded = json.loads(await store.seed(person, current, as_of=now, older=[]))
            self.assertEqual(next(iter(seeded)), "as_of")
            self.assertEqual(seeded["as_of"], "2026-11-24 화 16:00")
            self.assertNotIn("kakao_recent", seeded)
            self.assertEqual(seeded["recent_conversations"], [])
            card = seeded["call_cards"][0]
            self.assertEqual(card["when"], "어제 오후 9시 5분(11/23 월)")
            self.assertEqual(card["length"], "6분")
            self.assertEqual([item["who"] for item in seeded["current_call"]], ["시험친구 가", "마롱이"])
            self.assertFalse(any("created_at" in item for item in seeded["current_call"]))
        finally:
            await store.close()

    async def test_text_reply_reads_only_the_recent_private_call(self):
        person = self.fixture()
        now = datetime.now(timezone.utc)
        for room in (self.root, self.group, self.bound):
            self.message(now - timedelta(minutes=2), "합성 글", room=room)
        call_id = self.call(person, now - timedelta(minutes=14, seconds=3))
        admin("INSERT INTO call.cards(call_id,summary,model,prompt_version) VALUES(%s,'합성 요약','fixture','fixture')",
              (call_id,))
        store = Store(BOT_DSN, call_bridge=True)
        await store.open(wait=True)
        llm = ScriptedLLM(lambda body: message([text("시험용 답변")]))
        agent = Agent(load_settings(), store, SimpleNamespace(ready=False), llm)

        async def prompt(room, private=True):
            reply = await agent.handle(Incoming(room, self.user, "마롱아 다시 얘기해", is_channel=private),
                                       AsyncMock(return_value=True))
            self.assertTrue(reply)
            return "\n".join(item["text"] for item in llm.bodies[-1]["system"])

        try:
            with patch.object(continuity, "MODE", "on"):
                body = await prompt(self.root)
                self.assertIn("# 방금 통화 (마지막 말 10분 전, 4분 통화.", body)
                self.assertEqual(sum(line.startswith(("- 시험친구 가:", "- 마롱이:")) for line in body.splitlines()), 8)
                self.assertLess(body.index("# 방금 통화"), body.index("# 최근 통화"))
                self.assertNotIn("# 방금 통화", await prompt(self.group, private=False))
                self.assertNotIn("# 방금 통화", await prompt(self.bound))
                with patch("marong.store.read_recent_call", AsyncMock(side_effect=TimeoutError)):
                    self.assertNotIn("# 방금 통화", await prompt(self.root))
                admin("UPDATE call.calls SET status='live',ended_at=NULL,end_reason=NULL,organize_status='none' WHERE id=%s",
                      (call_id,))
                self.assertNotIn("# 방금 통화", await prompt(self.root))
                admin("UPDATE call.calls SET status='resting' WHERE id=%s", (call_id,))
                self.assertIn("# 방금 통화", await prompt(self.root))
                admin("UPDATE call.turns SET ended_at=ended_at - interval '1 hour',started_at=started_at - interval '1 hour' "
                      "WHERE call_id=%s", (call_id,))
                older = await prompt(self.root)
                self.assertNotIn("# 방금 통화", older)
                self.assertIn('"when"', older)
            with patch.object(continuity, "MODE", "off"):
                baseline = await prompt(self.root)
                self.assertNotIn("# 방금 통화", baseline)
                self.assertNotIn('"when"', baseline)
        finally:
            await store.close()


if __name__ == "__main__":
    unittest.main()
