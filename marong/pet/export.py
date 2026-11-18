"""Create member-owned, expiring pet ZIP downloads (API-183/184/185)."""

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import file_digest
from html import escape
from pathlib import Path
import tempfile
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from aiohttp import web
from psycopg.types.json import Jsonb

from .compose import BACKGROUNDS, compose
from .http import CONFIG, POOL, Problem, require_member, uuid_param
from .jobs import JobQueue
from .lifecycle import lock_pet
from .log import logger
from .push import SENDER, notify
from .quota import KST, quota_day
from .watermark import NOTICE, marked_png


LEASE = timedelta(minutes=10)
KEEP = timedelta(hours=24)
DESIGN = Path(__file__).resolve().parents[2] / "design/pet"
SYSTEM_FONT = Path("/usr/share/fonts/truetype/nanum/NanumSquareR.ttf")
EXPRESSIONS = ("front", "smile", "excited", "sleepy", "surprised", "sad", "pout")


def under(root, key):
    path = (root / key).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("invalid_export_path")
    return path


def render_diary(entry, pet, media, items, assets, item_dir):
    choice = entry["composite"]
    stage = BACKGROUNDS.get(choice.get("backgroundId"), BACKGROUNDS["home_livingroom"])
    scene = stage.asset(assets / "backgrounds")
    if not scene.is_file():
        stage = BACKGROUNDS["home_livingroom"]
        scene = stage.asset(assets / "backgrounds")
    expression = choice.get("expression") or "front"
    source = media.get(pet["sheet"].get(expression)) or media[pet["sheet"]["front"]]
    outfit = {}
    for slot, item_id in choice.get("outfit", {}).items():
        item = items.get(item_id)
        layer = item.get("layers", {}).get(pet["template"]) if item else None
        if layer:
            path = under(under(item_dir, item_id), layer)
            if path.is_file():
                outfit[slot] = path
    return compose(scene, stage, source, outfit=outfit)


def build_zip(destination, pet, media, entries, messages, items, assets, font, *, item_dir=None):
    safe_name = escape(pet["name"])
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as bundle:
        bundle.mkdir("pictures/")
        for expression in EXPRESSIONS:
            ident = pet["sheet"].get(expression)
            if ident is not None:
                bundle.writestr(f"pictures/{expression}.png", marked_png(media[ident], font))
        diary = [f'<!doctype html><html lang="ko"><meta charset="utf-8"><title>{safe_name}</title>'
                 '<style>body{font-family:system-ui,sans-serif}img{max-width:100%}p{white-space:pre-wrap}</style>'
                 f'<main><h1>{safe_name}</h1>']
        for entry in entries:
            name = f"pictures/{entry['kind']}-{entry['day'].isoformat()}.png"
            if entry["picture_id"] is not None:
                image = media[str(entry["picture_id"])]
            elif entry["composite"]:
                image = render_diary(entry, pet, media, items, assets, item_dir or assets / "items")
            else:
                image = None
            if image is not None:
                bundle.writestr(name, marked_png(image, font))
            picture = f'<img src="{name}" alt="{NOTICE}">' if image is not None else ""
            diary.append(f'<article><time>{entry["day"].isoformat()}</time>'
                         f'<h2>{escape(entry["title"] or "")}</h2>{picture}'
                         f'<p>{escape(entry["body"] or "")}</p></article>')
        diary.append("</main></html>")
        bundle.writestr("diary.html", "".join(diary))
        with bundle.open("chat.txt", "w") as chat:
            for entry in messages:
                stamp = entry["created_at"].astimezone(KST).isoformat(timespec="seconds")
                label = "나" if entry["role"] == "member" else pet["name"]
                chat.write(f"[{stamp}] {label}: {entry['content']}\n".encode())
        bundle.writestr("README.txt", NOTICE + "\nAI가 만든 캐릭터·그림·글이 포함되어 있어요.\n")


