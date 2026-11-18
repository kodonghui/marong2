"""TC-330 with isolated PostgreSQL, the service roles and a fake graph node."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.conninfo import make_conninfo

from marong.graphs.memory import LEASE, MemoryQueue, checkpoint_pool, compile_graph
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
            assert await call_queue.finish(call_work, "ok")
            assert not await call_queue.claim("call")
        finally:
            await call_store.close()
        assert_sqlstate(db, "marong", "SELECT 1 FROM call.turns WHERE false", "42501")
    finally:
        await store.close()


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(check_queue(db))
    finally:
        db.close()
    print("TC-330: debounced text, call eligibility, concurrent claims, lease recovery, fencing and ID-only checkpoints passed")
