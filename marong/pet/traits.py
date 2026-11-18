"""Create, edit and confirm a validated trait sheet (SPEC-318–319)."""

import asyncio
from datetime import timedelta
from hashlib import sha256

from aiohttp import web
from psycopg.types.json import Jsonb

from .account import require_overseas
from .creations import describe, owned
from .http import CONFIG, POOL, Problem, body_json, require_member, uuid_param
from .jobs import JobQueue
from .log import logger

COLORS = ("흰색", "검은색", "갈색", "크림", "회색", "황토", "주황", "은색")
CHOICES = {
    "species": ("dog", "cat", "other"),
    "pattern": ("단색", "얼룩", "줄무늬", "턱시도", "포인트", "삼색", "브린들"),
    "earShape": ("선 귀", "접힌 귀", "늘어진 귀", "반쯤 선 귀"),
    "eyeColor": ("갈색", "검은색", "파란색", "초록색", "노란색", "짝눈"),
    "build": ("작음", "중간", "큼", "긴 몸", "통통함"),
    "furLength": ("짧음", "중간", "긺", "곱슬"),
}
TEXT_LIMITS = {"breedGuess": 30, "patternNotes": 60, "distinctive": 60}
EDITABLE = CHOICES.keys() | TEXT_LIMITS.keys() | {"coatColors"}
FLAGS = {"petVisible", "multiplePets"}
CONFIDENCE = ("low", "medium", "high")
LEASE = timedelta(seconds=35)
ATTEMPTS = 2


def valid_edits(data):
    if not isinstance(data, dict) or not data.keys() <= EDITABLE:
        return False
    for key, value in data.items():
        if key in CHOICES and value not in CHOICES[key]:
            return False
        if key in TEXT_LIMITS and (not isinstance(value, str) or len(value) > TEXT_LIMITS[key]
                                   or "\x00" in value):
            return False
        if key == "coatColors" and (
            not isinstance(value, list) or not 1 <= len(value) <= 3
            or any(color not in COLORS for color in value) or len(set(value)) != len(value)
        ):
            return False
    return True


def valid_result(data):
    if not isinstance(data, dict) or data.keys() != EDITABLE | FLAGS | {"confidence"}:
        return False
    return (all(type(data[key]) is bool for key in FLAGS) and data["confidence"] in CONFIDENCE
            and valid_edits({key: data[key] for key in EDITABLE}))


def output_schema():
    # The server enforces string lengths, array lengths and uniqueness after parsing.
    fields = {key: {"type": "string", "enum": list(values)} for key, values in CHOICES.items()}
    fields.update({key: {"type": "string"} for key in TEXT_LIMITS})
    fields.update({key: {"type": "boolean"} for key in FLAGS})
    fields["coatColors"] = {"type": "array", "items": {"type": "string", "enum": list(COLORS)}}
    fields["confidence"] = {"type": "string", "enum": list(CONFIDENCE)}
    return {"type": "object", "properties": fields, "required": sorted(fields), "additionalProperties": False}


def template_for(traits):
    large = traits["build"] in {"큼", "통통함"}
    if traits["species"] == "cat":
        return "cat_round" if large else "cat"
    if traits["species"] != "dog":
        raise Problem("invalid_input")
    if traits["build"] == "긴 몸":
        return "dog_long"
    return "dog_large" if large else "dog_small"


async def update(req, *, confirm):
    member = await require_member(req)
    ident = uuid_param(req.match_info["id"])
    edits = {} if confirm else await body_json(req)
    if not valid_edits(edits):
        raise Problem("invalid_input")
    async with req.app[POOL].connection() as conn, conn.transaction():
        row = await owned(conn, member["id"], ident, lock=True)
        if row["state"] != "traits":
            raise Problem("wrong_state")
        data = {**row["traits"], **edits}
        state = "traits_confirmed" if confirm else "traits"
        template = template_for(data) if confirm else None
        await conn.execute("""UPDATE pet.creations SET traits=%s,state=%s,template=%s,updated_at=now()
            WHERE id=%s""", (Jsonb(data), state, template, ident))
        return web.json_response(await describe(conn, await owned(conn, member["id"], ident)))


async def edit(req):
    return await update(req, confirm=False)


async def confirm(req):
    return await update(req, confirm=True)


