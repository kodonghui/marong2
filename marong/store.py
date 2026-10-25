"""Postgres 저장소(psycopg 3 비동기).
대화 원문·요약·메모는 쌓기만 하고 지우거나 고치지 않는다. 봇 계정(marong)에는 그 권한 자체가 없다(schema.sql)."""
import hashlib
import logging

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("store")

SCHEMA_VERSION = 1
# 'ㅋㅋㅋ'·'ㅇㅇ'·이모티콘만 있는 말은 검색해도 쓸모가 없어 임베딩하지 않음(한글 음절·영문·숫자가 2개 이상 이어진 말만)
MEANINGFUL = "[가-힣A-Za-z0-9]{2}"


def vec(values) -> str:
    """pgvector 글자 형식 '[0.1,0.2,…]'."""
    return "[" + ",".join(f"{float(x):.6f}" for x in values) + "]"


def speaker_label(user_key: str | None, name: str | None) -> str:
    """이름을 모르는 친구는 '친구-a1b2'처럼 키로 만든 짧은 표시를 쓴다(키 원문은 드러내지 않음)."""
    if name:
        return name
    return "친구-" + hashlib.sha1((user_key or "").encode()).hexdigest()[:4]


class Store:
    def __init__(self, conninfo: str, timeout: float = 5):
        # timeout: DB 가 죽어 있을 때 연결을 기다리는 시간. 넘으면 오류 → 기억 없이 답함(답이 너무 늦지 않게)
        self.pool = AsyncConnectionPool(conninfo, min_size=1, max_size=4, open=False, timeout=timeout,
                                        kwargs={"autocommit": True, "row_factory": dict_row})

    async def open(self, wait: bool = False, timeout: float = 10) -> None:
        """wait=False 면 DB 가 늦게 떠도 봇은 먼저 켜지고, 연결은 뒤에서 계속 시도한다."""
        await self.pool.open(wait=wait, timeout=timeout)

    async def close(self) -> None:
        await self.pool.close()

    async def _all(self, sql: str, params=()) -> list[dict]:
        async with self.pool.connection() as c:
            cur = await c.execute(sql, params)
            return await cur.fetchall()

    async def _one(self, sql: str, params=()) -> dict | None:
        async with self.pool.connection() as c:
            cur = await c.execute(sql, params)
            return await cur.fetchone()

    async def schema_version(self) -> int | None:
        row = await self._one("SELECT value FROM marong.meta WHERE key = 'schema_version'")
        return int(row["value"]) if row else None

    # ── 답장할 때 ──────────────────────────────────────────────

    async def touch(self, room_key: str, is_channel: bool, user_key: str) -> dict:
        """방·친구를 처음 보면 만들고 마지막으로 본 시각을 바꾼다. 친구 줄(이름 포함)을 돌려준다."""
        async with self.pool.connection() as c:
            await c.execute(
                "INSERT INTO marong.rooms (room_key, is_channel) VALUES (%s, %s) "
                "ON CONFLICT (room_key) DO UPDATE SET last_seen = now(), is_channel = EXCLUDED.is_channel",
                (room_key, is_channel))
            cur = await c.execute(
                "INSERT INTO marong.people (user_key) VALUES (%s) "
                "ON CONFLICT (user_key) DO UPDATE SET last_seen = now() RETURNING user_key, name",
                (user_key,))
            return await cur.fetchone()

    async def add_message(self, room_key: str, role: str, content: str, user_key: str | None = None,
                          kakao_id: str | None = None, reply_to: int | None = None, meta: dict | None = None) -> int | None:
        """새 메시지 id. 같은 카카오 메시지가 이미 저장돼 있으면 None."""
        row = await self._one(
            "INSERT INTO marong.messages (room_key, user_key, role, content, kakao_id, reply_to, meta) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (room_key, kakao_id) DO NOTHING RETURNING id",
            (room_key, user_key, role, content, kakao_id, reply_to, Jsonb(meta or {})))
        return row["id"] if row else None

    async def recent(self, room_key: str, limit: int) -> list[dict]:
        """방의 최근 메시지(오래된 것부터). 친구에게 전달되지 못한 마롱이 답은 뺀다."""
        rows = await self._all(
            "SELECT m.id, m.role, m.user_key, p.name, m.content, m.created_at FROM marong.messages m "
            "LEFT JOIN marong.people p ON p.user_key = m.user_key "
            "WHERE m.room_key = %s AND m.meta->>'delivered' IS DISTINCT FROM 'false' "
            "ORDER BY m.id DESC LIMIT %s", (room_key, limit))
        return rows[::-1]

    async def summaries(self, room_key: str, limit: int) -> list[dict]:
        """방의 최근 요약(오래된 것부터). until 은 요약한 구간의 마지막 메시지 시각."""
        rows = await self._all(
            "SELECT s.id, s.first_id, s.last_id, s.content, m.created_at AS until FROM marong.summaries s "
            "JOIN marong.messages m ON m.id = s.last_id "
            "WHERE s.room_key = %s ORDER BY s.last_id DESC LIMIT %s", (room_key, limit))
        return rows[::-1]

    async def notes(self, room_key: str) -> list[dict]:
        """방 안 친구마다 가장 최근 메모."""
        return await self._all(
            "SELECT DISTINCT ON (n.user_key) n.user_key, p.name, n.content, n.created_at FROM marong.notes n "
            "JOIN marong.people p ON p.user_key = n.user_key WHERE n.room_key = %s "
            "ORDER BY n.user_key, n.id DESC", (room_key,))

    async def room_events(self, room_key: str) -> dict:
        """이벤트용: 이 방에서 친구들이 보낸 메시지 수, 마지막 이벤트 뒤 지난 초(없으면 None), 했던 이벤트 이름."""
        return await self._one(
            "SELECT count(*) FILTER (WHERE role = 'user') AS said, "
            "  extract(epoch FROM now() - max(created_at) FILTER (WHERE meta ? 'event'))::float8 AS since_s, "
            "  coalesce(array_agg(DISTINCT meta->>'event') FILTER (WHERE meta ? 'event'), '{}') AS events "
            "FROM marong.messages WHERE room_key = %s", (room_key,))

    async def set_name(self, user_key: str, name: str) -> None:
        async with self.pool.connection() as c:
            await c.execute("UPDATE marong.people SET name = %s, name_set_at = now() WHERE user_key = %s",
                            (name, user_key))

    async def similar(self, model: str, room_key: str, vector, before_id: int, skip_summary_ids: list[int],
                      limit: int) -> list[dict]:
        """같은 방에서 지금 말과 비슷한 예전 메시지·요약(비슷한 순). 최근 원문 구간과 이미 넣은 요약은 뺀다."""
        return await self._all(
            "WITH q AS (SELECT %s::vector AS v), hits AS ("
            "  SELECT e.source_type, e.source_id, 1 - (e.embedding <=> q.v) AS similarity "
            "  FROM marong.embeddings e, q WHERE e.model = %s AND e.room_key = %s "
            "  AND NOT (e.source_type = 'message' AND e.source_id >= %s) "
            "  AND NOT (e.source_type = 'summary' AND e.source_id = ANY(%s::bigint[])) "
            "  ORDER BY e.embedding <=> q.v LIMIT %s) "
            "SELECT h.source_type, h.source_id, h.similarity, m.role, m.user_key, p.name, "
            "  coalesce(m.content, s.content) AS content, coalesce(m.created_at, s.created_at) AS created_at "
            "FROM hits h "
            "LEFT JOIN marong.messages m ON h.source_type = 'message' AND m.id = h.source_id "
            "LEFT JOIN marong.people p ON p.user_key = m.user_key "
            "LEFT JOIN marong.summaries s ON h.source_type = 'summary' AND s.id = h.source_id "
            "ORDER BY h.similarity DESC",
            (vec(vector), model, room_key, before_id, list(skip_summary_ids), limit))

    # ── 뒤에서 하는 일(임베딩·요약) ─────────────────────────────

    async def pending_embeddings(self, model: str, limit: int) -> list[dict]:
        """아직 이 모델 임베딩이 없는 메시지·요약."""
        return await self._all(
            "(SELECT 'message' AS source_type, m.id AS source_id, m.room_key, m.content FROM marong.messages m "
            " WHERE m.content ~ %s AND NOT EXISTS (SELECT 1 FROM marong.embeddings e "
            "   WHERE e.model = %s AND e.source_type = 'message' AND e.source_id = m.id) ORDER BY m.id LIMIT %s) "
            "UNION ALL "
            "(SELECT 'summary', s.id, s.room_key, s.content FROM marong.summaries s "
            " WHERE s.content ~ %s AND NOT EXISTS (SELECT 1 FROM marong.embeddings e "
            "   WHERE e.model = %s AND e.source_type = 'summary' AND e.source_id = s.id) ORDER BY s.id LIMIT %s)",
            (MEANINGFUL, model, limit, MEANINGFUL, model, limit))

    async def add_embeddings(self, model: str, rows: list[tuple[str, int, str, list[float]]]) -> None:
        """rows: (source_type, source_id, room_key, 벡터)."""
        async with self.pool.connection() as c:
            async with c.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO marong.embeddings (model, source_type, source_id, room_key, embedding) "
                    "VALUES (%s, %s, %s, %s, %s::vector) ON CONFLICT DO NOTHING",
                    [(model, t, i, r, vec(v)) for t, i, r, v in rows])

    async def rooms_due(self, min_messages: int) -> list[str]:
        """마지막 요약 뒤로 메시지가 min_messages 개 이상 쌓인 방."""
        rows = await self._all(
            "SELECT m.room_key FROM marong.messages m "
            "LEFT JOIN (SELECT room_key, max(last_id) AS last_id FROM marong.summaries GROUP BY room_key) s "
            "  ON s.room_key = m.room_key "
            "WHERE m.id > coalesce(s.last_id, 0) GROUP BY m.room_key HAVING count(*) >= %s", (min_messages,))
        return [r["room_key"] for r in rows]

    async def unsummarized(self, room_key: str, limit: int) -> list[dict]:
        """마지막 요약 뒤의 메시지(오래된 것부터). delivered 가 False 면 친구에게 전달되지 못한 답."""
        return await self._all(
            "SELECT m.id, m.role, m.user_key, p.name, m.content, m.created_at, "
            "  m.meta->>'delivered' IS DISTINCT FROM 'false' AS delivered FROM marong.messages m "
            "LEFT JOIN marong.people p ON p.user_key = m.user_key "
            "WHERE m.room_key = %s AND m.id > coalesce("
            "  (SELECT max(last_id) FROM marong.summaries WHERE room_key = %s), 0) "
            "ORDER BY m.id LIMIT %s", (room_key, room_key, limit))

    async def add_summary(self, room_key: str, first_id: int, last_id: int, content: str,
                          notes: dict[str, str], meta: dict) -> int | None:
        """요약 한 개와 바뀐 친구 메모를 한 트랜잭션으로 쓴다. 같은 구간이 이미 있으면 None."""
        async with self.pool.connection() as c:
            async with c.transaction():
                cur = await c.execute(
                    "INSERT INTO marong.summaries (room_key, first_id, last_id, content, meta) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (room_key, last_id) DO NOTHING RETURNING id",
                    (room_key, first_id, last_id, content, Jsonb(meta)))
                row = await cur.fetchone()
                if not row:
                    return None
                for user_key, text in notes.items():
                    await c.execute(
                        "INSERT INTO marong.notes (room_key, user_key, content, summary_id) VALUES (%s, %s, %s, %s)",
                        (room_key, user_key, text, row["id"]))
                return row["id"]

    async def can_delete(self) -> bool:
        """--check 용: 봇 계정이 대화 원문을 지우거나 고칠 수 있는지(정상이면 False)."""
        row = await self._one(
            "SELECT has_table_privilege('marong.messages', 'DELETE') OR has_table_privilege('marong.messages', 'UPDATE') "
            "OR has_table_privilege('marong.messages', 'TRUNCATE') AS can")
        return bool(row["can"])

    async def counts(self) -> dict:
        """--check·관리 도구용 개수."""
        return await self._one(
            "SELECT (SELECT count(*) FROM marong.rooms) AS rooms, (SELECT count(*) FROM marong.people) AS people, "
            "(SELECT count(*) FROM marong.messages) AS messages, (SELECT count(*) FROM marong.summaries) AS summaries, "
            "(SELECT count(*) FROM marong.embeddings) AS embeddings")
