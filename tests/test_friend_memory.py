"""TC-330 with isolated PostgreSQL, the service roles and a fake graph node."""

import asyncio
import json
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from anthropic import APIConnectionError
from httpx import Request
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.conninfo import make_conninfo

from marong.forget_rewrite import RETRY, rewrite_one
from marong.friend_card import KST
from marong.friend_forget import forget_selected
from marong.friend_memory import MemoryExtraction, apply_ops, expire_loops, list_for_turn, memory_page
from marong.graphs.memory import LEASE, MemoryQueue, checkpoint_pool, compile_graph, run_text_memory
from marong.store import Store
from pg import ROOT, TestDB
from test_persona_schema import assert_sqlstate, prepare


async def check_queue(db):
    import sys
    sys.path.insert(0, str(ROOT / "tools" / "vertex_live"))
    from call_memory import MemoryStore
    from organizer import Organizer

    [(friend,)] = db.admin("INSERT INTO marong.friends(name) VALUES ('fixture') RETURNING id")
    db.admin("""INSERT INTO marong.people(user_key,friend_id) VALUES
        ('fixture:dm',%s),('fixture:group',%s),('fixture:unlinked',NULL)""", (friend, friend))
    db.admin("INSERT INTO marong.rooms(room_key,is_channel) VALUES ('fixture:dm',true),('fixture:group',false)")
    with patch.dict("os.environ", {"MARONG_FRIEND_MEMORY": "shadow"}):
        store = Store(db.app_url)
    await store.open(wait=True)
    try:
        when = datetime.now(timezone.utc)
        queue = MemoryQueue(store.pool, clock=lambda: when)
        old_ids = []
        previous_due = None
        for index in range(5):
            room = "fixture:dm" if index % 2 == 0 else "fixture:group"
            ident = await store.add_message(room, "user", "Synthetic text fixture", room, f"fixture-{index}")
            [(said,)] = db.admin("SELECT created_at FROM marong.messages WHERE id=%s", (ident,))
            [(due,)] = db.admin("SELECT due_at FROM marong.memory_jobs WHERE friend_id=%s AND source='text'", (friend,))
            assert due == said + timedelta(seconds=60)
            if previous_due:
                assert due >= previous_due
            old_ids.append(ident)
            assert await store.add_message(room, "user", "Duplicate", room, f"fixture-{index}") is None
            previous_due = due
        await store.add_message("fixture:dm", "assistant", "Synthetic assistant fixture")
        await store.add_message("fixture:dm", "user", "Synthetic unlinked fixture", "fixture:unlinked")
        when = due - timedelta(microseconds=1)
        assert await queue.claim("text") is None
        when = due
        results = await asyncio.gather(queue.claim("text"), queue.claim("text"))
        assert sum(item is not None for item in results) == 1
        first = next(item for item in results if item)
        assert first["message_ids"] == old_ids
        assert db.admin("SELECT lease_until FROM marong.memory_jobs") == [(due + LEASE,)]
        when = due + LEASE
        replacement = await queue.claim("text")
        assert replacement["token"] != first["token"] and replacement["message_ids"] == first["message_ids"]

        async def should_not_apply(*_):
            raise AssertionError("expired work affected the database")

        assert not await queue.finish(first, "ok", should_not_apply)

        late = await store.add_message("fixture:dm", "user", "A newer fixture", "fixture:dm")
        # Simulate a new 60-second idle window starting while extraction is running.
        late_due = when + timedelta(seconds=55)
        db.admin("UPDATE marong.memory_jobs SET due_at=%s WHERE friend_id=%s AND source='text'", (late_due, friend))
        seen = []

        async def inspect_ids(state):
            assert state == replacement
            return {"ephemeral": "sentinel-output-never-checkpointed"}

        async def persist(conn, state, result):
            assert result["ephemeral"] == "sentinel-output-never-checkpointed"
            seen.extend(state["message_ids"])
            cursor = await conn.execute("SELECT token::text FROM marong.memory_jobs WHERE friend_id=%s", (friend,))
            assert (await cursor.fetchone())["token"] == state["token"]

        async with checkpoint_pool(db.app_url) as pool:
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            graph = compile_graph(queue, inspect_ids, persist, checkpointer=saver)
            config = {"configurable": {"thread_id": f"memory:text:{friend}:{replacement['token']}"}}
            assert await graph.ainvoke(replacement, config) == replacement
            checkpoint = await saver.aget(config)
            assert "sentinel-output-never-checkpointed" not in repr(checkpoint)
            assert "Synthetic text fixture" not in repr(checkpoint)
        assert seen == old_ids
        assert db.admin("SELECT watermark,due_at FROM marong.memory_jobs") == [(old_ids[-1], late_due)]
        assert await queue.claim("text") is None
        when = late_due
        last = await queue.claim("text")
        assert last["message_ids"] == [late]
        for attempt in range(1, 4):
            assert await queue.finish(last, "ai_error")
            if attempt < 3:
                assert await queue.claim("text") is None
                when += LEASE
                last = await queue.claim("text")
                assert last["message_ids"] == [late]
        assert db.admin("SELECT watermark,attempts,due_at FROM marong.memory_jobs") == [(late, 0, None)]

        db.admin("""INSERT INTO marong.messages(room_key,user_key,role,content)
            SELECT 'fixture:dm','fixture:dm','user','batch fixture' FROM generate_series(1,201)""")
        due_id = await store.add_message("fixture:dm", "user", "Newest batch fixture", "fixture:dm")
        large = await queue.claim("text")
        assert len(large["message_ids"]) == 200 and large["next_message_id"]
        assert await queue.finish(large, "ok")
        second = await queue.claim("text")
        assert second["message_ids"] == [large["next_message_id"], due_id]
        await queue.finish(second, "ok")

        await store.add_message("fixture:group", "assistant", "Earlier group context")
        message = await store.add_message("fixture:group", "user", "나는 요즘 딸기가 좋아", "fixture:group")
        hidden = await store.add_message("fixture:group", "user", "Forgotten fixture", "fixture:group")
        [(forget,)] = db.admin("""INSERT INTO marong.memory_forgets(friend_id,via,request_key)
            VALUES (%s,'screen','forgotten-fixture') RETURNING id""", (friend,))
        db.admin("""INSERT INTO marong.forget_marks(forget_id,friend_id,target_type,target_id,state)
            VALUES (%s,%s,'message',%s,'forgotten')""", (forget, friend, hidden))
        work = await queue.claim("text")
        assert work["message_ids"] == [message]
        item = {"kind": "preference", "text": "딸기를 좋아함", "sensitive": None,
                "scope": "friend", "share": "known", "valid_until": None}
        op = {"op": "add", "item": item, "message_id": message, "quote": "딸기가 좋아"}

        async def infer(payload, actor):
            assert actor == friend
            [statement] = payload["messages"]
            assert statement["channel"] == "kakao_group" and statement["room"] == "fixture:group"
            assert "Earlier group context" in statement["context"]
            assert "Forgotten fixture" not in repr(payload)
            return {"ops": [op, {**op, "quote": "없는 말"}, {**op, "message_id": hidden},
                            {**op, "item": {**item, "scope": "room:fixture:dm"}},
                            {**op, "op": "retract", "target_id": 42, "item": item}]}

        extraction = MemoryExtraction(store.pool, infer)
        graph = compile_graph(queue, extraction.prepare, extraction.persist, checkpointer=None)
        await graph.ainvoke(work)
        [(current, room, channel, source, msg)] = db.admin("""SELECT id,room_key,channel,source,message_id
            FROM marong.memory_items WHERE friend_id=%s""", (friend,))
        assert (room, channel, source, msg) == ("fixture:group", "kakao_group", "text", message)
        private = await store.add_message("fixture:dm", "user", "딸기는 이제 안 먹어", "fixture:dm",
                                          meta={"transport": "app"})
        private_work = await queue.claim("text")
        forbidden = {"op": "retract", "message_id": private, "quote": "이제 안 먹어", "target_id": current}

        async def no_cross_room(conn, state):
            assert await apply_ops(conn, state, {"ops": [forbidden]}) == (0, 1)

        assert await queue.finish(private_work, "ok", no_cross_room)
        assert db.admin("SELECT status FROM marong.memory_items WHERE id=%s", (current,)) == [("current",)]
        newer = await store.add_message("fixture:group", "user", "요즘은 사과가 더 좋아", "fixture:group")
        replacement_work = await queue.claim("text")
        changed = {"op": "supersede", "target_id": current, "item": {**item, "text": "사과가 더 좋음"},
                   "message_id": newer, "quote": "사과가 더 좋아"}

        async def supersede(conn, state):
            assert await apply_ops(conn, state, {"ops": [changed]}) == (1, 0)

        assert await queue.finish(replacement_work, "ok", supersede)
        assert db.admin("SELECT status,replaces_id FROM marong.memory_items ORDER BY id") == [
            ("superseded", None), ("current", current)]
        loop_message = await store.add_message("fixture:dm", "user", "면접 일정 픽스됐어", "fixture:dm")
        loop_work = await queue.claim("text")
        due_day = datetime.now(KST).date() + timedelta(days=2)
        operation = {"op": "loop_open", "text": "면접", "due": due_day.isoformat(), "sensitivity": "mid",
                     "message_id": loop_message, "quote": "면접 일정 픽스됐어"}

        async def open_loop(conn, state):
            assert await apply_ops(conn, state, {"ops": [operation, operation]}) == (2, 0)

        assert await queue.finish(loop_work, "ok", open_loop)
        [(due, expires)] = db.admin("SELECT due,expires_at FROM marong.open_loops WHERE status='open'")
        assert due == due_day
        assert expires == datetime.combine(due_day + timedelta(days=7), time.min, KST)
        assert not await expire_loops(store.pool, expires - timedelta(microseconds=1))
        assert await expire_loops(store.pool, expires) == 1
        assert db.admin("SELECT status FROM marong.open_loops") == [("expired",)]

        [(caller,)] = db.admin("INSERT INTO call.callers(friend_id) VALUES (%s) RETURNING id", (friend,))
        [(call,)] = db.admin("""INSERT INTO call.calls(caller_id,client_id,prompt_version,voice,status,
            ended_at,end_reason,organize_status) VALUES
            (%s,gen_random_uuid(),'fixture','fixture','ended',now(),'hangup','pending') RETURNING id""", (caller,))
        [(segment,)] = db.admin("""INSERT INTO call.segments(call_id,mode,client_id)
            VALUES (%s,'start',gen_random_uuid()) RETURNING id""", (call,))
        dsn = make_conninfo(db.admin_url, user="marong_call")
        call_store = MemoryStore(dsn)
        await call_store.pool.open(wait=True)
        try:
            async with call_store.pool.connection() as conn:
                await Organizer.reserve_friend_memory(conn, call, caller)
            assert db.admin("SELECT count(*) FROM marong.memory_jobs WHERE source='call'") == [(0,)]
            db.admin("""INSERT INTO call.turns(call_id,segment_id,seq,role,content,started_at,ended_at)
                VALUES (%s,%s,1,'user','Synthetic caption',now(),now())""", (call, segment))

            async def fake_extractor(turns):
                assert len(turns) == 1 and turns[0]["role"] == "user"
                return {"summary": "", "memories": []}, {}

            with patch.dict("os.environ", {"MARONG_FRIEND_MEMORY": "shadow"}):
                organizer = Organizer(call_store, fake_extractor)
            call_state = await organizer.claim()
            await organizer.organize({**call_state, **await organizer.load(call_state)})
            async with call_store.pool.connection() as conn:
                await Organizer.reserve_friend_memory(conn, call, caller)
            call_queue = MemoryQueue(call_store.pool, clock=lambda: when)
            call_work = await call_queue.claim("call")
            assert call_work["call_ids"] == [str(call)] and call_work["message_ids"] == []
            [(turn,)] = db.admin("SELECT id FROM call.turns WHERE call_id=%s", (call,))
            learned = {"op": "add", "item": {**item, "kind": "fact", "text": "Synthetic caption fact"},
                       "message_id": turn, "quote": "Synthetic caption"}

            async def learn_call(conn, state):
                assert await apply_ops(conn, state, {"ops": [learned]}) == (1, 0)

            assert await call_queue.finish(call_work, "ok", learn_call)
            assert db.admin("""SELECT channel,message_id,call_turn_id FROM marong.memory_items
                WHERE source='call'""") == [("call", None, turn)]
            assert not await call_queue.claim("call")
        finally:
            await call_store.close()
        assert_sqlstate(db, "marong", "SELECT 1 FROM call.turns WHERE false", "42501")
        page = await memory_page(store.pool, friend)
        assert {row["channel"] for row in page["items"]} == {"kakao_group", "call"}
        assert all("quote" in row and "room_key" not in row for row in page["items"])
        assert await memory_page(store.pool, friend + 1) == {"items": [], "loops": [], "hasMore": False}
        after = await memory_page(store.pool, friend, before=page["items"][0]["id"])
        assert after["items"] == page["items"][1:] and not after["loops"]
        direct = await list_for_turn(store.pool, friend, "fixture:dm", private, "list-private", {})
        group = await list_for_turn(store.pool, friend, "fixture:group", newer, "list-group", {})
        assert {row["channel"] for row in direct["items"]} == {"call"}
        assert len(group["items"]) == 1 and "quote" not in group["items"][0] and group["hint"]
        assert await list_for_turn(store.pool, friend, "fixture:group", private, "list-forged", {}) is None
        assert await list_for_turn(store.pool, friend, "fixture:dm", private, "list-other", {"friend_id": 77}) is None
        assert db.admin("SELECT outcome FROM marong.persona_tool_calls ORDER BY id") == [
            ("ok",), ("ok",), ("refused",), ("invalid",)]
    finally:
        await store.close()


