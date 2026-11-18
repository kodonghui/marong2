"""Order creation, authenticated payment confirmation and retryable fulfilment."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_hex
from uuid import UUID

from aiohttp import web
from psycopg.types.json import Jsonb

from .account import require_overseas
from .creations import owned
from .http import POOL, Problem, body_json, require_member, uuid_param
from .log import logger
from .quota import KST, _day

AMOUNTS = {"character_creation": 5900, "recharge_half": 1500, "recharge_full": 2900, "subscription_month": 9900}
TITLE = {"character_creation": "캐릭터 만들기", "recharge_half": "절반 충전권",
         "recharge_full": "전부 충전권", "subscription_month": "한 달 구독"}
RULE = {
    "item": "산 지 7일 안에 한 번도 쓰지 않았으면 철회할 수 있어요. 사기 전에 미리 써 볼 수 있어요.",
    "character_creation": "후보 그리기가 시작되면 철회할 수 없어요. 무료 미리 보기를 먼저 보여 드렸어요.",
    "recharge_half": "사면 바로 채워져서 철회할 수 없어요.",
    "recharge_full": "사면 바로 채워져서 철회할 수 없어요.",
    "subscription_month": "결제 7일 안에 무료 한도를 넘겨 쓰지 않았다면 철회할 수 있어요.",
}
ACTIVE = {"created", "paid", "fulfilled"}
MAX_PAYMENT_KEY = 200


@dataclass(frozen=True)
class Payment:
    """Facts verified by the gateway, independently of the browser or webhook."""

    order_no: str
    transaction: str
    amount: int
    paid: bool


def order_view(row, at=None):
    at = at or datetime.now(timezone.utc)
    product = row["product"]
    eligible = row["status"] in ACTIVE and row["used_at"] is None and product not in {"recharge_half", "recharge_full"}
    if product == "character_creation":
        can_withdraw = eligible
    else:
        can_withdraw = eligible and at < (row["paid_at"] or row["created_at"]) + timedelta(days=7)
    return {
        "id": str(row["id"]), "orderNo": row["order_no"], "product": product, "itemName": row["item_name"],
        "amountKrw": row["amount_krw"], "vatKrw": row["vat_krw"], "status": row["status"],
        "createdAt": row["created_at"].isoformat(), "withdrawable": can_withdraw, "withdrawalNote": RULE[product],
    }


async def orders(conn, where, values, *, lock=False):
    # 'where' is supplied only by handlers below. Every value in it is parameterized.
    return await conn.execute("""
        SELECT o.*,i.name AS item_name FROM pet.orders o LEFT JOIN pet.items i ON i.id=o.item_id
        WHERE """ + where + (" FOR UPDATE OF o" if lock else ""), values)


def checkout_view(row, gateway):
    pg = None
    if row["status"] == "created" and gateway is not None:
        pg = {"clientKey": gateway.client_key, "orderName": row["item_name"] or TITLE[row["product"]],
              "amount": row["amount_krw"], "billing": row["product"] == "subscription_month"}
    return {"order": order_view(row), "pg": pg}


async def lock_member(conn, member_id):
    cur = await conn.execute("SELECT status,identity_verified_at,free_tickets FROM pet.members WHERE id=%s FOR UPDATE",
                             (member_id,))
    return await cur.fetchone()


async def check_recharge(conn, member_id, at):
    day = await _day(conn, member_id, at)
    if await spent_units(conn, member_id, day) == 0:
        raise Problem("quota_full")
    pending = await conn.execute("""
        SELECT count(*) AS count FROM pet.orders WHERE member_id=%s AND status IN ('created','paid')
          AND product IN ('recharge_half','recharge_full')
    """, (member_id,))
    if day["recharges"] + (await pending.fetchone())["count"] >= 3:
        raise Problem("recharge_limit")


async def spent_units(conn, member, day):
    held = await conn.execute("""
        SELECT coalesce(sum(units),0) AS units FROM pet.quota_holds
        WHERE member_id=%s AND day=%s AND status='held'
    """, (member, day["day"]))
    return max(0, day["used_units"] - (await held.fetchone())["units"])


async def create_order(conn, member_id, product, item_id, key, gateway, at, *, creation_id=None):
    member = await lock_member(conn, member_id)
    if not member or member["status"] != "active":
        raise Problem("unauthenticated")
    existing = await orders(conn, "o.member_id=%s AND o.idempotency_key=%s", (member_id, key))
    if prior := await existing.fetchone():
        return prior
    enabled = await conn.execute("SELECT value FROM pet.settings WHERE key='payments_enabled'")
    setting = await enabled.fetchone()
    if gateway is None or not setting or setting["value"] is not True:
        raise Problem("payments_off")
    if not member["identity_verified_at"]:
        raise Problem("identity_required")
    count = await conn.execute("SELECT count(*) AS count FROM pet.orders WHERE member_id=%s AND status='created'", (member_id,))
    if (await count.fetchone())["count"] >= 5:
        raise Problem("rate_limited")
    if product == "item":
        item = await conn.execute("""
            SELECT name,price_krw FROM pet.items WHERE id=%s AND sellable AND ended_at IS NULL
              AND (sale_starts_at IS NULL OR sale_starts_at<=%s) AND (sale_ends_at IS NULL OR sale_ends_at>%s)
        """, (item_id, at, at))
        item = await item.fetchone()
        if not item:
            raise Problem("not_found")
        duplicate = await conn.execute("""SELECT 1 FROM pet.inventory WHERE member_id=%s AND item_id=%s AND withdrawn_at IS NULL
            UNION ALL SELECT 1 FROM pet.orders WHERE member_id=%s AND item_id=%s AND status IN ('created','paid') LIMIT 1""",
                                       (member_id, item_id, member_id, item_id))
        if await duplicate.fetchone():
            raise Problem("already_owned")
        amount, item_name = item["price_krw"], item["name"]
    else:
        if product in ("recharge_half", "recharge_full"):
            await check_recharge(conn, member_id, at)
        amount, item_name = AMOUNTS[product], None
    return await insert_order(conn, member_id, product, item_id, key, at, amount=amount, item_name=item_name,
                              creation_id=creation_id)


async def insert_order(conn, member_id, product, item_id, key, at, *, amount, item_name,
                       creation_id=None, free=False):
    for _ in range(3):
        number = f"P{at.astimezone(KST):%Y%m%d}-{token_hex(3).upper()}"
        cur = await conn.execute("""
            INSERT INTO pet.orders(order_no,member_id,product,item_id,amount_krw,vat_krw,
                withdrawal_rule,idempotency_key,creation_id,free_ticket)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(order_no) DO NOTHING RETURNING *
        """, (number, member_id, product, item_id, amount, (amount + 5) // 11, "2026-11", key, creation_id, free))
        if row := await cur.fetchone():
            return {**row, "item_name": item_name}
    raise RuntimeError("pet_order_number_collision")


async def checkout_creation(conn, member, creation_id, key, free, gateway, at):
    owner = await lock_member(conn, member)
    if not owner or owner["status"] != "active":
        raise Problem("unauthenticated")
    creation = await owned(conn, member, creation_id, lock=True)
    prior = await orders(conn, "o.member_id=%s AND o.idempotency_key=%s", (member, key))
    if order := await prior.fetchone():
        if order["creation_id"] != creation_id or order["product"] != "character_creation":
            raise Problem("invalid_input")
        return order
    prior = await orders(conn, """o.member_id=%s AND o.creation_id=%s AND o.product='character_creation'
        AND o.status IN ('created','paid','fulfilled') ORDER BY o.created_at DESC LIMIT 1""", (member, creation_id))
    if order := await prior.fetchone():
        return order
    if creation["state"] != "previewed" or creation["expires_at"] <= at:
        raise Problem("wrong_state")
    await require_overseas(conn, member)
    if not free or not owner["free_tickets"]:
        return await create_order(conn, member, "character_creation", None, key, gateway, at, creation_id=creation_id)
    await conn.execute("UPDATE pet.members SET free_tickets=free_tickets-1 WHERE id=%s", (member,))
    order = await insert_order(conn, member, "character_creation", None, key, at, amount=0, item_name=None,
                               creation_id=creation_id, free=True)
    await deliver(conn, order, at)
    await conn.execute("UPDATE pet.orders SET status='fulfilled',paid_at=now(),fulfilled_at=now() WHERE id=%s",
                       (order["id"],))
    return {**order, "status": "fulfilled"}


async def confirm_order(pool, gateway, member_id, order_id, key, amount):
    async with pool.connection() as conn, conn.transaction():
        member = await lock_member(conn, member_id)
        if not member or member["status"] != "active":
            raise Problem("not_found")
        cur = await orders(conn, "o.id=%s AND o.member_id=%s", (order_id, member_id), lock=True)
        row = await cur.fetchone()
        if row is None:
            raise Problem("not_found")
        if row["status"] != "created":
            return row
        if gateway is None:
            raise Problem("wrong_state")
        approved = None
        if row["amount_krw"] == amount:
            approved = await asyncio.wait_for(gateway.approve(row["order_no"], key, amount), timeout=12)
        if not approved or approved.order_no != row["order_no"] or approved.amount != row["amount_krw"]:
            logger.warning("pet_payment_amount_or_order_invalid")
        if (approved is None or not approved.paid or approved.amount != row["amount_krw"]
                or approved.order_no != row["order_no"]):
            await conn.execute("UPDATE pet.orders SET status='failed' WHERE id=%s", (order_id,))
            return {**row, "status": "failed"}
        await conn.execute("UPDATE pet.orders SET status='paid',paid_at=now(),pg_tx_id=%s WHERE id=%s",
                           (approved.transaction, order_id))
        await conn.execute("INSERT INTO pet.jobs(kind,member_id,creation_id,ref) VALUES ('fulfil',%s,%s,%s)",
                           (member_id, row["creation_id"], Jsonb({"order": str(order_id)})))
        return {**row, "status": "paid"}


async def deliver(conn, row, at):
    product, member, ident = row["product"], row["member_id"], row["id"]
    if product == "item":
        result = await conn.execute("SELECT contents FROM pet.items WHERE id=%s", (row["item_id"],))
        item = await result.fetchone()
        await conn.execute("""
            INSERT INTO pet.inventory (member_id,item_id,source,order_id)
            SELECT %s,id,CASE WHEN id=%s THEN 'order' ELSE 'package' END,%s FROM pet.items
            WHERE id=ANY(%s::uuid[]) ON CONFLICT DO NOTHING
        """, (member, row["item_id"], ident, [row["item_id"], *item["contents"]]))
    elif product in ("recharge_half", "recharge_full"):
        day = await _day(conn, member, at)
        limit = day["quota_limit"] if product == "recharge_full" else day["quota_limit"] // 2
        delta = min(await spent_units(conn, member, day), limit)
        await conn.execute("""
            UPDATE pet.member_days SET used_units=used_units-%s,refilled_units=refilled_units+%s,
                recharges=recharges+1 WHERE member_id=%s AND day=%s AND recharges<3
        """, (delta, delta, member, day["day"]))
    elif product == "character_creation":
        changed = await conn.execute("""
            UPDATE pet.creations SET state='paid',order_id=%s,updated_at=now()
            WHERE id=%s AND member_id=%s AND state='previewed' AND order_id IS NULL
        """, (ident, row["creation_id"], member))
        if not changed.rowcount:
            raise RuntimeError("pet_checkout_creation_changed")
        await conn.execute("""UPDATE pet.media SET delete_after=NULL WHERE member_id=%s AND creation_id=%s
            AND kind IN ('photo','preview')""", (member, row["creation_id"]))
        await conn.execute("INSERT INTO pet.jobs(kind,member_id,creation_id) VALUES ('candidates',%s,%s)",
                           (member, row["creation_id"]))
    else:
        # Monthly billing-key and renewal rules belong to SPEC-359/TASK-369.
        raise RuntimeError("pet_subscription_adapter_unavailable")


async def fulfil(pool, member, ident, *, override=None):
    async with pool.connection() as conn, conn.transaction():
        owner = await lock_member(conn, member)
        cur = await orders(conn, "o.id=%s AND o.member_id=%s", (ident, member), lock=True)
        row = await cur.fetchone()
        if row is None or row["status"] != "paid" or not owner or owner["status"] != "active":
            return row
        due = await conn.execute("""
            SELECT id FROM pet.jobs WHERE kind='fulfil' AND member_id=%s AND ref->>'order'=%s
              AND status='queued' AND run_after<=now() LIMIT 1
        """, (member, str(ident)))
        if not await due.fetchone():
            return row
        try:
            async with conn.transaction():
                await (override or deliver)(conn, row, datetime.now(timezone.utc))
                await conn.execute("UPDATE pet.orders SET status='fulfilled',fulfilled_at=now() WHERE id=%s", (ident,))
                await conn.execute("""
                    UPDATE pet.jobs SET status='done',finished_at=now(),lease_until=NULL
                    WHERE kind='fulfil' AND member_id=%s AND ref->>'order'=%s AND status='queued'
                """, (member, str(ident)))
            return {**row, "status": "fulfilled"}
        except Exception:
            await conn.execute("""
                UPDATE pet.jobs SET attempts=attempts+1,run_after=now()+interval '1 minute',error_code='fulfil_retry'
                WHERE kind='fulfil' AND member_id=%s AND ref->>'order'=%s AND status='queued'
            """, (member, str(ident)))
            if row["paid_at"] <= datetime.now(timezone.utc) - timedelta(minutes=10):
                logger.error("pet_fulfil_overdue")
            return row


def confirm_fields(data):
    if set(data) != {"paymentKey", "amount"}:
        raise Problem("invalid_input")
    key, amount = data["paymentKey"], data["amount"]
    if (not isinstance(key, str) or not 1 <= len(key) <= MAX_PAYMENT_KEY or not key.isascii()
            or not key.isprintable() or type(amount) is not int or not 0 <= amount <= 100_000):
        raise Problem("invalid_input")
    return key, amount


def register(app, gateway, *, deliver_order=None):
    async def start(req):
        member = await require_member(req)
        data = await body_json(req)
        product = data.get("product")
        if not isinstance(product, str) or product not in ("item", "recharge_half", "recharge_full", "subscription_month"):
            raise Problem("invalid_input")
        keys = {"product", "idempotencyKey", "itemId"} if product == "item" else {"product", "idempotencyKey"}
        if set(data) != keys:
            raise Problem("invalid_input")
        ident = uuid_param(data["itemId"]) if product == "item" else None
        key = uuid_param(data["idempotencyKey"])
        async with app[POOL].connection() as conn, conn.transaction():
            row = await create_order(conn, member["id"], product, ident, key, gateway, datetime.now(timezone.utc))
        return web.json_response(checkout_view(row, gateway), status=201)

    async def listing(req):
        member = await require_member(req)
        async with app[POOL].connection() as conn:
            cur = await orders(conn, "o.member_id=%s ORDER BY o.created_at DESC,o.id DESC LIMIT 100", (member["id"],))
            return web.json_response({"items": [order_view(row) for row in await cur.fetchall()]})

    async def checkout(req):
        member = await require_member(req)
        ident = uuid_param(req.match_info["id"])
        data = await body_json(req)
        if set(data) != {"useFreeTicket", "idempotencyKey"} or type(data["useFreeTicket"]) is not bool:
            raise Problem("invalid_input")
        key = uuid_param(data["idempotencyKey"])
        async with app[POOL].connection() as conn, conn.transaction():
            order = await checkout_creation(conn, member["id"], ident, key, data["useFreeTicket"], gateway,
                                            datetime.now(timezone.utc))
        return web.json_response(checkout_view(order, gateway))

    async def confirm(req):
        member = await require_member(req)
        ident = uuid_param(req.match_info["id"])
        key, count = confirm_fields(await body_json(req))
        row = await confirm_order(app[POOL], gateway, member["id"], ident, key, count)
        if row["status"] == "paid":
            row = await fulfil(app[POOL], member["id"], ident, override=deliver_order)
        return web.json_response(order_view(row))

    async def webhook(req):
        raw = await req.read()
        if gateway is None or not gateway.valid_signature(raw, req.headers.get("X-PG-Signature", "")):
            logger.warning("pet_webhook_signature_invalid")
            raise Problem("bad_signature")
        data = await body_json(req)
        event_type = data.get("eventType")
        if not isinstance(event_type, str) or not 1 <= len(event_type) <= 50:
            raise Problem("invalid_input")
        if event_type == "PAYMENT_STATUS_CHANGED":
            fields = data.get("data")
            if not isinstance(fields, dict) or not isinstance(fields.get("orderNo"), str) or len(fields["orderNo"]) > 50:
                raise Problem("invalid_input")
            key, amount = confirm_fields({name: fields.get(name) for name in ("paymentKey", "amount")})
            async with app[POOL].connection() as conn:
                cur = await orders(conn, "o.order_no=%s", (fields["orderNo"],))
                row = await cur.fetchone()
            if row and row["member_id"]:
                row = await confirm_order(app[POOL], gateway, row["member_id"], row["id"], key, amount)
                if row["status"] == "paid":
                    await fulfil(app[POOL], row["member_id"], row["id"], override=deliver_order)
        return web.json_response({"ok": True})

    app.router.add_post("/api/orders", start)
    app.router.add_get("/api/orders", listing, allow_head=False)
    app.router.add_post("/api/creations/{id}/checkout", checkout)
    app.router.add_post("/api/orders/{id}/confirm", confirm)
    app.router.add_post("/api/pg/webhook", webhook, name="payment_webhook")

    if gateway is None:
        return

    async def retry(app):
        stop = asyncio.Event()

        async def run():
            while not stop.is_set():
                try:
                    async with app[POOL].connection() as conn:
                        cur = await conn.execute("""SELECT member_id,ref->>'order' AS id FROM pet.jobs
                            WHERE kind='fulfil' AND status='queued' AND run_after<=now() AND member_id IS NOT NULL
                            ORDER BY run_after,id LIMIT 10""")
                        due = await cur.fetchall()
                    for job in due:
                        await fulfil(app[POOL], job["member_id"], UUID(job["id"]), override=deliver_order)
                except Exception:
                    logger.error("pet_fulfil_worker_failed")
                try:
                    await asyncio.wait_for(stop.wait(), 5)
                except TimeoutError:
                    pass

        worker = asyncio.create_task(run())
        try:
            yield
        finally:
            stop.set()
            await worker

    app.cleanup_ctx.append(retry)
