"""Resume queued character work and publish complete image sets (SPEC-378–380)."""

import asyncio
from decimal import Decimal
import logging

from psycopg.types.json import Jsonb

from ..app_session import one
from ..pet.cost import microusd
from .graphics import EXPRESSIONS, MATCH, InvalidArtwork, alpha, fit_score, head_in_box, preview_png
from .photos import crop_pick
from .records import CANDIDATES, PHOTOS, CharacterError, query
from .traits import EDITABLE, template_for, valid_result


log = logging.getLogger(__name__)
WHOLE_PHOTO = (0, 0, 1, 1)


def photo_selection(ident, slots, number, box):
    if (type(number) is int and 1 <= number <= len(slots)
            and isinstance(box, list) and len(box) == 4
            and all(type(value) in (int, float) and 0 <= value <= 1 for value in box)):
        x, y, w, h = box
        if w >= .1 and h >= .1 and x + w <= 1 and y + h <= 1:
            return {"photo": slots[number - 1], "box": box}
    log.info("pet_box_fallback character=%s", ident)
    if not slots:
        raise CharacterError("photo_missing")
    return {"photo": slots[0], "box": list(WHOLE_PHOTO)}


class WorkerBudget:
    def __init__(self, store, prices):
        self.store = store
        self.prices = prices

    async def record(self, job, run):
        cost = Decimal(microusd(self.prices, run)) / 1_000_000
        await self.store._one("""
            UPDATE marong.character_jobs SET cost_usd=cost_usd+%s WHERE id=%s AND state='running'
            RETURNING id
        """, (cost, job))


