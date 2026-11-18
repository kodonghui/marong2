"""Source-scoped deletion marks and immutable receipts for SPEC-230."""

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
    message, turn = row["message_id"], row["call_turn_id"]
    if row["status"] == "forgotten":
        await remember(conn, friend, key, via, 0, 0)
        return {"forgot": 0, "messages": 0}

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
        await conn.execute("""
            INSERT INTO marong.forget_marks AS mark(forget_id,friend_id,target_type,target_id,state)
            SELECT %s,%s,'summary',s.id,'hidden'
            FROM marong.summaries s JOIN marong.messages m
              ON m.id=%s AND m.id BETWEEN s.first_id AND s.last_id
              AND (s.room_key=m.room_key OR s.meta->'rooms' ? m.room_key)
            ON CONFLICT(target_type,target_id) DO UPDATE
              SET forget_id=excluded.forget_id,state='hidden',replacement=NULL,attempts=0,
                  updated_at=now()
              WHERE mark.state='rewritten'
        """, (forget_id, friend, message))
    else:
        await add_source_mark(conn, forget_id, friend, "call_turn", turn)

    await hide_notes(conn, forget_id, friend, row["heard_at"])
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
        INSERT INTO marong.forget_marks(forget_id,friend_id,target_type,target_id,state)
        SELECT %s,%s,'note',n.id,'hidden' FROM marong.notes n JOIN marong.people p USING(user_key)
        WHERE p.friend_id=%s AND n.created_at>=%s
        UNION ALL
        SELECT %s,%s,'shared_note',n.id,'hidden' FROM marong.shared_notes n
        WHERE n.friend_id=%s AND n.created_at>=%s
        ON CONFLICT(target_type,target_id) DO NOTHING
    """, (forget_id, friend, friend, heard_at, forget_id, friend, friend, heard_at))
