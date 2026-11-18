"""Postgres 저장소(psycopg 3 비동기).
대화 원문·요약·메모는 쌓기만 하고 지우거나 고치지 않는다. 봇 계정(marong)에는 그 권한 자체가 없다(schema.sql)."""
import hashlib
import os
import logging
import re
from datetime import timedelta

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("store")

SCHEMA_VERSION = 9
# 'ㅋㅋㅋ'·'ㅇㅇ'·이모티콘만 있는 말은 검색해도 쓸모가 없어 임베딩하지 않음(한글 음절·영문·숫자가 2개 이상 이어진 말만)
MEANINGFUL = "[가-힣A-Za-z0-9]{2}"
SCAN_ROWS = 400          # 답할 최근 대화를 고를 때 거슬러 읽는 줄 수(선톡이 몰려도 친구 말 reply_turns 번을 찾게)
KEYWORD_ROWS = 300       # 낱말로 찾을 때 읽는 후보 수(최근 것부터)


def pick_recent(rows: list[dict], turns: int, max_rows: int, since_id: int | None = None,
                unanswered: int = 3) -> list[dict]:
    """답할 때 넣을 최근 대화(rows 는 오래된 것부터, proactive 는 선톡인지).
    친구 말(role user)이 turns 번 들어가도록 거슬러 올라간 구간에서, 친구가 답하지 않은 선톡(바로 다음 줄이 친구 말이
    아닌 선톡)은 가장 최근 unanswered 개만 남긴다. 그래도 max_rows 를 넘으면 오래된 줄부터 뺀다. since_id(묶어 답할 첫
    말)부터는 늘 다 넣는다(필받음 '최근 15턴', 2026-11-16 선톡이 몰려 최근 20줄이 다 선톡이던 일)."""
    start, users = 0, 0
    for i in range(len(rows) - 1, -1, -1):
        if rows[i]["role"] == "user":
            users += 1
            if users == turns:
                start = i
                break
    if since_id is not None:
        first = next((i for i, r in enumerate(rows) if r["id"] >= since_id), len(rows))
        start = min(start, first)
    picked = rows[start:]
    pro = [i for i, r in enumerate(picked) if r.get("proactive")]
    latest = set(pro[-unanswered:]) if unanswered > 0 else set()
    out = []
    for i, r in enumerate(picked):
        held = since_id is not None and r["id"] >= since_id
        answered = i + 1 < len(picked) and picked[i + 1]["role"] == "user"
        if r.get("proactive") and i not in latest and not answered and not held:
            continue
        out.append(r)
    if len(out) > max_rows:
        held = sum(1 for r in out if since_id is not None and r["id"] >= since_id)
        out = out[len(out) - max(max_rows, held):]
    return out


def keyword_terms(text: str, limit: int = 24) -> list[str]:
    """낱말 검색에 쓸 조각: 한글은 두 글자씩 겹쳐 자르고(코트 → '코트', 울코트 → '울코'·'코트'), 영문·숫자는 낱말 그대로
    (두 글자 이상, 소문자). 'ㅋㅋ' 같은 자모만 있는 말은 뺀다. 앞에 나온 것부터 limit 개(M10 RAG: 한글 2글자 BM25)."""
    terms: list[str] = []
    for word in re.findall(r"[가-힣]+|[A-Za-z0-9]+", text or ""):
        if re.fullmatch(r"[가-힣]+", word):
            grams = [word[i:i + 2] for i in range(len(word) - 1)]
        else:
            grams = [word.lower()] if len(word) >= 2 else []
        for g in grams:
            if g not in terms:
                terms.append(g)
    return terms[:limit]


