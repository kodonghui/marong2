"""Member subscription view, scheduled cancellation, and price consent (SPEC-359)."""

import asyncio
from datetime import datetime, timezone

from aiohttp import web

from .http import POOL, Problem, require_member
from .log import logger
from .quota import KST

MONTHLY_PRICE_KRW = 9900


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


async def request_cancel(conn, member, at, revoke):
    await active_owner(conn, member)
    row = await current(conn, member, lock=True)
    if row is None or row["status"] == "ended":
        raise Problem("wrong_state")
    if row["status"] == "active":
        cursor = await conn.execute("""
            UPDATE pet.subscriptions SET status='canceling',canceled_at=%s,next_charge_at=NULL,retry_at=NULL
            WHERE id=%s RETURNING *
        """, (at, row["id"]))
        row = await cursor.fetchone()
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


def register(app, revoke):
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
                    await reconcile_cancellations(application[POOL], datetime.now(timezone.utc), revoke)
                except Exception:
                    logger.warning("pet_subscription_reconcile_failed")

        process = asyncio.create_task(run())
        try:
            yield
        finally:
            process.cancel()
            await asyncio.gather(process, return_exceptions=True)

    app.cleanup_ctx.append(worker)
