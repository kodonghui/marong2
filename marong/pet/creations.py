"""Owner-scoped creation status and removal of expired creation media."""

import asyncio

from aiohttp import web

from .http import CONFIG, POOL, Problem, require_member, uuid_param
from .log import logger

PRICE_KRW = 5900
OPEN = "('done','rejected','failed_traits','failed_candidates','expired')"


def view(row, candidates=()):
    traits = row["traits"] or {}
    visible_traits = {key: value for key, value in traits.items()
                      if key not in {"confidence", "petVisible", "multiplePets"}}
    return {
        "id": str(row["id"]), "kind": row["kind"], "state": row["state"],
        "traits": visible_traits or None, "multiplePets": traits.get("multiplePets", False),
        "template": row["template"], "preview": media_url(row["preview_id"]) if row["preview_id"] else None,
        "candidates": list(candidates), "chosenId": str(row["chosen_id"]) if row["chosen_id"] else None,
        "regenerationsLeft": 2 - row["regenerations"], "failure": row["failure"], "priceKrw": PRICE_KRW,
        "petId": str(row["pet_id"]) if row.get("pet_id") else None,
        "createdAt": row["created_at"].isoformat(), "expiresAt": row["expires_at"].isoformat(),
    }


def media_url(ident):
    return f"/api/media/{ident}"


async def owned(conn, member_id, ident, *, lock=False):
    cur = await conn.execute(
        """SELECT c.*,p.id AS pet_id FROM pet.creations c LEFT JOIN pet.pets p
           ON p.creation_id=c.id AND p.member_id=c.member_id
           WHERE c.id=%s AND c.member_id=%s""" + (" FOR UPDATE OF c" if lock else ""),
        (ident, member_id),
    )
    row = await cur.fetchone()
    if not row:
        raise Problem("not_found")
    return row


async def describe(conn, row):
    cur = await conn.execute(
        """SELECT id,meta FROM pet.media WHERE creation_id=%s AND member_id=%s AND kind='candidate'
           AND (delete_after IS NULL OR delete_after>now()) ORDER BY created_at,id LIMIT 12""",
        (row["id"], row["member_id"]),
    )
    return view(row, ({"id": str(item["id"]), "url": media_url(item["id"]), "round": item["meta"].get("round", 0)}
                      for item in await cur.fetchall()))


async def get_creation(req):
    member = await require_member(req)
    ident = uuid_param(req.match_info["id"])
    async with req.app[POOL].connection() as conn:
        return web.json_response(await describe(conn, await owned(conn, member["id"], ident)))


async def list_creations(req):
    member = await require_member(req)
    async with req.app[POOL].connection() as conn:
        cur = await conn.execute(
            f"""SELECT * FROM pet.creations WHERE member_id=%s AND state NOT IN {OPEN}
            ORDER BY created_at DESC,id DESC LIMIT 3""", (member["id"],),
        )
        return web.json_response({"items": [await describe(conn, row) for row in await cur.fetchall()]})


async def cleanup(pool, media_dir):
    root = media_dir.resolve()
    async with pool.connection() as conn, conn.transaction():
        # The frozen schema currently permits expiry only after a template is set.
        await conn.execute(
            """UPDATE pet.creations SET state='expired',failure='expired',preview_id=NULL,updated_at=now()
            WHERE state='previewed' AND order_id IS NULL AND expires_at<=now()"""
        )
        await conn.execute(
            """UPDATE pet.media m SET delete_after=now() FROM pet.creations c
            WHERE m.creation_id=c.id AND m.member_id=c.member_id AND c.state='expired'
              AND m.kind IN ('photo','preview') AND (m.delete_after IS NULL OR m.delete_after>now())"""
        )
    async with pool.connection() as conn, conn.transaction():
        cur = await conn.execute(
            """SELECT id,storage_key FROM pet.media WHERE delete_after<=now() AND kind IN ('photo','preview')
            ORDER BY delete_after,id LIMIT 25 FOR UPDATE SKIP LOCKED"""
        )
        for row in await cur.fetchall():
            path = (root / row["storage_key"]).resolve()
            if not path.is_relative_to(root) or path == root:
                logger.error("pet_creation_cleanup_path_invalid")
                continue
            try:
                await asyncio.to_thread(path.unlink, missing_ok=True)
            except OSError:
                logger.error("pet_creation_cleanup_unlink_failed")
                continue
            await conn.execute("DELETE FROM pet.media WHERE id=%s", (row["id"],))


def register(app):
    app.router.add_get("/api/creations", list_creations, allow_head=False)
    app.router.add_get("/api/creations/{id}", get_creation, allow_head=False)
