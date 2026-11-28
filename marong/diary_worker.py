"""Night diary jobs and morning notices (SPEC-151, 153, 155–157)."""

import asyncio
import logging
import random
from dataclasses import replace
from datetime import datetime, time, timedelta
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from .app_push import TALK
from .diary import KST, STOP_AT, WRITE_FROM, drawing_allowed, read_day_bundle, scene_error
from .diary_models import ModelResult, PET_PROMPT_VERSION, PROMPT_VERSION, validate_draft
from .room_scope import writing_room_key
from .scene_picture import VERSION as SCENE_PROMPT_VERSION

log = logging.getLogger("marong.diary")
NOTICE_FROM = time(8, 30)
LEASE = timedelta(minutes=10)
WRITE_RETRIES = (timedelta(minutes=30), timedelta(hours=2))
DRAW_RETRY = timedelta(minutes=30)
NOTICE_LINES = (
    "어젯밤에 일기 썼어! 📔",
    "어제 일기 다 썼다~ 보러 올래? 📔",
    "마롱이 일기 왔어 📔",
)
_STOPPED = """
NOT EXISTS (
  SELECT 1 FROM marong.diary_settings s
  WHERE s.friend_id=d.friend_id AND s.stop_now AND s.from_date <= %(today)s
    AND s.id >= COALESCE((
        SELECT id FROM marong.diary_settings
        WHERE friend_id=d.friend_id AND from_date<=d.diary_date
        ORDER BY id DESC LIMIT 1
    ), 0)
)
"""


async def record_run(conn, diary_id, kind, origin, attempt, trace, model, style, sent, result, *, reask=False,
                     prompt_version=PROMPT_VERSION):
    effort, thinking = ("low", None) if kind == "draw" else (style, "adaptive")
    cursor = await conn.execute(
        """INSERT INTO marong.diary_ai_runs (
            diary_id, kind, origin, attempt, reask, trace_id, model, prompt_version, effort, thinking,
            sent_at, first_token_ms, total_ms, input_tokens, image_input_tokens, output_tokens,
            cache_read_tokens, cache_write_tokens, cost_usd, cost_estimated, outcome, stop_reason, error_code
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id""",
        (diary_id, kind, origin, attempt, reask, trace, model, prompt_version, effort, thinking,
         sent, result.first_ms, result.total_ms, result.input_tokens, result.image_input_tokens,
         result.output_tokens, result.cache_read_tokens, result.cache_write_tokens, result.cost,
         result.estimated, result.outcome, result.stop, result.error),
    )
    return (await cursor.fetchone())["id"]


