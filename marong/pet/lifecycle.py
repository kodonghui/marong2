"""Member-owned mode transitions, archiving and deletion for SPEC-338 and SPEC-341."""

import asyncio
from datetime import date, datetime, timedelta, timezone

from aiohttp import web
from psycopg.types.json import Jsonb

from .http import CONFIG, POOL, Problem, body_json, require_member, uuid_param
from .jobs import JobQueue
from .log import logger
from .pets import NAME, pet_rows, serialize
from .quota import KST, settle


REVERT_WINDOW = timedelta(days=7)
PURGE_LEASE = timedelta(minutes=5)
PURGE_TRIES = 2_147_483_647


async def lock_pet(conn, member, pet):
    owner = await conn.execute("SELECT id FROM pet.members WHERE id=%s AND status='active' FOR UPDATE", (member,))
    if not await owner.fetchone():
        raise Problem("unauthenticated")
    row = await conn.execute("SELECT * FROM pet.pets WHERE id=%s AND member_id=%s FOR UPDATE", (pet, member))
    owned = await row.fetchone()
    if owned is None:
        raise Problem("not_found")
    return owned


def parse_mode(data, at):
    mode = data.get("mode")
    if mode not in ("living", "memorial") or not set(data) <= {"mode", "passedOn"}:
        raise Problem("invalid_input")
    if "passedOn" not in data:
        return mode, None
    value = data["passedOn"]
    if mode != "memorial" or not isinstance(value, str) or len(value) != 10:
        raise Problem("invalid_input")
    try:
        passed = date.fromisoformat(value)
    except ValueError:
        raise Problem("invalid_input") from None
    if value != passed.isoformat() or passed > at.astimezone(KST).date():
        raise Problem("invalid_input")
    return mode, passed


async def mute_pending(conn, member, pet, at, *, archived=False):
    await conn.execute("""
        UPDATE pet.proactive_turns SET status='dropped',reason=%s,decided_at=%s,draft=NULL
        WHERE member_id=%s AND pet_id=%s AND status IN ('planned','retry')
    """, ("archived" if archived else "memorial", at, member, pet))
    jobs = ["proactive", "item_reaction"]
    if archived:
        jobs.extend(("reply", "redraw", "farewell"))
    await conn.execute("""
        UPDATE pet.jobs SET status='canceled',finished_at=%s,lease_until=NULL
        WHERE member_id=%s AND pet_id=%s AND kind=ANY(%s::text[]) AND status IN ('queued','running')
    """, (at, member, pet, jobs))


async def held_for_pet(conn, member, pet, at):
    held = await conn.execute("""
        SELECT h.id FROM pet.quota_holds h LEFT JOIN pet.calls c ON c.id=h.call_id
        LEFT JOIN pet.diary_entries d ON d.id=h.diary_id
        WHERE h.member_id=%s AND h.status='held' AND (c.pet_id=%s OR d.pet_id=%s)
        ORDER BY h.day,h.id
    """, (member, pet, pet))
    for hold in await held.fetchall():
        await settle(conn, member, hold["id"], at=at, commit=False)


async def delete_records(conn, row, at):
    member, pet, creation = row["member_id"], row["id"], row["creation_id"]
    await held_for_pet(conn, member, pet, at)
    owned_media = await conn.execute("""
        SELECT storage_key FROM pet.media WHERE member_id=%s AND (pet_id=%s OR creation_id=%s)
    """, (member, pet, creation))
    keys = [item["storage_key"] for item in await owned_media.fetchall()]
    if keys:
        await conn.execute("INSERT INTO pet.jobs(kind,ref) VALUES ('cleanup',%s)", (Jsonb({"storage": keys}),))
    await conn.execute("DELETE FROM pet.jobs WHERE member_id=%s AND (pet_id=%s OR creation_id=%s)",
                       (member, pet, creation))
    await conn.execute("DELETE FROM pet.pets WHERE id=%s AND member_id=%s", (pet, member))
    await conn.execute("DELETE FROM pet.creations WHERE id=%s AND member_id=%s", (creation, member))


