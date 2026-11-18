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

from marong.friend_card import KST
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


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(check_queue(db))
        asyncio.run(check_worker(db))
        asyncio.run(check_call_worker(db))
    finally:
        db.close()
    print("TC-330: debounced text, call eligibility, concurrent claims, lease recovery, fencing and ID-only checkpoints passed")
    print("TC-331–334: synthetic extraction, room scope, replacement, call provenance and loop expiry passed")
    print("TC-335: tool evidence, private list and room-scoped visibility passed")
    print("Text runtime: a retryable connection error retried once and stored the scheduled message")
    print("TC-341: the call organizer saved a sourced open loop after legacy organization failed")
