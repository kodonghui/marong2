"""Image validation and the preview worker (SPEC-320, AI-31)."""

import asyncio
import os
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from aiohttp import web
from PIL import Image

from .account import require_overseas
from .creations import describe, owned
from .http import CONFIG, POOL, Problem, require_member, uuid_param
from .jobs import JobQueue
from .log import logger
from .quota import KST, _day, quota_day

PREVIEWS = 3
IMAGE_MAX = 5 * 1024 * 1024
LEASE = timedelta(seconds=200)


def landscape_png(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= IMAGE_MAX:
        raise ValueError("invalid_image_bytes")
    with Image.open(BytesIO(raw)) as image:
        if image.format != "PNG" or image.size != (1536, 1024) or getattr(image, "n_frames", 1) != 1:
            raise ValueError("invalid_image_format")
        if image.convert("RGBA").getchannel("A").getextrema() != (255, 255):
            raise ValueError("unexpected_alpha")
        result = BytesIO()
        image.convert("RGB").save(result, format="PNG")
        if result.tell() > IMAGE_MAX:
            raise ValueError("invalid_image_bytes")
        return result.getvalue()


def preview_png(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= IMAGE_MAX:
        raise ValueError("invalid_image_bytes")
    with Image.open(BytesIO(raw)) as image:
        if image.format != "PNG" or image.size != (1024, 1024) or getattr(image, "n_frames", 1) != 1:
            raise ValueError("invalid_image_format")
        clean = image.convert("RGBA")
        min_alpha, max_alpha = clean.getchannel("A").getextrema()
        if min_alpha != 0 or max_alpha == 0:
            raise ValueError("unexpected_alpha")
        clean.info.clear()
        result = BytesIO()
        clean.save(result, "PNG")
    png = result.getvalue()
    if len(png) > IMAGE_MAX:
        raise ValueError("invalid_image_bytes")
    return png


async def generate_preview(render, settings, template, traits, job):
    for model in dict.fromkeys(filter(None, (settings.image_model, settings.image_fallback_model))):
        try:
            raw = await asyncio.wait_for(render(model=model, template=template, traits=traits, job=job), 90)
            return await asyncio.to_thread(preview_png, raw)
        except Exception:
            logger.warning("pet_preview_draw_failed")
    return None


async def reserve_preview(conn, member_id, creation_id, at):
    status = await conn.execute("SELECT status FROM pet.members WHERE id=%s FOR UPDATE", (member_id,))
    member = await status.fetchone()
    if not member or member["status"] != "active":
        raise Problem("unauthenticated")
    row = await owned(conn, member_id, creation_id, lock=True)
    if row["state"] != "traits_confirmed" or row["expires_at"] <= at:
        raise Problem("wrong_state")
    await require_overseas(conn, member_id)
    jobs = await conn.execute("""
        SELECT creation_id FROM pet.jobs WHERE member_id=%s AND kind='preview' AND status IN ('queued','running')
    """, (member_id,))
    pending = await jobs.fetchall()
    if any(work["creation_id"] == creation_id for work in pending):
        raise Problem("busy")
    day = await _day(conn, member_id, at)
    if day["previews"] >= PREVIEWS:
        limit_at = datetime.combine(quota_day(at) + timedelta(days=1), time(4), KST)
        raise Problem("preview_limit", extra={"resetsAt": limit_at.isoformat()})
    if day["previews"] + len(pending) >= PREVIEWS:
        raise Problem("busy")
    await conn.execute("INSERT INTO pet.jobs(kind,member_id,creation_id) VALUES ('preview',%s,%s)",
                       (member_id, creation_id))
    await conn.execute("UPDATE pet.creations SET failure=NULL,updated_at=now() WHERE id=%s", (creation_id,))
    return await owned(conn, member_id, creation_id)


async def finish_preview(pool, directory, job, png, at):
    path = None
    try:
        async with pool.connection() as conn, conn.transaction():
            cursor = await conn.execute("""
                SELECT id FROM pet.jobs WHERE id=%s AND status='running' AND lease_until=%s AND lease_until>now()
                FOR UPDATE
            """, (job["id"], job["lease_until"]))
            if not await cursor.fetchone():
                return
            cursor = await conn.execute("SELECT status FROM pet.members WHERE id=%s FOR UPDATE", (job["member_id"],))
            member = await cursor.fetchone()
            if not member or member["status"] != "active":
                return
            row = await owned(conn, job["member_id"], job["creation_id"], lock=True)
            try:
                await require_overseas(conn, job["member_id"])
            except Problem:
                png = None
            day = await _day(conn, job["member_id"], at)
            media_id = None
            if png and row["state"] == "traits_confirmed" and row["expires_at"] > at and day["previews"] < PREVIEWS:
                media_id = uuid4()
                key = f"previews/{media_id}.png"
                file = directory / key
                file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with os.fdopen(os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as image:
                    path = file
                    image.write(png)
                await conn.execute("""
                    INSERT INTO pet.media(id,member_id,creation_id,kind,storage_key,content_type,
                        bytes,width,height,sha256,delete_after)
                    VALUES (%s,%s,%s,'preview',%s,'image/png',%s,1024,1024,%s,%s)
                """, (media_id, job["member_id"], row["id"], key, len(png), sha256(png).digest(), row["expires_at"]))
                await conn.execute("""
                    UPDATE pet.member_days SET previews=previews+1 WHERE member_id=%s AND day=%s
                """, (job["member_id"], day["day"]))
                await conn.execute("""
                    UPDATE pet.creations SET state='previewed',preview_id=%s,failure=NULL,updated_at=now()
                    WHERE id=%s
                """, (media_id, row["id"]))
            elif row["state"] == "traits_confirmed":
                await conn.execute("""
                    UPDATE pet.creations SET failure='preview_failed',updated_at=now() WHERE id=%s
                """, (row["id"],))
            await conn.execute("""
                UPDATE pet.jobs SET status=%s,error_code=%s,result_media_id=%s,finished_at=now(),lease_until=NULL
                WHERE id=%s
            """, ("done" if media_id else "failed", None if media_id else "preview_failed", media_id, job["id"]))
    except BaseException:
        if path:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.error("pet_preview_rollback_unlink_failed")
        raise


async def next_preview(pool, settings, budget, render):
    job = await JobQueue(pool).claim(("preview",), lease=LEASE, attempts=1)
    async with pool.connection() as conn:
        await conn.execute("""
            UPDATE pet.creations c SET failure='preview_failed',updated_at=now()
            FROM pet.jobs j WHERE j.kind='preview' AND j.status='failed' AND j.error_code='deadline'
              AND c.id=j.creation_id AND c.member_id=j.member_id AND c.state='traits_confirmed'
              AND c.failure IS DISTINCT FROM 'preview_failed' AND c.updated_at<=j.finished_at
              AND NOT EXISTS(SELECT 1 FROM pet.jobs latest WHERE latest.creation_id=c.id AND latest.kind='preview'
                             AND latest.queued_at>j.queued_at)
        """)
    if not job:
        return False
    png = None
    try:
        async with pool.connection() as conn:
            row = await owned(conn, job["member_id"], job["creation_id"])
            cur = await conn.execute("SELECT id FROM pet.members WHERE id=%s AND status='active'", (job["member_id"],))
            if not await cur.fetchone():
                raise Problem("unauthenticated")
            await require_overseas(conn, job["member_id"])
        await budget.allow("preview")
        if row["state"] == "traits_confirmed" and row["expires_at"] > datetime.now(timezone.utc):
            traits = {key: value for key, value in row["traits"].items()
                      if key not in {"confidence", "petVisible", "multiplePets"}}
            png = await generate_preview(render, settings, row["template"], traits, job)
    except Problem:
        pass
    await finish_preview(pool, settings.media_dir, job, png, datetime.now(timezone.utc))
    return True


def register(app, budget_key, render):
    async def draw(req):
        member = await require_member(req)
        creation_id = uuid_param(req.match_info["id"])
        if render is None:
            raise Problem("server_error")
        await req.app[budget_key].allow("preview")
        async with req.app[POOL].connection() as conn, conn.transaction():
            row = await reserve_preview(conn, member["id"], creation_id, datetime.now(timezone.utc))
            return web.json_response(await describe(conn, row), status=202)

    app.router.add_post("/api/creations/{id}/preview", draw)
    if render is None:
        return

    async def worker(app):
        async def run():
            while True:
                try:
                    if await next_preview(app[POOL], app[CONFIG], app[budget_key], render):
                        continue
                except Exception:
                    logger.error("pet_preview_worker_failed")
                await asyncio.sleep(2)

        task = asyncio.create_task(run())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.cleanup_ctx.append(worker)