async def check_worker(db):
    [(friend,)] = db.admin("INSERT INTO marong.friends(name) VALUES ('worker fixture') RETURNING id")
    db.admin("INSERT INTO marong.people(user_key,friend_id) VALUES ('worker:dm',%s)", (friend,))
    db.admin("INSERT INTO marong.rooms(room_key,is_channel) VALUES ('worker:dm',true)")
    with patch.dict("os.environ", {"MARONG_FRIEND_MEMORY": "shadow"}):
        store = Store(db.app_url)
    await store.open(wait=True)
    try:
        message = await store.add_message("worker:dm", "user", "사과가 좋아", "worker:dm")
        db.admin("UPDATE marong.memory_jobs SET due_at=now() WHERE friend_id=%s AND source='text'", (friend,))
        requests = []

        class FakeLLM:
            async def create_once(self, body, timeout):
                requests.append(body)
                assert timeout == 60
                assert body["model"] == "fixture-ledger"
                if len(requests) == 1:
                    raise APIConnectionError(request=Request("POST", "https://fixture.test/"))
                assert body["output_config"]["format"]["type"] == "json_schema"
                [statement] = json.loads(body["messages"][0]["content"])["messages"]
                assert statement["id"] == message
                result = {"ops": [{"op": "add", "message_id": message, "quote": "사과가 좋아",
                                   "item": {"kind": "preference", "text": "사과를 좋아함", "sensitive": None,
                                            "scope": "friend", "share": "known", "valid_until": None}}]}
                return SimpleNamespace(stop_reason="end_turn", content=[
                    SimpleNamespace(type="text", text=json.dumps(result, ensure_ascii=False))],
                    usage=SimpleNamespace(input_tokens=11, output_tokens=5))

        with patch.dict("os.environ", {"MARONG_MEMORY_MODEL": "fixture-ledger"}):
            worker = asyncio.create_task(run_text_memory(store, db.app_url, FakeLLM(), "fixture"))
            await asyncio.sleep(0)
        try:
            async with asyncio.timeout(10):
                while db.admin("SELECT last_outcome FROM marong.memory_jobs WHERE friend_id=%s", (friend,)) != [("ok",)]:
                    await asyncio.sleep(0.05)
            assert len(requests) == 2
            assert db.admin("SELECT status,message_id FROM marong.memory_items WHERE friend_id=%s", (friend,)) == [
                ("current", message)]
            assert db.admin("""
                SELECT outcome,input_tokens,output_tokens,error_code FROM marong.persona_ai_runs
                WHERE friend_id=%s AND kind='memory_ops' ORDER BY id
            """, (friend,)) == [("error", None, None, "APIConnectionError"), ("ok", 11, 5, None)]
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    finally:
        await store.close()