async def read_inputs(pool, root, job):
    async with pool.connection() as conn:
        cur = await conn.execute(
            """SELECT m.storage_key,m.sha256 FROM pet.media m JOIN pet.creations c ON c.id=m.creation_id
               JOIN pet.members a ON a.id=c.member_id
               WHERE m.creation_id=%s AND m.member_id=%s AND c.member_id=m.member_id
                 AND c.state='photos' AND c.expires_at>now() AND a.status='active'
                 AND m.kind='photo' AND m.content_type='image/png' AND m.delete_after>now()
               ORDER BY (m.meta->>'photo')::int,m.id LIMIT 4""",
            (job["creation_id"], job["member_id"]),
        )
        rows = await cur.fetchall()
        if not 1 <= len(rows) <= 3:
            return []
        await require_overseas(conn, job["member_id"])
    photos = []
    for row in rows:
        path = (root / row["storage_key"]).resolve()
        if not path.is_relative_to(root / "photos"):
            raise ValueError("invalid_photo_path")
        content = await asyncio.to_thread(path.read_bytes)
        if not content.startswith(b"\x89PNG\r\n\x1a\n") or sha256(content).digest() != row["sha256"]:
            raise ValueError("invalid_photo_encoding")
        photos.append(content)
    return photos


async def publish(pool, job, state, code, data=None):
    async with pool.connection() as conn, conn.transaction():
        cur = await conn.execute(
            """SELECT id FROM pet.jobs WHERE id=%s AND status='running'
               AND lease_until=%s AND lease_until>now() FOR UPDATE""", (job["id"], job["lease_until"]),
        )
        if not await cur.fetchone():
            return
        cur = await conn.execute("SELECT status FROM pet.members WHERE id=%s FOR UPDATE", (job["member_id"],))
        member = await cur.fetchone()
        if not member or member["status"] != "active":
            state, code, data = None, "member_unavailable", None
        if state == "traits":
            try:
                await require_overseas(conn, job["member_id"])
            except Problem:
                state, code, data = "failed_traits", "traits_failed", None
        if state:
            await conn.execute(
                """UPDATE pet.creations SET state=%s, failure=%s, traits=%s, updated_at=now()
                   WHERE id=%s AND member_id=%s AND state='photos'""",
                (state, code, Jsonb(data) if data else None, job["creation_id"], job["member_id"]),
            )
            if state != "traits":
                await conn.execute("""UPDATE pet.media SET delete_after=now() WHERE creation_id=%s
                    AND member_id=%s AND kind='photo'""", (job["creation_id"], job["member_id"]))
        status = {"traits": "done", "rejected": "done", "failed_traits": "failed"}.get(state, "canceled")
        await conn.execute("""UPDATE pet.jobs SET status=%s,error_code=%s,lease_until=NULL,finished_at=now()
            WHERE id=%s""", (status, code, job["id"]))


async def settle_abandoned(pool):
    async with pool.connection() as conn, conn.transaction():
        await conn.execute(
            """WITH abandoned AS (
               UPDATE pet.creations c SET state='failed_traits',failure='traits_failed',updated_at=now()
               FROM pet.jobs j WHERE j.creation_id=c.id AND j.member_id=c.member_id AND c.state='photos'
                 AND j.kind='traits' AND j.status='failed' AND j.error_code='deadline'
               RETURNING c.id,c.member_id
            ) UPDATE pet.media m SET delete_after=now() FROM abandoned c
              WHERE m.creation_id=c.id AND m.member_id=c.member_id AND m.kind='photo'"""
        )


async def next_traits(pool, media_dir, extract, *, timeout=30):
    queue = JobQueue(pool)
    job = await queue.claim(("traits",), lease=LEASE, attempts=ATTEMPTS)
    await settle_abandoned(pool)
    if not job:
        return False
    try:
        photos = await read_inputs(pool, media_dir.resolve(), job)
        if not photos:
            await publish(pool, job, "failed_traits", "traits_failed")
            return True
        data = await asyncio.wait_for(extract(photos, job), timeout=timeout)
        if not valid_result(data):
            raise ValueError("invalid_traits")
    except Problem:
        await publish(pool, job, "failed_traits", "traits_failed")
    except Exception:
        if job["attempts"] < ATTEMPTS:
            await queue.fail(job, "traits_failed", retry_after=timedelta(), attempts=ATTEMPTS)
        else:
            await publish(pool, job, "failed_traits", "traits_failed")
    else:
        if data["species"] == "other":
            await publish(pool, job, "rejected", "not_dog_or_cat")
        elif not data["petVisible"]:
            await publish(pool, job, "rejected", "pet_not_visible")
        else:
            await publish(pool, job, "traits", None, data)
    return True


def register(app, extract=None):
    app.router.add_patch("/api/creations/{id}/traits", edit)
    app.router.add_post("/api/creations/{id}/confirm-traits", confirm)
    if extract is None:
        return

    async def worker(app):
        async def run():
            while True:
                try:
                    if await next_traits(app[POOL], app[CONFIG].media_dir, extract):
                        continue
                except Exception:
                    logger.error("pet_traits_worker_failed")
                await asyncio.sleep(2)
        task = asyncio.create_task(run())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.cleanup_ctx.append(worker)
