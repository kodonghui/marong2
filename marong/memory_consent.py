"""Private consent cards for sensitive friend memories (SPEC-231)."""

from datetime import timedelta

from .friend_card import CardError, friend_lock
from .friend_forget import forget_locked


QUESTION = "이거 기억해 둬도 돼?"
TTL = timedelta(hours=24)
UNSENT = timedelta(minutes=2)


async def settle(conn, friend, at):
    await conn.execute("""
        UPDATE marong.chat_cards SET status='replaced'
        WHERE friend_id=%s AND kind='memory_ok' AND status='open'
            AND message_id IS NULL AND created_at<=%s
    """, (friend, at - UNSENT))
    await conn.execute("""
        UPDATE marong.chat_cards SET status='expired'
        WHERE friend_id=%s AND kind='memory_ok' AND status='open'
            AND message_id IS NOT NULL AND expires_at<=%s
    """, (friend, at))
    pending = await conn.execute("""
        SELECT m.id,coalesce(c.answer,'keep') AS answer
        FROM marong.memory_items m JOIN LATERAL (
            SELECT status,answer FROM marong.chat_cards
            WHERE friend_id=m.friend_id AND kind='memory_ok' AND sensitive=m.sensitive
                AND status IN ('answered','expired') ORDER BY id DESC LIMIT 1
        ) c ON true
        WHERE m.friend_id=%s AND m.status='pending_ok' ORDER BY m.id
    """, (friend,))
    for item in await pending.fetchall():
        if item["answer"] == "forget":
            await forget_locked(conn, friend, "item", item["id"], f"sensitive:{item['id']}", via="card")
        else:
            await conn.execute("""
                UPDATE marong.memory_items SET status='current',changed_at=%s
                WHERE friend_id=%s AND id=%s AND status='pending_ok'
            """, (at, friend, item["id"]))


async def maintain(pool, at):
    async with pool.connection() as conn:
        query = await conn.execute("""
            SELECT DISTINCT friend_id FROM (
                SELECT friend_id FROM marong.chat_cards WHERE kind='memory_ok' AND status='open'
                    AND (expires_at<=%s OR (message_id IS NULL AND created_at<=%s))
                UNION ALL
                SELECT m.friend_id FROM marong.memory_items m
                WHERE m.status='pending_ok' AND EXISTS (
                    SELECT 1 FROM marong.chat_cards c WHERE c.friend_id=m.friend_id AND c.kind='memory_ok'
                      AND c.sensitive=m.sensitive AND c.status IN ('answered','expired'))
            ) due ORDER BY friend_id LIMIT 25
        """, (at, at - UNSENT))
        friends = await query.fetchall()
    for row in friends:
        friend = row["friend_id"]
        async with friend_lock(pool, friend) as conn:
            await settle(conn, friend, at)


async def reserve(pool, friend, room, at):
    async with friend_lock(pool, friend) as conn:
        await settle(conn, friend, at)
        allowed = await conn.execute("""
            SELECT 1 FROM marong.rooms WHERE room_key=%s AND is_channel AND NOT EXISTS (
                SELECT 1 FROM marong.safety_states
                WHERE friend_id=%s AND kind='crisis' AND closed_at IS NULL)
        """, (room, friend))
        if not await allowed.fetchone():
            return None
        query = await conn.execute("""
            INSERT INTO marong.chat_cards(friend_id,kind,memory_item_id,sensitive,room_key,expires_at,created_at)
            SELECT friend_id,'memory_ok',id,sensitive,%s,%s,%s FROM marong.memory_items m
            WHERE m.friend_id=%s AND m.status='pending_ok' AND NOT EXISTS (
                SELECT 1 FROM marong.chat_cards c WHERE c.friend_id=m.friend_id AND c.kind='memory_ok'
                  AND (c.status='open' OR (c.sensitive=m.sensitive AND c.status IN ('answered','expired'))))
            ORDER BY m.id LIMIT 1 RETURNING *
        """, (room, at + TTL, at, friend))
        return await query.fetchone()


async def undelivered(pool, friend, ident):
    async with friend_lock(pool, friend) as conn:
        await conn.execute("""
            UPDATE marong.chat_cards SET status='replaced'
            WHERE friend_id=%s AND id=%s AND kind='memory_ok' AND status='open' AND message_id IS NULL
        """, (friend, ident))


async def answer(pool, friend, ident, value, *, room, via, at):
    if value not in ("keep", "forget"):
        raise CardError("invalid_input")
    async with friend_lock(pool, friend) as conn:
        if via != "screen":
            scope = " AND room_key=%s"
            params = (friend, ident, room)
        else:
            # The app and Discord present the same authenticated 1:1 conversation.
            scope = ""
            params = (friend, ident)
        query = await conn.execute("""
            SELECT * FROM marong.chat_cards WHERE friend_id=%s AND id=%s AND kind='memory_ok'
        """ + scope, params)
        row = await query.fetchone()
        if not row:
            raise CardError("card_not_found")
        applied = row["status"] == "open" and row["expires_at"] > at and row["message_id"] is not None
        if applied:
            query = await conn.execute("""
                UPDATE marong.chat_cards SET status='answered',answer=%s,answered_at=%s,answered_via=%s
                WHERE id=%s RETURNING *
            """, (value, at, via, ident))
            row = await query.fetchone()
            await settle(conn, friend, at)
        elif row["status"] != "answered" or row["answer"] != value:
            raise CardError("card_closed")
        return {"card": row, "applied": applied, "effect": "memory_kept" if value == "keep" else "memory_forgotten"}


async def reply_choice(pool, friend, room, text, at):
    choice = {"기억해": "keep", "잊어": "forget"}.get(text.strip())
    if not choice:
        return None
    async with pool.connection() as conn:
        query = await conn.execute("""
            SELECT id FROM marong.chat_cards WHERE friend_id=%s AND room_key=%s AND kind='memory_ok'
                AND status='open' AND expires_at>%s AND message_id IS NOT NULL
        """, (friend, room, at))
        row = await query.fetchone()
    if row:
        return await answer(pool, friend, row["id"], choice, room=room, via="text", at=at)
