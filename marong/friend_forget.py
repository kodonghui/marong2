"""Source-scoped deletion marks and immutable receipts for SPEC-230."""

import re
from unicodedata import normalize

from .friend_card import friend_lock


SOURCE_TABLES = {"item": "memory_items", "loop": "open_loops"}


async def forget_selected(pool, friend, kind, ident, key, *, via, group=None):
    """Resolve a selected ID and apply its source marks under the friend's lock."""
    if kind not in SOURCE_TABLES or type(ident) is not int or not 1 <= ident < 2**63:
        raise ValueError("invalid memory selection")
    if not isinstance(key, str) or not 1 <= len(key) <= 100 or via not in {"tool", "screen", "card", "call"}:
        raise ValueError("invalid forget request")
    async with friend_lock(pool, friend) as conn:
        return await forget_locked(conn, friend, kind, ident, key, via=via, group=group)


async def forget_locked(conn, friend, kind, ident, key, *, via, group=None):
    previous = await conn.execute("""
        SELECT items AS forgot,messages FROM marong.memory_forgets
        WHERE friend_id=%s AND request_key=%s
    """, (friend, key))
    if receipt := await previous.fetchone():
        return receipt

    table = SOURCE_TABLES[kind]
    # Both tables keep provenance even after the text is cleared.
    source = await conn.execute(f"""
        SELECT message_id,call_turn_id,room_key,status,
               {'heard_at' if kind == 'item' else 'opened_at'} AS heard_at
        FROM marong.{table} WHERE friend_id=%s AND id=%s
    """, (friend, ident))
    row = await source.fetchone()
    if not row or (group is not None and row["room_key"] != group):
        return None
    if row["status"] == "forgotten":
        await remember(conn, friend, key, via, 0, 0)
        return {"forgot": 0, "messages": 0}

    return await forget_source_locked(conn, friend, row["message_id"], row["call_turn_id"], row["heard_at"], key, via)


async def forget_source_locked(conn, friend, message, turn, heard_at, key, via):
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                       (f"forget:{'message' if message is not None else 'call_turn'}:{message or turn}",))
    ids = await affected(conn, friend, message, turn)
    count = len(ids["item"]) + len(ids["loop"])
    mark = await conn.execute("""
        SELECT 1 FROM marong.forget_marks WHERE
            (target_type='message' AND target_id=%s) OR (target_type='call_turn' AND target_id=%s)
    """, (message, turn))
    messages = int(await mark.fetchone() is None)
    forget_id = await remember(conn, friend, key, via, count, messages)

    if message is not None:
        await add_source_mark(conn, forget_id, friend, "message", message)
        marks = await conn.execute("""
            INSERT INTO marong.forget_marks AS mark(forget_id,friend_id,target_type,target_id,state)
            SELECT %s,%s,'summary',s.id,'hidden'
            FROM marong.summaries s JOIN marong.messages m
              ON m.id=%s AND m.id BETWEEN s.first_id AND s.last_id
              AND (s.room_key=m.room_key OR s.meta->'rooms' ? m.room_key)
            ORDER BY s.id
            ON CONFLICT(target_type,target_id) DO UPDATE
              SET forget_id=excluded.forget_id,state='hidden',replacement=NULL,attempts=0,
                  updated_at=now()
              WHERE mark.state IN ('hidden','rewritten')
            RETURNING target_id
        """, (forget_id, friend, message))
        for mark in sorted(await marks.fetchall(), key=lambda row: row["target_id"]):
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                               (f"forget:summary:{mark['target_id']}",))
    else:
        await add_source_mark(conn, forget_id, friend, "call_turn", turn)

    await hide_notes(conn, forget_id, friend, heard_at)
    await conn.execute("""
        UPDATE marong.memory_items SET status='forgotten',text=NULL,quote=NULL,forget_id=%s,changed_at=now()
        WHERE id=ANY(%s::bigint[])
    """, (forget_id, ids["item"]))
    await conn.execute("""
        UPDATE marong.open_loops SET status='forgotten',text=NULL,quote=NULL,forget_id=%s,
            closed_at=coalesce(closed_at,now()) WHERE id=ANY(%s::bigint[])
    """, (forget_id, ids["loop"]))
    await conn.execute("""
        UPDATE marong.chat_cards SET status='replaced'
        WHERE memory_item_id=ANY(%s::bigint[]) AND status='open'
    """, (ids["item"],))
    await conn.execute("SELECT marong.forget_embeddings(%s)", (forget_id,))
    return {"forgot": count, "messages": messages}