async def material(pool, member, pet_id, root):
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cur = await conn.execute("SELECT * FROM pet.pets WHERE id=%s AND member_id=%s", (pet_id, member))
        pet = await cur.fetchone()
        if pet is None:
            raise ValueError("export_pet_missing")
        cur = await conn.execute("""
            SELECT id,storage_key FROM pet.media WHERE member_id=%s AND pet_id=%s AND kind IN
             ('sheet_front','sheet_expression','scene','farewell')
        """, (member, pet_id))
        media = {str(row["id"]): under(root, row["storage_key"]) for row in await cur.fetchall()}
        cur = await conn.execute("""
            SELECT day,kind,title,body,picture_id,composite FROM pet.diary_entries
            WHERE member_id=%s AND pet_id=%s AND status='ready' ORDER BY day,kind
        """, (member, pet_id))
        entries = await cur.fetchall()
        item_ids = {value for entry in entries for value in ((entry["composite"] or {}).get("outfit") or {}).values() if value}
        items = {}
        if item_ids:
            cur = await conn.execute("SELECT id,assets FROM pet.items WHERE id=ANY(%s::uuid[])", (list(item_ids),))
            items = {str(row["id"]): row["assets"] for row in await cur.fetchall()}
        cur = await conn.execute("""
            SELECT role,content,created_at FROM pet.messages
            WHERE member_id=%s AND pet_id=%s AND role IN ('member','pet') ORDER BY seq
        """, (member, pet_id))
        return pet, media, entries, await cur.fetchall(), items


def fingerprint(path):
    with path.open("rb") as source:
        return path.stat().st_size, file_digest(source, "sha256").digest()


async def publish(pool, member, pet, job, temp_zip, final, key, clock):
    size, digest = await asyncio.to_thread(fingerprint, temp_zip)
    async with pool.connection() as conn, conn.transaction():
        await lock_pet(conn, member, pet)
        cur = await conn.execute("""
            SELECT id FROM pet.jobs WHERE id=%s AND status='running' AND lease_until=%s
            AND lease_until>now() FOR UPDATE
        """, (job["id"], job["lease_until"]))
        if not await cur.fetchone():
            return False
        ident = uuid4()
        expires = clock() + KEEP
        await conn.execute("""
            INSERT INTO pet.media(id,member_id,pet_id,kind,storage_key,content_type,bytes,sha256,delete_after)
            VALUES (%s,%s,%s,'export',%s,'application/zip',%s,%s,%s)
        """, (ident, member, pet, key, size, digest, expires))
        await conn.execute("""
            UPDATE pet.jobs SET status='done',finished_at=now(),lease_until=NULL,result_media_id=%s WHERE id=%s
        """, (ident, job["id"]))
        temp_zip.replace(final)
    return True


async def run_export(pool, root, assets, font, clock, sender):
    queue = JobQueue(pool)
    job = await queue.claim(("export",), lease=LEASE, attempts=2)
    if job is None:
        return False
    member, pet = job["member_id"], job["pet_id"]
    key = f"exports/{uuid4()}.zip"
    final = under(root, key)
    ready = False
    try:
        data = await material(pool, member, pet, root)
        final.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".export-", dir=final.parent) as folder:
            temp_zip = Path(folder) / "archive.zip"
            # Finish the offloaded write before tearing down its temporary directory on shutdown.
            write = asyncio.create_task(asyncio.to_thread(build_zip, temp_zip, *data, assets, font,
                                                          item_dir=root / "items"))
            try:
                await asyncio.shield(write)
            except asyncio.CancelledError:
                await asyncio.gather(write, return_exceptions=True)
                raise
            committing = asyncio.create_task(publish(pool, member, pet, job, temp_zip, final, key, clock))
            try:
                ready = await asyncio.shield(committing)
            except asyncio.CancelledError:
                await committing
                raise
    except Exception:
        final.unlink(missing_ok=True)
        await queue.fail(job, "export_failed")
        logger.warning("pet_export_failed")
    if ready and sender:
        await notify(pool, member, pet, "export", send=sender)
    return True