async def check_call_worker(db):
    from call_memory import MemoryStore
    from organizer import Organizer, checkpoint_pool as call_checkpoint_pool

    [(friend,)] = db.admin("INSERT INTO marong.friends(name) VALUES ('call worker fixture') RETURNING id")
    [(caller,)] = db.admin("INSERT INTO call.callers(friend_id) VALUES (%s) RETURNING id", (friend,))
    [(call,)] = db.admin("""
        INSERT INTO call.calls(caller_id,client_id,prompt_version,voice,status,ended_at,end_reason,
                               organize_status,organize_attempts)
        VALUES (%s,gen_random_uuid(),'fixture','fixture','ended',now(),'hangup','running',3) RETURNING id
    """, (caller,))
    [(segment,)] = db.admin("INSERT INTO call.segments(call_id,mode,client_id) VALUES (%s,'start',gen_random_uuid()) RETURNING id",
                           (call,))
    [(turn,)] = db.admin("""
        INSERT INTO call.turns(call_id,segment_id,seq,role,content,started_at,ended_at)
        VALUES (%s,%s,1,'user','다음 주에 이사해',now(),now()) RETURNING id
    """, (call, segment))
    dsn = make_conninfo(db.admin_url, user="marong_call")
    store = MemoryStore(dsn)
    await store.pool.open(wait=True)
    try:
        with patch.dict("os.environ", {"MARONG_FRIEND_MEMORY": "shadow"}):
            organizer = Organizer(store)
        await organizer.fail(call)
        assert db.admin("SELECT calls FROM marong.memory_jobs WHERE friend_id=%s", (friend,)) == [([call],)]
        await organizer.fail(call)

        output = {"ops": [{"op": "loop_open", "message_id": turn, "quote": "다음 주에 이사해",
                           "text": "이사", "due": None, "sensitivity": "low"}]}

        async with call_checkpoint_pool(dsn) as pool:
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            with patch("organizer.aiohttp.ClientSession") as session, \
                    patch("organizer.google_headers", new=AsyncMock(return_value={})), \
                    patch.dict("os.environ", {"MARONG_MEMORY_MODEL": "fixture-call"}):
                http = MagicMock()
                session.return_value.__aenter__.return_value = http
                result = http.post.return_value.__aenter__.return_value
                result.status = 200
                result.json = AsyncMock(return_value={"candidates": [{
                    "finishReason": "STOP", "content": {"parts": [{"text": json.dumps(output, ensure_ascii=False)}]},
                }], "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 8}})
                worker = asyncio.create_task(organizer.run_friend_memory(saver))
                try:
                    async with asyncio.timeout(10):
                        while db.admin("SELECT last_outcome FROM marong.memory_jobs WHERE friend_id=%s",
                                       (friend,)) != [("ok",)]:
                            await asyncio.sleep(0.05)
                    assert db.admin("SELECT text,channel,call_turn_id FROM marong.open_loops WHERE friend_id=%s",
                                    (friend,)) == [("이사", "call", turn)]
                    assert_sqlstate(db, "marong", "SELECT 1 FROM call.turns WHERE false", "42501")
                    assert "fixture-call:generateContent" in http.post.call_args.args[0]
                    body = http.post.call_args.kwargs["json"]
                    assert body["generationConfig"]["responseJsonSchema"]["type"] == "object"
                    [statement] = json.loads(body["contents"][0]["parts"][0]["text"])["messages"]
                    assert statement["id"] == turn and statement["channel"] == "call"
                    assert db.admin("""
                        SELECT outcome,input_tokens,output_tokens,thinking FROM marong.persona_ai_runs
                        WHERE friend_id=%s AND kind='memory_ops'
                    """, (friend,)) == [("ok", 20, 8, "LOW")]
                finally:
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
    finally:
        await store.close()


async def check_forget_transaction(db):
    [(owner,)] = db.admin("INSERT INTO marong.friends(name) VALUES ('forget fixture') RETURNING id")
    [(other,)] = db.admin("INSERT INTO marong.friends(name) VALUES ('other forget fixture') RETURNING id")
    room = "synthetic-forget-dm"
    db.admin("INSERT INTO marong.rooms(room_key,is_channel) VALUES (%s,true)", (room,))
    db.admin("INSERT INTO marong.people(user_key,friend_id) VALUES (%s,%s)", (room, owner))
    [(message, said_at)] = db.admin("""
        INSERT INTO marong.messages(room_key,user_key,role,content)
        VALUES (%s,%s,'user','가상 기록') RETURNING id,created_at
    """, (room, room))
    [(summary,)] = db.admin("""
        INSERT INTO marong.summaries(room_key,first_id,last_id,content)
        VALUES (%s,%s,%s,'가상 요약') RETURNING id
    """, (room, message, message))
    [(note,)] = db.admin("""
        INSERT INTO marong.notes(room_key,user_key,summary_id,content)
        VALUES (%s,%s,%s,'가상 메모') RETURNING id
    """, (room, room, summary))
    [(shared,)] = db.admin("INSERT INTO marong.shared_notes(friend_id,content) VALUES (%s,'가상 공유') RETURNING id",
                         (owner,))
    [(unrelated,)] = db.admin("INSERT INTO marong.shared_notes(friend_id,content) VALUES (%s,'다른 시험') RETURNING id",
                            (other,))
    [(item,), (second,)] = db.admin("""
        INSERT INTO marong.memory_items(friend_id,kind,text,channel,message_id,heard_at,quote,source)
        VALUES (%s,'fact','가상 사실','discord_dm',%s,%s,'가상 기록','text'),
               (%s,'hard','가상 대화','discord_dm',%s,%s,'가상 기록','text') RETURNING id
    """, (owner, message, said_at, owner, message, said_at))
    [(loop,)] = db.admin("""
        INSERT INTO marong.open_loops(friend_id,text,channel,message_id,quote,opened_at,expires_at,sensitivity)
        VALUES (%s,'가상 일','discord_dm',%s,'가상 기록',now(),now()+interval '7 days','mid') RETURNING id
    """, (owner, message))
    db.admin("""
        INSERT INTO marong.embeddings(model,source_type,source_id,room_key,embedding)
        VALUES ('fixture','message',%s,%s,'[1,2,3]'),('fixture','summary',%s,%s,'[3,2,1]')
    """, (message, room, summary, room))
    store = Store(db.app_url)
    await store.open(wait=True)
    try:
        assert await forget_selected(store.pool, other, "item", item, "other", via="screen") is None
        assert await forget_selected(store.pool, owner, "item", item, "group", via="tool",
                                     group="different-group") is None
        completed = await asyncio.gather(
            forget_selected(store.pool, owner, "item", item, "same", via="screen"),
            forget_selected(store.pool, owner, "item", item, "same", via="screen"))
        assert completed == [{"forgot": 3, "messages": 1}] * 2
        assert await forget_selected(store.pool, owner, "loop", loop, "new-key", via="screen") == {
            "forgot": 0, "messages": 0,
        }
        assert db.admin("SELECT status,text,quote FROM marong.memory_items WHERE id IN (%s,%s) ORDER BY id",
                        (item, second)) == [("forgotten", None, None)] * 2
        assert db.admin("SELECT status,text,quote FROM marong.open_loops WHERE id=%s", (loop,)) == [
            ("forgotten", None, None)
        ]
        assert set(db.admin(
            "SELECT target_type,target_id,state FROM marong.forget_marks WHERE friend_id=%s", (owner,)
        )) == {("message", message, "forgotten"), ("summary", summary, "hidden"), ("note", note, "hidden"),
               ("shared_note", shared, "hidden")}
        assert db.admin("SELECT id FROM marong.shared_notes WHERE id=%s", (unrelated,)) == [(unrelated,)]
        assert db.admin("SELECT count(*) FROM marong.embeddings WHERE room_key=%s", (room,)) == [(0,)]
        assert not await store.recent(room, 10)
        assert not await store.recent_turns(room, 2, 20)
        assert not await store.notes(room)
        assert not await store.summaries(room, 10)
        assert not (await store.keyword_hits(room, ["가상"], message + 1, []))[0]
        assert not [entry for entry in await store.pending_embeddings("fixture", 1000)
                    if entry["room_key"] == room]
        await store.add_embeddings("new-fixture", [
            ("message", message, room, [1, 2, 3]), ("summary", summary, room, [3, 2, 1]),
        ])
        assert db.admin("SELECT count(*) FROM marong.embeddings WHERE room_key=%s", (room,)) == [(0,)]
        assert db.admin("SELECT content FROM marong.messages WHERE id=%s", (message,)) == [("가상 기록",)]
        assert db.admin("SELECT count(*) FROM marong.memory_forgets WHERE friend_id=%s", (owner,)) == [(2,)]

        at = datetime.now(timezone.utc)
        rewrites = []

        async def output(original, forgotten):
            assert forgotten == ["가상 기록"]
            rewrites.append(original)
            if original == "가상 공유":
                return "공개 일정"
            if original == "가상 메모" or at == started:
                return "가상 기록"
            if at == started + RETRY:
                return "원문보다 훨씬 길게 쓴 일정"
            return "예정"

        started = at
        for attempt in range(3):
            while await rewrite_one(store.pool, output, clock=lambda: at):
                pass
            if attempt < 2:
                assert not await store.summaries(room, 10)
                assert not await store.notes(room)
                assert db.admin("""SELECT attempts,updated_at FROM marong.forget_marks
                    WHERE target_type='summary' AND target_id=%s""", (summary,)) == [(attempt + 1, at + RETRY)]
            at += RETRY
        assert rewrites.count("가상 요약") == rewrites.count("가상 메모") == 3
        assert rewrites.count("가상 공유") == 1
        assert [entry["content"] for entry in await store.summaries(room, 10)] == ["예정"]
        assert [entry["content"] for entry in (await store.keyword_hits(room, ["예정"], message + 1, []))[0]] == ["예정"]
        assert not (await store.keyword_hits(room, ["가상"], message + 1, []))[0]
        assert [entry["content"] for entry in await store.notes(room)] == [""]
        assert db.admin("SELECT content FROM marong.summaries WHERE id=%s", (summary,)) == [("가상 요약",)]
        assert db.admin("SELECT state,attempts FROM marong.forget_marks WHERE target_type='note' AND target_id=%s",
                        (note,)) == [("dropped", 3)]
    finally:
        await store.close()


async def check_reply_context(db):
    from marong.agent import Agent, Incoming
    from marong.config import load_settings

    [(friend,)] = db.admin("INSERT INTO marong.friends(name) VALUES ('reply fixture') RETURNING id")
    [(other,)] = db.admin("INSERT INTO marong.friends(name) VALUES ('other reply fixture') RETURNING id")
    direct, group = "fixture-context-direct", "fixture-context-group"
    db.admin("INSERT INTO marong.rooms(room_key,is_channel) VALUES (%s,true)", (direct,))
    db.admin("INSERT INTO marong.rooms(room_key,is_channel,memory_room) VALUES (%s,false,%s)", (group, direct))
    db.admin("INSERT INTO marong.people(user_key,friend_id) VALUES ('context-author',%s),('context-other',%s)",
             (friend, other))

    store = Store(db.app_url, call_bridge=False)
    await store.open(wait=True)
    try:
        async def add_memory(owner, room, phrase, *, kind="fact", share="self", sensitivity=None):
            user = "context-author" if owner == friend else "context-other"
            source = await store.add_message(room, "user", f"출처 합성 문장 {phrase}", user)
            [(ident,)] = db.admin("""
                INSERT INTO marong.memory_items(friend_id,kind,text,status,heard_at,channel,message_id,quote,
                    room_key,share,sensitive,source)
                VALUES (%s,%s,%s,'current',now(),%s,%s,'출처 합성 문장',%s,%s,%s,'text')
                RETURNING id
            """, (owner, kind, phrase, "app" if room == direct else "kakao_group", source,
                  None if room == direct else room, share, sensitivity))
            return ident

        await add_memory(friend, direct, "개인 고정 항목")
        await add_memory(friend, direct, "개인 민감 항목", sensitivity="health")
        recalled = await add_memory(friend, direct, "서점 취향 검색", kind="hard")
        await add_memory(friend, group, "공개 운동회 일정", share="known")
        await add_memory(other, direct, "다른 친구 비공개")
        await store.add_message(group, "user", "같은 방 등장", "context-other")
        db.admin("UPDATE marong.friends SET share=true WHERE id=%s", (other,))
        db.admin("INSERT INTO marong.shared_notes(friend_id,content,close_content) VALUES (%s,%s,%s)",
                 (other, "- 공개 공유 소식", "- 친한 사이 한정 속사정"))
        with patch.dict("os.environ", {"BOT_TOKEN": "fixture", "ANTHROPIC_API_KEY": "fixture",
                                      "DATABASE_URL": db.app_url, "PROMPT_PATH": str(ROOT / "prompt.md")}):
            settings = load_settings()
        embedding = SimpleNamespace(ready=False)
        agent = Agent(settings, store, embedding, None)
        agent.friend_memory_mode = "on"
        person = {"friend_id": friend, "name": "fixture"}
        msg = Incoming(direct, "context-author", "서점 얘기 들려줘")

        async def context(message, owner):
            current = await store.add_message(message.room_key, "user", message.text, message.user_key)
            return await agent._context(message, owner, current, message.text)

        first, messages, meta = await context(msg, person)
        [stable] = [part for part in first if part["text"].startswith("# 고정 요약")]
        assert "개인 고정 항목" in stable["text"] and "개인 민감 항목" in stable["text"]
        assert "다른 친구 비공개" not in stable["text"] and "공개 운동회" not in stable["text"]
        assert stable["cache_control"]["type"] == "ephemeral"
        assert first[-1]["text"].startswith("# 지금 상황")
        assert [block["text"] for block in messages[-1]["content"]][-1].startswith("# 찾은 기억")
        assert "서점 취향 검색" in messages[-1]["content"][-1]["text"]
        assert "서점 취향 검색" not in repr(meta)

        await add_memory(friend, direct, "나중에 들어온 고정 항목")
        for prompt in ("서점 이야기 한 번 더", "서점 궁금해"):
            system, _, _ = await context(Incoming(direct, "context-author", prompt), person)
            assert [part for part in system if part["text"].startswith("# 고정 요약")] == [stable]
        reset_target = await add_memory(friend, direct, "회수할 시험 항목")
        await forget_selected(store.pool, friend, "item", reset_target, "fixture-reset", via="screen")
        system, _, _ = await context(msg, person)
        assert "나중에 들어온 고정 항목" in str(system)
        assert "회수할 시험 항목" not in str(system)

        group_msg = Incoming(group, "context-author", "운동회 일정 알려줘", is_channel=False)
        group_system, group_messages, _ = await context(group_msg, {**person, "memory_room": direct})
        group_dump = repr((group_system, group_messages))
        assert "공개 운동회 일정" in group_dump
        assert not any(clue in group_dump for clue in ("개인 고정 항목", "개인 민감 항목", "다른 친구 비공개"))
        assert "1:1 얘기도 이어서" not in group_dump
        assert "공개 공유 소식" not in group_dump
        group_msg.visible_friends = {friend, other}
        group_system, _, _ = await context(group_msg, person)
        assert "공개 공유 소식" in repr(group_system)
        assert "친한 사이 한정 속사정" not in repr(group_system)
        assert "다른 친구 비공개" not in repr(group_system)

        semantic_phrase = "길 잃은 물건"
        await add_memory(friend, direct, semantic_phrase, kind="hard")
        agent.emb = SimpleNamespace(ready=True, model="fixture-semantic",
            query=AsyncMock(return_value=[1, 0]), documents=AsyncMock(side_effect=lambda rows:
                [[1, 0] if phrase == semantic_phrase else [0, 1] for phrase in rows]))
        semantic = Incoming(direct, "context-author", "분실 관련 알려줘")
        sem_system, sem_messages, _ = await context(semantic, person)
        assert semantic_phrase in sem_messages[-1]["content"][-1]["text"]
        assert semantic_phrase not in repr(sem_system)

        async def delay(_):
            await asyncio.sleep(3)
        agent.emb.documents.side_effect = delay
        with patch("marong.agent.EMBED_TIMEOUT_S", .03):
            timeout_system, timeout_messages, _ = await context(semantic, person)
        assert "# 고정 요약" in repr(timeout_system) and "# 찾은 기억" not in repr(timeout_messages)
        agent.emb = embedding

        agent.friend_memory_mode = "shadow"
        shadow_system, shadow_messages, _ = await context(msg, person)
        assert "# 고정 요약" not in repr(shadow_system) and "# 찾은 기억" not in repr(shadow_messages)
        agent.friend_memory_mode = "on"

        async def during_reply(_system, _messages, _msg, _end):
            await forget_selected(store.pool, friend, "item", recalled, "fixture-concurrent", via="screen")
            return "회수 이전의 내용이 든 응답", {}

        agent.ask = during_reply
        reply, _ = await agent._reply(msg, person, None, msg.text, 3)
        assert reply == "방금 기억이 바뀌어서 다시 확인하고 있어. 지금 이야기부터 이어 가자."
    finally:
        await store.close()


async def check_forget_dialogue(db):
    from fakes import ScriptedLLM, message, tool_use
    from marong.agent import Agent, Incoming
    from marong.config import load_settings
    from marong.friend_card import FriendCards
    from marong.friend_forget import request_tool

    [(owner,), (other,)] = db.admin("""INSERT INTO marong.friends(name) VALUES
        ('forget-tool fixture'),('other-forget-tool fixture') RETURNING id""")
    private, group = "fixture-forget-tool-dm", "fixture-forget-tool-group"
    db.admin("INSERT INTO marong.rooms(room_key,is_channel) VALUES (%s,true),(%s,false)", (private, group))
    db.admin("""INSERT INTO marong.people(user_key,friend_id) VALUES
        ('forget-tool-user',%s),('forget-tool-other',%s)""", (owner, other))
    store = Store(db.app_url, call_bridge=False)
    await store.open(wait=True)
    try:
        async def seed(text, friend=owner):
            user = "forget-tool-user" if friend == owner else "forget-tool-other"
            original = await store.add_message(private, "user", text, user)
            [(ident,)] = db.admin("""
                INSERT INTO marong.memory_items(friend_id,kind,text,channel,message_id,quote,heard_at,source)
                VALUES (%s,'fact',%s,'app',%s,%s,now(),'text') RETURNING id""", (friend, text, original, text))
            return ident, original

        red, _ = await seed("가상 붉은 운동화")
        blue, source = await seed("가상 파란 운동화")
        outsider, _ = await seed("외부 운동화", other)

        async def ask(text, key, args, room=private):
            current = await store.add_message(room, "user", text, "forget-tool-user")
            return await request_tool(store.pool, owner, room, current, key, args), current

        result, _ = await ask("운동화 잊어 줘", "ambiguous",
                              {"quote": "운동화 잊어 줘", "fragment": "운동화", "item_id": red})
        assert result["status"] == "ask_which" and {row["id"] for row in result["candidates"]} == {red, blue}
        result, _ = await ask("운동화 잊어 줘", "foreign",
                              {"quote": "운동화 잊어 줘", "item_id": outsider})
        assert result["status"] == "none_matched"
        result, _ = await ask("운동화 잊지 마", "negative", {"quote": "잊어 줘", "item_id": red})
        assert result["status"] == "refused"
        result, _ = await ask("가상 붉은 운동화 잊어 줘", "group",
                              {"quote": "가상 붉은 운동화 잊어 줘", "item_id": red}, room=group)
        assert result["status"] == "none_matched"
        assert db.admin("SELECT count(*) FROM marong.memory_forgets WHERE friend_id=%s", (owner,)) == [(0,)]

        args = {"quote": "파란 운동화 잊어 줘", "fragment": "파란 운동화"}
        success, current = await ask(args["quote"], "accepted", args)
        assert success == {"status": "ok", "forgot": 1, "messages": 1}
        assert await request_tool(store.pool, owner, private, current, "accepted", args) == success
        assert db.admin("SELECT target_id FROM marong.forget_marks WHERE friend_id=%s AND target_type='message'",
                        (owner,)) == [(source,)]

        raw = await store.add_message(private, "user", "겨울나무표식 이야기", "forget-tool-user")
        raw_args = {"quote": "겨울나무표식 원문을 잊어 줘", "fragment": "겨울나무표식", "source_only": True}
        result, _ = await ask(raw_args["quote"], "source-only", raw_args)
        assert result == {"status": "ok", "forgot": 0, "messages": 1}
        assert db.admin("SELECT content FROM marong.messages WHERE id=%s", (raw,)) == [("겨울나무표식 이야기",)]
        assert all(row["id"] != raw for row in await store.recent(private, 100))
        repeat, _ = await ask(raw_args["quote"], "new-source-only-key", raw_args)
        assert repeat["status"] == "none_matched"
        assert db.admin("SELECT count(*) FROM marong.forget_marks WHERE friend_id=%s AND target_type='message'",
                        (owner,)) == [(2,)]

        with patch.dict("os.environ", {"BOT_TOKEN": "fixture", "ANTHROPIC_API_KEY": "fixture",
                                      "DATABASE_URL": db.app_url, "PROMPT_PATH": str(ROOT / "prompt.md")}):
            settings = load_settings()
        payload = {"quote": "붉은 운동화 잊어 줘", "fragment": "붉은 운동화"}
        llm = ScriptedLLM(lambda _: message([tool_use("memory_forget", payload)], "tool_use"))
        agent = Agent(settings, store, SimpleNamespace(ready=False), llm)
        agent.friend_cards = FriendCards(store)
        agent.friend_memory_mode = "on"

        async def send(text):
            assert text == "응, 잊었어"
            assert db.admin("SELECT status FROM marong.memory_items WHERE id=%s", (red,)) == [("forgotten",)]
            return True

        assert await agent.handle(Incoming(private, "forget-tool-user", payload["quote"]), send) == "응, 잊었어"
        assert len(llm.bodies) == 1
        assert any(definition["name"] == "memory_forget" for definition in llm.bodies[0]["tools"])
        assert db.admin("SELECT status FROM marong.memory_items WHERE id=%s", (outsider,)) == [("current",)]

        agent.ask = AsyncMock(return_value=("응, 잊었어", {}))
        actual, _ = await agent._reply(Incoming(private,"forget-tool-user","그거 잊어 줘"), None, None,
                                       "그거 잊어 줘", 2)
        assert actual == "지금은 못 지웠어"

        # Reports read through the bot role and the existing transcript view.
        import psycopg
        from psycopg.rows import dict_row
        from tools.report import call_transcripts, fetch

        echo = await store.add_message(private, "assistant", "가상 옛 답변", reply_to=source,
                                       meta={"delivered": True})
        [(caller,)] = db.admin("INSERT INTO call.callers(friend_id) VALUES (%s) RETURNING id", (owner,))
        [(call,)] = db.admin("""
            INSERT INTO call.calls(caller_id,client_id,prompt_version,voice,status,ended_at,end_reason,organize_status)
            VALUES (%s,gen_random_uuid(),'fixture','fixture','ended',now(),'hangup','skipped') RETURNING id
        """, (caller,))
        [(segment,)] = db.admin("""
            INSERT INTO call.segments(call_id,mode,client_id) VALUES (%s,'start',gen_random_uuid()) RETURNING id
        """, (call,))
        [(turn,), (kept_turn,)] = db.admin("""
            INSERT INTO call.turns(call_id,segment_id,seq,role,content,started_at,ended_at,finalized)
            VALUES (%s,%s,1,'user','잊을 합성 통화',now(),now(),true),
                   (%s,%s,2,'user','남은 합성 통화',now(),now(),true) RETURNING id
        """, (call, segment, call, segment))
        [(voice_item,)] = db.admin("""
            INSERT INTO marong.memory_items(friend_id,kind,text,channel,call_turn_id,quote,heard_at,source)
            VALUES (%s,'fact','합성 통화','call',%s,'잊을 합성 통화',now(),'call') RETURNING id
        """, (owner, turn))
        await forget_selected(store.pool, owner, "item", voice_item, "fixture-voice-report", via="screen")
        assert db.admin("SELECT forgotten_at FROM call.turns WHERE id=%s", (turn,)) == [(None,)]
        with psycopg.connect(db.app_url, row_factory=dict_row) as report:
            report.read_only = True
            start, end = datetime.now(timezone.utc)-timedelta(days=2), datetime.now(timezone.utc)+timedelta(seconds=1)
            data = fetch(report, start, end, vectors=False)
            visible = {row["id"] for row in data["messages"]}
            assert not {source, echo, raw} & visible
            assert not {source, echo, raw} & set(data["ref_messages"])
            turns = {row["id"] for row in call_transcripts(report, start, end)}
            assert kept_turn in turns and turn not in turns
    finally:
        await store.close()


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(check_queue(db))
        asyncio.run(check_worker(db))
        asyncio.run(check_call_worker(db))
        asyncio.run(check_forget_transaction(db))
        asyncio.run(check_reply_context(db))
        asyncio.run(check_forget_dialogue(db))
    finally:
        db.close()
    print("TC-330: debounced text, call eligibility, concurrent claims, lease recovery, fencing and ID-only checkpoints passed")
    print("TC-331–334: synthetic extraction, room scope, replacement, call provenance and loop expiry passed")
    print("TC-335: tool evidence, private list and room-scoped visibility passed")
    print("Text runtime: a retryable connection error retried once and stored the scheduled message")
    print("TC-341: the call organizer saved a sourced open loop after legacy organization failed")

    print("TC-336 transaction: ownership, sibling text and loops, source marks, vector removal and concurrent receipts")

    print("TC-337: validated rewrites, 10-minute retries, clean keyword reads and blank fallback")

    print("TC-339/340: scoped group input, cached prefix, transient recall, shadow parity and concurrent forget fencing")

    print("TC-336 dialogue: owner intent, ambiguity, original-only marking, idempotency and commit-before-ack")

    print("TC-336 report: excluded original and reply plus marked call without raw-table changes")
