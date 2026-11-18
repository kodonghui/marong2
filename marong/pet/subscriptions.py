"""Member subscription view, scheduled cancellation, and price consent (SPEC-359)."""

import asyncio
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from aiohttp import web

from .http import POOL, Problem, require_member
from .log import logger
from .push import notify_price_change
from .quota import KST, _day

MONTHLY_PRICE_KRW = 9900
RENEWAL_RULE = "2026-11-renewal"


class PriceChangeError(ValueError):
    pass


def view(row):
    if row is None:
        return {"status": "none", "priceKrw": MONTHLY_PRICE_KRW, "periodEnd": None,
                "nextChargeAt": None, "newPrice": None}
    price = None
    if row["status"] == "active" and row["new_price_from"] is not None:
        price = {"priceKrw": row["new_price_krw"], "from": row["new_price_from"].isoformat(),
                 "agreed": row["new_price_agreed_at"] is not None}
    return {"status": row["status"], "priceKrw": row["price_krw"],
            "periodEnd": row["period_end"].isoformat(), "newPrice": price,
            "nextChargeAt": row["next_charge_at"].isoformat() if row["next_charge_at"] else None}


async def current(conn, member, *, lock=False):
    cursor = await conn.execute("""
        SELECT * FROM pet.subscriptions WHERE member_id=%s
        ORDER BY (status<>'ended') DESC,period_end DESC,id LIMIT 1
        """ + (" FOR UPDATE" if lock else ""), (member,))
    return await cursor.fetchone()


async def active_owner(conn, member):
    cursor = await conn.execute("SELECT 1 FROM pet.members WHERE id=%s AND status='active' FOR UPDATE", (member,))
    if not await cursor.fetchone():
        raise Problem("unauthenticated")


def next_period(start):
    local = start.astimezone(KST)
    year, month = local.year + (local.month == 12), local.month % 12 + 1
    end = local.replace(year=year, month=month, day=min(local.day, monthrange(year, month)[1]))
    charge = end.replace(hour=9, minute=0, second=0, microsecond=0)
    return end, charge


async def activate_paid(conn, order, encrypted_key, at):
    """Activate a verified first payment and its quota inside the caller's transaction."""
    if order["product"] != "subscription_month" or not isinstance(encrypted_key, bytes) or not encrypted_key:
        raise Problem("wrong_state")
    member = order["member_id"]
    await active_owner(conn, member)
    prior = await current(conn, member, lock=True)
    if prior and prior["first_order_id"] == order["id"]:
        return prior
    if prior and prior["status"] != "ended":
        raise Problem("already_subscribed")
    end, charge = next_period(at)
    cursor = await conn.execute("""
        INSERT INTO pet.subscriptions(member_id,status,billing_key_enc,price_krw,first_order_id,
                                      period_start,period_end,next_charge_at)
        VALUES (%s,'active',%s,%s,%s,%s,%s,%s) RETURNING *
    """, (member, encrypted_key, order["amount_krw"], order["id"], at, end, charge))
    subscription = await cursor.fetchone()
    await _day(conn, member, at)
    return subscription


def renewal_due(row, at):
    scheduled = row["retry_at"] or row["next_charge_at"]
    return (row["status"] == "active" and row["billing_key_enc"] is not None
            and row["next_charge_at"] is not None and scheduled <= at)


async def cancel_renewal(conn, row, at, revoke, *, end_now=False):
    cursor = await conn.execute("""
        UPDATE pet.subscriptions SET status='canceling',canceled_at=%s,next_charge_at=NULL,retry_at=NULL,
          period_end=CASE WHEN %s THEN greatest(period_start+interval '1 microsecond',least(period_end,%s))
                   ELSE period_end END
        WHERE id=%s RETURNING *
    """, (at, end_now, at, row["id"]))
    return await finish_cancellation(conn, await cursor.fetchone(), at, revoke)


