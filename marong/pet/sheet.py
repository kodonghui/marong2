"""Choose an owned candidate and build the six expression images (SPEC-324)."""

import asyncio
import os
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from math import ceil
from uuid import uuid4

import numpy as np
from aiohttp import web
from PIL import Image
from psycopg.types.json import Jsonb

from .account import require_overseas
from .candidates import fit_score
from .creations import describe, owned
from .http import CONFIG, POOL, Problem, body_json, require_member, uuid_param
from .images import preview_png
from .jobs import JobQueue
from .log import logger
from .push import SENDER, notify_creation

EXPRESSIONS = ("smile", "excited", "sleepy", "surprised", "sad", "pout")
LEASE = timedelta(minutes=5)


def alpha(png):
    with Image.open(BytesIO(png)) as graphic:
        return graphic.getchannel("A")


def head_in_box(mask, box):
    if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
        raise ValueError("invalid_template_head_box")
    y, x = np.nonzero(np.asarray(mask) >= 128)
    if not len(y):
        return False
    top = y < y.min() + ceil((y.max() - y.min() + 1) * 0.4)
    center_x = (x[top].mean() + 0.5) / mask.width
    center_y = (y[top].mean() + 0.5) / mask.height
    return box[0] <= center_x <= box[2] and box[1] <= center_y <= box[3]


async def draw_expression(render, settings, template, front, reference, box, expression, job):
    second = settings.image_fallback_model or settings.image_model
    for model in (settings.image_model, second):
        try:
            raw = await asyncio.wait_for(render(model=model, template=template, front=front, expression=expression, job=job),
                                         timeout=90)
            picture = await asyncio.to_thread(preview_png, raw)
            score = await asyncio.to_thread(fit_score, picture, reference)
            fits = await asyncio.to_thread(head_in_box, alpha(picture), box)
            if score >= 0.85 and fits:
                return (picture, score)
        except Exception:
            logger.warning("pet_expression_draw_failed")
    return None


async def save_sheet(pool, directory, job, pictures):
    written = []
    try:
        async with pool.connection() as conn, conn.transaction():
            lock = await conn.execute("""
                SELECT 1 FROM pet.jobs WHERE id=%s AND status='running' AND lease_until=%s AND lease_until>now()
                FOR UPDATE
            """, (job["id"], job["lease_until"]))
            if not await lock.fetchone():
                return
            member = await conn.execute("SELECT 1 FROM pet.members WHERE id=%s AND status='active' FOR UPDATE",
                                        (job["member_id"],))
            if not await member.fetchone():
                return
            row = await owned(conn, job["member_id"], job["creation_id"], lock=True)
            if row["state"] != "chosen":
                return
            try:
                await require_overseas(conn, row["member_id"])
            except Problem:
                pictures = []
            ready = len(pictures) == len(EXPRESSIONS) and all(pictures)
            if ready:
                for label, (png, score) in zip(EXPRESSIONS, pictures, strict=True):
                    ident = uuid4()
                    key = f"sheet/{ident}.png"
                    path = directory / key
                    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
                        written.append(path)
                        file.write(png)
                    await conn.execute("""
                        INSERT INTO pet.media(id,member_id,creation_id,kind,storage_key,content_type,
                            bytes,width,height,sha256,meta)
                        VALUES (%s,%s,%s,'sheet_expression',%s,'image/png',%s,1024,1024,%s,%s)
                    """, (ident, row["member_id"], row["id"], key, len(png), sha256(png).digest(),
                          Jsonb({"expression": label, "iou": score})))
                await conn.execute("UPDATE pet.media SET kind='sheet_front',delete_after=NULL WHERE id=%s",
                                   (row["chosen_id"],))
                await conn.execute("""
                    UPDATE pet.media SET delete_after=CASE kind WHEN 'candidate' THEN now()+interval '7 days'
                                                               ELSE now() END
                    WHERE member_id=%s AND creation_id=%s AND kind IN ('photo','candidate')
                """, (row["member_id"], row["id"]))
            await conn.execute("UPDATE pet.creations SET state=%s,updated_at=now() WHERE id=%s",
                               ("sheet_ready" if ready else "sheet_needs_operator", row["id"]))
            await conn.execute("""
                UPDATE pet.jobs SET status=%s,error_code=%s,finished_at=now(),lease_until=NULL WHERE id=%s
            """, ("done" if ready else "failed", None if ready else "sheet_needs_operator", job["id"]))
        if not ready:
            logger.error("pet_sheet_operator_required")
    except BaseException:
        for path in written:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.error("pet_sheet_rollback_unlink_failed")
        raise
    return ready