async def expire_exports(pool, clock):
    async with pool.connection() as conn, conn.transaction():
        cur = await conn.execute("""
            DELETE FROM pet.media m USING (
                SELECT id FROM pet.media WHERE kind='export' AND delete_after<=%s
                ORDER BY delete_after,id LIMIT 100 FOR UPDATE SKIP LOCKED
            ) expired WHERE m.id=expired.id RETURNING m.storage_key
        """, (clock(),))
        keys = [row["storage_key"] for row in await cur.fetchall()]
        if keys:
            await conn.execute("INSERT INTO pet.jobs(kind,ref) VALUES ('cleanup',%s)", (Jsonb({"storage": keys}),))


def view(row, at):
    expiry = row.get("delete_after")
    status = row["status"]
    if status == "done" and (expiry is None or expiry <= at):
        raise Problem("not_found")
    if status == "canceled":
        status = "failed"
    return {"id": str(row["id"]), "status": status, "readyUntil": expiry.isoformat() if expiry else None}


def register(app, *, assets=None, font=None, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    assets = Path(assets or DESIGN).resolve()
    font = Path(font or SYSTEM_FONT)

    async def start(req):
        member = (await require_member(req))["id"]
        pet = uuid_param(req.match_info["id"])
        at = clock()
        day = quota_day(at).isoformat()
        async with app[POOL].connection() as conn, conn.transaction():
            await lock_pet(conn, member, pet)
            cur = await conn.execute("""
                SELECT id FROM pet.jobs WHERE kind='export' AND member_id=%s AND pet_id=%s
                  AND (status IN ('queued','running') OR (status='done' AND ref->>'day'=%s)) LIMIT 1
            """, (member, pet, day))
            if await cur.fetchone():
                raise Problem("export_limit")
            new = await conn.execute("""
                INSERT INTO pet.jobs(kind,member_id,pet_id,ref,queued_at)
                VALUES ('export',%s,%s,%s,%s) RETURNING id,status
            """, (member, pet, Jsonb({"day": day}), at))
            created = await new.fetchone()
        return web.json_response(view(created, at), status=202)

    async def read(req):
        member = (await require_member(req))["id"]
        ident = uuid_param(req.match_info["id"])
        at = clock()
        async with app[POOL].connection() as conn:
            cur = await conn.execute("""
                SELECT j.id,j.status,m.delete_after,m.storage_key FROM pet.jobs j
                LEFT JOIN pet.media m ON m.id=j.result_media_id AND m.member_id=j.member_id
                WHERE j.id=%s AND j.member_id=%s AND j.kind='export'
            """, (ident, member))
            row = await cur.fetchone()
        if row is None:
            raise Problem("not_found")
        result = view(row, at)
        if req.match_info.route.name != "pet_export_download":
            return web.json_response(result)
        if result["status"] != "done":
            raise Problem("not_found")
        source = under(app[CONFIG].media_dir.resolve(), row["storage_key"])
        if not source.is_file():
            raise Problem("not_found")
        return web.FileResponse(source, headers={"Content-Type": "application/zip",
                                                "Content-Disposition": 'attachment; filename="marong-pet.zip"'})

    async def worker(_app):
        async def run():
            pool = app[POOL]
            root = app[CONFIG].media_dir.resolve()
            sender = app.get(SENDER)
            while True:
                try:
                    await expire_exports(pool, clock)
                    if await run_export(pool, root, assets, font, clock, sender):
                        continue
                except Exception:
                    logger.error("pet_export_worker_failed")
                await asyncio.sleep(2)

        task = asyncio.create_task(run())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.router.add_post("/api/pets/{id}/export", start)
    app.router.add_get("/api/exports/{id}", read, allow_head=False)
    app.router.add_get("/api/exports/{id}/download", read, allow_head=False, name="pet_export_download")
    app.cleanup_ctx.append(worker)
