"""TC-671/672: real PostgreSQL, synthetic conversations, existing DB roles."""

import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import unittest
from unittest.mock import patch
from uuid import uuid4

from psycopg import AsyncConnection, connect
from psycopg.rows import dict_row

from call_memory import MemoryStore, Principal, memory_scope
from fixture_database import BOT_DSN, CALL_DSN, database
from marong.continuity import SIGNAL_TEXTS
from marong.continuity_db import read_previous


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


if __name__ == "__main__":
    unittest.main()