async def insert_picture(conn, row, revision, origin, run_id, picture):
    cursor = await conn.execute(
        """INSERT INTO marong.diary_drawings (diary_id,revision,origin,ai_run_id,format,width,height,image)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (row["id"], revision, origin, run_id, picture.format, picture.width, picture.height, picture.data),
    )
    return (await cursor.fetchone())["id"]


class DiaryWorker:
    def __init__(self, store, models, delivery, budget, *, now=None, rng=None, on_saved=None, unified=False,
                 pet_voice=False, scenes=None, wear_catalog=None):
        self.store = store
        self.models = models
        self.delivery = delivery
        self.budget = budget
        self.now = now or (lambda: datetime.now(KST))
        self.rng = rng or random.SystemRandom()
        self.on_saved = on_saved
        self.running = False
        self.unified = unified
        self.pet_voice = pet_voice
        self.scenes = scenes
        self.wear_catalog = wear_catalog

    def destination(self, friend):
        if self.unified:
            return f"SELECT {writing_room_key(friend)} AS room_key,NULL::text AS channel_id"
        return (f"SELECT room_key,channel_id FROM marong.discord_dm_links "
                f"WHERE friend_id={friend} AND channel_id IS NOT NULL")

    async def run(self):
        job = None
        try:
            while True:
                if job is None or job.done():
                    job = asyncio.create_task(self.tick())
                await asyncio.sleep(60)
        finally:
            if job is not None:
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)

    async def tick(self):
        if self.running:
            return
        self.running = True
        try:
            now = self.now()
            await self._expire(now)
            if NOTICE_FROM <= now.time() < STOP_AT:
                await self._notice(now)
            now = self.now()
            if WRITE_FROM <= now.time() < STOP_AT:
                await self._queue(now)
                row = await self._claim(now)
                if row:
                    await self._work(row, datetime.combine(now.date(), STOP_AT, KST))
        except psycopg.Error as error:
            log.warning("diary_db_unavailable %s", type(error).__name__)
        except Exception as error:
            log.error("diary_job_error %s", type(error).__name__)
        finally:
            self.running = False

    async def _expire(self, now):
        last = now.date() if now.time() >= STOP_AT else now.date() - timedelta(days=1)
        params = {"now": now, "last": last}
        async with self.store.pool.connection() as conn, conn.transaction():
            await conn.execute(
                """UPDATE marong.diaries SET
                    state=CASE WHEN revision IS NULL THEN 'failed' ELSE 'ready' END,
                    fail_reason=CASE WHEN revision IS NULL THEN 'late' END,
                    placeholder_reason=CASE WHEN revision IS NOT NULL THEN 'late' END,
                    ready_at=CASE WHEN revision IS NOT NULL THEN %(now)s::timestamptz END,
                    notice_state=CASE WHEN revision IS NULL THEN 'none' ELSE 'cancelled' END,
                    lease_until=NULL, updated_at=%(now)s
                WHERE state IN ('pending','writing','drawing')
                  AND GREATEST(diary_date+1, (updated_at AT TIME ZONE 'Asia/Seoul')::date) <= %(last)s""",
                params,
            )
            await conn.execute(
                """UPDATE marong.diaries SET notice_state='cancelled', notice_next_at=NULL, updated_at=%(now)s
                WHERE notice_state='waiting' AND diary_date+1 <= %(last)s""", params,
            )

    async def _queue(self, now):
        params = {"now": now, "today": now.date(), "day": now.date() - timedelta(days=1)}
        async with self.store.pool.connection() as conn:
            await conn.execute(
                f"""INSERT INTO marong.diaries (friend_id,diary_date,next_at,created_at,updated_at)
                SELECT d.friend_id,%(day)s,%(now)s,%(now)s,%(now)s
                FROM (SELECT c.friend_id, %(day)s::date AS diary_date
                    FROM call.callers c JOIN LATERAL ({self.destination("c.friend_id")}) l ON l.room_key IS NOT NULL
                    WHERE c.enabled) d
                WHERE (SELECT enabled FROM marong.diary_settings
                       WHERE friend_id=d.friend_id AND from_date<=d.diary_date ORDER BY id DESC LIMIT 1)
                  AND {_STOPPED}
                ON CONFLICT (friend_id,diary_date) DO NOTHING""", params,
            )

    async def _claim(self, now):
        return await self.store._one(
            """WITH due AS (
                SELECT id FROM marong.diaries WHERE state IN ('pending','writing','drawing')
                  AND diary_date < %s AND next_at <= %s AND (lease_until IS NULL OR lease_until <= %s)
                ORDER BY next_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
            )
            UPDATE marong.diaries d SET
                state=CASE WHEN d.revision IS NULL THEN 'writing' ELSE 'drawing' END,
                lease_until=%s, updated_at=%s
            FROM due WHERE d.id=due.id RETURNING d.*""",
            (now.date(), now, now, now + LEASE, now),
        )

    async def _work(self, row, deadline):
        trace = uuid4().hex
        if row["state"] == "writing":
            row = await self._write(row, deadline, trace)
        if row:
            await self._draw(row, deadline, trace)

    async def _owned(self, conn, row):
        cursor = await conn.execute(
            "SELECT 1 FROM marong.diaries WHERE id=%s AND lease_until=%s FOR UPDATE",
            (row["id"], row["lease_until"]),
        )
        return await cursor.fetchone() is not None

    async def _writer(self, row):
        character_id = row["character_id"]
        if character_id is None and row["attempts"] == 0:
            updated = await self.store._one("""
                UPDATE marong.diaries d SET character_id=(
                    SELECT c.id FROM marong.friend_profiles p
                    JOIN marong.characters c ON c.id=p.character_id AND c.friend_id=d.friend_id AND c.status='ready'
                    WHERE p.friend_id=d.friend_id
                )
                WHERE d.id=%s AND d.lease_until=%s AND d.character_id IS NULL RETURNING character_id
            """, (row["id"], row["lease_until"]))
            character_id = updated["character_id"] if updated else None
        if self.pet_voice and character_id is not None:
            return await self.store._one("""
                SELECT name,kind,owner_call FROM marong.characters WHERE id=%s AND friend_id=%s
            """, (character_id, row["friend_id"]))
        return None

    async def _write(self, row, deadline, trace):
        async with self.store.pool.connection() as conn:
            bundle = await read_day_bundle(conn, row["friend_id"], row["diary_date"], unified=self.unified)
        now = self.now()
        if not bundle.enough or now >= deadline:
            await self.store._one(
                """UPDATE marong.diaries SET state=%s,fail_reason=%s,lease_until=NULL,updated_at=%s
                WHERE id=%s AND lease_until=%s RETURNING id""",
                ("failed" if now >= deadline else "skipped", "late" if now >= deadline else None,
                 now, row["id"], row["lease_until"]),
            )
            return None
        friend = await self.store._one(
            """SELECT f.name, l.hair IS NOT NULL AS has_look FROM marong.friends f
            LEFT JOIN marong.diary_looks l ON l.friend_id=f.id WHERE f.id=%s""", (row["friend_id"],),
        )
        attempt = min(row["attempts"] + 1, 3)
        origin = "night" if attempt == 1 else "retry"
        writer = await self._writer(row) if self.unified else None
        draft, scene_problem, run_id, outcome = await self._draft(
            row["id"], friend, bundle.value, attempt, origin, trace, deadline, writer=writer,
        )
        async with self.store.pool.connection() as conn, conn.transaction():
            if not await self._owned(conn, row):
                return None
            now = self.now()
            if now >= deadline or not draft:
                if now >= deadline:
                    failure = "late"
                elif outcome == "refused":
                    failure = "refused"
                else:
                    failure = "write_failed" if attempt == 3 else None
                next_at = now if failure else now + WRITE_RETRIES[attempt - 1]
                await conn.execute(
                    """UPDATE marong.diaries SET state=%s,fail_reason=%s,attempts=%s,next_at=%s,
                    lease_until=NULL,updated_at=%s WHERE id=%s""",
                    ("failed" if failure else "pending", failure, attempt, next_at, now, row["id"]),
                )
                return None
            scene = None if scene_problem else draft["scene"]
            await conn.execute(
                """INSERT INTO marong.diary_revisions(diary_id,revision,source,title,weather,body,scene,ai_run_id)
                VALUES (%s,1,'write',%s,%s,%s,%s,%s)""",
                (row["id"], draft["title"], draft["weather"], draft["body"], scene, run_id),
            )
            new_lease = now + LEASE
            cursor = await conn.execute(
                """UPDATE marong.diaries SET state='drawing',attempts=%s,revision=1,next_at=%s,
                updated_at=%s,lease_until=%s WHERE id=%s RETURNING *""",
                (attempt, now, now, new_lease, row["id"]),
            )
            return await cursor.fetchone()

    async def _draft(self, diary_id, friend, bundle, attempt, origin, trace, deadline, *, writer=None):
        previous = reason = None
        valid_text = None
        options = {"character": writer} if writer else {}
        version = PET_PROMPT_VERSION if writer else PROMPT_VERSION
        for reask in (False, True):
            sent = self.now()
            if sent >= deadline:
                break
            try:
                async with asyncio.timeout((deadline - sent).total_seconds()):
                    result = await self.models.write(friend["name"], friend["has_look"], bundle,
                                                     previous=previous, reason=reason, **options)
            except TimeoutError:
                result = ModelResult(outcome="timeout", error="deadline")
            problem = scene_problem = None
            if result.outcome == "ok":
                problem, scene_problem = validate_draft(result.value, friend["has_look"])
            error = problem or (f"scene:{scene_problem}" if scene_problem else None)
            async with self.store.pool.connection() as conn:
                run_id = await record_run(
                    conn, diary_id, "write", origin, attempt, trace, self.models.text_model, self.models.effort,
                    sent, replace(result, outcome="invalid", error=error) if error else result,
                    reask=reask, prompt_version=version,
                )
            if result.outcome != "ok":
                if valid_text:
                    return valid_text
                return None, None, run_id, result.outcome
            if not error:
                return result.value, None, run_id, "ok"
            if valid_text:
                return valid_text
            if scene_problem:
                valid_text = (result.value, scene_problem, run_id, "ok")
            if problem not in (None, "title_length", "body_length"):
                break
            previous, reason = result.value, error
        if valid_text:
            return valid_text
        return None, None, None, "invalid"

    async def _draw(self, row, deadline, trace):
        context = await self.store._one(
            """SELECT r.scene,r.weather,f.name AS friend_name,l.hair,l.glasses,l.top FROM marong.diary_revisions r
            JOIN marong.diaries d ON d.id=r.diary_id
            JOIN marong.friends f ON f.id=d.friend_id
            LEFT JOIN marong.diary_looks l ON l.friend_id=d.friend_id
            WHERE r.diary_id=%s AND r.revision=%s""", (row["id"], row["revision"]),
        )
        look = context if context["hair"] else None
        scene = context["scene"]
        pet_scene = self.scenes is not None and row.get("character_id") is not None
        now = self.now()
        placeholder = None
        if now >= deadline:
            placeholder = "late"
        elif not scene or scene_error(scene, has_look=bool(look)):
            placeholder = "scene_rejected"
        elif not self.models.image_key:
            placeholder = "draw_unavailable"
        elif not pet_scene and not await drawing_allowed(self.store, self.budget, now):
            placeholder = "drawing_budget"
        if placeholder:
            async with self.store.pool.connection() as conn, conn.transaction():
                if await self._owned(conn, row):
                    await self._ready(conn, row, self.now(), None, placeholder, row["draw_tries"])
            if placeholder == "draw_unavailable":
                log.warning("diary_draw_unavailable")
            return
        attempt = min(row["draw_tries"] + 1, 2)
        origin = "night" if attempt == 1 else "retry"
        sent = self.now()
        if sent >= deadline:
            async with self.store.pool.connection() as conn, conn.transaction():
                if await self._owned(conn, row):
                    await self._ready(conn, row, sent, None, "late", row["draw_tries"])
            return
        try:
            async with asyncio.timeout((deadline - sent).total_seconds()):
                if pet_scene:
                    result = await self.scenes.diary_art(row, scene, look, context["weather"], context["friend_name"])
                else:
                    from .diary_models import marong_outfit_snapshot, outfit_snapshot_prompts
                    catalog = self.wear_catalog if row.get('character_id') is None else None
                    snapshot = await marong_outfit_snapshot(self.store, catalog, row['friend_id'])
                    outfit = outfit_snapshot_prompts(catalog, snapshot) if catalog else []
                    result = await self.models.draw(scene, look, outfit=outfit) if outfit else await self.models.draw(scene, look)
                    if catalog and result.outcome == 'ok' and snapshot != await marong_outfit_snapshot(self.store, catalog, row['friend_id']):
                        result = replace(result, value=None, outcome='error', error='outfit_changed')
        except TimeoutError:
            result = ModelResult(outcome="timeout", error="deadline")
        async with self.store.pool.connection() as conn:
            model = self.scenes.model if pet_scene else self.models.image_model
            version = SCENE_PROMPT_VERSION if pet_scene else PROMPT_VERSION
            run_id = await record_run(conn, row["id"], "draw", origin, attempt, trace, model,
                                      "low", sent, result, prompt_version=version)
        async with self.store.pool.connection() as conn, conn.transaction():
            if not await self._owned(conn, row):
                return
            done = self.now()
            picture_id = None
            if done >= deadline:
                placeholder = "late"
            elif result.outcome == "ok":
                picture_id = await insert_picture(conn, row, row["revision"], origin, run_id, result.value)
            elif result.outcome == "refused":
                placeholder = "draw_refused"
            elif result.error in ("billing_or_auth", "references"):
                placeholder = "draw_unavailable"
                log.warning("diary_draw_unavailable")
            elif attempt == 1:
                await conn.execute(
                    """UPDATE marong.diaries SET draw_tries=1,next_at=%s,lease_until=NULL,updated_at=%s
                    WHERE id=%s""", (done + DRAW_RETRY, done, row["id"]),
                )
                return
            else:
                placeholder = "draw_failed"
            await self._ready(conn, row, done, picture_id, placeholder, attempt)

    async def _ready(self, conn, row, now, drawing, placeholder, draw_tries):
        morning = row["diary_date"] + timedelta(days=1)
        end = datetime.combine(morning, STOP_AT, KST)
        at = max(now, datetime.combine(morning, NOTICE_FROM, KST))
        await conn.execute(
            """UPDATE marong.diaries SET state='ready',drawing_id=%s,placeholder_reason=%s,draw_tries=%s,
                ready_at=%s,notice_state=%s,notice_next_at=%s,lease_until=NULL,updated_at=%s WHERE id=%s""",
            (drawing, placeholder, draw_tries, now, "waiting" if at < end else "cancelled",
             at if at < end else None, now, row["id"]),
        )

    async def _notice(self, now):
        params = {"now": now, "today": now.date(), "day": now.date() - timedelta(days=1)}
        row = await self.store._one(
            f"""WITH due AS (
                SELECT d.id, l.room_key, l.channel_id FROM marong.diaries d
                JOIN call.callers c ON c.friend_id=d.friend_id AND c.enabled
                JOIN LATERAL ({self.destination("d.friend_id")}) l ON l.room_key IS NOT NULL
                WHERE d.diary_date=%(day)s AND d.notice_state='waiting' AND d.notice_next_at<=%(now)s
                    AND d.state='ready' AND NOT d.hidden AND {_STOPPED}
                ORDER BY d.notice_next_at,d.id LIMIT 1 FOR UPDATE OF d SKIP LOCKED
            )
            UPDATE marong.diaries d SET notice_state='sending',notice_sending_at=%(now)s,updated_at=%(now)s
            FROM due WHERE d.id=due.id
            RETURNING d.*,due.room_key,due.channel_id""", params,
        )
        if not row:
            return
        previous = await self.store._one(
            """SELECT notice_line FROM marong.diaries WHERE friend_id=%s AND notice_state='sent'
            ORDER BY notified_at DESC,id DESC LIMIT 1""", (row["friend_id"],),
        )
        last = previous["notice_line"] if previous else None
        line = self.rng.choice([line for line in range(1, 4) if line != last])
        first = NOTICE_LINES[line - 1]
        text = f"{first}\n{self.delivery.origin}/chat/diary/{row['diary_date'].isoformat()}"
        end = datetime.combine(now.date(), STOP_AT, KST)
        still_eligible = await self.store._one(
            f"""SELECT id FROM marong.diaries d WHERE id=%(id)s AND notice_state='sending'
            AND NOT hidden AND {_STOPPED}""", {"id": row["id"], "today": now.date()},
        )
        left = int((end - self.now()).total_seconds())
        outcome, meta = "later", {}
        if still_eligible and left > 0:
            if self.unified:
                sent = await self.delivery.say(
                    row["friend_id"], text, kind="diary", app_channel=TALK, ttl_s=left, app_text=first,
                    meta={"diary": True}, key=f"app-diary:{row['id']}",
                )
                outcome = "sent" if sent else "later"
            else:
                outcome, meta = await self.delivery.say(
                    row["friend_id"], row["channel_id"], text, kind="diary", app_channel=TALK,
                    ttl_s=left, open_path="/chat/", app_text=first,
                )
        done = self.now()
        attempts = row["notice_attempts"] + (outcome != "later")
        next_at = done + timedelta(minutes=1 if outcome == "later" else 10)
        if outcome == "sent":
            state = "sent"
        elif not still_eligible or next_at >= end:
            state = "cancelled"
        else:
            state = "failed" if attempts >= 3 else "waiting"
        async with self.store.pool.connection() as conn, conn.transaction():
            await conn.execute(
                """UPDATE marong.diaries SET notice_state=%s,notice_attempts=%s,notice_next_at=%s,
                    notified_at=%s,notice_line=%s,updated_at=%s WHERE id=%s AND notice_state='sending'""",
                (state, attempts, next_at if state == "waiting" else None, done if state == "sent" else None,
                 line if state == "sent" else None, done, row["id"]),
            )
            if state == "sent" and not self.unified:
                await conn.execute(
                    "INSERT INTO marong.messages(room_key,role,content,meta) VALUES (%s,'assistant',%s,%s)",
                    (row["room_key"], text, Jsonb({**meta, "diary": True, "delivered": True})),
                )
        if state == "sent" and self.on_saved:
            self.on_saved()
