"""Unified character creation and wardrobe APIs (API-219–229, 238, 242)."""

import asyncio
from decimal import Decimal
import re

from aiohttp import BodyPartReader, web
from psycopg.types.json import Jsonb

from ..app_session import one
from ..pet.cost import month_bounds
from ..unified_prompt import clean, particle
from .graphics import EXPRESSIONS, TEMPLATE_IDS
from .photos import MAX_BODY, MAX_PHOTO, PhotoError, sanitize
from .records import (BASE, CANDIDATES, CARDS, MAX_CHARACTERS, PHOTOS, CharacterError, Media, describe,
                      image_record, image_url, owned, query, require_stage)
from .traits import valid_edits


IDENT = re.compile(r"[0-9]{1,19}")
SLOTS = {*PHOTOS, *CANDIDATES, *EXPRESSIONS, "front", "preview"}


def positive_id(value):
    if type(value) is int and 0 < value < 2**63:
        return value
    if isinstance(value, str) and IDENT.fullmatch(value):
        ident = int(value)
        if 0 < ident < 2**63:
            return ident
    raise CharacterError("invalid_input")


class CharacterAPI:
    def __init__(self, chat, root=None, detector=None, budget=Decimal("20"), *, enabled=True):
        self.chat = chat
        self.pool = chat.store.pool
        self.media = Media(root) if root else None
        self.detector = detector
        self.budget = budget
        self.enabled = enabled and self.media is not None

    async def member(self, req, write=False):
        who = await self.chat.profile.who(req, write=write)
        if not self.enabled:
            raise CharacterError("feature_off" if write else "not_found")
        return who["friend_id"]

    def ident(self, req):
        return positive_id(req.match_info["id"])

    async def reduced_body(self, req, required, optional=()):
        return await self.chat._session_body(req, required, optional)

    async def spent(self, conn):
        now = self.chat.sessions.now()
        start, end = month_bounds(now)
        row = await one(conn, """
            SELECT coalesce(sum(cost_usd),0) AS amount FROM marong.character_jobs WHERE finished_at>=%s AND finished_at<%s
        """, (start, end))
        return row["amount"]

    async def require_budget(self, conn):
        if await self.spent(conn) >= self.budget:
            raise CharacterError("image_budget")

    async def enqueue(self, conn, ident, step):
        await conn.execute("INSERT INTO marong.character_jobs(character_id,step) VALUES (%s,%s)", (ident, step))

    async def response(self, conn, friend, ident, status=200):
        return self.chat._json(status, {"character": await describe(conn, await owned(conn, friend, ident))})

    async def list(self, req):
        friend = await self.member(req)
        async with self.pool.connection() as conn:
            rows = await query(conn, CARDS + " WHERE c.friend_id=%s AND c.status<>'retired' ORDER BY c.id DESC", (friend,))
            return self.chat._json(200, {"characters": [await describe(conn, r) for r in rows], "limit": MAX_CHARACTERS})

    async def get(self, req):
        friend = await self.member(req)
        async with self.pool.connection() as conn:
            return await self.response(conn, friend, self.ident(req))

    async def create(self, req):
        friend = await self.member(req, write=True)
        data = await self.reduced_body(req, "kind")
        if data["kind"] not in ("dog", "cat"):
            raise CharacterError("invalid_input")
        async with self.pool.connection() as conn, conn.transaction():
            await one(conn, "SELECT friend_id FROM marong.friend_profiles WHERE friend_id=%s FOR UPDATE", (friend,))
            await self.require_budget(conn)
            count = await one(conn, "SELECT count(*) AS count FROM marong.characters WHERE friend_id=%s AND status<>'retired'",
                              (friend,))
            if count["count"] >= MAX_CHARACTERS:
                raise CharacterError("too_many_characters")
            row = await one(conn, "INSERT INTO marong.characters(friend_id,kind) VALUES (%s,%s) RETURNING id",
                            (friend, data["kind"]))
            return await self.response(conn, friend, row["id"], 201)

    async def photos(self, req):
        friend = await self.member(req, write=True)
        ident = self.ident(req)
        async with self.pool.connection() as conn:
            require_stage(await owned(conn, friend, ident), "photos", "traits")
        if self.detector is None:
            raise CharacterError("check_unavailable")
        if req.content_length is not None and req.content_length > MAX_BODY:
            raise CharacterError("too_large")
        if req.content_type != "multipart/form-data" or req.headers.get("Content-Encoding"):
            raise CharacterError("invalid_input")
        photos = []
        try:
            form = await req.multipart()
            async for part in form:
                if not isinstance(part, BodyPartReader) or part.name != "photos" or len(photos) >= len(PHOTOS):
                    raise CharacterError("invalid_input")
                raw = bytearray()
                while piece := await part.read_chunk(64 * 1024):
                    raw.extend(piece)
                    if len(raw) > MAX_PHOTO:
                        raise CharacterError("photo_invalid")
                if not raw:
                    raise CharacterError("photo_invalid")
                photos.append(await asyncio.to_thread(sanitize, bytes(raw), len(photos) + 1, self.detector))
        except PhotoError as e:
            raise CharacterError(e.code, [{"field": f"photos.{e.number}", "reason": e.code}]) from None
        except (AssertionError, TypeError) as e:
            raise CharacterError("invalid_input") from e
        if not photos:
            raise CharacterError("invalid_input")
        async with self.media.change(self.pool) as (conn, batch):
            require_stage(await owned(conn, friend, ident, lock=True), "photos", "traits")
            await batch.remove(conn, ident, PHOTOS)
            for slot, photo in zip(PHOTOS, photos):
                await batch.replace(conn, ident, slot, photo.png)
            await self.enqueue(conn, ident, "traits")
            return await self.response(conn, friend, ident, 202)

    async def traits(self, req):
        friend = await self.member(req, write=True)
        ident = self.ident(req)
        data = await self.reduced_body(req, "traits", ("template", "tone"))
        if not data.get("template") or data["template"] not in TEMPLATE_IDS or not valid_edits(data["traits"]):
            raise CharacterError("invalid_input")
        tone = data.get("tone")
        if "tone" in data and (not isinstance(tone, str) or len(tone) > 60):
            raise CharacterError("invalid_input")
        async with self.media.change(self.pool) as (conn, batch):
            row = await owned(conn, friend, ident, lock=True)
            require_stage(row, "traits", "preview")
            kind = row["kind"]
            if (kind != data["traits"].get("species") or not data["template"].startswith(kind)
                    or not {"coatColors", "build"} <= data["traits"].keys()):
                raise CharacterError("invalid_input")
            await batch.remove(conn, ident, ("preview",))
            await conn.execute("""
                UPDATE marong.characters SET stage='preview',template=%s,traits=%s,tone=coalesce(%s,tone) WHERE id=%s
            """, (data["template"], Jsonb(data["traits"]), clean(tone, 60) if tone is not None else None, ident))
            return await self.response(conn, friend, ident)

    async def queue_images(self, req):
        friend = await self.member(req, write=True)
        ident = self.ident(req)
        step = req.match_info["step"]
        async with self.pool.connection() as conn, conn.transaction():
            row = await owned(conn, friend, ident, lock=True)
            await self.require_budget(conn)
            require_stage(row, *("preview", "candidates") if step == "candidates" else ("preview",))
            if step == "candidates":
                if row["stage"] == "candidates":
                    if not row["regen_left"]:
                        raise CharacterError("no_regen_left")
                    await conn.execute("UPDATE marong.characters SET regen_left=regen_left-1 WHERE id=%s", (ident,))
                elif not await image_record(conn, ident, "preview"):
                    raise CharacterError("wrong_stage")
            await self.enqueue(conn, ident, step)
            return await self.response(conn, friend, ident, 202)

    async def pick(self, req):
        friend = await self.member(req, write=True)
        ident = self.ident(req)
        data = await self.reduced_body(req, "slot")
        if data["slot"] not in CANDIDATES:
            raise CharacterError("invalid_input")
        async with self.media.change(self.pool) as (conn, batch):
            require_stage(await owned(conn, friend, ident, lock=True), "candidates", "sheet")
            try:
                chosen = await self.media.read(conn, ident, data["slot"])
            except (CharacterError, OSError) as e:
                raise CharacterError("not_found") from e
            await batch.replace(conn, ident, "front", chosen)
            await conn.execute("UPDATE marong.characters SET stage='sheet' WHERE id=%s", (ident,))
            await self.enqueue(conn, ident, "sheet")
            return await self.response(conn, friend, ident, 202)

    async def name(self, req):
        friend = await self.member(req, write=True)
        ident = self.ident(req)
        chosen = (await self.reduced_body(req, "name"))["name"]
        if (not isinstance(chosen, str) or not 1 <= len(chosen.strip()) <= 12
                or not (name := clean(chosen, 12))):
            raise CharacterError("invalid_input")
        async with self.pool.connection() as conn, conn.transaction():
            require_stage(await owned(conn, friend, ident, lock=True), "name", "done")
            await conn.execute("UPDATE marong.characters SET stage='done',status='ready',name=%s,ready_at=coalesce(ready_at,now()) WHERE id=%s",
                               (name, ident))
            return await self.response(conn, friend, ident)

    async def image(self, req):
        # Current characters stay visible when new creation is disabled.
        friend = (await self.chat.profile.who(req))["friend_id"]
        ident, slot = self.ident(req), req.match_info["slot"]
        if slot not in SLOTS or self.media is None:
            raise CharacterError("not_found")
        async with self.pool.connection() as conn:
            await owned(conn, friend, ident)
            image = await image_record(conn, ident, slot)
            if not image:
                raise CharacterError("not_found")
            path = await asyncio.to_thread(self.media.under_root, image["path"])
            if not await asyncio.to_thread(path.is_file):
                raise CharacterError("not_found")
            req["cache"] = "private, max-age=0"
            return web.FileResponse(path)

    async def try_on(self, req):
        friend = (await self.chat.profile.who(req))["friend_id"]
        if not self.enabled:
            raise CharacterError("not_found")
        ident = self.ident(req)
        async with self.pool.connection() as conn:
            row = await owned(conn, friend, ident)
            if row["status"] != "ready":
                raise CharacterError("not_ready")
        name = row["name"]
        return self.chat._json(200, {"botName": name, "faces": {slot: image_url(ident, slot)
                                                                  for slot in ("front", *EXPRESSIONS)},
                                    "chatSample": [{"from": "me", "text": "오늘 뭐 했어?"},
                                                   {"from": "bot", "text": "나는 네 생각 하면서 기다렸지. 너는 뭐 했어?"},
                                                   {"from": "bot", "text": "밥은 챙겨 먹었어?"}],
                                    "callLine": f"여보세요, 나 {name}{particle(name)}."})

    async def apply(self, req):
        friend = await self.member(req, write=True)
        requested = (await self.reduced_body(req, "characterId"))["characterId"]
        async with self.pool.connection() as conn, conn.transaction():
            name, ident = "마롱이", None
            if requested is not None:
                if type(requested) is not int:
                    raise CharacterError("invalid_input")
                ident = positive_id(requested)
                row = await owned(conn, friend, ident, lock=True)
                if row["status"] != "ready":
                    raise CharacterError("not_ready")
                name = row["name"]
            await conn.execute("""
                UPDATE marong.friend_profiles SET character_id=%s,bot_name=%s,updated_at=now() WHERE friend_id=%s
            """, (ident, name, friend))
        return self.chat._json(200, await self.chat.profile.read(friend))

    async def retire(self, req):
        friend = await self.member(req, write=True)
        ident = self.ident(req)
        async with self.media.change(self.pool) as (conn, batch):
            row = await owned(conn, friend, ident, lock=True)
            if row["job_state"] in {"queued", "running"}:
                raise CharacterError("job_running")
            await conn.execute("UPDATE marong.characters SET status='retired',retired_at=now() WHERE id=%s", (ident,))
            await conn.execute("""
                UPDATE marong.friend_profiles SET character_id=NULL,bot_name='마롱이',updated_at=now()
                WHERE friend_id=%s AND character_id=%s
            """, (friend, ident))
            await batch.remove(conn, ident)
        return web.Response(status=204)

    async def page(self, req):
        from ..app_chat import Problem
        from ..app_session import SessionError
        try:
            await self.member(req)
        except (Problem, SessionError) as error:
            if error.code not in {"login_required", "unauthenticated"}:
                raise
            raise web.HTTPFound("/chat/login") from None
        return self.chat.unified_page("character")

    def register(self, router):
        router.add_get("/chat/character/new", self.page)
        router.add_get("/chat/character/{id}/{stage:photos|traits|preview|candidates|name|try}", self.page)
        router.add_get(BASE, self.list)
        router.add_post(BASE, self.create)
        router.add_get(BASE + "/{id}", self.get)
        router.add_patch(BASE + "/{id}", self.name)
        router.add_delete(BASE + "/{id}", self.retire)
        router.add_put(BASE + "/{id}/photos", self.photos)
        router.add_patch(BASE + "/{id}/traits", self.traits)
        router.add_post(BASE + "/{id}/{step:preview|candidates}", self.queue_images)
        router.add_post(BASE + "/{id}/pick", self.pick)
        router.add_get(BASE + "/{id}/try", self.try_on)
        router.add_get(BASE + "/{id}/images/{slot}", self.image)
        router.add_patch("/chat/api/profile/character", self.apply)