class CharacterWorker:
    def __init__(self, api, templates, extractor, editor, settings, prices, *, on_complete=None):
        self.api = api
        self.pool = api.pool
        self.templates = templates
        self.extract = extractor
        self.editor = editor
        self.settings = settings
        self.prices = prices
        self.on_complete = on_complete

    async def recover(self):
        async with self.pool.connection() as conn, conn.transaction():
            stale = await query(conn, """
                SELECT j.id,j.character_id,j.step,j.attempts,c.stage FROM marong.character_jobs j
                JOIN marong.characters c ON c.id=j.character_id WHERE j.state='running'
                FOR UPDATE OF j,c
            """)
            for row in stale:
                await self.fail(conn, row, "timeout")

    async def run(self):
        await self.recover()
        while True:
            try:
                ran = await self.step()
            except Exception as e:
                log.warning("character_job_error error=%s", type(e).__name__)
                await self.recover()
                ran = False
            if not ran:
                await asyncio.sleep(1)

    async def claim(self):
        async with self.pool.connection() as conn, conn.transaction():
            return await one(conn, """
                WITH next_job AS (
                    SELECT j.id FROM marong.character_jobs j WHERE j.state='queued' ORDER BY j.id LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE marong.character_jobs j SET state='running',attempts=j.attempts+1,
                      started_at=coalesce(j.started_at,now())
                FROM next_job n,marong.characters c
                WHERE j.id=n.id AND c.id=j.character_id
                RETURNING j.*,c.friend_id,c.stage,c.kind,c.traits,c.template,c.photo_pick
            """)

    async def fail(self, conn, job, error):
        retry = job["attempts"] < 3 and error not in {"model_refused", "budget", "photo_missing"}
        if retry:
            await conn.execute("UPDATE marong.character_jobs SET state='queued' WHERE id=%s", (job["id"],))
            return
        await conn.execute("""
            UPDATE marong.character_jobs SET state='failed',error=%s,finished_at=now() WHERE id=%s
        """, (error, job["id"]))
        if job["step"] == "candidates" and job["stage"] == "candidates":
            await conn.execute("UPDATE marong.characters SET regen_left=least(2,regen_left+1) WHERE id=%s",
                               (job["character_id"],))

    async def step(self):
        job = await self.claim()
        if job is None:
            return False
        error = None
        try:
            async with asyncio.timeout(1800 if job["step"] in {"candidates", "sheet"} else 120):
                traits, drawings, selected = await self.process(job)
        except CharacterError as e:
            error = e.code
        except TimeoutError:
            error = "timeout"
        except ValueError as e:
            error = "model_refused" if str(e) in {"vision_refused", "image_refused"} else "model_error"
        except (OSError, RuntimeError, TypeError, KeyError):
            error = "model_error"
        if error:
            async with self.pool.connection() as conn, conn.transaction():
                before = await self.api.spent(conn)
                await self.fail(conn, job, error)
                after = await self.api.spent(conn)
            self.warn_budget(before, after)
            return True
        await self.publish(job, traits, drawings, selected)
        if self.on_complete and job["step"] in {"candidates", "sheet"}:
            try:
                await self.on_complete(job["friend_id"], job["step"], job["character_id"])
            except Exception as e:
                log.warning("character_job_notice_error error=%s", type(e).__name__)
        return True

    def warn_budget(self, before, after):
        warning = self.api.budget * Decimal(".8")
        if before < warning <= after:
            log.info("image_budget_warn")

    async def photo_slots(self, conn, ident):
        saved = await query(conn, """
            SELECT slot FROM marong.character_images WHERE character_id=%s AND removed_at IS NULL
            AND slot=ANY(%s) ORDER BY slot
        """, (ident, list(PHOTOS)))
        return [row["slot"] for row in saved]

    async def photo_reference(self, ident, selected):
        try:
            async with self.pool.connection() as conn:
                if selected is None:
                    selected = photo_selection(ident, await self.photo_slots(conn, ident), None, None)
                raw = await self.api.media.read(conn, ident, selected["photo"])
            return await asyncio.to_thread(crop_pick, raw, selected["box"])
        except (CharacterError, OSError, ValueError) as e:
            raise CharacterError("photo_missing") from e

    async def process(self, job):
        step, ident = job["step"], job["character_id"]
        model = self.settings.vision_model if step == "traits" else self.settings.image_model
        if model not in self.prices.prices:
            raise CharacterError("budget")
        if step == "traits":
            async with self.pool.connection() as conn:
                slots = await self.photo_slots(conn, ident)
                try:
                    photos = [await self.api.media.read(conn, ident, slot) for slot in slots]
                except (CharacterError, OSError) as e:
                    raise CharacterError("photo_missing") from e
            if not photos:
                raise CharacterError("photo_missing")
            observed = await self.extract(photos, job)
            if not valid_result(observed) or not observed["petVisible"] or observed["species"] != job["kind"]:
                raise CharacterError("model_refused")
            selected = photo_selection(ident, slots, observed["bestPhoto"], observed["petBox"])
            return {key: value for key, value in observed.items() if key in EDITABLE}, {}, selected
        template = job["template"]
        if step in {"preview", "candidates"}:
            photo = await self.photo_reference(ident, job["photo_pick"])
        if step == "preview":
            raw = await self.editor.preview(model=model, template=template, traits=job["traits"], photo=photo, job=job)
            return None, {"preview": await asyncio.to_thread(preview_png, raw)}, None
        reference = self.templates.mask(template)
        if step == "candidates":
            drawings = {}
            for index, slot in enumerate(CANDIDATES, 1):
                async def generate():
                    return await self.editor.candidate(model=model, template=template, traits=job["traits"], note=None,
                                                       slot=index, photo=photo, job=job)
                drawings[slot] = await self.fitted(generate, reference, MATCH)
            return None, drawings, None
        async with self.pool.connection() as conn:
            front = await self.api.media.read(conn, ident, "front")
        drawings = {}
        head = self.templates.head(template)
        for slot in EXPRESSIONS:
            async def generate():
                return await self.editor.expression(model=model, template=template, front=front, expression=slot, job=job)
            drawings[slot] = await self.fitted(generate, reference, .85, head)
        return None, drawings, None

    async def fitted(self, draw, reference, threshold, box=None):
        for _ in range(3):
            try:
                image = await asyncio.to_thread(preview_png, await draw())
            except InvalidArtwork:
                continue
            if await asyncio.to_thread(fit_score, image, reference) >= threshold:
                if box is None or await asyncio.to_thread(head_in_box, alpha(image), box):
                    return image
        raise CharacterError("check_failed")

    async def publish(self, job, traits, drawings, selected):
        ident, step = job["character_id"], job["step"]
        async with self.api.media.change(self.pool) as (conn, batch):
            before = await self.api.spent(conn)
            locked = await one(conn, """
                SELECT id FROM marong.character_jobs WHERE id=%s AND state='running' FOR UPDATE
            """, (job["id"],))
            if not locked:
                return
            for slot, data in drawings.items():
                await batch.replace(conn, ident, slot, data)
            if step == "traits":
                await conn.execute("""
                    UPDATE marong.characters SET stage='traits',traits=%s,template=%s,photo_pick=%s WHERE id=%s
                """, (Jsonb(traits), template_for(traits), Jsonb(selected), ident))
            elif step == "candidates":
                await conn.execute("UPDATE marong.characters SET stage='candidates' WHERE id=%s", (ident,))
            elif step == "sheet":
                await conn.execute("UPDATE marong.characters SET stage='name',photo_pick=NULL WHERE id=%s", (ident,))
                await batch.remove(conn, ident, PHOTOS)
            await conn.execute("UPDATE marong.character_jobs SET state='done',finished_at=now() WHERE id=%s", (job["id"],))
            await self.api.chat.usage.record(job["friend_id"], conn=conn, images=len(drawings))
            after = await self.api.spent(conn)
        self.warn_budget(before, after)
