"""Account-scoped character rows and media file operations."""

import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import os
from pathlib import Path
import tempfile

from PIL import Image

from ..app_session import one


CARDS = """
    SELECT c.*,j.step,j.state AS job_state,j.error
    FROM marong.characters c
    LEFT JOIN LATERAL (
        SELECT step,state,error FROM marong.character_jobs WHERE character_id=c.id ORDER BY id DESC LIMIT 1
    ) j ON true
"""
BASE = "/chat/api/characters"
PHOTOS = ("photo_1", "photo_2", "photo_3")
CANDIDATES = tuple(f"candidate_{i}" for i in range(1, 5))
MAX_CHARACTERS = 3


def image_url(character_id, slot):
    return f"{BASE}/{character_id}/images/{slot}"


class CharacterError(ValueError):
    def __init__(self, code, errors=()):
        super().__init__(code)
        self.code = code
        self.errors = errors


async def query(conn, sql, params=()):
    return await (await conn.execute(sql, params)).fetchall()


async def owned(conn, friend, character, *, lock=False):
    suffix = " FOR UPDATE OF c" if lock else ""
    row = await one(conn, CARDS + " WHERE c.friend_id=%s AND c.id=%s AND c.status<>'retired'" + suffix,
                    (friend, character))
    if not row:
        raise CharacterError("not_found")
    return row


def require_stage(character, *stages):
    if character["job_state"] in {"queued", "running"}:
        raise CharacterError("job_running")
    if character["stage"] not in stages:
        raise CharacterError("wrong_stage")


async def describe(conn, character):
    ident = character["id"]
    media = await query(conn, """
        SELECT slot FROM marong.character_images WHERE character_id=%s AND removed_at IS NULL ORDER BY slot
    """, (ident,))
    job = ({"step": character["step"], "state": character["job_state"], "error": character["error"]}
           if character["step"] is not None else None)
    return {"id": ident, "kind": character["kind"], "stage": character["stage"], "status": character["status"],
            "name": character["name"], "template": character["template"], "traits": character["traits"],
            "tone": character["tone"], "regenLeft": character["regen_left"], "job": job,
            "images": {row["slot"]: image_url(ident, row["slot"]) for row in media}}


async def image_record(conn, character, slot):
    return await one(conn, """
        SELECT path FROM marong.character_images WHERE character_id=%s AND slot=%s AND removed_at IS NULL
    """, (character, slot))


class Media:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = asyncio.Lock()

    def under_root(self, relative):
        full = (self.root / relative).resolve()
        if not full.is_relative_to(self.root):
            raise OSError("invalid_character_image_path")
        return full

    async def read(self, conn, character, slot):
        record = await image_record(conn, character, slot)
        if not record:
            raise CharacterError("not_found")
        return await asyncio.to_thread(self.under_root(record["path"]).read_bytes)

    @asynccontextmanager
    async def change(self, pool):
        async with self.lock:
            batch = FileBatch(self)
            try:
                async with pool.connection() as conn, conn.transaction():
                    yield conn, batch
            except BaseException:
                await asyncio.to_thread(batch.rollback)
                raise
            await asyncio.to_thread(batch.commit)


class FileBatch:
    def __init__(self, media):
        self.media = media
        self.original = {}
        self.removed = set()

    async def replace(self, conn, character, slot, data):
        suffix = "jpg" if slot in PHOTOS else "png"
        relative = f"{character}/{slot}.{suffix}"
        path = self.media.under_root(relative)
        if path not in self.original:
            self.original[path] = await asyncio.to_thread(path.read_bytes) if await asyncio.to_thread(path.exists) else None
        self.removed.discard(path)
        width, height, encoded = await asyncio.to_thread(self.write, path, data, suffix)
        await conn.execute("""
            UPDATE marong.character_images SET removed_at=now()
            WHERE character_id=%s AND slot=%s AND removed_at IS NULL
        """, (character, slot))
        await conn.execute("""
            INSERT INTO marong.character_images(character_id,slot,path,width,height,bytes) VALUES (%s,%s,%s,%s,%s,%s)
        """, (character, slot, relative, width, height, encoded))

    @staticmethod
    def write(path, data, suffix):
        with Image.open(BytesIO(data)) as photo:
            width, height = photo.size
            if suffix == "jpg":
                result = BytesIO()
                rgb = photo.convert("RGB")
                rgb.info.clear()
                rgb.save(result, "JPEG", quality=91)
                data = result.getvalue()
        FileBatch.atomic_write(path, data)
        return width, height, len(data)

    @staticmethod
    def atomic_write(path, data):
        path.parent.mkdir(mode=0o700, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stash:
            staged = Path(stash.name)
            try:
                stash.write(data)
            except BaseException:
                stash.close()
                staged.unlink(missing_ok=True)
                raise
        try:
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)

    async def remove(self, conn, character, slots=None):
        rows = await query(conn, """
            UPDATE marong.character_images SET removed_at=now()
            WHERE character_id=%s AND removed_at IS NULL AND (%s::text[] IS NULL OR slot=ANY(%s::text[]))
            RETURNING path
        """, (character, list(slots) if slots else None, list(slots) if slots else None))
        self.removed.update(self.media.under_root(row["path"]) for row in rows)

    def rollback(self):
        for path, before in self.original.items():
            if before is None:
                path.unlink(missing_ok=True)
            else:
                self.atomic_write(path, before)

    def commit(self):
        for path in self.removed:
            path.unlink(missing_ok=True)
