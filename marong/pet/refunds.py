"""Payment cancellation and restoration of unused item orders (SPEC-360)."""

import asyncio
from datetime import timedelta

from .http import Problem
from .log import logger


def item_withdrawal_denial(order, at):
    if order["status"] not in {"paid", "fulfilled"}:
        return "wrong_state", "결제가 완료된 주문만 철회할 수 있어요"
    if order["paid_at"] is None or at >= order["paid_at"] + timedelta(days=7):
        return "expired", "결제한 지 7일이 지났어요"
    if order["used_at"] is not None:
        return "used", "한 번 입혔어요" if order["item_kind"] == "wear" else "한 번 썼어요"
    return None


async def refund_item(conn, member, ident, gateway, at):
    """Use the same member lock as delivery, purchase and outfit updates."""
    async with conn.transaction():
        owner = await conn.execute("SELECT 1 FROM pet.members WHERE id=%s AND status='active' FOR UPDATE",
                                   (member,))
        if not await owner.fetchone():
            raise Problem("not_found")
        locked = await conn.execute("""
            SELECT o.*,i.name AS item_name,i.kind AS item_kind FROM pet.orders o JOIN pet.items i ON i.id=o.item_id
            WHERE o.id=%s AND o.member_id=%s AND o.product='item' FOR UPDATE OF o
        """, (ident, member))
        row = await locked.fetchone()
        if row is None:
            raise Problem("not_found")
        if row["status"] == "refunded":
            return row
        retry = row["status"] == "refund_pending" and row["refund_reason"] == "withdrawal"
        denial = None if retry else item_withdrawal_denial(row, at)
        if denial:
            reason, detail = denial
            raise Problem("withdrawal_not_allowed", extra={
                "reason": reason, "detail": f"이 주문은 철회할 수 없어요: {detail}",
            })
        try:
            paid = gateway is not None and row["pg_tx_id"] and await asyncio.wait_for(
                gateway.cancel(row["pg_tx_id"], row["amount_krw"], "withdrawal"), timeout=12,
            )
        except Exception:
            paid = False
        if not paid:
            await conn.execute("""
                UPDATE pet.orders SET status='refund_pending',refund_reason='withdrawal' WHERE id=%s
            """, (row["id"],))
            logger.warning("pet_refund_pending")
            return {**row, "status": "refund_pending"}
        await undo_item_grant(conn, row, at)
        await conn.execute("""
            UPDATE pet.orders SET status='refunded',refund_reason='withdrawal',refunded_at=%s WHERE id=%s
        """, (at, row["id"]))
        return {**row, "status": "refunded"}


async def undo_item_grant(conn, row, at):
    member, order = row["member_id"], row["id"]
    cursor = await conn.execute("""
        UPDATE pet.inventory SET withdrawn_at=%s
        WHERE member_id=%s AND order_id=%s AND withdrawn_at IS NULL RETURNING item_id
    """, (at, member, order))
    items = [entry["item_id"] for entry in await cursor.fetchall()]
    if not items:
        return
    await conn.execute("""
        UPDATE pet.decor d SET
            head_item=CASE WHEN head_item=ANY(%(items)s::uuid[]) THEN NULL ELSE head_item END,
            body_item=CASE WHEN body_item=ANY(%(items)s::uuid[]) THEN NULL ELSE body_item END,
            neck_item=CASE WHEN neck_item=ANY(%(items)s::uuid[]) THEN NULL ELSE neck_item END,
            theme_item=CASE WHEN theme_item=ANY(%(items)s::uuid[]) THEN NULL ELSE theme_item END,
            font_item=CASE WHEN font_item=ANY(%(items)s::uuid[]) THEN NULL ELSE font_item END,
            updated_at=%(at)s
        FROM pet.pets p WHERE p.id=d.pet_id AND p.member_id=%(member)s
          AND ARRAY[head_item,body_item,neck_item,theme_item,font_item] && %(items)s::uuid[]
    """, {"items": items, "member": member, "at": at})
