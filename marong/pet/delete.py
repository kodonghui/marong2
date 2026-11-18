"""Account erasure in the isolated service (SPEC-314)."""

import asyncio
from datetime import datetime, timedelta, timezone

from aiohttp import web

from .http import CONFIG, COOKIE, POOL, Problem, body_json, require_member
from .creations import cleanup as cleanup_creations
from .jobs import JobQueue
from .log import logger, member_ref
from .quota import release_expired

RETRY = timedelta(hours=1)
LEASE = timedelta(minutes=5)
MAX_ATTEMPTS = 2_147_483_647


async def request_delete(req):
    member = await require_member(req)
    data = await body_json(req)
    if set(data) != {"confirm"} or not isinstance(data["confirm"], str) or len(data["confirm"]) > 10:
        raise Problem("invalid_input")
    if data["confirm"] != "계정 지우기":
        raise Problem("confirm_required")
    async with req.app[POOL].connection() as conn, conn.transaction():
        updated = await conn.execute(
            """UPDATE pet.members SET status='deleting',deleting_since=now(),sub_hash=NULL
            WHERE id=%s AND status='active' RETURNING id""", (member["id"],),
        )
        if not await updated.fetchone():
            raise Problem("unauthenticated")
        await conn.execute("DELETE FROM pet.sessions WHERE member_id=%s", (member["id"],))
        await conn.execute(
            """UPDATE pet.subscriptions SET status='canceling',canceled_at=COALESCE(canceled_at,now()),
            next_charge_at=NULL,retry_at=NULL WHERE member_id=%s AND status='active'""", (member["id"],),
        )
        await conn.execute("INSERT INTO pet.jobs(kind,member_id) VALUES ('account_delete',%s)", (member["id"],))
    req.pop("member", None)
    response = web.json_response({"ok": True}, status=202)
    response.del_cookie(COOKIE, path="/")
    return response


async def _erase(pool, job, root, revoke):
    async with pool.connection() as conn, conn.transaction():
        claimed = await conn.execute(
            """SELECT id FROM pet.jobs WHERE id=%s AND status='running' AND lease_until=%s
            AND lease_until>now() FOR UPDATE""", (job["id"], job["lease_until"]),
        )
        if not await claimed.fetchone():
            return
        member = job["member_id"]
        await conn.execute("""
            UPDATE pet.members SET status='deleting',deleting_since=now(),sub_hash=NULL
            WHERE id=%s AND status='minor_locked' AND minor_locked_at<=now()-interval '7 days'
        """, (member,))
        owned = await conn.execute("SELECT id FROM pet.members WHERE id=%s AND status='deleting' FOR UPDATE", (member,))
        if not await owned.fetchone():
            await conn.execute("DELETE FROM pet.jobs WHERE id=%s", (job["id"],))
            return
        keys = await conn.execute("SELECT billing_key_enc FROM pet.subscriptions WHERE member_id=%s "
                                  "AND billing_key_enc IS NOT NULL", (member,))
        for key in await keys.fetchall():
            if revoke is None:
                raise RuntimeError("billing_revocation_unavailable")
            await asyncio.wait_for(revoke(key["billing_key_enc"]), 15)
        cursor = await conn.execute("SELECT storage_key FROM pet.media WHERE member_id=%s", (member,))
        for row in await cursor.fetchall():
            path = (root / row["storage_key"]).resolve()
            if not path.is_relative_to(root) or path == root:
                raise RuntimeError("invalid_storage_path")
            await asyncio.to_thread(path.unlink, missing_ok=True)
        await conn.execute("DELETE FROM pet.jobs WHERE member_id=%s", (member,))
        await conn.execute("DELETE FROM pet.settings WHERE starts_with(key,%s)", (f"ticket_grant:{member}:",))
        await conn.execute("DELETE FROM pet.members WHERE id=%s", (member,))


async def erase_next(pool, root, *, revoke=None):
    queue = JobQueue(pool)
    job = await queue.claim(("account_delete",), lease=LEASE, attempts=MAX_ATTEMPTS)
    if not job:
        return False
    try:
        await _erase(pool, job, root.resolve(), revoke)
    except Exception:
        await queue.fail(job, "account_delete_retry", retry_after=RETRY, attempts=MAX_ATTEMPTS)
        if datetime.now(timezone.utc) - job["queued_at"] >= timedelta(hours=24):
            logger.error("pet_delete_overdue member=%s", member_ref(str(job["member_id"])))
    return True


def register(app, *, revoke=None):
    app.router.add_delete("/api/me", request_delete)

    async def maintenance(app):
        stop = asyncio.Event()

        async def run():
            while not stop.is_set():
                try:
                    await erase_next(app[POOL], app[CONFIG].media_dir, revoke=revoke)
                    await release_expired(app[POOL], datetime.now(timezone.utc))
                    await cleanup_creations(app[POOL], app[CONFIG].media_dir)
                except Exception:
                    logger.error("pet_maintenance_failed")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30)
                except TimeoutError:
                    pass

        worker = asyncio.create_task(run())
        try:
            yield
        finally:
            stop.set()
            await worker

    app.cleanup_ctx.append(maintenance)