def like_pattern(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def scope(room: str) -> str:
    """room(SQL 자리표시자나 열)과 기억을 같이 쓰는 방들(그 방 포함)의 키를 고르는 SQL(표 버전 9 기억 묶기). 묶인 단체방은
    rooms.memory_room 에 1:1 방을 가리키고, 묶음의 뿌리(1:1 방)는 비어 있다. 묶지 않은 방은 그 방 하나."""
    return ("(SELECT sc.room_key FROM marong.rooms sc WHERE coalesce(sc.memory_room, sc.room_key) = "
            f"(SELECT coalesce(s0.memory_room, s0.room_key) FROM marong.rooms s0 WHERE s0.room_key = {room}))")


def root(room: str) -> str:
    """room 의 묶음 뿌리(묶인 단체방이면 그 1:1 방, 아니면 그 방). 새 요약·메모는 뿌리 쪽에 쌓는다."""
    return f"(SELECT coalesce(s1.memory_room, s1.room_key) FROM marong.rooms s1 WHERE s1.room_key = {room})"


def done(room: str) -> str:
    """room(열) 메시지를 어디까지 요약했는지(요약 last_id, 없으면 0): 그 방 요약과, 그 방을 함께 요약한 묶음 요약(뿌리 쪽
    요약 중 meta.rooms 에 그 방이 있는 것) 가운데 가장 뒤. 묶기 전에 방마다 따로 한 요약에서 이어 가서, 묶어도 빠지거나 두 번
    요약되는 말이 없다."""
    return (f"coalesce((SELECT max(sd.last_id) FROM marong.summaries sd WHERE sd.room_key = {room} "
            f"OR sd.meta->'rooms' ? {room}), 0)")


# 선톡, 그림 화두, 선 전화를 못 받았을 때 남긴 한마디. 이 조건을 쓰는 쿼리의 메시지 별칭은 m.
PROACTIVE_MESSAGE = "(m.meta->>'proactive' = 'true' OR m.meta->>'hello' = 'true')"


# 카카오에서 온 방마다 마지막 사람 말과 이 방의 선톡 일정·조건 재료. 친구(user_key·name)는 1:1 방이면 그 친구, 1:1 방에 묶인
# 단체방이면 그 1:1 친구, 그냥 단체방이면 마지막으로 마롱이에게 말한 사람(카카오는 단체방에서 마롱이를 태그한 말만 보내 줌).
# 터미널 대화('terminal' 방)는 카카오 id 가 없어서 빠짐. 시각은 DB 시계 now() 에서 거꾸로 잰 길이: quiet_for(묶인 방들 어디서든
# 마지막 사람 말 뒤), sent_ago(묶인 방들 어디서든 마지막 선톡 뒤. 없으면 NULL), failures(마지막 사람 말 뒤 이 방에서 전달에
# 실패한 선톡 수)
ROOM_STATE = (
    "SELECT r.room_key, r.is_channel, r.memory_room, coalesce(w.user_key, u.user_key) AS user_key, p.name, "
    "  u.created_at AS last_said, r.proactive, r.group_proactive, "
    "  r.proactive_per_day AS per_day, r.proactive_start AS start_hour, r.proactive_end AS end_hour, "
    "  now() - u.created_at AS quiet_for, "
    "  now() - (SELECT max(x.created_at) FROM marong.messages x WHERE x.room_key IN " + scope("r.room_key") + " "
    "    AND x.meta->>'proactive' = 'true') AS sent_ago, "
    "  (SELECT count(*) FROM marong.messages f WHERE f.room_key = r.room_key AND f.id > u.id "
    "    AND f.meta->>'proactive' = 'true' AND f.meta->>'delivered' = 'false') AS failures, "
    "  (SELECT count(*) FROM marong.messages m WHERE m.room_key IN " + scope("r.room_key") + " AND m.id > u.id "
    "    AND m.role = 'assistant' AND m.meta->>'delivered' = 'true' AND " + PROACTIVE_MESSAGE + ") AS unanswered "
    "FROM marong.rooms r "
    "CROSS JOIN LATERAL (SELECT m.id, m.user_key, m.kakao_id, m.created_at FROM marong.messages m "
    "  WHERE m.room_key IN " + scope("r.room_key") + " AND m.role = 'user' ORDER BY m.id DESC LIMIT 1) u "
    "LEFT JOIN LATERAL (SELECT m.user_key FROM marong.messages m "
    "  WHERE m.room_key = coalesce(r.memory_room, r.room_key) AND m.role = 'user' ORDER BY m.id DESC LIMIT 1) w ON true "
    "LEFT JOIN marong.people p ON p.user_key = coalesce(w.user_key, u.user_key) "
    "WHERE u.kakao_id IS NOT NULL AND r.room_key NOT LIKE 'discord-dm:%%' ")
# 선톡 대상: 선톡을 켜 둔 1:1 방(기본 켬)과 관리자가 켠 단체방(group_proactive, 기본 꺼짐, 표 버전 8)
PROACTIVE_ON = "AND CASE WHEN r.is_channel THEN r.proactive ELSE r.group_proactive END "


def vec(values) -> str:
    """pgvector 글자 형식 '[0.1,0.2,…]'."""
    return "[" + ",".join(f"{float(x):.6f}" for x in values) + "]"


def speaker_label(user_key: str | None, name: str | None) -> str:
    """이름을 모르는 친구는 '친구-a1b2'처럼 키로 만든 짧은 표시를 쓴다(키 원문은 드러내지 않음)."""
    if name:
        return name
    return "친구-" + hashlib.sha1((user_key or "").encode()).hexdigest()[:4]


class Store:
    def __init__(self, conninfo: str, timeout: float = 5, call_bridge: bool | None = None):
        # timeout: DB 가 죽어 있을 때 연결을 기다리는 시간. 넘으면 오류 → 기억 없이 답함(답이 너무 늦지 않게)
        self.pool = AsyncConnectionPool(conninfo, min_size=1, max_size=4, open=False, timeout=timeout,
                                        kwargs={"autocommit": True, "row_factory": dict_row})
        self.call_bridge = os.getenv('MARONG_CALL_MEMORY') == '1' if call_bridge is None else call_bridge
        # Keep privacy filters on when injection is disabled during a rollback.
        self.call_context_enabled = os.getenv('MARONG_CALL_CONTEXT', '1') == '1'
        self.discord_context_enabled = os.getenv("MARONG_DISCORD_CONTEXT") == "1"

    def _call_guard(self, kind: str, source_id: str, room: str, requested: str = '%(room)s', expression=False) -> str:
        if not self.call_bridge:
            return ''
        k = kind if expression else "'" + kind + "'"
        return (f" AND NOT call.kakao_hidden({k},{source_id},{room}) "
                f"AND ((SELECT is_channel FROM marong.rooms WHERE room_key={requested}) "
                f"OR NOT call.kakao_private({k},{source_id},{room})) ")

    async def open(self, wait: bool = False, timeout: float = 10) -> None:
        """wait=False 면 DB 가 늦게 떠도 봇은 먼저 켜지고, 연결은 뒤에서 계속 시도한다."""
        await self.pool.open(wait=wait, timeout=timeout)

    async def close(self) -> None:
        await self.pool.close()

    async def private_revision(self, room_key: str) -> int | None:
        if not self.call_bridge:return None
        row=await self._one("SELECT coalesce(max(c.context_revision),0) AS revision FROM call.kakao_guards g JOIN call.callers c ON c.friend_id=g.friend_id WHERE g.room_key IN " + scope('%s'),(room_key,))
        return row['revision']

    async def _privacy_write_ok(self,c,room_key,revision):
        if not self.call_bridge or revision is None:return True
        await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('call.kakao:'||"+root('%s')+",0))",(room_key,))
        cur=await c.execute("SELECT coalesce(max(c.context_revision),0) AS revision FROM call.kakao_guards g JOIN call.callers c ON c.friend_id=g.friend_id WHERE g.room_key IN "+scope('%s'),(room_key,))
        return (await cur.fetchone())['revision']==revision

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
        이 방의 선톡 받기(proactive: 1:1 은 proactive, 단체방은 group_proactive)와 이 방만의 하루 선톡 수(per_day, 비면 None),
        기억 묶기(memory_room: 이 단체방이 묶인 1:1 방, linked_name: 그 1:1 친구 이름, followers: 이 방에 묶인 단체방 수)를
        붙여 돌려준다. share 는 친구에 안 묶인 키(이름을 모름)면 None."""
        async with self.pool.connection() as c:
            cur = await c.execute(
                "INSERT INTO marong.rooms AS t (room_key, is_channel) VALUES (%s, %s) "
                "ON CONFLICT (room_key) DO UPDATE SET last_seen = now(), is_channel = EXCLUDED.is_channel "
                "RETURNING CASE WHEN t.is_channel THEN t.proactive ELSE t.group_proactive END AS proactive, "
                "  t.proactive_per_day, t.memory_room, "
                "  (SELECT count(*) FROM marong.rooms x WHERE x.memory_room = t.room_key) AS followers, "
                "  (SELECT p.name FROM marong.messages m JOIN marong.people p ON p.user_key = m.user_key "
                "   WHERE m.room_key = t.memory_room AND m.role = 'user' ORDER BY m.id DESC LIMIT 1) AS linked_name",
                (room_key, is_channel))
            room = await cur.fetchone()
            cur = await c.execute(
                "INSERT INTO marong.people (user_key) VALUES (%s) "
                "ON CONFLICT (user_key) DO UPDATE SET last_seen = now() RETURNING user_key, name, friend_id, "
                "(SELECT f.share FROM marong.friends f WHERE f.id = people.friend_id) AS share",
                (user_key,))
            return {**await cur.fetchone(), "proactive": room["proactive"], "per_day": room["proactive_per_day"],
                    "memory_room": room["memory_room"], "linked_name": room["linked_name"],
                    "followers": room["followers"]}

    async def add_message(self, room_key: str, role: str, content: str, user_key: str | None = None,
                          kakao_id: str | None = None, reply_to: int | None = None, meta: dict | None = None) -> int | None:
        """새 메시지 id. 같은 카카오 메시지가 이미 저장돼 있으면 None."""
        row = await self._one(
            "INSERT INTO marong.messages (room_key, user_key, role, content, kakao_id, reply_to, meta) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (room_key, kakao_id) DO NOTHING RETURNING id",
            (room_key, user_key, role, content, kakao_id, reply_to, Jsonb(meta or {})))
        return row["id"] if row else None

    def _reply_rooms(self, room: str) -> str:
        return scope(room)

    def _reply_embedding_filter(self) -> str:
        return ""

    async def recent(self, room_key: str, limit: int, since_id: int | None = None) -> list[dict]:
        """방(묶인 방들 함께)의 최근 메시지(오래된 것부터). since_id 가 있으면 그 메시지부터는 limit 을 넘어도 다 넣는다.
        친구에게 전달되지 못한 마롱이 답은 뺀다."""
        rows = await self._all(
            "SELECT m.id, m.role, m.user_key, p.name, m.content, m.created_at, "
            "  coalesce(" + PROACTIVE_MESSAGE + ", false) AS proactive FROM marong.messages m "
            "LEFT JOIN marong.people p ON p.user_key = m.user_key "
            "WHERE m.room_key IN " + self._reply_rooms("%(room)s") + " AND m.meta->>'delivered' IS DISTINCT FROM 'false' "
            + self._call_guard('message','m.id','m.room_key') +
            "ORDER BY m.id DESC LIMIT greatest(%(limit)s, "
            "(SELECT count(*) FROM marong.messages WHERE room_key IN " + self._reply_rooms("%(room)s") + " AND id >= %(since)s))",
            {"room": room_key, "limit": limit, "since": since_id})
        return rows[::-1]

    async def recent_proactives(self, room_key: str, within: timedelta, limit: int) -> list[dict]:
        """같은 대화 범위에서 최근 전달된 선톡과 선 전화 뒤 한마디(새것부터)."""
        return await self._all(
            "SELECT m.id, m.content, m.created_at FROM marong.messages m "
            "WHERE m.room_key IN " + self._reply_rooms("%(room)s") + " AND m.role = 'assistant' "
            "AND m.meta->>'delivered' = 'true' AND " + PROACTIVE_MESSAGE + " AND m.created_at >= now() - %(within)s "
            + self._call_guard("message", "m.id", "m.room_key") + "ORDER BY m.created_at DESC, m.id DESC LIMIT %(limit)s",
            {"room": room_key, "within": within, "limit": limit})

    async def recent_turns(self, room_key: str, turns: int, max_rows: int, since_id: int | None = None,
                           unanswered: int = 3) -> list[dict]:
        """답할 때 넣는 최근 대화(오래된 것부터). 고르는 법은 pick_recent. 친구에게 전달되지 못한 마롱이 답은 뺀다."""
        rows = await self._all(
            "SELECT m.id, m.role, m.user_key, p.name, m.content, m.created_at, "
            "  coalesce(m.meta->>'proactive' = 'true', false) AS proactive FROM marong.messages m "
            "LEFT JOIN marong.people p ON p.user_key = m.user_key "
            "WHERE m.room_key IN " + self._reply_rooms("%(room)s") + " AND m.meta->>'delivered' IS DISTINCT FROM 'false' "
            + self._call_guard('message','m.id','m.room_key') +
            "ORDER BY m.id DESC LIMIT greatest(%(scan)s, "
            "(SELECT count(*) FROM marong.messages WHERE room_key IN " + self._reply_rooms("%(room)s") + " AND id >= %(since)s))",
            {"room": room_key, "scan": SCAN_ROWS, "since": since_id})
        return pick_recent(rows[::-1], turns, max_rows, since_id, unanswered)

    async def keyword_hits(self, room_key: str, terms: list[str], before_id: int, skip_summary_ids: list[int],
                           limit: int = KEYWORD_ROWS) -> tuple[list[dict], int]:
        """같은 방(묶인 방들 함께)에서 terms 중 하나라도 든 예전 메시지·요약(최근 것부터)과, 찾은 범위의 전체 수(점수의
        IDF 에 씀). 최근 원문 구간(before_id 부터)과 이미 넣은 요약은 뺀다. 점수는 agent 가 매긴다."""
        if not terms:
            return [], 0
        params = {"room": room_key, "before": before_id, "skip": list(skip_summary_ids),
                  "pats": [like_pattern(x) for x in terms], "limit": limit}
        rows = await self._all(
            "SELECT * FROM ("
            "  SELECT 'message' AS source_type, m.id AS source_id, m.role, m.user_key, p.name, m.content, m.created_at "
            "  FROM marong.messages m LEFT JOIN marong.people p ON p.user_key = m.user_key "
            "  WHERE m.room_key IN " + self._reply_rooms("%(room)s") + " AND m.id < %(before)s "
            "  AND m.meta->>'delivered' IS DISTINCT FROM 'false' AND m.content ILIKE ANY(%(pats)s) "
            + self._call_guard('message','m.id','m.room_key') +
            "  UNION ALL "
            "  SELECT 'summary', s.id, NULL, NULL, NULL, s.content, s.created_at FROM marong.summaries s "
            "  WHERE s.room_key IN " + self._reply_rooms("%(room)s") + " AND s.content <> '' "
            "  AND NOT (s.id = ANY(%(skip)s::bigint[])) AND s.content ILIKE ANY(%(pats)s) "
            + self._summary_keyword_filter()
            + self._call_guard('summary','s.id','s.room_key') +
            ") k ORDER BY created_at DESC LIMIT %(limit)s", params)
        total = await self._one(
            "SELECT (SELECT count(*) FROM marong.messages m WHERE m.room_key IN " + self._reply_rooms("%(room)s")
            + " AND m.id < %(before)s) + (SELECT count(*) FROM marong.summaries s WHERE s.room_key IN "
            + self._reply_rooms("%(room)s") + ") AS n", params)
        return rows, int(total["n"] if total else len(rows))

    def _summary_keyword_filter(self) -> str:
        return ""

    async def neighbors(self, room_key: str, ids: list[int]) -> dict[int, dict]:
        """메시지마다 짝이 되는 말(문답 한 쌍으로 기억하기): 친구 말이면 바로 뒤 마롱이 답, 마롱이 말이면 바로 앞 친구 말.
        같은 방 안에서만, 짝이 없으면 뺀다. {메시지 id: 짝 줄}(LangGraph 실측: 뽑은 사실보다 원문 문답 검색이 나음)."""
        if not ids:
            return {}
        rows = await self._all(
            "SELECT h.id AS hit, n.id, n.role, n.user_key, p.name, n.content, n.created_at "
            "FROM marong.messages h CROSS JOIN LATERAL ("
            "  (SELECT x.* FROM marong.messages x WHERE h.role = 'user' AND x.room_key = h.room_key AND x.id > h.id "
            "   AND x.meta->>'delivered' IS DISTINCT FROM 'false' ORDER BY x.id LIMIT 1) "
            "  UNION ALL "
            "  (SELECT x.* FROM marong.messages x WHERE h.role = 'assistant' AND x.room_key = h.room_key AND x.id < h.id "
            "   ORDER BY x.id DESC LIMIT 1)"
            ") n LEFT JOIN marong.people p ON p.user_key = n.user_key "
            "WHERE h.id = ANY(%(ids)s::bigint[]) AND h.room_key IN " + self._reply_rooms("%(room)s") + " "
            "AND n.role <> h.role " + self._call_guard('message','n.id','n.room_key'),
            {"room": room_key, "ids": list(ids)})
        return {r["hit"]: r for r in rows}

    async def summaries(self, room_key: str, limit: int) -> list[dict]:
        """방(묶인 방들 함께)의 최근 요약(오래된 것부터). until 은 요약한 구간의 마지막 메시지 시각."""
        rows = await self._all(
            "SELECT s.id, s.first_id, s.last_id, s.content, m.created_at AS until FROM marong.summaries s "
            "JOIN marong.messages m ON m.id = s.last_id "
            "WHERE s.room_key IN " + scope("%(room)s") + self._call_guard('summary','s.id','s.room_key') + " ORDER BY s.last_id DESC LIMIT %(limit)s",
            {"room": room_key, "limit": limit})
        return rows[::-1]

    async def notes(self, room_key: str) -> list[dict]:
        """방(묶인 방들 함께) 안 친구(카카오 키)마다 가장 최근 메모. 묶음 뿌리(1:1 방)의 메모가 있으면 그것(묶은 뒤 메모는
        뿌리 쪽에 쌓여서 묶기 전 단체방 메모보다 앞섬)."""
        return await self._all(
            "SELECT DISTINCT ON (n.user_key) n.id, n.user_key, p.name, n.content, n.created_at FROM marong.notes n "
            "JOIN marong.people p ON p.user_key = n.user_key WHERE n.room_key IN " + scope("%(room)s") + " "
            + self._call_guard('note','n.id','n.room_key') +
            "ORDER BY n.user_key, n.room_key = " + root("%(room)s") + " DESC, n.id DESC", {"room": room_key})

    async def set_name(self, user_key: str, name: str, room_key: str | None = None) -> int | None:
        """이름을 저장하고 이 키를 친구 한 명(friends)에 묶는다. 묶은 친구 id(카카오에서 말한 적 없는 키이거나 같은 이름
        친구가 이미 있어서 묶지 않았으면 None)."""
        async with self.pool.connection() as c:
            async with c.transaction():
                await c.execute("UPDATE marong.people SET name = %s, name_set_at = now() WHERE user_key = %s",
                                (name, user_key))
                return await self._link(c, user_key, name, room_key)

    # ── 친구들(서로 아는 사이) ───────────────────────────────────

    @staticmethod
    async def _link(c, user_key: str, name: str, room_key: str | None = None) -> int | None:
        """키를 친구에 묶는다(이미 묶였으면 친구 이름만 바꿈). 같은 이름 친구가 없으면 새 친구로 묶고, 있으면 묶지 않고
        묶기 요청을 남긴다(이름은 누구나 댈 수 있어서. 관리자가 admin link 로 묶거나 unlink 로 따로 둠). 터미널 대화 키는
        묶지 않는다."""
        await c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("marong.friend:" + name,))
        cur = await c.execute("SELECT friend_id FROM marong.people WHERE user_key = %s FOR UPDATE", (user_key,))
        row = await cur.fetchone()
        if row is None:
            return None
        if row["friend_id"]:
            await c.execute("UPDATE marong.friends SET name = %s WHERE id = %s", (name, row["friend_id"]))
            return row["friend_id"]
        cur = await c.execute("SELECT 1 FROM marong.messages WHERE user_key = %s AND kakao_id IS NOT NULL LIMIT 1",
                              (user_key,))
        if await cur.fetchone() is None:
            return None
        cur = await c.execute("SELECT 1 FROM marong.friends f WHERE f.name = %s "
                              "AND EXISTS (SELECT 1 FROM marong.people p WHERE p.friend_id = f.id)", (name,))
        if await cur.fetchone():
            await Store._request(c, user_key, None, room_key, "link", {"name": name})
            return None
        cur = await c.execute("INSERT INTO marong.friends (name) VALUES (%s) RETURNING id", (name,))
        friend_id = (await cur.fetchone())["id"]
        await c.execute("UPDATE marong.people SET friend_id = %s WHERE user_key = %s", (friend_id, user_key))
        return friend_id

    @staticmethod
    async def _request(c, user_key: str, friend_id: int | None, room_key: str | None, kind: str, detail: dict) -> None:
        """대화로 한 요청을 남긴다(바꾸지는 않음). 이 키의 바로 앞 요청과 같으면(같은 말을 또 하면) 남기지 않는다."""
        await c.execute(
            "INSERT INTO marong.requests (user_key, friend_id, room_key, kind, detail) "
            "SELECT %(k)s, %(f)s, %(r)s, %(kind)s, %(d)s WHERE NOT EXISTS ("
            "  SELECT 1 FROM (SELECT kind, detail FROM marong.requests WHERE user_key = %(k)s ORDER BY id DESC LIMIT 1) x "
            "  WHERE x.kind = %(kind)s AND x.detail = %(d)s)",
            {"k": user_key, "f": friend_id, "r": room_key, "kind": kind, "d": Jsonb(detail)})

    async def link_unlinked(self) -> int:
        """이름은 있는데 친구에 안 묶인 키를 묶는다(표 버전 3 전에 이름만 저장된 키. 그 뒤엔 set_name 이 묶음).
        같은 이름 친구가 있어 묶기 요청으로 남긴 키는 계속 안 묶인 채로 둔다."""
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
        먼저, 그다음 최근에 본 순. 줄마다 name, told(말해 준 사이)·label(그 관계)·teller(말해 준 쪽: me 지금 친구, them 그 친구,
        다른 친구나 관리자면 None)·close(가까운 사이), same_group, shared(그 친구를 아는 친구에게 하는 가벼운 얘기),
        shared_close(가까운 사이에게만 하는 요즘 근황)."""
        return await self._all(
            "WITH me AS (SELECT friend_id FROM marong.people WHERE user_key = %(k)s), "
            "keys AS (SELECT user_key FROM marong.people WHERE friend_id = (SELECT friend_id FROM me) "
            "  UNION SELECT %(k)s::text), "
            "mates AS (SELECT DISTINCT p.friend_id AS id FROM marong.messages m "
            "  JOIN marong.people p ON p.user_key = m.user_key WHERE p.friend_id IS NOT NULL AND m.room_key IN ("
            "    SELECT m2.room_key FROM marong.messages m2 JOIN marong.rooms r ON r.room_key = m2.room_key "
            "    WHERE NOT r.is_channel AND m2.user_key IN (SELECT user_key FROM keys))), "
            "told AS (SELECT CASE WHEN fs.friend_a = me.friend_id THEN fs.friend_b ELSE fs.friend_a END AS id, fs.label, "
            "  fs.close, CASE WHEN fs.told_by = me.friend_id THEN 'me' WHEN fs.told_by IN (fs.friend_a, fs.friend_b) "
            "    THEN 'them' END AS teller "
            "  FROM marong.friendships fs JOIN me ON me.friend_id IN (fs.friend_a, fs.friend_b)) "
            "SELECT f.id, f.name, t.id IS NOT NULL AS told, t.label, t.teller, coalesce(t.close, false) AS close, "
            "  g.id IS NOT NULL AS same_group, s.content AS shared, s.close_content AS shared_close, "
            "  (SELECT max(p.last_seen) FROM marong.people p WHERE p.friend_id = f.id) AS last_seen "
            "FROM marong.friends f LEFT JOIN told t ON t.id = f.id LEFT JOIN mates g ON g.id = f.id "
            "LEFT JOIN LATERAL (SELECT x.content, x.close_content FROM marong.shared_notes x WHERE x.friend_id = f.id "
            "  ORDER BY x.id DESC LIMIT 1) s ON true "
            "WHERE f.share AND f.id IS DISTINCT FROM (SELECT friend_id FROM me) "
            "  AND EXISTS (SELECT 1 FROM marong.people p WHERE p.friend_id = f.id) "
            "ORDER BY (t.id IS NOT NULL OR g.id IS NOT NULL) DESC, last_seen DESC NULLS LAST LIMIT %(n)s",
            {"k": user_key, "n": limit})

    async def add_request(self, user_key: str, room_key: str, kind: str, name: str | None = None,
                          label: str | None = None, per_day: int | None = None, *,
                          feature: str | None = None) -> tuple[str, str | None]:
        """친구가 대화로 한 요청을 남긴다. 바꾸지는 않는다(관리자가 정함). kind: share_off 자기 얘기를 다른 친구에게 하지
        마라 · share_on 다시 해도 된다 · friendship name 친구와 label 사이다 · proactive_off/on/less/more 이 방 선톡을
        그만·다시·덜·더(per_day 는 친구가 말한 하루 횟수). 돌려주는 것: (결과, 말하는 친구 이름).
        결과: ok | already(이미 그렇게 돼 있음) | no_speaker(이름을 몰라 친구에 안 묶인 키) | unknown(그 이름 친구 없음)
        | ambiguous(여럿) | self. 선톡 요청은 이름을 몰라도 남긴다."""
        async with self.pool.connection() as c:
            async with c.transaction():
                cur = await c.execute("SELECT f.id, f.name, f.share FROM marong.people p "
                                      "JOIN marong.friends f ON f.id = p.friend_id WHERE p.user_key = %s", (user_key,))
                me = await cur.fetchone()
                if kind == "feature":
                    from .capabilities import TEXT_FEATURE_NAMES

                    if feature not in TEXT_FEATURE_NAMES:
                        raise ValueError("unknown feature")
                    await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('feature:'||%s,0))", (user_key,))
                    await self._request(c, user_key, me and me["id"], room_key, kind, {"feature": feature})
                    return "ok", me and me["name"]
                if kind.startswith("proactive_"):
                    cur = await c.execute("SELECT CASE WHEN is_channel THEN proactive ELSE group_proactive END AS proactive "
                                          "FROM marong.rooms WHERE room_key = %s", (room_key,))
                    room = await cur.fetchone()
                    if kind in ("proactive_off", "proactive_on") and room and room["proactive"] == (kind == "proactive_on"):
                        return "already", me and me["name"]
                    await self._request(c, user_key, me and me["id"], room_key, kind,
                                        {"per_day": per_day} if per_day else {})
                    return "ok", me and me["name"]
                if not me:
                    return "no_speaker", None
                detail = {}
                if kind in ("share_off", "share_on") and me["share"] == (kind == "share_on"):
                    return "already", me["name"]
                if kind == "friendship":
                    cur = await c.execute(
                        "SELECT f.id FROM marong.friends f WHERE f.name = %s AND f.id <> %s "
                        "AND EXISTS (SELECT 1 FROM marong.people p WHERE p.friend_id = f.id)", (name, me["id"]))
                    others = await cur.fetchall()
                    if not others:
                        return ("self" if name == me["name"] else "unknown"), me["name"]
                    if len(others) > 1:
                        return "ambiguous", me["name"]
                    detail = {"name": name, "label": label or None, "with": others[0]["id"]}
                await self._request(c, user_key, me["id"], room_key, kind, detail)
                return "ok", me["name"]

    async def similar(self, model: str, room_key: str, vector, before_id: int, skip_summary_ids: list[int],
                      limit: int) -> list[dict]:
        """같은 방(묶인 방들 함께)에서 지금 말과 비슷한 예전 메시지·요약(비슷한 순). 최근 원문 구간과 이미 넣은 요약은 뺀다."""
        return await self._all(
            "WITH q AS (SELECT %s::vector AS v), hits AS ("
            "  SELECT e.source_type, e.source_id, 1 - (e.embedding <=> q.v) AS similarity "
            "  FROM marong.embeddings e, q WHERE e.model = %s AND e.room_key IN " + self._reply_rooms("%s") + " "
            + self._reply_embedding_filter() +
            "  AND NOT (e.source_type = 'message' AND e.source_id >= %s) "
            "  AND NOT (e.source_type = 'summary' AND e.source_id = ANY(%s::bigint[])) "
            "  ORDER BY e.embedding <=> q.v LIMIT %s) "
            "SELECT h.source_type, h.source_id, h.similarity, m.role, m.user_key, p.name, "
            "  coalesce(m.content, s.content) AS content, coalesce(m.created_at, s.created_at) AS created_at "
            "FROM hits h "
            "LEFT JOIN marong.messages m ON h.source_type = 'message' AND m.id = h.source_id "
            "LEFT JOIN marong.people p ON p.user_key = m.user_key "
            "LEFT JOIN marong.summaries s ON h.source_type = 'summary' AND s.id = h.source_id "
            "WHERE true " + self._call_guard('h.source_type','h.source_id','coalesce(m.room_key,s.room_key)','%s',True) +
            "ORDER BY h.similarity DESC",
            (vec(vector), model, room_key, before_id, list(skip_summary_ids), limit) + ((room_key,) if self.call_bridge else ()))

    # ── 선톡(먼저 말 걸기) ──────────────────────────────────────

    async def proactive_rooms(self, room_key: str | None = None) -> list[dict]:
        """선톡을 켜 둔 카카오 1:1 방과 관리자가 켠 단체방(오래 조용한 방부터), 일정·조건 재료(ROOM_STATE). 보낼지는
        proactive.py 가 방마다 일정으로 정한다. room_key 를 주면 그 방만."""
        moved = ("AND NOT EXISTS (SELECT 1 FROM marong.discord_dm_links d WHERE d.proactive_moved_at IS NOT NULL "
                 "AND d.kakao_room_key = coalesce(r.memory_room,r.room_key)) " if self.discord_context_enabled else "")
        return await self._all(ROOM_STATE + PROACTIVE_ON + moved + "AND (%(room)s::text IS NULL OR r.room_key = %(room)s) "
                               "ORDER BY u.created_at", {"room": room_key})

    async def proactive_count(self, within: timedelta) -> int:
        """최근 within 안에 보낸(전달 실패 포함) 선톡 수(시각은 DB 시계에서 거꾸로 잼)."""
        row = await self._one("SELECT count(*) AS n FROM marong.messages "
                              "WHERE meta->>'proactive' = 'true' AND created_at >= now() - %s", (within,))
        return row["n"]

    async def channel_rooms(self, who: str) -> list[dict]:
        """선톡 시험용 방. 이름이나 #짧은키(tools/admin.py 와 같은 표시. # 은 빼도 됨)가 친구면 그 친구의 1:1 방들,
        방 키면 그 방(단체방도)."""
        tag = "#" + who.lstrip("#")
        people = await self._all("SELECT user_key, name FROM marong.people")
        keys = [p["user_key"] for p in people
                if p["name"] == who or "#" + hashlib.sha1(p["user_key"].encode()).hexdigest()[:8] == tag]
        if keys:
            return await self._all(ROOM_STATE + "AND r.is_channel AND EXISTS (SELECT 1 FROM marong.messages k "
                                   "WHERE k.room_key = r.room_key AND k.user_key = ANY(%s)) ORDER BY u.created_at DESC",
                                   (keys,))
        rooms = [r["room_key"] for r in await self._all("SELECT room_key FROM marong.rooms")
                 if "#" + hashlib.sha1(r["room_key"].encode()).hexdigest()[:8] == tag]
        return await self._all(ROOM_STATE + "AND r.room_key = ANY(%s)", (rooms,)) if rooms else []

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
        """마지막 요약 뒤로 메시지가 min_messages 개 이상 쌓인 방(묶인 방들은 묶음 뿌리 하나로 셈)."""
        rows = await self._all(
            "SELECT coalesce(w.memory_room, w.room_key) AS room_key "
            "FROM (SELECT r.room_key, r.memory_room, " + done("r.room_key") + " AS done FROM marong.rooms r) w "
            "JOIN marong.messages m ON m.room_key = w.room_key AND m.id > w.done "
            "GROUP BY 1 HAVING count(*) >= %s", (min_messages,))
        return [r["room_key"] for r in rows]

    async def unsummarized(self, room_key: str, limit: int) -> list[dict]:
        """아직 요약 안 한 메시지(묶인 방들 함께, 방마다 그 방을 요약한 데 뒤로, 오래된 것부터). delivered 가 False 면
        친구에게 전달되지 못한 답."""
        return await self._all(
            "SELECT m.id, m.role, m.user_key, p.name, m.content, m.created_at, "
            "  m.meta->>'delivered' IS DISTINCT FROM 'false' AS delivered, "
            "  coalesce(m.meta->>'proactive' = 'true', false) AS proactive "
            "FROM (SELECT w.room_key, " + done("w.room_key") + " AS done FROM marong.rooms w "
            "  WHERE w.room_key IN " + scope("%(room)s") + ") w "
            "JOIN marong.messages m ON m.room_key = w.room_key AND m.id > w.done "
            "LEFT JOIN marong.people p ON p.user_key = m.user_key "
            "WHERE true " + self._call_guard('message','m.id','m.room_key') +
            "ORDER BY m.id LIMIT %(limit)s", {"room": room_key, "limit": limit})

    async def add_summary(self, room_key: str, first_id: int, last_id: int, content: str,
                          notes: dict[str, str], meta: dict, private_revision=None) -> int | None:
        """요약 한 개와 바뀐 친구 메모를 한 트랜잭션으로 쓴다. 같은 구간이 이미 있으면 None. 묶인 방들을 함께 요약했으면
        meta.rooms 에 그 방들을 적는다(방마다 어디까지 요약했는지 셀 때 씀)."""
        async with self.pool.connection() as c:
            async with c.transaction():
                if not await self._privacy_write_ok(c,room_key,private_revision):return None
                cur = await c.execute("SELECT array_agg(room_key ORDER BY room_key) AS rooms FROM marong.rooms "
                                      "WHERE room_key IN " + scope("%s"), (room_key,))
                rooms = (await cur.fetchone())["rooms"] or []
                if len(rooms) > 1:
                    meta = {**meta, "rooms": rooms}
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

    async def rooms_to_note(self) -> list[dict]:
        """마지막 요약과 마지막으로 메모를 먼저 고친 때(noted_id) 뒤로 친구 말이 새로 있는 방(오래 기다린 방부터). 묶인
        방들은 묶음 뿌리(1:1 방) 하나로: 그 방들의 말을 함께 보고 메모는 뿌리 쪽에 쌓는다."""
        rows = await self._all(
            "SELECT coalesce(w.memory_room, w.room_key) AS room_key, min(m.id) AS first_new "
            "FROM (SELECT r.room_key, r.memory_room, r.noted_id, " + done("r.room_key") + " AS done "
            "  FROM marong.rooms r) w "
            "JOIN marong.messages m ON m.room_key = w.room_key AND m.role = 'user' "
            "  AND m.id > greatest(w.noted_id, w.done) "
            "GROUP BY 1 ORDER BY 2")
        return [r["room_key"] for r in rows]

    async def add_notes(self, room_key: str, notes: dict[str, str], last_id: int, private_revision=None) -> None:
        """요약 없이 바뀐 친구 메모를 쓰고, 그 방(묶인 방들 함께)을 last_id 까지 메모를 고친 것으로 적는다(한 트랜잭션)."""
        async with self.pool.connection() as c:
            async with c.transaction():
                if not await self._privacy_write_ok(c,room_key,private_revision):return
                for user_key, text in notes.items():
                    await c.execute("INSERT INTO marong.notes (room_key, user_key, content) VALUES (%s, %s, %s)",
                                    (room_key, user_key, text))
                await c.execute("UPDATE marong.rooms SET noted_id = greatest(noted_id, %s) WHERE room_key IN "
                                + scope("%s"), (last_id, room_key))

    async def friend_notes(self) -> list[dict]:
        """공유를 켠 친구마다 방·키별 지금 메모(공유 메모를 거를 재료). friend_id, name, note_id, content, is_channel."""
        return await self._all(
            "SELECT * FROM (SELECT DISTINCT ON (n.room_key, n.user_key) p.friend_id, f.name, n.id AS note_id, "
            "  n.content, r.is_channel FROM marong.notes n JOIN marong.people p ON p.user_key = n.user_key "
            "  JOIN marong.friends f ON f.id = p.friend_id JOIN marong.rooms r ON r.room_key = n.room_key "
            "  WHERE f.share " + ("AND NOT call.kakao_private('note',n.id,n.room_key) AND NOT call.kakao_hidden('note',n.id,n.room_key) " if self.call_bridge else '') +
            "ORDER BY n.room_key, n.user_key, n.id DESC) x ORDER BY friend_id, note_id")

    async def call_context(self, room_key: str, user_key: str, user_id: int | None = None) -> dict:
        """Read only this person's voice memories into their 1:1 Kakao room.

        Before returning content, permanently mark the room's subsequent material
        private. Sharing then reads its pre-bridge notes, never call-derived notes.
        """
        if not self.call_bridge or not self.call_context_enabled:
            return {}
        async with self.pool.connection() as c:
            async with c.transaction():
                await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('call.kakao:'||"+root('%s')+",0))",(room_key,))
                cur = await c.execute("""SELECT c.id,c.friend_id FROM marong.people p
                    JOIN call.callers c ON c.friend_id=p.friend_id JOIN marong.rooms r ON r.room_key=%s
                    WHERE p.user_key=%s AND r.is_channel AND c.enabled
                    AND EXISTS(SELECT 1 FROM marong.messages m WHERE m.room_key=r.room_key AND m.user_key=p.user_key)""", (room_key,user_key))
                caller = await cur.fetchone()
                if not caller:
                    return {}
                cur = await c.execute("""SELECT 'card' AS source,c.id::text AS id,k.summary AS content FROM call.cards k
                    JOIN call.calls c ON c.id=k.call_id WHERE c.caller_id=%s AND c.deleted_at IS NULL
                    AND k.forgotten_at IS NULL ORDER BY c.started_at DESC LIMIT 2""", (caller['id'],))
                cards = await cur.fetchall()
                cur = await c.execute("""SELECT 'memory' AS source,m.id::text AS id,m.content FROM call.memories m
                    JOIN call.calls c ON c.id=m.call_id WHERE m.caller_id=%s AND m.status='active'
                    AND c.deleted_at IS NULL ORDER BY m.created_at DESC LIMIT 10""", (caller['id'],))
                memories = await cur.fetchall()
                rows = memories + cards
                if not rows:
                    return {}
                await c.execute("""INSERT INTO call.kakao_guards(room_key,friend_id,message_floor,note_floor,summary_floor)
                    SELECT r.room_key,%(friend)s,
                      CASE WHEN r.room_key=%(room)s AND %(user_id)s::bigint IS NOT NULL THEN greatest(0,%(user_id)s-1)
                        ELSE coalesce((SELECT max(id) FROM marong.messages WHERE room_key=r.room_key),0) END,
                      coalesce((SELECT max(id) FROM marong.notes WHERE room_key=r.room_key),0),
                      coalesce((SELECT max(id) FROM marong.summaries WHERE room_key=r.room_key),0)
                    FROM marong.rooms r WHERE r.room_key IN """ + scope('%(room)s') +
                    " ON CONFLICT(room_key) DO NOTHING", {'friend':caller['friend_id'],'room':room_key,'user_id':user_id})
                selected=[];remaining=1200
                for row in rows:
                    if remaining<40:break
                    text=row['content'][:min(400,remaining-30)];remaining-=len(text)+30
                    selected.append({'source':row['source'],'id':row['id'],'text':text})
                return {'friend_id':caller['friend_id'],'items':selected}

    async def discord_context(self, room_key: str, user_key: str, user_id: int | None) -> list[dict]:
        """Only the same friend's Discord DM enters this exact Kakao 1:1 room."""
        if not self.call_bridge or not self.discord_context_enabled or user_id is None:
            return []
        async with self.pool.connection() as c, c.transaction():
            await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('call.kakao:'||" + root("%s") + ",0))",
                            (room_key,))
            cur = await c.execute(
                """SELECT d.friend_id, d.room_key
                     FROM marong.discord_dm_links d
                     JOIN marong.rooms r ON r.room_key=d.kakao_room_key AND r.is_channel AND r.memory_room IS NULL
                     JOIN marong.people p ON p.user_key=%s AND p.friend_id=d.friend_id
                     JOIN marong.people dp ON dp.user_key=d.user_key AND dp.friend_id=d.friend_id
                     JOIN call.kakao_guards g ON g.room_key=d.room_key AND g.friend_id=d.friend_id
                    WHERE d.kakao_room_key=%s AND d.channel_id IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM marong.messages m LEFT JOIN marong.people mp USING(user_key)
                         WHERE m.room_key=r.room_key AND m.role='user' AND mp.friend_id IS DISTINCT FROM d.friend_id
                      )""", (user_key, room_key),
            )
            link = await cur.fetchone()
            if not link:
                return []
            cur = await c.execute(
                """SELECT id,role,left(content,260) AS text FROM marong.messages
                    WHERE room_key=%s AND meta->>'delivered' IS DISTINCT FROM 'false'
                      AND NOT call.kakao_hidden('message',id,room_key)
                    ORDER BY id DESC LIMIT 8""", (link["room_key"],),
            )
            rows = await cur.fetchall()
            if not rows:
                return []
            await c.execute(
                """INSERT INTO call.kakao_guards(room_key,friend_id,message_floor,note_floor,summary_floor)
                   VALUES(%(room)s,%(friend)s,greatest(0,%(current)s-1),
                          coalesce((SELECT max(id) FROM marong.notes WHERE room_key=%(room)s),0),
                          coalesce((SELECT max(id) FROM marong.summaries WHERE room_key=%(room)s),0))
                   ON CONFLICT(room_key) DO NOTHING""",
                {"room": room_key, "friend": link["friend_id"], "current": user_id},
            )
            guard = await c.execute("SELECT friend_id FROM call.kakao_guards WHERE room_key=%s", (room_key,))
            if (await guard.fetchone())["friend_id"] != link["friend_id"]:
                return []
            return rows[::-1]

    async def shared_sources(self) -> dict[int, tuple[list[int], str | None]]:
        """공유를 켠 친구마다 가장 최근 공유 메모를 만들 때 거른 메모 id 들과 거른 규칙(memory.SHARE_RULES)."""
        rows = await self._all(
            "SELECT DISTINCT ON (s.friend_id) s.friend_id, s.meta->'note_ids' AS note_ids, s.meta->>'rules' AS rules "
            "FROM marong.shared_notes s JOIN marong.friends f ON f.id = s.friend_id WHERE f.share "
            "ORDER BY s.friend_id, s.id DESC")
        return {r["friend_id"]: (list(r["note_ids"] or []), r["rules"]) for r in rows}

    async def add_shared_note(self, friend_id: int, content: str, close_content: str, meta: dict) -> int:
        """content: 그 친구를 아는 친구에게 하는 가벼운 얘기, close_content: 가까운 사이에게만 하는 요즘 근황."""
        row = await self._one("INSERT INTO marong.shared_notes (friend_id, content, close_content, meta) "
                              "VALUES (%s, %s, %s, %s) RETURNING id", (friend_id, content, close_content, Jsonb(meta)))
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