async def next_sheet(pool, settings, budget, render, head_for, *, send=None):
    job = await JobQueue(pool).claim(("sheet",), lease=LEASE, attempts=2_147_483_647)
    if not job:
        return False
    pictures = []
    try:
        async with pool.connection() as conn:
            row = await owned(conn, job["member_id"], job["creation_id"])
            await require_overseas(conn, row["member_id"])
            selected = await conn.execute("""
                SELECT m.storage_key,m.sha256 FROM pet.media m JOIN pet.members a ON a.id=m.member_id
                WHERE m.id=%s AND m.kind='candidate' AND m.member_id=%s AND m.creation_id=%s AND a.status='active'
            """, (row["chosen_id"], row["member_id"], row["id"]))
            selected = await selected.fetchone()
        if not selected or row["state"] != "chosen":
            raise ValueError("candidate_unavailable")
        root = settings.media_dir.resolve()
        path = (root / selected["storage_key"]).resolve()
        if not path.is_relative_to(root / "candidates"):
            raise ValueError("candidate_path_invalid")
        front = await asyncio.to_thread(path.read_bytes)
        if sha256(front).digest() != selected["sha256"]:
            raise ValueError("candidate_digest_invalid")
        reference = alpha(front)
        box = await asyncio.to_thread(head_for, row["template"])
        await budget.allow("expression", paid=True)
        pictures = await asyncio.gather(*(draw_expression(render, settings, row["template"], front, reference,
                                                           box, label, job) for label in EXPRESSIONS))
    except (Problem, ValueError, OSError):
        pass
    ready = await save_sheet(pool, settings.media_dir, job, pictures)
    if ready and send is not None:
        await notify_creation(pool, job["member_id"], job["creation_id"], "sheet", send=send)
    return True


def register(app, budget_key, render, head_for):
    async def choose(req):
        member = await require_member(req)
        ident = uuid_param(req.match_info["id"])
        body = await body_json(req)
        if set(body) != {"candidateId"}:
            raise Problem("invalid_input")
        candidate = uuid_param(body["candidateId"])
        async with app[POOL].connection() as conn, conn.transaction():
            row = await owned(conn, member["id"], ident, lock=True)
            if row["state"] == "chosen":
                raise Problem("busy")
            if row["state"] != "candidates":
                raise Problem("wrong_state")
            cur = await conn.execute("""
                SELECT 1 FROM pet.media WHERE id=%s AND member_id=%s AND creation_id=%s AND kind='candidate'
            """, (candidate, member["id"], ident))
            if not await cur.fetchone():
                raise Problem("not_found")
            if not render or not head_for:
                raise Problem("server_error")
            await conn.execute("UPDATE pet.creations SET state='chosen',chosen_id=%s,updated_at=now() WHERE id=%s",
                               (candidate, ident))
            await conn.execute("INSERT INTO pet.jobs(kind,member_id,creation_id) VALUES ('sheet',%s,%s)",
                               (member["id"], ident))
            return web.json_response(await describe(conn, await owned(conn, member["id"], ident)), status=202)

    app.router.add_post("/api/creations/{id}/choose", choose)
    if not render or not head_for:
        return

    async def worker(app):
        async def run():
            while True:
                try:
                    if await next_sheet(app[POOL], app[CONFIG], app[budget_key], render, head_for, send=app.get(SENDER)):
                        continue
                except Exception:
                    logger.error("pet_sheet_worker_failed")
                await asyncio.sleep(2)
        task = asyncio.create_task(run())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.cleanup_ctx.append(worker)
