"""Structured friend-memory lookups for an authenticated live call."""

from datetime import datetime

from marong.friend_card import KST
from marong.friend_forget import forget_intent, forget_locked, same_words


async def recall_items(conn, friend, query):
    rows = await conn.execute("""
        SELECT 'friend_memory' AS source,id::text, text AS content,heard_at AS created_at
        FROM marong.memory_items
        WHERE friend_id=%s AND status='current'
          AND (room_key IS NULL OR (sensitive IS NOT NULL AND share='self'))
          AND (valid_until IS NULL OR valid_until>=%s) AND strpos(lower(text),%s)>0
        ORDER BY heard_at DESC,id DESC LIMIT 6
    """, (friend, datetime.now(KST).date(), query))
    return await rows.fetchall()


async def forget_item(conn, p, call_id, segment, key, args):
    if not isinstance(args, dict) or set(args) - {"quote", "fragment", "item_id"} or not key:
        return {"result": "refused"}
    quote, fragment, ident = (args.get(field) for field in ("quote", "fragment", "item_id"))
    if (not isinstance(quote, str) or not 2 <= len(quote) <= 120
            or (fragment is not None and (not isinstance(fragment, str) or not 2 <= len(fragment) <= 80))
            or (ident is not None and (type(ident) is not int or not 1 <= ident < 2**63))):
        return {"result": "refused"}
    current = await conn.execute("""
        SELECT t.seq,t.content,t.finalized,t.interrupted,
               t.forgotten_at IS NULL AND t.ended_at>=now()-interval '1 minute'
                 AND NOT EXISTS (SELECT 1 FROM marong.forget_marks f
                                 WHERE f.target_type='call_turn' AND f.target_id=t.id) AS eligible
        FROM call.turns t JOIN call.calls c ON c.id=t.call_id
        WHERE t.call_id=%s AND t.segment_id=%s AND c.caller_id=%s AND t.role='user'
        ORDER BY t.seq DESC LIMIT 1
    """, (call_id, segment, p.caller_id))
    current = await current.fetchone()
    if (not current or not current["eligible"] or not current["finalized"] or current["interrupted"]
            or not forget_intent(current["content"]) or not forget_intent(quote)):
        return {"result": "refused"}
    evidence = same_words(current["content"])
    if same_words(quote) not in evidence:
        return {"result": "refused"}
    piece = same_words(fragment) if fragment else None
    if piece and (len(piece) < 2 or piece not in evidence):
        return {"result": "refused"}
    if not piece and ident is None:
        return {"result": "ask_which"}
    looked_up = None if piece else ident
    rows = await conn.execute("""
        SELECT id,text FROM marong.memory_items
        WHERE friend_id=%s AND status='current' AND (room_key IS NULL OR (sensitive IS NOT NULL AND share='self'))
          AND (%s::bigint IS NULL OR id=%s)
          AND (%s::text IS NULL OR strpos(lower(text),%s)>0 OR strpos(lower(coalesce(quote,'')),%s)>0)
        ORDER BY heard_at DESC,id DESC LIMIT 6
    """, (p.friend_id, looked_up, looked_up, piece, piece, piece))
    items = await rows.fetchall()
    if not items:
        return {"result": "none_matched"}
    if len(items) > 1:
        return {"result": "ask_which", "candidates": items[:5]}
    item = items[0]
    if ident is not None and ident != item["id"]:
        return {"result": "ask_which"}
    if not piece and same_words(item["text"]) not in evidence:
        previous = await conn.execute("""
            SELECT t.content FROM call.turns t WHERE t.call_id=%s AND t.role='assistant' AND t.seq<%s
              AND t.finalized AND NOT t.interrupted AND t.forgotten_at IS NULL
              AND NOT EXISTS (SELECT 1 FROM marong.forget_marks f WHERE f.target_type='call_turn' AND f.target_id=t.id)
            ORDER BY t.seq DESC LIMIT 1
        """, (call_id, current["seq"]))
        previous = await previous.fetchone()
        if not previous or same_words(item["text"]) not in same_words(previous["content"]):
            return {"result": "ask_which"}
    receipt = await forget_locked(conn, p.friend_id, "item", item["id"], key, via="call")
    return {"result": "forgotten", "ok": True, **receipt}