async def reserve_renewal(pool, member, at, revoke):
    from .billing import insert_order, orders

    async with pool.connection() as conn, conn.transaction():
        await active_owner(conn, member)
        row = await current(conn, member, lock=True)
        today = at.astimezone(KST).date()
        if (row and row["status"] == "active" and row["new_price_from"] is not None
                and row["new_price_agreed_at"] is None and row["new_price_from"] <= today):
            await cancel_renewal(conn, row, at, revoke, end_now=True)
            return None
        if not row or not renewal_due(row, at):
            return None
        scheduled = row["next_charge_at"].astimezone(KST).date()
        changed_price = row["new_price_from"] is not None and row["new_price_from"] <= scheduled
        if changed_price and row["new_price_agreed_at"] is None:
            await cancel_renewal(conn, row, at, revoke, end_now=True)
            return None
        target = f"marong-pet/renewal/{row['id']}/{row['period_end'].astimezone(KST).date()}"
        key = uuid5(NAMESPACE_URL, target)
        cursor = await orders(conn, "o.member_id=%s AND o.idempotency_key=%s", (member, key))
        invoice = await cursor.fetchone()
        if invoice is None:
            amount = row["new_price_krw"] if changed_price else row["price_krw"]
            invoice = await insert_order(conn, member, "subscription_month", None, key, at,
                                         amount=amount, item_name=None)
            await conn.execute("UPDATE pet.orders SET withdrawal_rule=%s WHERE id=%s",
                               (RENEWAL_RULE, invoice["id"]))
        return row["id"], row["period_end"], invoice


async def renew_one(pool, member, at, gateway, revoke):
    # Commit the invoice first so retries use the same order number with the gateway.
    reserved = await reserve_renewal(pool, member, at, revoke)
    if reserved is None:
        return False
    subscription, old_end, invoice = reserved
    async with pool.connection() as conn, conn.transaction():
        await active_owner(conn, member)
        row = await current(conn, member, lock=True)
        if (invoice["status"] != "created" or not row or row["id"] != subscription or row["period_end"] != old_end
                or not renewal_due(row, at)):
            return False
        amount = invoice["amount_krw"]
        try:
            payment = await asyncio.wait_for(
                gateway.charge(row["billing_key_enc"], invoice["order_no"], amount), timeout=12,
            )
        except Exception:
            payment = None
        if not payment or not payment.paid or payment.order_no != invoice["order_no"] or payment.amount != amount:
            if row["retry_at"] is None:
                await conn.execute("UPDATE pet.subscriptions SET retry_at=%s WHERE id=%s",
                                   (at + timedelta(days=1), subscription))
            else:
                if payment is not None and not payment.paid:
                    await conn.execute("UPDATE pet.orders SET status='failed' WHERE id=%s", (invoice["id"],))
                else:
                    logger.warning("pet_renewal_unconfirmed")
                await cancel_renewal(conn, row, at, revoke)
            return False
        end, charge = next_period(old_end)
        scheduled = row["next_charge_at"].astimezone(KST).date()
        new_applied = row["new_price_from"] is not None and row["new_price_from"] <= scheduled
        await conn.execute("""
            UPDATE pet.subscriptions SET period_start=least(%s,period_end),period_end=%s,next_charge_at=%s,
              retry_at=NULL,price_krw=%s,new_price_krw=CASE WHEN %s THEN NULL ELSE new_price_krw END,
              new_price_from=CASE WHEN %s THEN NULL ELSE new_price_from END,
              new_price_agreed_at=CASE WHEN %s THEN NULL ELSE new_price_agreed_at END WHERE id=%s
        """, (at, end, charge, amount, new_applied, new_applied, new_applied, subscription))
        await conn.execute("""
            UPDATE pet.orders SET status='fulfilled',paid_at=%s,fulfilled_at=%s,pg_tx_id=%s WHERE id=%s
        """, (at, at, payment.transaction, invoice["id"]))
        await _day(conn, member, at)
        return True


async def apply_price_consent(conn, member, at):
    await active_owner(conn, member)
    row = await current(conn, member, lock=True)
    if (row is None or row["status"] != "active" or row["new_price_from"] is None
            or at.astimezone(KST).date() >= row["new_price_from"]):
        raise Problem("wrong_state")
    cursor = await conn.execute("""
        UPDATE pet.subscriptions SET new_price_agreed_at=coalesce(new_price_agreed_at,%s)
        WHERE id=%s RETURNING *
    """, (at, row["id"]))
    return await cursor.fetchone()


async def announce_price(pool, amount, day, at, send=None):
    if not 1 <= amount <= 100_000:
        raise PriceChangeError("invalid_subscription_price")
    if day < at.astimezone(KST).date() + timedelta(days=30):
        raise PriceChangeError("price_notice_too_soon")
    async with pool.connection() as conn, conn.transaction():
        cursor = await conn.execute("""
            UPDATE pet.subscriptions s SET new_price_krw=%s,new_price_from=%s,new_price_agreed_at=NULL
            FROM pet.members m WHERE s.member_id=m.id AND m.status='active' AND s.status='active'
              AND (s.new_price_krw,s.new_price_from) IS DISTINCT FROM (%s,%s)
            RETURNING s.member_id
        """, (amount, day, amount, day))
        members = [row["member_id"] for row in await cursor.fetchall()]
    delivered = await notify_price_change(pool, members, amount, day, send) if send and members else 0
    return len(members), delivered


