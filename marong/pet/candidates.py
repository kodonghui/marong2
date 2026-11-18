"""Draw and validate candidate rounds with a separately configured image renderer."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from aiohttp import web
from PIL import Image, ImageChops
from psycopg.types.json import Jsonb

from .account import require_overseas
from .creations import describe, owned
from .http import CONFIG, POOL, Problem, body_json, require_member, uuid_param
from .images import preview_png
from .jobs import JobQueue
from .log import logger

CANDIDATE_WINDOW = timedelta(minutes=30)
LEASE = CANDIDATE_WINDOW + timedelta(minutes=1)
CANDIDATES = 4
MATCH = 0.75


def silhouette(image):
    return image.point(lambda value: 255 if value >= 128 else 0, mode="1")


def fit_score(png, reference):
    with Image.open(BytesIO(png)) as image:
        generated = silhouette(image.getchannel("A"))
    if reference.mode != "L" or reference.size != generated.size:
        raise ValueError("invalid_template_mask")
    expected = silhouette(reference)
    counts = ImageChops.logical_or(generated, expected).histogram()
    if not counts[255]:
        return 0.0
    return ImageChops.logical_and(generated, expected).histogram()[255] / counts[255]


async def draw_candidate(render, settings, row, reference, index):
    options = (settings.image_model, settings.image_model, settings.image_fallback_model)
    safe_traits = {key: value for key, value in row["traits"].items()
                   if key not in {"confidence", "petVisible", "multiplePets"}}
    for model in filter(None, options):
        try:
            raw = await asyncio.wait_for(render(model=model, template=row["template"], traits=safe_traits,
                                                slot=index, note=row["regenerate_note"]), 90)
            png = await asyncio.to_thread(preview_png, raw)
            score = await asyncio.to_thread(fit_score, png, reference)
            if score >= MATCH:
                return png, score
        except Exception:
            logger.warning("pet_candidate_draw_failed")
    return None


async def cancel_order(conn, gateway, row):
    cur = await conn.execute("""
        SELECT id,status,pg_tx_id,amount_krw,free_ticket FROM pet.orders
        WHERE id=%s AND member_id=%s FOR UPDATE
    """, (row["order_id"], row["member_id"]))
    order = await cur.fetchone()
    if not order or order["status"] not in {"paid", "fulfilled", "refund_pending"}:
        return
    ok = False
    if order["free_ticket"]:
        await conn.execute("UPDATE pet.members SET free_tickets=least(20,free_tickets+1) WHERE id=%s", (row["member_id"],))
        ok = True
    elif gateway is not None and order["pg_tx_id"]:
        try:
            ok = await asyncio.wait_for(gateway.cancel(order["pg_tx_id"], order["amount_krw"],
                                                       "auto_generation_failed"), timeout=12)
        except Exception:
            logger.warning("pet_candidate_refund_pending")
    await conn.execute("""
        UPDATE pet.orders SET status=%s,refund_reason='auto_generation_failed',
            refunded_at=CASE WHEN %s THEN now() ELSE refunded_at END WHERE id=%s
    """, ("refunded" if ok else "refund_pending", ok, order["id"]))


async def save_candidate(pool, directory, job, index, picture):
    written = None
    try:
        async with pool.connection() as conn, conn.transaction():
            row = await locked_creation(conn, job)
            if row is None:
                return
            try:
                await require_overseas(conn, row["member_id"])
            except Problem:
                return
            existing = await candidate_slots(conn, row)
            if index in existing:
                return
            data, score = picture
            ident = uuid4()
            key = f"candidates/{ident}.png"
            target = directory / key
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
                written = target
                file.write(data)
            await conn.execute("""
                INSERT INTO pet.media(id,member_id,creation_id,kind,storage_key,content_type,bytes,width,height,sha256,meta)
                VALUES (%s,%s,%s,'candidate',%s,'image/png',%s,1024,1024,%s,%s)
            """, (ident, row["member_id"], row["id"], key, len(data), sha256(data).digest(),
                  Jsonb({"round": row["regenerations"], "slot": index, "iou": score})))
    except BaseException:
        if written is not None:
            try:
                written.unlink(missing_ok=True)
            except OSError:
                logger.error("pet_candidate_rollback_unlink_failed")
        raise


async def candidate_slots(conn, row):
    result = await conn.execute("""
        SELECT meta->'slot' AS slot FROM pet.media WHERE member_id=%s AND creation_id=%s AND kind='candidate'
          AND meta->>'round'=%s AND (delete_after IS NULL OR delete_after>now())
    """, (row["member_id"], row["id"], str(row["regenerations"])))
    return {item["slot"] for item in await result.fetchall()}


async def locked_creation(conn, job):
    locked = await conn.execute("""
        SELECT 1 FROM pet.jobs WHERE id=%s AND status='running' AND lease_until=%s
            AND lease_until>now() FOR UPDATE
    """, (job["id"], job["lease_until"]))
    if not await locked.fetchone():
        return None
    member = await conn.execute("SELECT status FROM pet.members WHERE id=%s FOR UPDATE", (job["member_id"],))
    member = await member.fetchone()
    if not member or member["status"] != "active":
        return None
    row = await owned(conn, job["member_id"], job["creation_id"], lock=True)
    return row if row["state"] == "paid" else None


async def finish_round(pool, job, gateway):
    async with pool.connection() as conn, conn.transaction():
        row = await locked_creation(conn, job)
        if row is not None:
            count = await conn.execute("""
                SELECT count(*) AS n FROM pet.media WHERE member_id=%s AND creation_id=%s AND kind='candidate'
                  AND (delete_after IS NULL OR delete_after>now())
            """, (row["member_id"], row["id"]))
            any_candidates = bool((await count.fetchone())["n"])
            if not any_candidates:
                deadline = job["queued_at"] + CANDIDATE_WINDOW
                if datetime.now(timezone.utc) < deadline:
                    await conn.execute("""
                        UPDATE pet.jobs SET status='queued',run_after=%s,lease_until=NULL WHERE id=%s
                    """, (deadline, job["id"]))
                    return
                await cancel_order(conn, gateway, row)
                await conn.execute("""
                    UPDATE pet.media SET delete_after=now() WHERE member_id=%s AND creation_id=%s AND kind IN ('photo','preview')
                """, (row["member_id"], row["id"]))
            await conn.execute("""
                UPDATE pet.creations SET state=%s,failure=%s,regenerate_note=NULL,updated_at=now() WHERE id=%s
            """, ("candidates" if any_candidates else "failed_candidates",
                  None if any_candidates else "candidates_failed", row["id"]))
            await conn.execute("""
                UPDATE pet.jobs SET status=%s,error_code=%s,finished_at=now(),lease_until=NULL WHERE id=%s
            """, ("done" if any_candidates else "failed", None if any_candidates else "candidates_failed", job["id"]))


async def next_candidates(pool, settings, budget, draw, mask_for, gateway):
    job = await JobQueue(pool).claim(("candidates",), lease=LEASE, attempts=2_147_483_647)
    if not job:
        return False
    try:
        async with pool.connection() as conn, conn.transaction():
            row = await locked_creation(conn, job)
            if row is None:
                return True
            await require_overseas(conn, job["member_id"])
            slots = await candidate_slots(conn, row)
            await conn.execute("UPDATE pet.orders SET used_at=coalesce(used_at,now()) WHERE id=%s", (row["order_id"],))
        remaining = (job["queued_at"] + CANDIDATE_WINDOW - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            await budget.allow("candidate", paid=True)
            mask = await asyncio.to_thread(mask_for, row["template"])

            async def draw_and_save(slot):
                picture = await draw_candidate(draw, settings, row, mask, slot)
                if picture is not None:
                    await save_candidate(pool, settings.media_dir, job, slot, picture)

            async with asyncio.TaskGroup() as workers:
                for slot in range(CANDIDATES):
                    if slot not in slots:
                        workers.create_task(draw_and_save(slot))
    except (Problem, TimeoutError, ValueError, OSError):
        pass
    await finish_round(pool, job, gateway)
    return True


def register(app, budget_key, draw, mask_for, gateway):
    async def regenerate(req):
        member = await require_member(req)
        ident = uuid_param(req.match_info["id"])
        data = await body_json(req)
        note = data.get("note", "")
        if set(data) - {"note"} or not isinstance(note, str) or len(note) > 100 or "\0" in note:
            raise Problem("invalid_input")
        async with app[POOL].connection() as conn, conn.transaction():
            row = await owned(conn, member["id"], ident, lock=True)
            if row["state"] == "paid":
                raise Problem("busy")
            if row["state"] != "candidates":
                raise Problem("wrong_state")
            if row["regenerations"] >= 2:
                raise Problem("regenerate_limit")
            if draw is None or mask_for is None:
                raise Problem("server_error")
            await conn.execute("""
                UPDATE pet.creations SET state='paid',regenerations=regenerations+1,regenerate_note=%s,
                    updated_at=now() WHERE id=%s
            """, (note or None, ident))
            await conn.execute("INSERT INTO pet.jobs(kind,member_id,creation_id) VALUES ('candidates',%s,%s)",
                               (member["id"], ident))
            return web.json_response(await describe(conn, await owned(conn, member["id"], ident)), status=202)

    app.router.add_post("/api/creations/{id}/regenerate", regenerate)
    if draw is None or mask_for is None:
        return

    async def worker(app):
        async def run():
            while True:
                try:
                    if await next_candidates(app[POOL], app[CONFIG], app[budget_key], draw, mask_for, gateway):
                        continue
                except Exception:
                    logger.error("pet_candidate_worker_failed")
                await asyncio.sleep(2)
        task = asyncio.create_task(run())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.cleanup_ctx.append(worker)
