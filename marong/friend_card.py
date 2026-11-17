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
CARD_UPDATE = {
    "name": "card_update",
    "description": "지금 바람, 친구 규칙 또는 대화를 이끌 방법을 친구가 직접 말했을 때 적는 도구야.",
    "input_schema": {
        "type": "object",
        "properties": {
            "op": {"enum": ["want", "rule_add", "rule_remove", "lead", "proactive_lower", "call_first_off"]},
            "quote": {"type": "string", "minLength": 1, "maxLength": 2000},
            "kind": {"enum": list(RULE_LENGTH)},
            "value": {"enum": [*OPTIONS["support"], *OPTIONS["lead"], *OPTIONS["proactive"]]},
            "text": {"type": "string", "minLength": 1, "maxLength": 20},
        },
        "required": ["op", "quote"],
        "additionalProperties": False,
    },
}


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


def choices(card):
    if card["kind"] == "card_question":
        return question_choices(card["step"])
    if card["kind"] == "card_draft":
        return (("yes", "맞아"), ("edit", "고칠래"))
    if card["kind"] == "ask_support":
        return (("listen", "일단 들어 줘"), ("solve", "같이 방법 찾자"))
    return ()


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

    async def read(self, friend, *, private=True, include_call_first=True):
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
                    "SELECT text,understood,polite,version,via,updated_at FROM marong.custom_instructions WHERE friend_id=%s",
                    (friend,),
                )
                instruction = await cur.fetchone()
            call_first = None
            if private and include_call_first:
                cur = await conn.execute("SELECT hello_call FROM marong.topic_prefs WHERE friend_id=%s", (friend,))
                call_first = (await cur.fetchone() or {}).get("hello_call", True)
        return {"card": card, "rules": rules, "instruction": instruction, "call_first": call_first}

    async def set(self, friend, changes, *, source, by="friend"):
        if not changes or any(k not in OPTIONS or value not in OPTIONS[k] for k, value in changes.items()):
            raise ValueError("invalid card value")
        async with friend_lock(self.store.pool, friend) as conn:
            return await self._set(conn, friend, changes, source, by)

    async def update_from_screen(self, friend, changes):
        if not changes or any(k not in OPTIONS or v not in OPTIONS[k] for k, v in changes.items()):
            raise CardError("invalid_request")
        async with friend_lock(self.store.pool, friend) as conn:
            current = await conn.execute("SELECT state,proactive FROM marong.friend_cards WHERE friend_id=%s", (friend,))
            row = await current.fetchone() or {}
            if row.get("state") != "set" and any(key not in changes for key, _, _ in QUESTIONS):
                raise CardError("requires_three")
            old = row.get("proactive") or "normal"
            new = changes.get("proactive", old)
            if OPTIONS["proactive"].index(new) < OPTIONS["proactive"].index(old):
                raise CardError("needs_owner")
            await self._set(conn, friend, changes, "screen", "friend")
            await conn.execute("""UPDATE marong.chat_cards SET status='replaced'
                WHERE friend_id=%s AND status='open' AND kind IN ('card_question','card_draft')""", (friend,))

    async def get_rule(self, friend, rule_id):
        row = await self.store._one(
            """SELECT id,kind,text FROM marong.friend_rules WHERE friend_id=%s AND id=%s""",
            (friend, rule_id),
        )
        return row

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

    async def first_question(self, friend, room, at, *, before_message=None):
        """Start atomically once the transport decides this is an eligible direct reply."""
        async with friend_lock(self.store.pool, friend) as conn:
            last = await conn.execute(
                """SELECT id FROM marong.chat_cards WHERE friend_id=%s AND kind='card_question'
                UNION ALL SELECT friend_id FROM marong.friend_cards WHERE friend_id=%s AND state='set' LIMIT 1""",
                (friend, friend),
            )
            if await last.fetchone():
                return None
            if before_message:
                prepared = await conn.execute(
                    "SELECT 1 FROM marong.persona_ai_runs WHERE friend_id=%s AND kind='card_draft' LIMIT 1", (friend,))
                attempted = await prepared.fetchone()
                history = await conn.execute(
                    """SELECT 1 FROM marong.messages m JOIN marong.people p USING(user_key)
                    JOIN marong.rooms r USING(room_key)
                    WHERE p.friend_id=%s AND m.id<%s AND m.role='user' AND r.is_channel
                    UNION ALL SELECT 1 FROM call.calls c JOIN call.callers a ON a.id=c.caller_id
                    WHERE a.friend_id=%s LIMIT 1""", (friend, before_message, friend),
                )
                if await history.fetchone() and not attempted:
                    return None
            await conn.execute("""INSERT INTO marong.friend_cards(friend_id,state,asking_since)
                VALUES (%s,'asking',%s) ON CONFLICT(friend_id) DO UPDATE SET
                state='asking',asking_since=EXCLUDED.asking_since,updated_at=now(),updated_by='system'
                WHERE marong.friend_cards.state='none'""", (friend, at))
            return await self._publish_question(conn, friend, room, 1, at, at + timedelta(hours=24))

    async def draft_card(self, friend, room, at):
        async with friend_lock(self.store.pool, friend) as conn:
            cur = await conn.execute("SELECT * FROM marong.friend_cards WHERE friend_id=%s AND state='draft'", (friend,))
            current = await cur.fetchone()
            if not current or not card_sentence(current):
                return None
            cur = await conn.execute("""SELECT 1 FROM marong.chat_cards
                WHERE friend_id=%s AND kind='card_draft' LIMIT 1""", (friend,))
            if await cur.fetchone():
                return None
            cur = await conn.execute("""INSERT INTO marong.chat_cards(friend_id,kind,room_key,expires_at,created_at)
                VALUES (%s,'card_draft',%s,%s,%s) RETURNING *""",
                (friend, room, at + timedelta(hours=24), at))
            return await cur.fetchone(), card_sentence(current)

    async def answer_draft(self, friend, card_id, value, *, via, at):
        async with friend_lock(self.store.pool, friend) as conn:
            cur = await conn.execute("""SELECT * FROM marong.chat_cards WHERE friend_id=%s AND id=%s
                AND kind='card_draft'""", (friend, card_id))
            row = await cur.fetchone()
            if not row:
                raise CardError("card_not_found")
            if value not in dict(choices(row)) or via not in ("button", "screen", "text"):
                raise CardError("invalid_input")
            effect = "card_set" if value == "yes" else "open_card_screen"
            if row["status"] == "answered" and row["answer"] == value:
                previous = await conn.execute("SELECT content FROM marong.messages WHERE id=%s", (row["message_id"],))
                original = await previous.fetchone()
                prefix = "내가 본 너는 이래: "
                ending = " 맞아? 고칠래?"
                sentence = None
                if original and prefix in original["content"] and original["content"].endswith(ending):
                    sentence = original["content"].split(prefix, 1)[1][:-len(ending)]
                if sentence is None and value == "yes":
                    previous = await conn.execute("SELECT * FROM marong.friend_cards WHERE friend_id=%s", (friend,))
                    sentence = card_sentence(await previous.fetchone())
                return {"card": row, "effect": effect, "applied": False, "sentence": sentence}
            if row["status"] != "open" or row["expires_at"] <= at:
                raise CardError("card_closed")
            cur = await conn.execute("""UPDATE marong.chat_cards SET status='answered',answer=%s,
                answered_via=%s,answered_at=%s WHERE id=%s RETURNING *""", (value, via, at, row["id"]))
            row = await cur.fetchone()
            sentence = None
            if value == "yes":
                current = await conn.execute("SELECT * FROM marong.friend_cards WHERE friend_id=%s", (friend,))
                current = await current.fetchone()
                values = {key: current[key] for key in ("support", "advice", "honesty", "lead")}
                sentence = card_sentence(await self._set(conn, friend, values, "draft", "friend"))
            return {"card": row, "effect": effect, "applied": True, "sentence": sentence}

    async def answer_card(self, friend, card, value, **kwargs):
        if card["kind"] == "card_draft":
            return await self.answer_draft(friend, card["id"], value, via=kwargs["via"], at=kwargs["at"])
        if card["kind"] == "ask_support":
            return await self.answer_support(friend, card["id"], value, via=kwargs["via"], at=kwargs["at"])
        return await self.answer_question(friend, card["id"], value, **kwargs)

    async def ask_support(self, friend, room, at):
        async with friend_lock(self.store.pool, friend) as conn:
            current = await conn.execute("SELECT * FROM marong.friend_cards WHERE friend_id=%s", (friend,))
            current = await current.fetchone()
            if not current or current["support"] != "ask" or current["want_until"] and current["want_until"] > at:
                return None
            cur = await conn.execute("""SELECT 1 FROM marong.chat_cards WHERE friend_id=%s AND kind='ask_support'
                AND created_at>%s LIMIT 1""", (friend, at-timedelta(hours=6)))
            if await cur.fetchone():
                return None
            await conn.execute("""UPDATE marong.chat_cards SET status='replaced'
                WHERE friend_id=%s AND kind='ask_support' AND status='open'""", (friend,))
            cur = await conn.execute("""INSERT INTO marong.chat_cards(friend_id,kind,room_key,expires_at,created_at)
                VALUES (%s,'ask_support',%s,%s,%s) RETURNING *""", (friend, room, at+timedelta(hours=24), at))
            return await cur.fetchone()

    async def answer_support(self, friend, id, value, *, via, at):
        async with friend_lock(self.store.pool, friend) as conn:
            cur = await conn.execute("SELECT * FROM marong.chat_cards WHERE id=%s AND friend_id=%s AND kind='ask_support'",
                                     (id, friend))
            row = await cur.fetchone()
            if not row:
                raise CardError("card_not_found")
            if value not in dict(choices(row)) or via not in ("screen", "text", "button"):
                raise CardError("invalid_input")
            if row["status"] == "answered" and row["answer"] == value:
                return {"card": row, "effect": "want_set", "applied": False}
            if row["status"] != "open" or row["expires_at"] <= at:
                raise CardError("card_closed")
            cur = await conn.execute("""UPDATE marong.chat_cards SET status='answered',answer=%s,answered_via=%s,
                answered_at=%s WHERE id=%s RETURNING *""", (value, via, at, id))
            row = await cur.fetchone()
            await conn.execute("""UPDATE marong.friend_cards SET want=%s,want_until=%s,updated_at=now(),
                updated_by='friend' WHERE friend_id=%s""", (value, at+timedelta(hours=24), friend))
            await self._signal(conn, friend, "support", value, at.astimezone(KST).date(), "ask_support", None, None)
            return {"card": row, "effect": "want_set", "applied": True}

    async def support_text(self, friend, room, text, at):
        row = await self.store._one(
            """SELECT id FROM marong.chat_cards WHERE friend_id=%s AND room_key=%s
            AND kind='ask_support' AND status='open' AND expires_at>%s""", (friend, room, at),
        )
        values = {"1": "listen", "일단 들어 줘": "listen", "일단 들어줘": "listen",
                  "2": "solve", "같이 방법 찾자": "solve"}
        value = values.get(text.strip())
        if row and value:
            return await self.answer_support(friend, row["id"], value, via="text", at=at)
        return None

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

    async def shown_today(self, friend, card, since):
        row = await self.store._one(
            """SELECT count(*) AS n FROM marong.messages m JOIN marong.chat_cards c ON c.room_key=m.room_key
            WHERE c.friend_id=%s AND c.id=%s AND m.role='assistant' AND m.created_at>=%s
            AND m.meta->>'persona_question'=c.id::text AND m.meta->>'delivered'='true'""", (friend, card, since),
        )
        return row["n"]

    async def answer_question(self, friend, card_id, value, *, room, via, at, publish_message=False):
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
                upcoming = await self._publish_question(conn, friend, room, card["step"] + 1, at, card["expires_at"])
                if publish_message:
                    cur = await conn.execute(
                        """INSERT INTO marong.messages(room_key,role,content,meta)
                        VALUES (%s,'assistant',%s,'{"transport":"app","delivered":true}') RETURNING id""",
                        (room, QUESTIONS[card["step"]][1]),
                    )
                    await conn.execute("UPDATE marong.chat_cards SET message_id=%s WHERE id=%s",
                                       ((await cur.fetchone())["id"], upcoming["id"]))
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
                """UPDATE marong.chat_cards SET status='expired' WHERE friend_id=%s
                AND kind IN ('card_question','card_draft') AND status='open' AND expires_at<=%s
                RETURNING id,room_key,kind""", (friend, at),
            )
            timed_out = await expiring.fetchone()
            if not timed_out:
                return None
            current = await conn.execute("SELECT * FROM marong.friend_cards WHERE friend_id=%s", (friend,))
            current = await current.fetchone() or {}
            if current.get("state") == "set":
                return None
            if timed_out["kind"] == "card_draft":
                values = {key: current[key] for key in ("support", "advice", "honesty", "lead")}
                await self._set(conn, friend, values, "draft_silent", "system")
            else:
                await self._set(conn, friend, DEFAULT_CARD, "default", "system")
            return timed_out

    async def pending_notice(self, friend):
        row = await self.store._one("""SELECT source FROM marong.friend_cards WHERE friend_id=%s
            AND state='set' AND source IN ('default','draft_silent') AND notice_sent_at IS NULL""", (friend,))
        return row["source"] if row else None

    async def notice_delivered(self, friend):
        async with friend_lock(self.store.pool, friend) as conn:
            await conn.execute("""UPDATE marong.friend_cards SET notice_sent_at=COALESCE(notice_sent_at,now())
                WHERE friend_id=%s AND source IN ('default','draft_silent')""", (friend,))

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

    async def draft(self, friend, values, at):
        """Keep a generated card as a draft until the friend confirms it."""
        if set(values) != {"support", "advice", "honesty", "lead"} or any(
            value not in OPTIONS[key] for key, value in values.items()
        ):
            raise CardError("invalid_request")
        async with friend_lock(self.store.pool, friend) as conn:
            await conn.execute("""INSERT INTO marong.friend_cards
                (friend_id,state,support,advice,honesty,lead,source,asking_since,updated_by)
                VALUES (%s,'draft',%s,%s,%s,%s,'draft',%s,'system')
                ON CONFLICT(friend_id) DO NOTHING""",
                (friend, values["support"], values["advice"], values["honesty"], values["lead"], at))

    async def remove_rule(self, friend, rule_id):
        async with friend_lock(self.store.pool, friend) as conn:
            cur = await conn.execute(
                """UPDATE marong.friend_rules SET removed_at=COALESCE(removed_at,now())
                WHERE friend_id=%s AND id=%s RETURNING id""", (friend, rule_id),
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
            return await self._write_instruction(conn, friend, text, understood, polite, via)

    @staticmethod
    async def _write_instruction(conn, friend, text, understood, polite, via):
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

    async def save_interpretation(self, friend, text, interpretation, *, via):
        async with friend_lock(self.store.pool, friend) as conn:
            rules = []
            for kind, rule in interpretation["rules"]:
                applied, added = await self._add_rule(conn, friend, kind, rule, "instruction")
                if applied.outcome != "ok":
                    raise CardError("rule_limit")
                if added:
                    rules.append({"id": applied.target_id, "kind": kind, "text": rule})
            proactive = interpretation["proactive"]
            moved = None
            if proactive:
                await conn.execute("INSERT INTO marong.friend_cards(friend_id) VALUES (%s) ON CONFLICT DO NOTHING",
                                   (friend,))
                cursor = await conn.execute("SELECT proactive FROM marong.friend_cards WHERE friend_id=%s", (friend,))
                old = (await cursor.fetchone())["proactive"]
                if OPTIONS["proactive"].index(proactive) > OPTIONS["proactive"].index(old):
                    await conn.execute("""UPDATE marong.friend_cards SET proactive=%s,updated_at=now(),
                        updated_by='friend' WHERE friend_id=%s""", (proactive, friend))
                    moved = proactive
            if interpretation["turn_off"]:
                await conn.execute("""INSERT INTO marong.topic_prefs(friend_id,hello_call) VALUES (%s,false)
                    ON CONFLICT(friend_id) DO UPDATE SET hello_call=false,updated_at=now(),updated_by='friend'""",
                    (friend,))
            await self._write_instruction(conn, friend, text, interpretation["understood"],
                                          interpretation["polite"], via)
            return {"rules": rules, "proactive": moved}

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
        if operation == "proactive_lower" and value in OPTIONS["proactive"]:
            await conn.execute("""INSERT INTO marong.friend_cards(friend_id,proactive) VALUES (%s,%s)
                ON CONFLICT(friend_id) DO UPDATE SET proactive=EXCLUDED.proactive,updated_at=now(),updated_by='friend'""",
                (friend, value))
            return ToolResult("ok", target_type="card", target_id=friend)
        if operation == "call_first_off":
            await conn.execute("""INSERT INTO marong.topic_prefs(friend_id,hello_call) VALUES (%s,false)
                ON CONFLICT(friend_id) DO UPDATE SET hello_call=false,updated_at=now(),updated_by='friend'""", (friend,))
            return ToolResult("ok", target_type="card", target_id=friend)
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

    async def proactive_allowed(self, friend, at):
        data = await self.read(friend)
        row = data["card"] or {}
        if row.get("proactive") == "off" or row.get("quiet_until") and row["quiet_until"] > at:
            return False
        if row.get("proactive") != "less":
            return True
        day = at.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
        count = await self.store._one(
            """WITH owned AS (SELECT DISTINCT m.room_key FROM marong.messages m JOIN marong.people p USING(user_key)
                JOIN marong.rooms r USING(room_key) WHERE p.friend_id=%s AND r.is_channel)
            SELECT count(*) AS n FROM marong.messages m WHERE m.room_key IN (SELECT room_key FROM owned)
            AND m.meta->>'proactive'='true'
            AND m.meta->>'delivered'='true' AND m.created_at>=%s""", (friend, day),
        )
        return count["n"] < 1
