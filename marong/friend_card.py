"""Per-friend card, rules, instructions, and preference signals (TBL-115–118)."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from psycopg import sql

KST = ZoneInfo("Asia/Seoul")
OPTIONS = {
    "support": ("listen", "side", "solve", "distract", "chat", "ask"),
    "advice": ("asked", "sometimes", "any"),
    "honesty": ("gentle", "direct", "let_go"),
    "lead": ("follow", "lead"),
    "proactive": ("normal", "less", "off"),
}
DEFAULT_CARD = {"support": "ask", "advice": "asked", "honesty": "gentle", "lead": "follow", "proactive": "normal"}
QUESTIONS = (
    ("support", "힘들 때 나한테 제일 바라는 건?",
     ("그냥 들어주기", "내 편", "같이 방법 찾기", "기분 전환", "그냥 수다", "그때그때 물어봐")),
    ("advice", "조언은 언제 해 줄까?", ("물어볼 때만", "괜찮아 보이면 가끔", "언제든")),
    ("honesty", "내가 좀 아닌 것 같을 때는?", ("부드럽게", "솔직하게", "그냥 넘어가 줘")),
)
SENTENCE = {
    "support": {"listen": "힘들다고 하면 일단 들을게", "solve": "힘들다고 하면 같이 방법을 찾아볼게",
                "ask": "힘들 땐 어떻게 해 줄지 그때그때 물어볼게"},
    "advice": {"asked": "조언은 네가 물어볼 때만 하고", "any": "필요하면 조언도 바로 하고"},
    "honesty": {"gentle": "아닌 것 같을 땐 부드럽게 말할게", "direct": "아닌 것 같을 땐 솔직하게 말할게",
                "let_go": "웬만한 건 그냥 넘어갈게"},
}
RULE_LENGTH = {"no_vocative": (1, 4), "avoid_topic": (2, 20), "call_me": (1, 4)}


def card_sentence(row):
    if not row or row["state"] not in ("draft", "set"):
        return None
    support, advice, honesty = (SENTENCE[field].get(row[field]) for field in SENTENCE)
    if not all((support, advice, honesty)):
        return None
    return f"{support}. {advice}, {honesty}."


def question_choices(step):
    field, _, labels = QUESTIONS[step - 1]
    return tuple(zip(OPTIONS[field], labels, strict=True))


def text_choice(step, text):
    choices = question_choices(step)
    value = text.strip()
    for index, (option, label) in enumerate(choices, 1):
        if value in (str(index), label):
            return option
    return None


class CardError(Exception):
    """Stable error codes shared by the channel transports."""


@dataclass(frozen=True)
class ToolResult:
    outcome: str
    why: str | None = None
    target_type: str | None = None
    target_id: int | None = None


@dataclass(frozen=True)
class ModelRun:
    kind: str
    trace_id: str
    model: str
    prompt_version: str
    sent_at: datetime
    outcome: str
    friend_id: int | None = None
    ref_id: int | None = None
    effort: str | None = None
    thinking: str | None = None
    first_token_ms: int | None = None
    total_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost_usd: Decimal | None = None
    stop_reason: str | None = None
    error_code: str | None = None
    fallback: str | None = None


@asynccontextmanager
async def friend_lock(pool, friend):
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(%s::bigint)", (friend,))
        yield conn


class FriendCards:
    def __init__(self, store):
        self.store = store

    async def read(self, friend, *, private=True):
        async with self.store.pool.connection() as conn, conn.transaction():
            await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur = await conn.execute(
                """SELECT id,kind,text,source FROM marong.friend_rules
                WHERE friend_id=%s AND removed_at IS NULL ORDER BY id""", (friend,),
            )
            rules = await cur.fetchall()
            card = instruction = None
            if private:
                cur = await conn.execute("SELECT * FROM marong.friend_cards WHERE friend_id=%s", (friend,))
                card = await cur.fetchone()
                cur = await conn.execute(
                    "SELECT text,understood,polite,version,via FROM marong.custom_instructions WHERE friend_id=%s",
                    (friend,),
                )
                instruction = await cur.fetchone()
        return {"card": card, "rules": rules, "instruction": instruction}

    async def set(self, friend, changes, *, source, by="friend"):
        if not changes or any(k not in OPTIONS or value not in OPTIONS[k] for k, value in changes.items()):
            raise ValueError("invalid card value")
        async with friend_lock(self.store.pool, friend) as conn:
            return await self._set(conn, friend, changes, source, by)

    @staticmethod
    async def _set(conn, friend, changes, source, by):
        cur = await conn.execute("SELECT * FROM marong.friend_cards WHERE friend_id=%s", (friend,))
        old = await cur.fetchone()
        fields = dict(changes)
        if not old or old["state"] != "set":
            fields = {**{key: (old or {}).get(key) or value for key, value in DEFAULT_CARD.items()}, **fields}
        await conn.execute("INSERT INTO marong.friend_cards(friend_id) VALUES (%s) ON CONFLICT DO NOTHING", (friend,))
        assignments = [sql.SQL("{}=%s").format(sql.Identifier(key)) for key in fields]
        stmt = sql.SQL("""UPDATE marong.friend_cards SET {},state='set',source=%s,updated_by=%s,updated_at=now(),
                       set_at=COALESCE(set_at,now()) WHERE friend_id=%s RETURNING *""")
        cur = await conn.execute(stmt.format(sql.SQL(",").join(assignments)), (*fields.values(), source, by, friend))
        return await cur.fetchone()

    @staticmethod
    async def _publish_question(conn, friend, room, step, at, expires):
        row = await conn.execute(
            """INSERT INTO marong.chat_cards(friend_id,kind,step,room_key,expires_at,created_at)
            VALUES (%s,'card_question',%s,%s,%s,%s) RETURNING *""", (friend, step, room, expires, at),
        )
        return await row.fetchone()

    async def first_question(self, friend, room, at):
        """Start atomically once the transport decides this is an eligible direct reply."""
        async with friend_lock(self.store.pool, friend) as conn:
            last = await conn.execute(
                """SELECT id FROM marong.chat_cards WHERE friend_id=%s AND kind='card_question'
                UNION ALL SELECT friend_id FROM marong.friend_cards WHERE friend_id=%s AND state='set' LIMIT 1""",
                (friend, friend),
            )
            if await last.fetchone():
                return None
            return await self._publish_question(conn, friend, room, 1, at, at + timedelta(hours=24))

    async def open_question(self, friend, room, at):
        return await self.store._one(
            """SELECT * FROM marong.chat_cards WHERE friend_id=%s AND room_key=%s AND kind='card_question'
            AND status='open' AND expires_at>%s""", (friend, room, at),
        )

    async def attach_question(self, friend, card_id, message_id):
        """Attach a shown question only to an assistant message in its own conversation."""
        async with friend_lock(self.store.pool, friend) as conn:
            upd = await conn.execute(
                """UPDATE marong.chat_cards AS card SET message_id=msg.id
                FROM marong.messages AS msg WHERE card.friend_id=%s AND card.id=%s
                AND msg.id=%s AND msg.room_key=card.room_key AND msg.role='assistant' AND card.message_id IS NULL""",
                (friend, card_id, message_id),
            )
            return upd.rowcount == 1

    async def answer_question(self, friend, card_id, value, *, room, via, at):
        async with friend_lock(self.store.pool, friend) as conn:
            cursor = await conn.execute(
                """SELECT * FROM marong.chat_cards WHERE id=%s AND friend_id=%s AND kind='card_question'""",
                (card_id, friend),
            )
            card = await cursor.fetchone()
            if not card:
                raise CardError("card_not_found")
            if value not in dict(question_choices(card["step"])) or via not in ("button", "text", "screen"):
                raise CardError("invalid_input")
            if card["status"] == "answered" and value == card["answer"]:
                return await self._question_result(conn, card, applied=False)
            if card["status"] != "open" or card["expires_at"] <= at:
                raise CardError("card_closed")
            current = await conn.execute("SELECT state FROM marong.friend_cards WHERE friend_id=%s", (friend,))
            if (await current.fetchone() or {}).get("state") == "set":
                raise CardError("card_closed")
            picked = await conn.execute(
                """UPDATE marong.chat_cards SET status='answered',answer=%s,answered_via=%s,answered_at=%s
                WHERE id=%s RETURNING *""", (value, via, at, card_id),
            )
            card = await picked.fetchone()
            if card["step"] < 3:
                await self._publish_question(conn, friend, room, card["step"] + 1, at, card["expires_at"])
            else:
                rows = await conn.execute(
                    """SELECT step,answer FROM marong.chat_cards WHERE friend_id=%s AND kind='card_question'
                    AND status='answered' AND expires_at=%s ORDER BY step""", (friend, card["expires_at"]),
                )
                answers = {QUESTIONS[item["step"] - 1][0]: item["answer"] for item in await rows.fetchall()}
                await self._set(conn, friend, answers, "questions", "friend")
            return await self._question_result(conn, card, applied=True)

    @staticmethod
    async def _question_result(conn, card, *, applied):
        if card["step"] < 3:
            cur = await conn.execute(
                """SELECT * FROM marong.chat_cards WHERE friend_id=%s AND kind='card_question'
                AND step=%s AND expires_at=%s ORDER BY id DESC LIMIT 1""",
                (card["friend_id"], card["step"] + 1, card["expires_at"]),
            )
            return {"card": card, "effect": "next_question", "next": await cur.fetchone(), "applied": applied}
        # Recompute from the choices that completed this questionnaire even if the friend edited their card later.
        rows = await conn.execute(
            """SELECT step,answer FROM marong.chat_cards WHERE friend_id=%s AND kind='card_question'
            AND status='answered' AND expires_at=%s ORDER BY step""", (card["friend_id"], card["expires_at"]),
        )
        values = {QUESTIONS[item["step"] - 1][0]: item["answer"] for item in await rows.fetchall()}
        return {"card": card, "effect": "card_set", "sentence": card_sentence({"state": "set", **values}), "applied": applied}

    async def expire_question(self, friend, at):
        """Apply the fallback when the original 24-hour deadline expires."""
        async with friend_lock(self.store.pool, friend) as conn:
            expiring = await conn.execute(
                """UPDATE marong.chat_cards SET status='expired' WHERE friend_id=%s AND kind='card_question'
                AND status='open' AND expires_at<=%s RETURNING id,room_key""", (friend, at),
            )
            timed_out = await expiring.fetchone()
            if not timed_out:
                return None
            current = await conn.execute("SELECT state FROM marong.friend_cards WHERE friend_id=%s", (friend,))
            if (await current.fetchone() or {}).get("state") == "set":
                return None
            await self._set(conn, friend, DEFAULT_CARD, "default", "system")
            return timed_out

    @staticmethod
    def _rule(kind, text):
        if not isinstance(kind, str) or kind not in RULE_LENGTH or not isinstance(text, str):
            return None
        low, high = RULE_LENGTH[kind]
        text = " ".join(text.split())
        return text if low <= len(text) <= high else None

    async def add_rule(self, friend, kind, text, *, source="screen"):
        async with friend_lock(self.store.pool, friend) as conn:
            return await self._add_rule(conn, friend, kind, text, source)

    async def _add_rule(self, conn, friend, kind, text, source, message_id=None):
        text = self._rule(kind, text)
        if text is None:
            return ToolResult("invalid", "too_long"), False
        cur = await conn.execute(
            """SELECT id,lower(text)=lower(%s) AS same FROM marong.friend_rules
            WHERE friend_id=%s AND kind=%s AND removed_at IS NULL""", (text, friend, kind),
        )
        rows = await cur.fetchall()
        for row in rows:
            if row["same"]:
                return ToolResult("ok", target_type="rule", target_id=row["id"]), False
        if kind == "call_me":
            await conn.execute(
                """UPDATE marong.friend_rules SET removed_at=now()
                WHERE friend_id=%s AND kind='call_me' AND removed_at IS NULL""", (friend,),
            )
        elif len(rows) >= 20:
            return ToolResult("refused", "limit"), False
        cur = await conn.execute(
            """INSERT INTO marong.friend_rules(friend_id,kind,text,source,message_id)
            VALUES (%s,%s,%s,%s,%s) RETURNING id""", (friend, kind, text, source, message_id),
        )
        return ToolResult("ok", target_type="rule", target_id=(await cur.fetchone())["id"]), True

    async def remove_rule(self, friend, rule_id):
        async with friend_lock(self.store.pool, friend) as conn:
            cur = await conn.execute(
                """UPDATE marong.friend_rules SET removed_at=now()
                WHERE friend_id=%s AND id=%s AND removed_at IS NULL RETURNING id""", (friend, rule_id),
            )
            return await cur.fetchone() is not None

    async def write_instruction(self, friend, text, understood=None, *, polite=False, via=None):
        if text is None:
            understood, polite, via = None, False, None
        elif (not isinstance(text, str) or not 1 <= len(text.strip()) <= 500 or not isinstance(understood, str)
              or not 1 <= len(understood.strip()) <= 300 or via not in ("chat", "screen")):
            raise ValueError("invalid custom instruction")
        else:
            text, understood = text.strip(), understood.strip()
        async with friend_lock(self.store.pool, friend) as conn:
            cur = await conn.execute(
                """INSERT INTO marong.custom_instructions AS current(friend_id,text,understood,polite,via)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT(friend_id) DO UPDATE SET
                  text=EXCLUDED.text,understood=EXCLUDED.understood,polite=EXCLUDED.polite,via=EXCLUDED.via,
                  version=current.version+1,updated_at=now()
                WHERE (current.text,current.understood,current.polite,current.via) IS DISTINCT FROM
                      (EXCLUDED.text,EXCLUDED.understood,EXCLUDED.polite,EXCLUDED.via)
                RETURNING version""", (friend, text, understood, polite, via),
            )
            row = await cur.fetchone()
            if row:
                return row["version"]
            cur = await conn.execute("SELECT version FROM marong.custom_instructions WHERE friend_id=%s", (friend,))
            return (await cur.fetchone())["version"]

    @staticmethod
    async def _signal(conn, friend, field, value, day, source, message_id, turn_id):
        cur = await conn.execute(
            """INSERT INTO marong.preference_signals(friend_id,field,value,day,source,message_id,call_turn_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(friend_id,field,value,day) DO NOTHING RETURNING id""",
            (friend, field, value, day, source, message_id, turn_id),
        )
        return await cur.fetchone() is not None

    async def signal(self, friend, field, value, *, source, at, message_id=None, turn_id=None):
        if field == "proactive" or field not in OPTIONS or value not in OPTIONS[field]:
            raise ValueError("invalid preference signal")
        async with friend_lock(self.store.pool, friend) as conn:
            return await self._signal(conn, friend, field, value, at.astimezone(KST).date(), source, message_id, turn_id)

    async def open_signals(self, friend, field):
        return await self.store._all(
            """SELECT value,count(*) AS days,max(day) AS latest
            FROM marong.preference_signals WHERE friend_id=%s AND field=%s AND closed_at IS NULL
            GROUP BY value ORDER BY days DESC, latest DESC, value""", (friend, field),
        )

    async def close_signals(self, friend, field, reason):
        async with friend_lock(self.store.pool, friend) as conn:
            await conn.execute(
                """UPDATE marong.preference_signals SET closed_at=now(),closed_by=%s
                WHERE friend_id=%s AND field=%s AND closed_at IS NULL""", (reason, friend, field),
            )

    async def record_run(self, run: ModelRun):
        async with self.store.pool.connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO marong.persona_ai_runs(
                    kind,trace_id,model,prompt_version,sent_at,outcome,friend_id,ref_id,effort,thinking,
                    first_token_ms,total_ms,input_tokens,output_tokens,cache_read_tokens,cache_write_tokens,
                    cost_usd,stop_reason,error_code,fallback
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (run.kind, run.trace_id, run.model, run.prompt_version, run.sent_at, run.outcome, run.friend_id,
                 run.ref_id, run.effort, run.thinking, run.first_token_ms, run.total_ms, run.input_tokens,
                 run.output_tokens, run.cache_read_tokens, run.cache_write_tokens, run.cost_usd,
                 run.stop_reason, run.error_code, run.fallback),
            )
            return (await cursor.fetchone())["id"]

    async def apply_tool(self, actor, room, message_id, request_key, args):
        """Apply the rule tool once, against the original text and speaker of this turn."""
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 100 or not isinstance(args, dict):
            return ToolResult("invalid", "not_known")
        async with friend_lock(self.store.pool, actor) as conn:
            cur = await conn.execute(
                """SELECT outcome,why,target_type,target_id FROM marong.persona_tool_calls
                WHERE friend_id=%s AND request_key=%s""", (actor, request_key),
            )
            seen = await cur.fetchone()
            if seen:
                return ToolResult(**seen)
            cur = await conn.execute(
                """SELECT m.content,p.friend_id FROM marong.messages m JOIN marong.people p USING(user_key)
                WHERE m.id=%s AND m.room_key=%s AND m.role='user' AND NOT (m.meta ? 'image')""", (message_id, room),
            )
            speaker = await cur.fetchone()
            if not speaker or speaker["friend_id"] != actor:
                applied = ToolResult("refused", "not_speaker")
            elif args.get("friend_id", actor) != actor:
                applied = ToolResult("refused", "other_friend")
            elif (not isinstance(args.get("quote"), str) or not args["quote"].strip()
                  or args["quote"] not in speaker["content"]):
                applied = ToolResult("refused", "quote_missing")
            else:
                applied = await self._mutate_tool(conn, actor, message_id, args)
            arg_chars = min(sum(len(value) for value in args.values() if isinstance(value, str)), 32767)
            await conn.execute(
                """INSERT INTO marong.persona_tool_calls(friend_id,room_key,message_id,tool,request_key,outcome,why,
                    target_type,target_id,arg_chars)
                VALUES (%s,%s,%s,'card_update',%s,%s,%s,%s,%s,%s)""",
                (actor, room, message_id if speaker else None, request_key, applied.outcome, applied.why,
                 applied.target_type, applied.target_id, arg_chars),
            )
            return applied

    async def _mutate_tool(self, conn, friend, message_id, args):
        operation, kind = args.get("op"), args.get("kind")
        text = args.get("text")
        if operation == "rule_add" and isinstance(kind, str):
            applied, _ = await self._add_rule(conn, friend, kind, text, "talk", message_id)
            return applied
        if operation == "rule_remove" and isinstance(kind, str):
            text = self._rule(kind, text)
            if text is None:
                return ToolResult("invalid", "too_long")
            cur = await conn.execute(
                """UPDATE marong.friend_rules SET removed_at=now() WHERE friend_id=%s AND kind=%s
                AND lower(text)=lower(%s) AND removed_at IS NULL RETURNING id""", (friend, kind, text),
            )
            row = await cur.fetchone()
            return ToolResult("ok", target_type="rule", target_id=row["id"]) if row else ToolResult("none_matched")
        value = args.get("value")
        if operation == "want" and value in OPTIONS["support"]:
            now = datetime.now(KST)
            await conn.execute(
                """INSERT INTO marong.friend_cards(friend_id,want,want_until) VALUES (%s,%s,%s)
                ON CONFLICT(friend_id) DO UPDATE SET want=EXCLUDED.want,want_until=EXCLUDED.want_until,
                updated_at=now(),updated_by='friend'""", (friend, value, now + timedelta(hours=24)),
            )
            await self._signal(conn, friend, "support", value, now.date(), "want", message_id, None)
            return ToolResult("ok", target_type="card", target_id=friend)
        if operation == "lead" and value in OPTIONS["lead"]:
            await conn.execute(
                """INSERT INTO marong.friend_cards(friend_id,lead) VALUES (%s,%s)
                ON CONFLICT(friend_id) DO UPDATE SET lead=EXCLUDED.lead,updated_at=now(),updated_by='friend'""",
                (friend, value),
            )
            return ToolResult("ok", target_type="card", target_id=friend)
        return ToolResult("invalid", "not_known")
