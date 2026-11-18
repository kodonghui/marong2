"""Friend-memory scheduling and lease fencing (SPEC-224–225, TBL-127)."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, TypedDict
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

IDLE = timedelta(seconds=60)
LEASE = timedelta(minutes=10)
MAX_MESSAGES = 200
MAX_ATTEMPTS = 3
log = logging.getLogger("friend_memory")


class MemoryState(TypedDict):
    friend_id: int
    source: Literal["text", "call"]
    token: str
    message_ids: list[int]
    next_message_id: int | None
    call_ids: list[str]


async def lock_message_writer(conn, user_key):
    cursor = await conn.execute("SELECT friend_id FROM marong.people WHERE user_key=%s", (user_key,))
    identity = await cursor.fetchone()
    friend_id = identity["friend_id"] if identity else None
    if friend_id is not None:
        # Message IDs from two senders linked to the same friend must commit in order.
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('memory:text:'||%s::text,0))",
                           (friend_id,))
    return friend_id


async def schedule_text(conn, friend_id, created_at):
    await conn.execute(
        """INSERT INTO marong.memory_jobs AS work(friend_id,source,due_at)
        VALUES (%s,'text',%s) ON CONFLICT(friend_id,source) DO UPDATE
          SET due_at=greatest(work.due_at,excluded.due_at),updated_at=now()""",
        (friend_id, created_at + IDLE),
    )


async def message_ids(conn, friend_id, watermark):
    cursor = await conn.execute(
        """SELECT m.id FROM marong.messages m JOIN marong.people p ON p.user_key=m.user_key
           WHERE p.friend_id=%s AND m.id>%s AND m.role='user'
             AND NOT EXISTS(SELECT 1 FROM marong.forget_marks f
                            WHERE f.friend_id=p.friend_id AND f.target_type='message'
                              AND f.target_id=m.id AND f.state='forgotten')
           ORDER BY m.id LIMIT %s""",
        (friend_id, watermark, MAX_MESSAGES + 1),
    )
    return [entry["id"] for entry in await cursor.fetchall()]


class MemoryQueue:
    def __init__(self, pool, *, clock=None):
        self.pool = pool
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def claim(self, source):
        now = self.clock()
        token = uuid4()
        async with self.pool.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                """WITH due AS (
                   SELECT friend_id FROM marong.memory_jobs WHERE source=%s AND due_at<=%s
                     AND (lease_until IS NULL OR lease_until<=%s)
                   ORDER BY due_at,friend_id LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE marong.memory_jobs work SET token=%s,lease_until=%s,updated_at=%s
                FROM due WHERE work.source=%s AND work.friend_id=due.friend_id
                RETURNING work.friend_id,work.watermark,work.calls""",
                (source, now, now, token, now + LEASE, now, source),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            ids = []
            if source == "text":
                ids = await message_ids(conn, row["friend_id"], row["watermark"])
        return MemoryState(friend_id=row["friend_id"], source=source, token=str(token),
                           message_ids=ids[:MAX_MESSAGES], next_message_id=ids[MAX_MESSAGES] if len(ids) > MAX_MESSAGES else None,
                           call_ids=list(map(str, row["calls"])))

    async def finish(self, state, outcome, apply=None):
        """Publish results and advance the cursor in the same transaction under the lease."""
        now = self.clock()
        friend = state["friend_id"]
        source = state["source"]
        token = state["token"]
        async with self.pool.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                """SELECT watermark,calls,due_at,attempts FROM marong.memory_jobs
                WHERE friend_id=%s AND source=%s AND token=%s AND lease_until>%s FOR UPDATE""",
                (friend, source, token, now),
            )
            row = await cursor.fetchone()
            if row is None:
                return False
            attempts = row["attempts"] + 1 if outcome == "ai_error" else 0
            watermark = row["watermark"]
            calls = row["calls"]
            if 0 < attempts < MAX_ATTEMPTS:
                due = now + LEASE
            elif source == "text":
                watermark = max(state["message_ids"], default=watermark)
                remaining = await message_ids(conn, friend, watermark)
                due = None
                if remaining:
                    due = now if state["next_message_id"] else max(row["due_at"], now)
            else:
                completed_calls = set(state["call_ids"])
                calls = [call for call in calls if str(call) not in completed_calls]
                due = now if calls else None
            if apply is not None and outcome in {"ok", "rejected"}:
                await apply(conn, state)
            updated = await conn.execute(
                """UPDATE marong.memory_jobs SET watermark=%s,calls=%s,due_at=%s,attempts=%s,
                token=NULL,lease_until=NULL,last_outcome=%s,updated_at=%s
                WHERE friend_id=%s AND source=%s AND token=%s""",
                (watermark, calls, due, attempts if 0 < attempts < MAX_ATTEMPTS else 0,
                 outcome, now, friend, source, token),
            )
            return updated.rowcount == 1


def compile_graph(queue, prepare, persist, *, checkpointer):
    from langgraph.graph import END, START, StateGraph

    async def organize(state):
        if not state["message_ids"] and not state["call_ids"]:
            await queue.finish(state, "skipped")
            return {}
        result = await prepare(state)

        async def apply(conn, current):
            await persist(conn, current, result)

        await queue.finish(state, "ok", apply)
        return {}

    graph = StateGraph(MemoryState)
    graph.add_node("organize", organize)
    graph.add_edge(START, "organize")
    graph.add_edge("organize", END)
    return graph.compile(checkpointer=checkpointer)


async def run_queue(queue, graph, source):
    """Run only when the approved extractor and result validator are wired in."""
    while True:
        try:
            state = await queue.claim(source)
            if state is not None:
                thread = f"memory:{source}:{state['friend_id']}:{state['token']}"
                try:
                    await graph.ainvoke(state, {"configurable": {"thread_id": thread}})
                except Exception:
                    log.warning("friend_memory_job_failed source=%s", source)
                    await queue.finish(state, "ai_error")
        except Exception:
            log.error("friend_memory_queue_failed source=%s", source)
        await asyncio.sleep(10)


def checkpoint_pool(dsn):
    return AsyncConnectionPool(
        dsn, open=False, min_size=1, max_size=2, check=AsyncConnectionPool.check_connection,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row,
                "options": "-c search_path=talk_graph,public"},
    )