def purge_paths(root, keys):
    for key in keys:
        path = (root / key).resolve()
        if path == root or not path.is_relative_to(root):
            raise ValueError("invalid_storage_path")
        path.unlink(missing_ok=True)


async def purge_one(pool, root):
    queue = JobQueue(pool)
    job = await queue.claim(("cleanup",), lease=PURGE_LEASE, attempts=PURGE_TRIES)
    if job is None:
        return False
    try:
        await asyncio.to_thread(purge_paths, root.resolve(), job["ref"]["storage"])
    except (OSError, ValueError, KeyError):
        await queue.fail(job, "pet_media_purge_retry", retry_after=timedelta(minutes=1), attempts=PURGE_TRIES)
        logger.error("pet_media_purge_failed")
    else:
        # The lease check also prevents a slower worker from discarding a reissued cleanup.
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM pet.jobs WHERE id=%s AND status='running' AND lease_until=%s",
                               (job["id"], job["lease_until"]))
    return True


def register(app, *, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))

    async def change_mode(req):
        member = (await require_member(req))["id"]
        pet = uuid_param(req.match_info["id"])
        at = clock()
        mode, passed = parse_mode(await body_json(req), at)
        async with app[POOL].connection() as conn, conn.transaction():
            row = await lock_pet(conn, member, pet)
            if row["status"] == "archived":
                raise Problem("archived")
            if row["mode"] != mode:
                memorial = mode == "memorial"
                if not memorial and at >= row["memorial_since"] + REVERT_WINDOW:
                    raise Problem("revert_window_passed")
                await conn.execute("""
                    UPDATE pet.pets SET mode=%s,memorial_since=%s,passed_on=%s,updated_at=%s WHERE id=%s
                """, (mode, at if memorial else None, passed, at, pet))
                if memorial:
                    await mute_pending(conn, member, pet, at)
            result = (await pet_rows(conn, member, pet))[0]
        return web.json_response(serialize(result, now=at))

    async def change_archive(req):
        member = (await require_member(req))["id"]
        pet = uuid_param(req.match_info["id"])
        at = clock()
        archive = req.match_info.route.name == "pet_archive"
        status = "archived" if archive else "active"
        async with app[POOL].connection() as conn, conn.transaction():
            row = await lock_pet(conn, member, pet)
            if archive and row["mode"] != "memorial":
                raise Problem("not_memorial")
            if row["status"] != status:
                await conn.execute("UPDATE pet.pets SET status=%s,updated_at=%s WHERE id=%s", (status, at, pet))
                if archive:
                    await mute_pending(conn, member, pet, at, archived=True)
                    await held_for_pet(conn, member, pet, at)
            result = (await pet_rows(conn, member, pet))[0]
        return web.json_response(serialize(result, now=at))

    async def delete_pet(req):
        member = (await require_member(req))["id"]
        pet = uuid_param(req.match_info["id"])
        data = await body_json(req)
        if set(data) != {"confirm"} or not isinstance(data["confirm"], str) or not NAME.fullmatch(data["confirm"]):
            raise Problem("invalid_input")
        async with app[POOL].connection() as conn, conn.transaction():
            row = await lock_pet(conn, member, pet)
            if data["confirm"] != row["name"]:
                raise Problem("confirm_required")
            await delete_records(conn, row, clock())
        return web.Response(status=204)

    async def cleanup(_app):
        async def run():
            while True:
                try:
                    if await purge_one(app[POOL], app[CONFIG].media_dir):
                        continue
                except Exception:
                    logger.error("pet_media_purge_worker_failed")
                await asyncio.sleep(2)

        worker = asyncio.create_task(run())
        try:
            yield
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    app.router.add_post("/api/pets/{id}/mode", change_mode)
    app.router.add_post("/api/pets/{id}/archive", change_archive, name="pet_archive")
    app.router.add_post("/api/pets/{id}/unarchive", change_archive, name="pet_unarchive")
    app.router.add_delete("/api/pets/{id}", delete_pet)
    app.cleanup_ctx.append(cleanup)
