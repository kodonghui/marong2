"""Friend-scoped safety decisions without storing signal text (SPEC-206–211)."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
import re

from .friend_card import friend_lock

log = logging.getLogger("marong.safety")
WEAK = re.compile(r"죽고\s*싶|사라지고\s*싶|다\s*그만하고\s*싶|없어지고\s*싶|살기\s*싫")
DISTRESS = re.compile(r"힘들|우울|짜증|속상|서럽|억울|울었|울고|지쳤|지쳐|스트레스|망했|불안|외로|잘렸")
PLAN = re.compile(r"약\s*모아\s*놨|오늘\s*밤에\s*(?:죽을|끝낼)\s*거야|유서\s*(?:썼|적었|써\s*놨)")
CONTEXT_PLAN = re.compile(r"^오늘\s*밤에\s*할\s*거야[.!。]?$|^지금\s*(?:옥상|한강).*왔어[.!。]?$")
INJURY = re.compile(r"약\s*다\s*먹었어|피가\s*안\s*멈춰|(?:손목|팔|몸)(?:을)?\s*그었어|^그었어[.!。]?$")
METHOD = re.compile(r"(?:높|몇\s*미터).{0,32}(?:다리|옥상|건물)|(?:다리|옥상|건물).{0,32}(?:높|몇\s*미터)|"
                    r"(?:약|번개탄|끈).{0,15}(?:얼마|몇\s*개|용량|양|어디서|방법)")
NO = re.compile(r"^(?:아니|그\s*정도는|괜찮아|농담)")
YES = re.compile(r"^(?:응(?:[\s,.!?]|$)|진짜|하려고|할\s*거야)")
OWNER_ALERT = re.compile(r"위험해\s*보여|자살|자해|정신건강\s*위기")
BODY = re.compile(r"하루\s*한\s*끼만|하루\s*(?:500|600|700|800)\s*(?:칼로리|kcal)|물만\s*마실|굶을|"
                  r"먹고\s*토했|먹토|씹뱉|먹은\s*게\s*너무\s*후회돼서", re.I)
ASK = ("친구가 위험할 수 있어. 화제를 바꾸지 말고 이번 답에서 '혹시 진짜 죽고 싶은 마음까지 들어?'처럼 "
       "직접 한 번 물어봐. 방법·도구·장소는 절대 말하지 마.")
ASKED = "이미 물었고 답을 들었어. 다시 묻지 말고 곁에 있어 줘."
CALL_HELP = "같이 있겠다는 말과 함께 '자살예방 상담전화 109(국번 없이)'를 한 줄로 한 번 말해."
URGENT = "이미 다쳤다고 했어. 119로 응급 도움을 요청하도록 말해."
BODY_HELP = ("친구 계획이 몸에 무리일 수 있어. 걱정된다고 한 번 솔직하게 말하고, 혼자 버거우면 "
             "'정신건강 상담전화 1577-0199나 가까운 정신건강복지센터에 얘기해 볼 수도 있어'를 "
             "한 줄로 한 번만 말해. 훈계하지 마.")


def difficult(text):
    return bool(DISTRESS.search(text) and not any(mark in text for mark in ("ㅋㅋ", "😂", "🤣", "😆")))


def judge(text, nearby=()):
    if INJURY.search(text):
        return "injury"
    concerning = any(difficult(line) or WEAK.search(line) for line in (*nearby, text))
    if PLAN.search(text) or concerning and CONTEXT_PLAN.search(text.strip()):
        return "plan"
    if METHOD.search(text) and concerning:
        return "method"
    if WEAK.search(text):
        return "weak"
    return None


def owner_private(text):
    return bool(judge(text) or OWNER_ALERT.search(text) or BODY.search(text))


@dataclass(frozen=True)
class Decision:
    id: int
    kind: str
    prompt: str
    mark: str | None


class Safety:
    def __init__(self, store, classify):
        self.store = store
        self.classify = classify

    async def _classify(self, mode, rows):
        try:
            result = await asyncio.wait_for(self.classify(mode, rows[-6:]), 5)
            allowed = ("yes", "no") if mode == "signal" else ("now", "not_now", "unknown")
            if result not in allowed:
                raise ValueError("invalid safety response")
            return result
        except Exception as error:
            log.warning("crisis_judge_error mode=%s error=%s", mode, type(error).__name__)
            return "no" if mode == "signal" else "unknown"

    async def active(self, friend, at):
        return await self.store._all(
            """SELECT * FROM marong.safety_states WHERE friend_id=%s AND closed_at IS NULL AND
            last_signal_at>%s-CASE WHEN kind='crisis' THEN interval '3 days' ELSE interval '7 days' END
            ORDER BY kind DESC""", (friend, at),
        )

    async def apply(self, friend, text, nearby, at, *, via="text"):
        recent = [*nearby[-5:], text]
        signal = judge(text, nearby)
        if signal == "weak" and await self._classify("signal", recent) != "yes":
            signal = None
        kind = "crisis" if signal else "body" if BODY.search(text) else None
        states = await self.active(friend, at)
        crisis = next((row for row in states if row["kind"] == "crisis"), None)
        if crisis and CONTEXT_PLAN.search(text.strip()):
            signal, kind = "plan", "crisis"
        answer = None
        if crisis and crisis["asked_at"] and crisis["answer"] is None and not signal:
            answer = "not_now" if NO.search(text) else "now" if YES.search(text) else await self._classify("answer", recent)
        async with friend_lock(self.store.pool, friend) as conn:
            await conn.execute("""UPDATE marong.safety_states
                SET closed_at=%s,close_reason=CASE WHEN kind='crisis' THEN 'quiet_3d' ELSE 'quiet_7d' END
                WHERE friend_id=%s AND closed_at IS NULL
                AND last_signal_at<=%s-CASE WHEN kind='crisis' THEN interval '3 days' ELSE interval '7 days' END""",
                (at, friend, at))
            if kind:
                await conn.execute("""INSERT INTO marong.safety_states AS s
                    (friend_id,kind,injured,opened_at,opened_via,last_signal_at) VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(friend_id,kind) WHERE closed_at IS NULL DO UPDATE
                    SET injured=(s.injured OR EXCLUDED.injured),last_signal_at=greatest(s.last_signal_at,EXCLUDED.last_signal_at)""",
                    (friend, kind, signal == "injury", at, via, at))
            if answer:
                await conn.execute("""UPDATE marong.safety_states SET answer=%s,answered_at=%s
                    WHERE id=%s AND answer IS NULL AND closed_at IS NULL""", (answer, at, crisis["id"]))
            cur = await conn.execute("""SELECT * FROM marong.safety_states WHERE friend_id=%s AND closed_at IS NULL
                ORDER BY (kind='crisis') DESC LIMIT 1""", (friend,))
            row = await cur.fetchone()
        if not row:
            return None
        if row["kind"] == "body":
            return Decision(row["id"], "body", "" if row["told_help_at"] else BODY_HELP,
                            None if row["told_help_at"] else "body")
        if row["injured"] or signal == "plan" or row["answer"] == "now":
            if row["told_109_at"] is None or signal == "injury" and crisis and not crisis["injured"]:
                return Decision(row["id"], "crisis", URGENT if row["injured"] else CALL_HELP,
                                "119" if row["injured"] else "109")
        if not row["asked_at"] and not row["told_109_at"]:
            return Decision(row["id"], "crisis", ASK, "ask")
        return Decision(row["id"], "crisis", ASKED if row["asked_at"] else "", None)

    async def delivered(self, friend, decision, text, at):
        field = None
        if decision.mark == "ask" and "?" in text and WEAK.search(text):
            field = "asked_at"
        elif decision.mark in ("109", "119") and decision.mark in text:
            field = "told_109_at"
        elif decision.mark == "body" and "1577-0199" in text:
            field = "told_help_at"
        if field:
            from psycopg import sql
            async with friend_lock(self.store.pool, friend) as conn:
                statement = sql.SQL("""UPDATE marong.safety_states SET {field}=COALESCE({field},%s)
                    WHERE id=%s AND friend_id=%s AND closed_at IS NULL""").format(field=sql.Identifier(field))
                await conn.execute(statement, (at, decision.id, friend))