async def affected(conn, friend, message, turn):
    ids = {}
    for kind, table in SOURCE_TABLES.items():
        cur = await conn.execute(f"""
            SELECT id FROM marong.{table} WHERE friend_id=%s AND status<>'forgotten'
              AND (message_id=%s OR call_turn_id=%s) ORDER BY id
        """, (friend, message, turn))
        ids[kind] = [row["id"] for row in await cur.fetchall()]
    return ids


async def remember(conn, friend, key, via, items, messages):
    cur = await conn.execute("""
        INSERT INTO marong.memory_forgets(friend_id,request_key,via,items,messages)
        VALUES (%s,%s,%s,%s,%s) RETURNING id
    """, (friend, key, via, items, messages))
    return (await cur.fetchone())["id"]


async def add_source_mark(conn, forget_id, friend, kind, ident):
    await conn.execute("""
        INSERT INTO marong.forget_marks(forget_id,friend_id,target_type,target_id,state)
        VALUES (%s,%s,%s,%s,'forgotten') ON CONFLICT(target_type,target_id) DO NOTHING
    """, (forget_id, friend, kind, ident))


async def hide_notes(conn, forget_id, friend, heard_at):
    await conn.execute("""
        INSERT INTO marong.forget_marks AS mark(forget_id,friend_id,target_type,target_id,state)
        SELECT %s,%s,'note',n.id,'hidden' FROM marong.notes n JOIN marong.people p USING(user_key)
        WHERE p.friend_id=%s AND n.created_at>=%s
        UNION ALL
        SELECT %s,%s,'shared_note',n.id,'hidden' FROM marong.shared_notes n
        WHERE n.friend_id=%s AND n.created_at>=%s
        ORDER BY 3,4
        ON CONFLICT(target_type,target_id) DO UPDATE
            SET forget_id=excluded.forget_id,attempts=0,updated_at=now()
            WHERE mark.state='hidden'
    """, (forget_id, friend, friend, heard_at, forget_id, friend, friend, heard_at))

FORGET_TOOL = {
    "name": "memory_forget",
    "description": ("지금 말한 친구가 자기 기억을 직접 잊으라고 요청했을 때만 써. "
                    "원문 인용과 기억 id 또는 친구가 말한 찾을 조각을 넣어. "
                    "그 말 원문만 잊으라고 명확히 요청했으면 source_only를 써. "
                    "ask_which면 하나를 다시 짚고, ok가 오기 전에 잊었다고 말하지 마."),
    "input_schema": {
        "type": "object", "required": ["quote"], "additionalProperties": False,
        "properties": {
            "quote": {"type": "string", "minLength": 2, "maxLength": 120},
            "fragment": {"type": "string", "minLength": 2, "maxLength": 80},
            "item_id": {"type": "integer", "minimum": 1},
            "source_only": {"type": "boolean"},
        },
    },
}
DIRECTIVE = re.compile(r"(?:잊어\s*(?:줘|줄래|주라|버려)?|기억하지\s*마|지워\s*(?:줘|줄래|주라)|기억에서\s*빼\s*줘)[.!?~ ]*$")


def same_words(text):
    return " ".join(normalize("NFKC", text).casefold().split())


def forget_intent(text):
    return bool(DIRECTIVE.search(same_words(text)))


async def request_tool(pool, friend, room, message_id, request_key, args):
    """Validate the current speaker and quoted request before touching any memory."""
    key = f"tool:{message_id}:{request_key}"
    if not isinstance(request_key, str) or not request_key or len(key) > 100:
        return {"status": "refused"}
    async with friend_lock(pool, friend) as conn:
        current = await conn.execute("""
            SELECT m.content,r.is_channel FROM marong.messages m JOIN marong.people p USING(user_key)
            JOIN marong.rooms r USING(room_key)
            WHERE m.id=%s AND m.room_key=%s AND m.role='user' AND p.friend_id=%s
        """, (message_id, room, friend))
        speaker = await current.fetchone()
        prior = await conn.execute("""
            SELECT outcome FROM marong.persona_tool_calls WHERE friend_id=%s AND request_key=%s
        """, (friend, key))
        prior = await prior.fetchone()
        if prior:
            if prior["outcome"] == "ok":
                receipt = await conn.execute("""
                    SELECT items AS forgot,messages FROM marong.memory_forgets WHERE friend_id=%s AND request_key=%s
                """, (friend, key))
                return {"status": "ok", **await receipt.fetchone()}
            return {"status": prior["outcome"]}

        outcome, why, target, result = "refused", "not_speaker", None, {}
        if speaker:
            outcome, why, target, result = await resolve_request(
                conn, friend, room, message_id, key, speaker, args)
        length = len(args.get("quote", "")) if isinstance(args, dict) and isinstance(args.get("quote"), str) else 0
        await conn.execute("""
            INSERT INTO marong.persona_tool_calls(friend_id,room_key,message_id,tool,request_key,outcome,why,
                                                 target_type,target_id,arg_chars)
            VALUES (%s,%s,%s,'memory_forget',%s,%s,%s,%s,%s,%s)
        """, (friend, room, message_id if speaker else None, key, outcome, why,
              "memory_item" if target else None, target, min(length, 32767)))
        return {"status": outcome, **result}