async def request_cancel(conn, member, at, revoke):
    await active_owner(conn, member)
    row = await current(conn, member, lock=True)
    if row is None or row["status"] == "ended":
        raise Problem("wrong_state")
    if row["status"] == "active":
        return await cancel_renewal(conn, row, at, revoke)
    return await finish_cancellation(conn, row, at, revoke)


async def finish_cancellation(conn, row, at, revoke):
    if row["billing_key_enc"] is not None and revoke is not None:
        try:
            success = await asyncio.wait_for(revoke(row["billing_key_enc"]), timeout=10)
        except Exception:
            success = False
        if success is not False:
            await conn.execute("UPDATE pet.subscriptions SET billing_key_enc=NULL WHERE id=%s", (row["id"],))
            row = {**row, "billing_key_enc": None}
        else:
            logger.warning("pet_billing_key_revoke_pending")
    if row["billing_key_enc"] is None and row["period_end"] <= at:
        cursor = await conn.execute("""
            UPDATE pet.subscriptions SET status='ended',ended_at=%s WHERE id=%s RETURNING *
        """, (at, row["id"]))
        row = await cursor.fetchone()
    return row


async def reconcile_cancellations(pool, at, revoke):
    async with pool.connection() as conn:
        cursor = await conn.execute("""
            SELECT member_id,id FROM pet.subscriptions WHERE status='canceling'
              AND (period_end<=%s OR (%s AND billing_key_enc IS NOT NULL))
            ORDER BY canceled_at,id LIMIT 20
        """, (at, revoke is not None))
        rows = await cursor.fetchall()
    for item in rows:
        async with pool.connection() as conn, conn.transaction():
            owner = await conn.execute("SELECT 1 FROM pet.members WHERE id=%s AND status='active' FOR UPDATE",
                                       (item["member_id"],))
            if not await owner.fetchone():
                continue
            found = await conn.execute("SELECT * FROM pet.subscriptions WHERE id=%s AND status='canceling' FOR UPDATE",
                                       (item["id"],))
            row = await found.fetchone()
            if row:
                await finish_cancellation(conn, row, at, revoke)


async def reconcile_renewals(pool, at, gateway, revoke):
    async with pool.connection() as conn:
        cursor = await conn.execute("""
            SELECT s.member_id FROM pet.subscriptions s JOIN pet.members m ON m.id=s.member_id
            WHERE s.status='active' AND m.status='active' AND s.billing_key_enc IS NOT NULL
              AND (coalesce(s.retry_at,s.next_charge_at)<=%s
                OR (s.new_price_agreed_at IS NULL AND s.new_price_from<=%s))
            ORDER BY coalesce(s.retry_at,s.next_charge_at),s.id LIMIT 20
        """, (at, at.astimezone(KST).date()))
        rows = await cursor.fetchall()
    for row in rows:
        try:
            await renew_one(pool, row["member_id"], at, gateway, revoke)
        except Problem as error:
            if error.code != "unauthenticated":
                raise


def register(app, revoke, *, renewal_gateway=None):
    async def show(req):
        member = await require_member(req)
        async with app[POOL].connection() as conn:
            return web.json_response(view(await current(conn, member["id"])))

    async def cancel(req):
        member = await require_member(req)
        at = datetime.now(timezone.utc)
        async with app[POOL].connection() as conn, conn.transaction():
            row = await request_cancel(conn, member["id"], at, revoke)
        return web.json_response(view(row))

    async def agree(req):
        member = await require_member(req)
        at = datetime.now(timezone.utc)
        async with app[POOL].connection() as conn, conn.transaction():
            row = await apply_price_consent(conn, member["id"], at)
        return web.json_response(view(row))

    app.router.add_get("/api/subscription", show, allow_head=False)
    app.router.add_post("/api/subscription/cancel", cancel)
    app.router.add_post("/api/subscription/price-consent", agree)

    async def worker(application):
        async def run():
            while True:
                await asyncio.sleep(60)
                try:
                    at = datetime.now(timezone.utc)
                    await reconcile_cancellations(application[POOL], at, revoke)
                    if renewal_gateway is not None:
                        await reconcile_renewals(application[POOL], at, renewal_gateway, revoke)
                except Exception:
                    logger.warning("pet_subscription_reconcile_failed")

        process = asyncio.create_task(run())
        try:
            yield
        finally:
            process.cancel()
            await asyncio.gather(process, return_exceptions=True)

    app.cleanup_ctx.append(worker)
