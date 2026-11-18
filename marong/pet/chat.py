"""Owner-scoped conversation, crisis notices and reply scheduling (SPEC-327–330)."""

import asyncio
from collections import deque
from datetime import datetime, time, timedelta, timezone
import json
import re

from aiohttp import web
from psycopg.types.json import Jsonb

from ..safety import CONTEXT_PLAN, judge
from .account import require_overseas
from .http import POOL, Problem, body_json, require_member, uuid_param
from .quota import KST, _day


DELAY = timedelta(seconds=8)
SIGNAL_WINDOW = timedelta(minutes=30)
CRISIS_GAP = timedelta(days=3)
CRISIS_HELP = "자살예방상담전화 109 · 24시간"
CRISIS_URGENT = "이미 다쳤으면 119"
CLAUSES = re.compile(r"[,，;；.!?。！？\n]+\s*")
BEREAVEMENT_INTENT = re.compile(r"따라\s*가고\s*싶")
SEQ = re.compile(r"[0-9]{1,19}\Z")
COLUMNS = "id,seq,role,kind,content,composite,client_id,created_at"


def view(row):
    return {"id": str(row["id"]), "role": row["role"], "kind": row["kind"], "text": row["content"],
            "composite": row["composite"], "clientId": str(row["client_id"]) if row["client_id"] else None,
            "createdAt": row["created_at"].isoformat()}


async def owned(conn, member, pet, *, lock=False):
    cursor = await conn.execute(
        "SELECT name,status,mode,species,intro FROM pet.pets WHERE member_id=%s AND id=%s"
        + (" FOR UPDATE" if lock else ""), (member, pet),
    )
    row = await cursor.fetchone()
    if row is None:
        raise Problem("not_found")
    return row


def crisis_signal(content, nearby=()):
    direct = judge(content, nearby)
    if direct in {"plan", "injury"}:
        return direct
    *earlier, last = CLAUSES.split(content.strip().rstrip(".!?。！？"))
    if CONTEXT_PLAN.fullmatch(last):
        context = (*nearby, *earlier)
        if judge(last, context) == "plan" or any(BEREAVEMENT_INTENT.search(line) for line in context):
            return "plan"
    return None


async def same_crisis(conn, member, pet, notice, row, at):
    last_signal = notice["created_at"]
    if at - last_signal < CRISIS_GAP:
        return True
    context = deque(maxlen=5)
    # Reuse the private transcript so an episode survives worker restarts without another copy of the messages.
    async with conn.cursor("pet_crisis_history") as history:
        await history.execute("""
            SELECT content,created_at FROM pet.messages
            WHERE member_id=%s AND pet_id=%s AND role='member' AND kind='chat' AND seq<%s AND created_at>=%s
            ORDER BY seq
        """, (member, pet, row["seq"], last_signal - SIGNAL_WINDOW))
        async for previous in history:
            when = previous["created_at"]
            if when - last_signal >= CRISIS_GAP:
                return False
            nearby = [text for seen, text in context if when - seen <= SIGNAL_WINDOW]
            if when > last_signal and crisis_signal(previous["content"], nearby):
                last_signal = when
            context.append((when, previous["content"]))
    return at - last_signal < CRISIS_GAP


async def add_crisis_notice(conn, member, pet, row, at):
    signal = crisis_signal(row["content"])
    # A short follow-up can supply the plan after a separate preceding message.
    last_clause = CLAUSES.split(row["content"].strip().rstrip(".!?。！？"))[-1]
    if signal is None and CONTEXT_PLAN.fullmatch(last_clause):
        recent = await conn.execute("""
            SELECT content FROM pet.messages
            WHERE member_id=%s AND pet_id=%s AND role='member' AND kind='chat' AND seq<%s AND created_at>=%s
            ORDER BY seq DESC LIMIT 5
        """, (member, pet, row["seq"], at - SIGNAL_WINDOW))
        signal = crisis_signal(row["content"], [item["content"] for item in await recent.fetchall()])
    if signal is None:
        return
    content = CRISIS_URGENT if signal == "injury" else CRISIS_HELP
    prior = await conn.execute("""
        SELECT content,created_at FROM pet.messages
        WHERE member_id=%s AND pet_id=%s AND role='system' AND kind='crisis_notice'
        ORDER BY seq DESC LIMIT 1
    """, (member, pet))
    notice = await prior.fetchone()
    if notice and (signal != "injury" or notice["content"] == CRISIS_URGENT):
        if await same_crisis(conn, member, pet, notice, row, at):
            return
    await conn.execute("""
        INSERT INTO pet.messages(member_id,pet_id,role,kind,content,created_at)
        VALUES (%s,%s,'system','crisis_notice',%s,%s)
    """, (member, pet, content, at))


