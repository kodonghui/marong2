"""Postgres 저장소(psycopg 3 비동기).
대화 원문·요약·메모는 쌓기만 하고 지우거나 고치지 않는다. 봇 계정(marong)에는 그 권한 자체가 없다(schema.sql)."""
import hashlib
import logging
from datetime import datetime, timedelta

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("store")

SCHEMA_VERSION = 3
# 'ㅋㅋㅋ'·'ㅇㅇ'·이모티콘만 있는 말은 검색해도 쓸모가 없어 임베딩하지 않음(한글 음절·영문·숫자가 2개 이상 이어진 말만)
MEANINGFUL = "[가-힣A-Za-z0-9]{2}"
# 카카오에서 온 1:1 방(채널채팅)마다 친구의 마지막 말. 터미널 대화('terminal' 방)는 카카오 id 가 없어서 빠짐
CHANNEL_ROOMS = (
    "SELECT r.room_key, u.user_key, p.name, u.created_at AS last_said, r.proactive FROM marong.rooms r "
    "CROSS JOIN LATERAL (SELECT m.id, m.user_key, m.kakao_id, m.created_at FROM marong.messages m "
    "  WHERE m.room_key = r.room_key AND m.role = 'user' ORDER BY m.id DESC LIMIT 1) u "
    "LEFT JOIN marong.people p ON p.user_key = u.user_key "
    "WHERE r.is_channel AND u.kakao_id IS NOT NULL ")


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
        """방·친구를 처음 보면 만들고 마지막으로 본 시각을 바꾼다. 친구 줄(user_key, name, friend_id, share)에
        이 방의 선톡 받기(proactive)를 붙여 돌려준다. share 는 친구에 안 묶인 키(이름을 모름)면 None."""
        async with self.pool.connection() as c:
            cur = await c.execute(
                "INSERT INTO marong.rooms (room_key, is_channel) VALUES (%s, %s) "
                "ON CONFLICT (room_key) DO UPDATE SET last_seen = now(), is_channel = EXCLUDED.is_channel "
                "RETURNING proactive",
                (room_key, is_channel))
            room = await cur.fetchone()
            cur = await c.execute(
                "INSERT INTO marong.people (user_key) VALUES (%s) "
                "ON CONFLICT (user_key) DO UPDATE SET last_seen = now() RETURNING user_key, name, friend_id, "
                "(SELECT f.share FROM marong.friends f WHERE f.id = people.friend_id) AS share",
                (user_key,))
            return {**await cur.fetchone(), "proactive": room["proactive"]}

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

    async def set_name(self, user_key: str, name: str) -> int | None:
        """이름을 저장하고 이 키를 친구 한 명(friends)에 묶는다. 묶은 친구 id(카카오에서 말한 적 없는 키면 None)."""
        async with self.pool.connection() as c:
            async with c.transaction():
                await c.execute("UPDATE marong.people SET name = %s, name_set_at = now() WHERE user_key = %s",
                                (name, user_key))
                return await self._link(c, user_key, name)

    async def set_proactive(self, room_key: str, on: bool) -> None:
        async with self.pool.connection() as c:
            await c.execute("UPDATE marong.rooms SET proactive = %s WHERE room_key = %s", (on, room_key))

    # ── 친구들(서로 아는 사이) ───────────────────────────────────

    @staticmethod
    async def _link(c, user_key: str, name: str) -> int | None:
        """키를 친구에 묶는다(이미 묶였으면 친구 이름만 바꿈). 같은 이름 친구가 하나뿐이면 그 친구에, 아니면 새 친구로.
        사람마다 1:1 방은 하나라서 1:1 키는 이미 1:1 키가 있는 친구에게는 묶지 않는다. 터미널 대화 키는 묶지 않는다."""
        await c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("marong.friend:" + name,))
        cur = await c.execute("SELECT friend_id FROM marong.people WHERE user_key = %s FOR UPDATE", (user_key,))
        row = await cur.fetchone()
        if row is None:
            return None
        if row["friend_id"]:
            await c.execute("UPDATE marong.friends SET name = %s WHERE id = %s", (name, row["friend_id"]))
            return row["friend_id"]
        cur = await c.execute(
            "SELECT bool_or(r.is_channel) AS channel FROM marong.messages m "
            "JOIN marong.rooms r ON r.room_key = m.room_key WHERE m.user_key = %s AND m.kakao_id IS NOT NULL",
            (user_key,))
        channel = (await cur.fetchone())["channel"]
        if channel is None:
            return None
        cur = await c.execute(
            "SELECT f.id FROM marong.friends f WHERE f.name = %s AND NOT (%s AND EXISTS ("
            "  SELECT 1 FROM marong.people p JOIN marong.messages m ON m.user_key = p.user_key "
            "  JOIN marong.rooms r ON r.room_key = m.room_key WHERE p.friend_id = f.id AND r.is_channel))",
            (name, channel))
        found = await cur.fetchall()
        if len(found) == 1:
            friend_id = found[0]["id"]
        else:
            cur = await c.execute("INSERT INTO marong.friends (name) VALUES (%s) RETURNING id", (name,))
            friend_id = (await cur.fetchone())["id"]
        await c.execute("UPDATE marong.people SET friend_id = %s WHERE user_key = %s", (friend_id, user_key))
        return friend_id

    async def link_unlinked(self) -> int:
        """이름은 있는데 친구에 안 묶인 키를 묶는다(표 버전 3 으로 올린 뒤 한 번. 그 뒤엔 set_name 이 묶음)."""
        rows = await self._all("SELECT user_key, name FROM marong.people WHERE name IS NOT NULL AND friend_id IS NULL "
                               "ORDER BY first_seen")
        linked = 0
        for r in rows:
            async with self.pool.connection() as c:
                async with c.transaction():
                    linked += await self._link(c, r["user_key"], r["name"]) is not None
        return linked

    async def friend_circle(self, user_key: str, limit: int) -> list[dict]:
        """지금 말하는 친구 말고 마롱이가 아는 친구들(공유를 끈 친구는 뺌). 아는 사이(같은 단체방에서 말함·말해 준 관계)
        먼저, 그다음 최근에 본 순. 줄마다 name, told(말해 준 사이)·label(그 관계), same_group, shared(다른 친구에게 해도 되는 얘기)."""
        return await self._all(
            "WITH me AS (SELECT friend_id FROM marong.people WHERE user_key = %(k)s), "
            "keys AS (SELECT user_key FROM marong.people WHERE friend_id = (SELECT friend_id FROM me) "
            "  UNION SELECT %(k)s::text), "
            "mates AS (SELECT DISTINCT p.friend_id AS id FROM marong.messages m "
            "  JOIN marong.people p ON p.user_key = m.user_key WHERE p.friend_id IS NOT NULL AND m.room_key IN ("
            "    SELECT m2.room_key FROM marong.messages m2 JOIN marong.rooms r ON r.room_key = m2.room_key "
            "    WHERE NOT r.is_channel AND m2.user_key IN (SELECT user_key FROM keys))), "
            "told AS (SELECT CASE WHEN fs.friend_a = me.friend_id THEN fs.friend_b ELSE fs.friend_a END AS id, fs.label "
            "  FROM marong.friendships fs JOIN me ON me.friend_id IN (fs.friend_a, fs.friend_b)) "
            "SELECT f.id, f.name, t.id IS NOT NULL AS told, t.label, g.id IS NOT NULL AS same_group, s.content AS shared, "
            "  (SELECT max(p.last_seen) FROM marong.people p WHERE p.friend_id = f.id) AS last_seen "
            "FROM marong.friends f LEFT JOIN told t ON t.id = f.id LEFT JOIN mates g ON g.id = f.id "
            "LEFT JOIN LATERAL (SELECT x.content FROM marong.shared_notes x WHERE x.friend_id = f.id "
            "  ORDER BY x.id DESC LIMIT 1) s ON true "
            "WHERE f.share AND f.id IS DISTINCT FROM (SELECT friend_id FROM me) "
            "  AND EXISTS (SELECT 1 FROM marong.people p WHERE p.friend_id = f.id) "
            "ORDER BY (t.id IS NOT NULL OR g.id IS NOT NULL) DESC, last_seen DESC NULLS LAST LIMIT %(n)s",
            {"k": user_key, "n": limit})

    async def add_friendship(self, user_key: str, name: str, label: str) -> tuple[str, str | None]:
        """지금 말하는 친구와 name 친구를 아는 사이로 저장한다. 돌려주는 것: (결과, 말하는 친구 이름).
        결과: ok | no_speaker(이름을 몰라 친구에 안 묶인 키) | unknown(그 이름 친구 없음) | ambiguous(여럿) | self"""
        async with self.pool.connection() as c:
            async with c.transaction():
                cur = await c.execute("SELECT f.id, f.name FROM marong.people p JOIN marong.friends f ON f.id = p.friend_id "
                                      "WHERE p.user_key = %s", (user_key,))
                me = await cur.fetchone()
                if not me:
                    return "no_speaker", None
                cur = await c.execute(
                    "SELECT f.id FROM marong.friends f WHERE f.name = %s AND f.id <> %s "
                    "AND EXISTS (SELECT 1 FROM marong.people p WHERE p.friend_id = f.id)", (name, me["id"]))
                others = await cur.fetchall()
                if not others:
                    return ("self" if name == me["name"] else "unknown"), me["name"]
                if len(others) > 1:
                    return "ambiguous", me["name"]
                a, b = sorted((me["id"], others[0]["id"]))
                await c.execute(
                    "INSERT INTO marong.friendships (friend_a, friend_b, label, told_by) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (friend_a, friend_b) DO UPDATE SET label = EXCLUDED.label, told_by = EXCLUDED.told_by",
                    (a, b, label or None, me["id"]))
                return "ok", me["name"]

    async def set_share(self, user_key: str, on: bool) -> bool:
        """지금 말하는 친구의 공유(가벼운 얘기를 아는 친구에게 해도 되는지)를 바꾼다. 친구에 안 묶인 키면 False."""
        row = await self._one("UPDATE marong.friends f SET share = %s FROM marong.people p "
                              "WHERE p.user_key = %s AND p.friend_id = f.id RETURNING f.id", (on, user_key))
        return row is not None

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

    # ── 선톡(먼저 말 걸기) ──────────────────────────────────────

    async def proactive_due(self, today: datetime, every_days: int, limit: int,
                            room_key: str | None = None) -> list[dict]:
        """선톡할 1:1 방(오래 조용한 친구부터): 선톡을 켜 둔 방에서 친구가 오늘(today = 한국 시각 0시) 아직 말하지
        않았고, 최근 every_days 일(오늘 포함) 안에 선톡을 안 보냈고, 지난 선톡에 친구가 답한(또는 선톡을 받은 적 없는)
        방. 보냈다가 전달에 실패한 것도 보낸 것으로 친다. room_key 를 주면 그 방만 확인."""
        return await self._all(
            CHANNEL_ROOMS + "AND r.proactive AND u.created_at < %(today)s "
            "AND NOT EXISTS (SELECT 1 FROM marong.messages x WHERE x.room_key = r.room_key "
            "  AND x.meta->>'proactive' = 'true' AND (x.id > u.id OR x.created_at >= %(since)s)) "
            "AND (%(room)s::text IS NULL OR r.room_key = %(room)s) ORDER BY u.created_at LIMIT %(n)s",
            {"today": today, "since": today - timedelta(days=every_days - 1), "room": room_key, "n": limit})

    async def proactive_count(self, since: datetime) -> int:
        """since 뒤로 보낸(전달 실패 포함) 선톡 수."""
        row = await self._one("SELECT count(*) AS n FROM marong.messages "
                              "WHERE meta->>'proactive' = 'true' AND created_at >= %s", (since,))
        return row["n"]

    async def channel_rooms(self, who: str) -> list[dict]:
        """이름이나 #짧은키(tools/admin.py 와 같은 표시)로 찾은 친구의 1:1 방들(선톡 시험용)."""
        people = await self._all("SELECT user_key, name FROM marong.people")
        keys = [p["user_key"] for p in people
                if p["name"] == who or "#" + hashlib.sha1(p["user_key"].encode()).hexdigest()[:8] == who]
        if not keys:
            return []
        return await self._all(CHANNEL_ROOMS + "AND u.user_key = ANY(%s) ORDER BY u.created_at DESC", (keys,))

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

    async def friend_notes(self) -> list[dict]:
        """공유를 켠 친구마다 방·키별 지금 메모(공유 메모를 거를 재료). friend_id, name, note_id, content, is_channel."""
        return await self._all(
            "SELECT * FROM (SELECT DISTINCT ON (n.room_key, n.user_key) p.friend_id, f.name, n.id AS note_id, "
            "  n.content, r.is_channel FROM marong.notes n JOIN marong.people p ON p.user_key = n.user_key "
            "  JOIN marong.friends f ON f.id = p.friend_id JOIN marong.rooms r ON r.room_key = n.room_key "
            "  WHERE f.share ORDER BY n.room_key, n.user_key, n.id DESC) x ORDER BY friend_id, note_id")

    async def shared_sources(self) -> dict[int, tuple[list[int], str | None]]:
        """공유를 켠 친구마다 가장 최근 공유 메모를 만들 때 거른 메모 id 들과 거른 규칙(memory.SHARE_RULES)."""
        rows = await self._all(
            "SELECT DISTINCT ON (s.friend_id) s.friend_id, s.meta->'note_ids' AS note_ids, s.meta->>'rules' AS rules "
            "FROM marong.shared_notes s JOIN marong.friends f ON f.id = s.friend_id WHERE f.share "
            "ORDER BY s.friend_id, s.id DESC")
        return {r["friend_id"]: (list(r["note_ids"] or []), r["rules"]) for r in rows}

    async def add_shared_note(self, friend_id: int, content: str, meta: dict) -> int:
        row = await self._one("INSERT INTO marong.shared_notes (friend_id, content, meta) VALUES (%s, %s, %s) "
                              "RETURNING id", (friend_id, content, Jsonb(meta)))
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
            "(SELECT count(*) FROM marong.friends f WHERE EXISTS (SELECT 1 FROM marong.people p "
            "  WHERE p.friend_id = f.id)) AS friends, "
            "(SELECT count(*) FROM marong.messages) AS messages, (SELECT count(*) FROM marong.summaries) AS summaries, "
            "(SELECT count(*) FROM marong.embeddings) AS embeddings")