async def resolve_request(conn, friend, room, message, key, speaker, args):
    if not isinstance(args, dict) or set(args) - {"quote", "fragment", "item_id", "source_only"}:
        return "invalid", None, None, {}
    quote, fragment, target, original = (args.get(key) for key in ("quote", "fragment", "item_id", "source_only"))
    if (not isinstance(quote, str) or not 2 <= len(quote) <= 120
            or (fragment is not None and (not isinstance(fragment, str) or not 2 <= len(fragment) <= 80))
            or (target is not None and (type(target) is not int or not 1 <= target < 2**63))
            or (original is not None and type(original) is not bool) or (original and target is not None)):
        return "invalid", None, None, {}
    evidence = same_words(speaker["content"])
    quoted = same_words(quote)
    if not forget_intent(evidence) or not quoted or quoted not in evidence or not forget_intent(quoted):
        return "refused", "quote_missing", None, {}
    fragment = same_words(fragment) if fragment else None
    if fragment and (len(fragment) < 2 or fragment not in evidence):
        return "refused", "quote_missing", None, {}
    if original:
        if (not speaker["is_channel"] or not fragment or len(fragment) < 4
                or not re.search(r"원문|메시지|그 말|그 문장|내가 한 말", evidence)):
            return "refused", "group_room" if not speaker["is_channel"] else "quote_missing", None, {}
        prior = await conn.execute("""
            SELECT m.id,m.created_at,m.content FROM marong.messages m JOIN marong.people p USING(user_key)
            WHERE m.room_key=%s AND p.friend_id=%s AND m.role='user' AND m.id<%s
                AND strpos(lower(m.content),%s)>0
                AND NOT EXISTS (SELECT 1 FROM marong.forget_marks f WHERE f.target_type='message' AND f.target_id=m.id)
            ORDER BY m.id DESC LIMIT 31
        """, (room, friend, message, fragment))
        recent = await prior.fetchall()
        if len(recent) > 30:
            return "ask_which", None, None, {}
        matches = [row for row in recent if not forget_intent(row["content"])]
        if len(matches) != 1:
            return ("ask_which" if matches else "none_matched"), None, None, {}
        source = matches[0]
        receipt = await forget_source_locked(conn, friend, source["id"], None, source["created_at"], key, "tool")
        return "ok", None, None, receipt

    if not fragment and target is None:
        return "ask_which", None, None, {}
    scope = "" if speaker["is_channel"] else " AND room_key=%s AND share='known' AND sensitive IS NULL"
    looked_up = None if fragment else target
    params = (friend, looked_up, looked_up, fragment, fragment, fragment)
    if scope:
        params += (room,)
    matches = await conn.execute("""
        SELECT id,text FROM marong.memory_items
        WHERE friend_id=%s AND status='current'
          AND (%s::bigint IS NULL OR id=%s)
          AND (%s::text IS NULL OR strpos(lower(text),%s)>0 OR strpos(lower(coalesce(quote,'')),%s)>0)
    """ + scope + " ORDER BY heard_at DESC,id DESC LIMIT 6", params)
    rows = await matches.fetchall()
    if len(rows) > 1:
        return "ask_which", None, None, {"candidates": rows[:5]}
    if not rows:
        return "none_matched", None, None, {}
    item = rows[0]
    if target is not None and target != item["id"]:
        return "ask_which", None, None, {}
    if not fragment and same_words(item["text"]) not in evidence:
        # A bare model-generated id needs a recent answer that actually named this item.
        prev = await conn.execute("""
            SELECT content FROM marong.messages WHERE room_key=%s AND id<%s AND role='assistant'
                AND meta->>'delivered'='true' ORDER BY id DESC LIMIT 1
        """, (room, message))
        previous = await prev.fetchone()
        if not previous or same_words(item["text"]) not in same_words(previous["content"]):
            return "ask_which", None, None, {}
    result = await forget_locked(conn, friend, "item", item["id"], key, via="tool",
                                 group=None if speaker["is_channel"] else room)
    return "ok", None, item["id"], result