async def add_message(conn, member, pet, client, content, at):
    owner = await conn.execute("SELECT status FROM pet.members WHERE id=%s FOR UPDATE", (member,))
    profile = await owner.fetchone()
    if not profile or profile["status"] != "active":
        raise Problem("unauthenticated")
    info = await owned(conn, member, pet, lock=True)
    previous = await conn.execute(
        "SELECT " + COLUMNS + ",pet_id FROM pet.messages WHERE member_id=%s AND client_id=%s", (member, client),
    )
    duplicate = await previous.fetchone()
    if duplicate:
        if duplicate["pet_id"] != pet:
            raise Problem("invalid_input")
        return duplicate, 200
    if info["status"] == "archived":
        raise Problem("archived")
    await require_overseas(conn, member)
    day = await _day(conn, member, at)
    if day["messages"] >= 300:
        wakes = datetime.combine(day["day"] + timedelta(days=1), time(4), KST)
        raise Problem("asleep", extra={"name": info["name"], "wakesAt": wakes.isoformat()})
    rest = day["messages"] == 99 and day["rest_nudged_at"] is None
    await conn.execute("""
        UPDATE pet.member_days SET messages=messages+1,
          rest_nudged_at=CASE WHEN %s THEN %s ELSE rest_nudged_at END
        WHERE member_id=%s AND day=%s
    """, (rest, at, member, day["day"]))
    inserted = await conn.execute(
        "INSERT INTO pet.messages(member_id,pet_id,role,kind,content,client_id,created_at) "
        "VALUES (%s,%s,'member','chat',%s,%s,%s) RETURNING " + COLUMNS, (member, pet, content, client, at),
    )
    row = await inserted.fetchone()
    await add_crisis_notice(conn, member, pet, row, at)
    queued = await conn.execute("""
        SELECT id,status,ref FROM pet.jobs WHERE member_id=%s AND pet_id=%s AND kind='reply'
          AND status IN ('queued','running') ORDER BY queued_at,id LIMIT 1 FOR UPDATE
    """, (member, pet))
    pending = await queued.fetchone()
    if pending:
        ref = {**pending["ref"], "last": row["seq"], "rest": rest or pending["ref"]["rest"]}
        await conn.execute("""
            UPDATE pet.jobs SET ref=%s,status='queued',lease_until=NULL,
                run_after=CASE WHEN status='running' THEN %s ELSE run_after END WHERE id=%s
        """, (Jsonb(ref), at, pending["id"]))
    else:
        ref = {"first": row["seq"], "last": row["seq"], "rest": rest}
        await conn.execute("""
            INSERT INTO pet.jobs(kind,member_id,pet_id,ref,run_after,queued_at)
            VALUES ('reply',%s,%s,%s,%s,%s)
        """, (member, pet, Jsonb(ref), at + DELAY, at))
    return row, 201


def register(app, *, clock=lambda: datetime.now(timezone.utc)):
    async def messages(req):
        member = (await require_member(req))["id"]
        pet = uuid_param(req.match_info["id"])
        raw = req.query.get("before")
        if raw is not None and (not SEQ.fullmatch(raw) or not 0 < int(raw) <= 2**63 - 1):
            raise Problem("invalid_input")
        async with app[POOL].connection() as conn:
            await owned(conn, member, pet)
            cursor = await conn.execute(
                "SELECT " + COLUMNS + " FROM pet.messages WHERE member_id=%s AND pet_id=%s "
                "AND (%s::bigint IS NULL OR seq<%s::bigint) ORDER BY seq DESC LIMIT 51",
                (member, pet, raw, raw),
            )
            rows = await cursor.fetchall()
        return web.json_response({"items": [view(row) for row in rows[:50]],
                                  "before": str(rows[49]["seq"]) if len(rows) > 50 else None})

    async def send(req):
        member = (await require_member(req))["id"]
        pet = uuid_param(req.match_info["id"])
        data = await body_json(req)
        if set(data) != {"text", "clientId"} or not isinstance(data["text"], str):
            raise Problem("invalid_input")
        content = data["text"].strip()
        if not 1 <= len(content) <= 1000 or "\0" in content or any(0xD800 <= ord(char) <= 0xDFFF for char in content):
            raise Problem("invalid_input")
        client = uuid_param(data["clientId"])
        async with app[POOL].connection() as conn, conn.transaction():
            row, status = await add_message(conn, member, pet, client, content, clock())
        return web.json_response(view(row), status=status)

    async def events(req):
        member = (await require_member(req))["id"]
        pet = uuid_param(req.match_info["id"])
        async with app[POOL].connection() as conn:
            await owned(conn, member, pet)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store",
                                               "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff"})
        await response.prepare(req)

        async def emit(name, value):
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            await response.write(f"event: {name}\ndata: {encoded}\n\n".encode())

        since, was_typing = 0, False
        loop = asyncio.get_running_loop()
        next_ping = loop.time() + 25
        try:
            while req.transport is not None and not req.transport.is_closing():
                async with app[POOL].connection() as conn:
                    valid = await conn.execute("""
                        SELECT 1 FROM pet.sessions s JOIN pet.members m ON m.id=s.member_id
                        WHERE s.token_hash=%s AND s.member_id=%s AND m.status='active'
                          AND s.expires_at>now() AND s.absolute_expires_at>now()
                    """, (req["session_hash"], member))
                    if not await valid.fetchone():
                        break
                    order = "DESC" if not since else "ASC"
                    cursor = await conn.execute(
                        "SELECT " + COLUMNS + " FROM pet.messages WHERE member_id=%s AND pet_id=%s AND seq>%s "
                        f"ORDER BY seq {order} LIMIT 50", (member, pet, since),
                    )
                    rows = await cursor.fetchall()
                    if order == "DESC":
                        rows.reverse()
                    status = await conn.execute("""
                        SELECT EXISTS(SELECT 1 FROM pet.jobs WHERE member_id=%s AND pet_id=%s AND kind='reply'
                                      AND status='running' AND lease_until>now()) AS typing
                    """, (member, pet))
                    typing = (await status.fetchone())["typing"]
                for row in rows:
                    await emit("message", view(row))
                    since = row["seq"]
                if typing and not was_typing:
                    await emit("typing", {})
                was_typing = typing
                if loop.time() >= next_ping:
                    await emit("ping", {})
                    next_ping = loop.time() + 25
                await asyncio.sleep(2)
        except ConnectionError:
            pass
        return response

    app.router.add_get("/api/pets/{id}/messages", messages, allow_head=False)
    app.router.add_post("/api/pets/{id}/messages", send)
    app.router.add_get("/api/pets/{id}/events", events, allow_head=False)
