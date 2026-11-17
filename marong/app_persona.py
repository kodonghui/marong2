"""App chat endpoints for the first stage of the friend card (API-127–130, API-136)."""

from collections import defaultdict, deque
from datetime import datetime, timezone
import math
from uuid import uuid4
from pathlib import Path
import re

from aiohttp import web

from .app_chat import Problem, bad
from .friend_card import CardError, ModelRun, card_sentence, choices
from .persona_instructions import LIMIT, InterpretationError, interpret
from .style import check as check_style

BASE = "/chat/persona/api"
STATIC = Path(__file__).with_name("app_chat_static") / "persona"
VALUES = ("support", "advice", "honesty")


def serialize_question(row, at):
    status = row["status"]
    if status == "open" and row["expires_at"] <= at:
        status = "expired"
    return {"id": row["id"], "kind": row["kind"], "step": row["step"], "status": status, "answer": row["answer"],
            "expiresAt": row["expires_at"].isoformat(),
            "options": [{"value": value, "label": label} for value, label in choices(row)]}


class AppPersona:
    def __init__(self, chat):
        self.chat = chat
        self.writes = defaultdict(deque)

    @property
    def cards(self):
        return getattr(self.chat.agent, "friend_cards", None)

    async def page(self, req):
        await self._who(req)
        name = req.match_info.get("asset")
        if name is None:
            name = "instructions.html" if req.path.endswith("instructions") else "index.html"
        if name not in ("index.html", "instructions.html", "persona.css", "persona.js"):
            raise web.HTTPNotFound()
        return web.FileResponse(STATIC / name)

    async def _who(self, req, *, write=False):
        try:
            who = await self.chat._who(req, write=write)
        except Problem as error:
            if error.code == "no_dm":
                raise Problem("not_allowed") from None
            raise
        if not self.cards:
            raise Problem("feature_off")
        return who

    async def _view(self, friend):
        data = await self.cards.read(friend)
        card = data["card"] or {}
        now = datetime.now(timezone.utc)
        until = card.get("want_until")
        values = {key: card.get(key) for key in VALUES}
        state = card.get("state", "none")
        if state in ("none", "asking"):
            answered = await self.cards.store._all(
                """SELECT step,answer FROM marong.chat_cards WHERE friend_id=%s AND kind='card_question'
                AND status IN ('open','answered') ORDER BY id""", (friend,),
            )
            if answered:
                state = "asking"
                values.update({VALUES[row["step"] - 1]: row["answer"] for row in answered})
        return {"state": state, "values": {**values, "lead": card.get("lead") or "follow"},
                "proactive": card.get("proactive") or "normal", "callFirst": data["call_first"],
                "sentence": card_sentence(card), "source": card.get("source"),
                "setAt": card["set_at"].isoformat() if card.get("set_at") else None,
                "want": {"value": card["want"], "until": until.isoformat()} if until and until > now else None,
                "rules": [{key: rule[key] for key in ("id", "kind", "text")} for rule in data["rules"]], "ruleMax": 20}

    async def get_card(self, req):
        who = await self._who(req)
        return self.chat._json(200, await self._view(who["friend_id"]))

    async def patch_card(self, req):
        who = await self._who(req, write=True)
        changes = await self.chat._body(req)
        try:
            await self.cards.update_from_screen(who["friend_id"], changes)
        except CardError as error:
            code = str(error)
            if code == "requires_three":
                raise bad(*[(field, "required") for field in VALUES if field not in changes]) from None
            raise Problem(code) from None
        return self.chat._json(200, await self._view(who["friend_id"]))

    async def add_rule(self, req):
        who = await self._who(req, write=True)
        body = await self.chat._body(req)
        if set(body) != {"kind", "text"}:
            raise bad(("body", "bad_format"))
        applied, added = await self.cards.add_rule(who["friend_id"], body["kind"], body["text"])
        if applied.why == "limit":
            raise Problem("rule_limit")
        if applied.outcome != "ok":
            raise bad(("text", "bad_format"))
        rule = await self.cards.get_rule(who["friend_id"], applied.target_id)
        if not rule:
            raise Problem("not_found")
        return self.chat._json(201 if added else 200, rule)

    async def remove_rule(self, req):
        who = await self._who(req, write=True)
        id = self.chat._number(req.match_info["ruleId"], "ruleId", minimum=1, required=True)
        if not await self.cards.remove_rule(who["friend_id"], id):
            raise Problem("not_found")
        return web.Response(status=204)

    async def _instruction_view(self, friend):
        row = await self.cards.store._one("""SELECT text,understood,polite,version,updated_at
            FROM marong.custom_instructions WHERE friend_id=%s""", (friend,))
        return {"text": row["text"] if row else None, "understood": row["understood"] if row else None,
                "polite": row["polite"] if row else False, "version": row["version"] if row else 0,
                "updatedAt": row["updated_at"].isoformat() if row else None, "max": LIMIT}

    async def get_instruction(self, req):
        who = await self._who(req)
        return self.chat._json(200, await self._instruction_view(who["friend_id"]))

    async def put_instruction(self, req):
        who = await self._who(req, write=True)
        body = await self.chat._body(req)
        if set(body) != {"text"} or not isinstance(body["text"], str) or not 1 <= len(body["text"].strip()) <= LIMIT:
            raise bad(("text", "bad_format"))
        text = body["text"].strip()
        friend = who["friend_id"]
        clock = self.chat.clock
        sent = self.writes[friend]
        began = clock()
        while sent and began - sent[0] >= 60:
            sent.popleft()
        if len(sent) >= 5:
            raise Problem("too_many_requests", headers={"Retry-After": str(max(1, math.ceil(60 - (began-sent[0]))))})
        sent.append(began)
        now = datetime.now(timezone.utc)
        agent = self.chat.agent
        model = agent.s.anthropic_model
        try:
            parsed = await interpret(agent.llm, model, text)
            reviewed = check_style(parsed["understood"], code_only=True)
            parsed["understood"] = reviewed.text
            if re.search(r"[ㅋㅎ]+|(?<![가-힣])야[!,.?\s]", parsed["understood"]):
                raise InterpretationError("invalid tone")
            moved = await self.cards.save_interpretation(friend, text, parsed, via="screen")
        except (InterpretationError, CardError) as error:
            await self.cards.record_run(ModelRun("instruction", uuid4().hex, model, "instruction-v1", now,
                                                 "invalid", friend_id=friend,
                                                 total_ms=round((clock()-began)*1000), error_code=type(error).__name__))
            raise Problem("ai_unavailable") from None
        await self.cards.record_run(ModelRun("instruction", uuid4().hex, model, "instruction-v1", now, "ok",
                                             friend_id=friend, total_ms=round((clock()-began)*1000)))
        reasons = parsed["reasons"]
        asked = False
        if "raise" in reasons:
            outcome, _ = await self.cards.store.add_request(who["user_key"], who["room_key"], "proactive_more", "", "")
            asked = outcome == "ok"
        cannot = []
        if "safety" in reasons:
            cannot.append("위험할 때 하는 말은 바꿀 수 없어.")
        if "fact" in reasons:
            cannot.append("사실과 다른 맞장구는 못 해.")
        return self.chat._json(200, {"instructions": await self._instruction_view(friend), "moved": moved,
                                     "ownerAsked": asked, "cannot": " ".join(cannot) or None})

    async def clear_instruction(self, req):
        who = await self._who(req, write=True)
        if (await self._instruction_view(who["friend_id"]))["text"] is not None:
            await self.cards.write_instruction(who["friend_id"], None)
        return web.Response(status=204)

    async def answer(self, req):
        who = await self._who(req, write=True)
        id = self.chat._number(req.match_info["cardId"], "cardId", minimum=1, required=True)
        body = await self.chat._body(req)
        if set(body) != {"value"} or not isinstance(body["value"], str):
            raise bad(("value", "bad_format"))
        now = datetime.now(timezone.utc)
        try:
            row = await self.cards.store._one("""SELECT id,kind FROM marong.chat_cards
                WHERE friend_id=%s AND id=%s AND kind IN ('card_question','card_draft','ask_support')""", (who["friend_id"], id))
            if not row:
                raise CardError("card_not_found")
            result = await self.cards.answer_card(who["friend_id"], row, body["value"], room=who["room_key"],
                                                      via="screen", at=now, publish_message=True)
        except CardError as error:
            code = str(error)
            if code == "invalid_input":
                raise bad(("value", "not_an_option")) from None
            raise Problem("not_found" if code == "card_not_found" else code) from None
        if result["applied"]:
            self.chat.pulse()
        return self.chat._json(200, {"card": serialize_question(result["card"], now), "effect": result["effect"],
                                     "sentence": result.get("sentence")})

    async def messages(self, who, rows):
        messages = [self.chat.message(row) for row in rows]
        if not self.cards or not rows:
            return messages
        cards = await self.cards.store._all(
            """SELECT * FROM marong.chat_cards WHERE friend_id=%s AND room_key=%s
            AND kind IN ('card_question','card_draft','ask_support') AND message_id=ANY(%s::bigint[])""",
            (who["friend_id"], who["room_key"], [row["id"] for row in rows]),
        )
        by_id = {row["message_id"]: row for row in cards}
        now = datetime.now(timezone.utc)
        for message, row in zip(messages, rows, strict=True):
            card = by_id.get(row["id"])
            if card:
                message["card"] = serialize_question(card, now)
        return messages

    def register(self, app):
        app.router.add_get("/chat/persona/", self.page)
        app.router.add_get("/chat/persona/instructions", self.page)
        app.router.add_get(r"/chat/persona/{asset:persona\.(?:css|js)}", self.page)
        app.router.add_get(BASE + "/card", self.get_card)
        app.router.add_patch(BASE + "/card", self.patch_card)
        app.router.add_post(BASE + "/rules", self.add_rule)
        app.router.add_delete(BASE + "/rules/{ruleId}", self.remove_rule)
        app.router.add_get(BASE + "/instructions", self.get_instruction)
        app.router.add_put(BASE + "/instructions", self.put_instruction)
        app.router.add_delete(BASE + "/instructions", self.clear_instruction)
        app.router.add_post(BASE + "/cards/{cardId}/answer", self.answer)
