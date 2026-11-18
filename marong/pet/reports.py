import asyncio
from datetime import datetime, time, timedelta

from aiohttp import web
from psycopg.types.json import Jsonb

from .cost import KST
from .http import POOL, Problem, body_json, require_member, uuid_param
from .log import logger


REASONS = frozenset(("strange", "hurtful", "sexual", "dangerous", "bad_picture", "other"))


async def save(req):
    member = (await require_member(req))["id"]
    payload = await body_json(req)
    target_type, reason, note = payload.get("targetType"), payload.get("reason"), payload.get("note", "")
    if (target_type not in ("message", "picture") or not isinstance(reason, str) or reason not in REASONS
            or not isinstance(note, str) or len(note) > 200 or "\x00" in note):
        raise Problem("invalid_input")
    target = uuid_param(payload.get("targetId"))
    at = req.app[CLOCK]().astimezone(KST)
    day = datetime.combine(at.date(), time.min, KST)
    async with req.app[POOL].connection() as conn, conn.transaction():
        owner = await conn.execute("SELECT status FROM pet.members WHERE id=%s FOR UPDATE", (member,))
        profile = await owner.fetchone()
        if not profile or profile["status"] != "active":
            raise Problem("unauthenticated")
        previous = await conn.execute(
            "SELECT id FROM pet.reports WHERE member_id=%s AND target_type=%s AND target_id=%s",
            (member, target_type, target),
        )
        found = await previous.fetchone()
        if found:
            return web.json_response({"jobId": str(found["id"])})
        if target_type == "message":
            cursor = await conn.execute(
                "SELECT content FROM pet.messages WHERE member_id=%s AND id=%s AND role='pet'", (member, target),
            )
        else:
            cursor = await conn.execute(
                "SELECT id FROM pet.media WHERE member_id=%s AND id=%s AND (delete_after IS NULL OR delete_after>now()) "
                "AND kind IN ('preview','candidate','sheet_front','sheet_expression','scene','farewell')",
                (member, target),
            )
        evidence = await cursor.fetchone()
        if evidence is None:
            raise Problem("not_found")
        count = await conn.execute(
            "SELECT count(*) AS n FROM pet.reports WHERE member_id=%s AND created_at>=%s AND created_at<%s",
            (member, day, day + timedelta(days=1)),
        )
        if (await count.fetchone())["n"] >= 20:
            raise Problem("rate_limited")
        created = await conn.execute(
            """
            INSERT INTO pet.reports(member_id,target_type,target_id,reason,note,copy_text,copy_media,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """,
            (member, target_type, target, reason, note, evidence.get("content"), evidence.get("id"), at),
        )
        report = await created.fetchone()
    return web.json_response({"jobId": str(report["id"])}, status=201)


async def report_digest(pool, at):
    """Return today's pending count once; no member or conversation data enters the alert."""
    at = at.astimezone(KST)
    if at.hour < 9:
        return 0
    day = datetime.combine(at.date(), time.min, KST)
    async with pool.connection() as conn, conn.transaction():
        cursor = await conn.execute("SELECT count(*) AS n FROM pet.reports WHERE status='open' AND created_at<%s",
                                    (day.replace(hour=9),))
        count = (await cursor.fetchone())["n"]
        marked = await conn.execute(
            "INSERT INTO pet.settings(key,value) VALUES (%s,%s) ON CONFLICT (key) DO NOTHING RETURNING key",
            (f"report_digest:{day.date()}", Jsonb({"count": count})),
        )
        return count if await marked.fetchone() else 0


async def report_loop(pool, clock):
    while True:
        try:
            count = await report_digest(pool, clock())
            if count:
                logger.warning("pet_reports_pending count=%s", count)
        except Exception:
            logger.error("pet_report_digest_failed")
        await asyncio.sleep(60)


CLOCK = web.AppKey("pet_report_clock")


def register(app, *, clock=None):
    app[CLOCK] = clock or (lambda: datetime.now(KST))
    app.router.add_post("/api/reports", save)

    async def worker(_app):
        task = asyncio.create_task(report_loop(app[POOL], app[CLOCK]))
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.cleanup_ctx.append(worker)
