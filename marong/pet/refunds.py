"""Withdrawal checks and transaction-scoped fulfilment rollback (SPEC-360)."""

import asyncio
from datetime import timedelta

from .http import Problem
from .log import logger
from .quota import quota_day
from .subscriptions import current as current_subscription, finish_cancellation


async def withdrawal_denial(conn, order, at):
    product = order["product"]
    if order["status"] not in {"paid", "fulfilled"}:
        return "wrong_state", "결제가 완료된 주문만 철회할 수 있어요"
    if product in {"recharge_half", "recharge_full"}:
        return "recharge", "사면 바로 채워져서 철회할 수 없어요"
    if product == "character_creation":
        return ("used", "후보 그리기가 시작됐어요") if order["used_at"] is not None else None
    paid_at = order["paid_at"]
    if paid_at is None or at >= paid_at + timedelta(days=7):
        return "expired", "결제한 지 7일이 지났어요"
    if order["used_at"] is not None:
        return "used", "한 번 입혔어요" if order["item_kind"] == "wear" else "한 번 썼어요"
    if product == "subscription_month":
        used = await conn.execute("""
            SELECT 1 FROM pet.quota_holds WHERE member_id=%s AND status='committed' AND day BETWEEN %s AND %s
            GROUP BY day HAVING sum(units)>100 AND max(settled_at)>=%s LIMIT 1
        """, (order["member_id"], quota_day(paid_at), quota_day(at), paid_at))
        if await used.fetchone():
            return "used", "무료 한도를 넘겨 썼어요"
    return None


async def withdraw_order(conn, member, ident, gateway, at, *, revoke=None):
    """Use the same member lock as delivery, purchase and outfit updates."""
    async with conn.transaction():
        owner = await conn.execute("SELECT 1 FROM pet.members WHERE id=%s AND status='active' FOR UPDATE",
                                   (member,))
        if not await owner.fetchone():
            raise Problem("not_found")
        locked = await conn.execute("""
            SELECT o.*,i.name AS item_name,i.kind AS item_kind FROM pet.orders o LEFT JOIN pet.items i ON i.id=o.item_id
            WHERE o.id=%s AND o.member_id=%s FOR UPDATE OF o
        """, (ident, member))
        row = await locked.fetchone()
        if row is None:
            raise Problem("not_found")
        if row["status"] == "refunded":
            return row
        retry = row["status"] == "refund_pending" and row["refund_reason"] == "withdrawal"
        denial = None if retry else await withdrawal_denial(conn, row, at)
        if denial:
            reason, detail = denial
            raise Problem("withdrawal_not_allowed", extra={
                "reason": reason, "detail": f"이 주문은 철회할 수 없어요: {detail}",
            })
        if not await refund_gateway(conn, gateway, row):
            await conn.execute("""
                UPDATE pet.orders SET status='refund_pending',refund_reason='withdrawal' WHERE id=%s
            """, (row["id"],))
            if row["product"] == "subscription_month":
                await end_paid_period(conn, row, at, revoke, pending=True)
            logger.error("pet_refund_pending")
            return {**row, "status": "refund_pending"}
        if row["product"] == "item":
            await undo_item_grant(conn, row, at)
        elif row["product"] == "character_creation":
            await restore_preview(conn, row)
        elif row["product"] == "subscription_month":
            await end_paid_period(conn, row, at, revoke, pending=False)
        await conn.execute("""
            UPDATE pet.orders SET status='refunded',refund_reason='withdrawal',refunded_at=%s WHERE id=%s
        """, (at, row["id"]))
        return {**row, "status": "refunded"}


async def refund_gateway(conn, gateway, row):
    if row["free_ticket"]:
        await conn.execute("UPDATE pet.members SET free_tickets=least(20,free_tickets+1) WHERE id=%s",
                           (row["member_id"],))
        return True
    if gateway is None or not row["pg_tx_id"]:
        return False
    try:
        return await asyncio.wait_for(gateway.cancel(row["pg_tx_id"], row["amount_krw"], "withdrawal"), timeout=12)
    except Exception:
        return False


async def restore_preview(conn, row):
    member, creation = row["member_id"], row["creation_id"]
    await conn.execute("""
        UPDATE pet.creations SET state='previewed',order_id=NULL,updated_at=now()
        WHERE id=%s AND member_id=%s AND order_id=%s AND state='paid'
    """, (creation, member, row["id"]))
    await conn.execute("""
        UPDATE pet.jobs SET status='canceled',finished_at=now(),lease_until=NULL
        WHERE member_id=%s AND creation_id=%s AND kind='candidates' AND status='queued'
    """, (member, creation))


async def end_paid_period(conn, row, at, revoke, *, pending):
    member = row["member_id"]
    subscription = await current_subscription(conn, member, lock=True)
    if not subscription or subscription["status"] == "ended":
        return
    latest = await conn.execute("""
        SELECT id FROM pet.orders WHERE member_id=%s AND product='subscription_month'
          AND status IN ('paid','fulfilled','refund_pending') AND paid_at IS NOT NULL
        ORDER BY paid_at DESC,id LIMIT 1
    """, (member,))
    order = await latest.fetchone()
    if not order or order["id"] != row["id"]:
        return
    updated = await conn.execute("""
        UPDATE pet.subscriptions SET status='canceling',canceled_at=coalesce(canceled_at,%s),
          next_charge_at=NULL,retry_at=NULL,
          period_end=CASE WHEN %s THEN period_end ELSE
              greatest(period_start+interval '1 microsecond',least(period_end,%s)) END
        WHERE id=%s RETURNING *
    """, (at, pending, at, subscription["id"]))
    if not pending:
        await finish_cancellation(conn, await updated.fetchone(), at, revoke)


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
