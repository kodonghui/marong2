"""Keep text memory checkpoints ordered with a friend's forget transaction."""

from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


class TextMemorySaver(AsyncPostgresSaver):
    def __init__(self, checkpoint_pool, store_pool):
        super().__init__(checkpoint_pool)
        self.store_pool = store_pool
        self.active = {}

    @asynccontextmanager
    async def job(self, config, state):
        thread = config["configurable"]["thread_id"]
        self.active[thread] = (state["friend_id"], state["message_ids"])
        try:
            yield
        finally:
            self.active.pop(thread, None)

    @asynccontextmanager
    async def allow_write(self, config):
        thread = config["configurable"]["thread_id"]
        reference = self.active.get(thread)
        if reference is None:
            yield True
            return
        friend, messages = reference
        async with self.store_pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(%s::bigint)", (friend,))
            result = await conn.execute("""
                SELECT NOT EXISTS (
                    SELECT 1 FROM marong.forget_marks
                    WHERE friend_id=%s AND target_type='message' AND target_id=ANY(%s::bigint[])
                ) AS allowed
            """, (friend, messages))
            yield (await result.fetchone())["allowed"]

    async def aput(self, config, checkpoint, metadata, new_versions):
        async with self.allow_write(config) as allowed:
            if allowed:
                return await super().aput(config, checkpoint, metadata, new_versions)
        # The already-running graph can finish with its in-memory state. Its
        # persistence step still revalidates the message against forget_marks.
        return {"configurable": {**config["configurable"], "checkpoint_id": checkpoint["id"]}}

    async def aput_writes(self, config, writes, task_id, task_path=""):
        async with self.allow_write(config) as allowed:
            if allowed:
                await super().aput_writes(config, writes, task_id, task_path)
