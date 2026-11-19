"""Idempotent diary fixes and redraws (API-111/112)."""

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timedelta
from math import ceil

from .app_chat import UUID, Problem, bad
from .app_diary import _date
from .diary import KST, diary_day, drawing_allowed, drawing_allowed_in, read_day_bundle, scene_error
from .diary_models import validate_draft
from .diary_worker import insert_picture, record_run

log = logging.getLogger("marong.diary")
LIMITS = {"fix": ("fixes_used", 5), "redraw": ("redraws_used", 2)}
LEASES = {"fix": timedelta(seconds=90), "redraw": timedelta(seconds=120)}


class DiaryEdits:
    def __init__(self, api):
        self.api = api
        self.chat = api.chat
        self.store = api.store
        self.models = self.chat.diary_models

    async def fix(self, req):
        return await self._edit(req, "fix", "text")

    async def redraw(self, req):
        return await self._edit(req, "redraw", "change")

    async def _edit(self, req, kind, field):
        deadline = asyncio.get_running_loop().time() + 40
        friend = (await self.chat._who(req, write=True))["friend_id"]
        day = _date(req.match_info["date"], "date")
        key = req.headers.get("Idempotency-Key", "").lower()
        if not UUID.fullmatch(key):
            raise bad(("Idempotency-Key", "bad_format" if key else "required"))
        data = await self.chat._body(req)
        revision = data.get("revision")
        note = data.get(field, "" if kind == "redraw" else None)
        if set(data) - {"revision", field}:
            raise bad(("body", "bad_format"))
        if type(revision) is not int or not 1 <= revision <= 2_147_483_647:
            raise bad(("revision", "bad_format"))
        if not isinstance(note, str):
            raise bad((field, "bad_format"))
        if (kind == "fix" and not 1 <= len(note.strip()) <= 200) or (kind == "redraw" and len(note) > 200):
            raise bad((field, "bad_format"))
        row, code, changed, retry = await self._begin(friend, day, kind, key, revision)
        trace = req["trace_id"]
        if kind == "fix" and row:
            code, changed = await self._run_fix(row, key, note.strip(), trace, deadline)
        if code != "ok":
            if code == "too_many_requests":
                raise Problem(code, headers={"Retry-After": str(retry)},
                              title="고치기와 다시 그리기를 합쳐 1분에 5번 넘게 보냄")
            raise Problem(code)
        if kind == "fix":
            day_data = await self.api.day_data(friend, day, datetime.now(KST))
            return self.chat._json(200, {"sceneChanged": changed, "day": day_data})
        try:
            day_data = await self.api.day_data(friend, day, datetime.now(KST))
        finally:
            if row:
                self.chat._spawn(self._run_redraw(row, note.strip(), trace))
        return self.chat._json(202, {"day": day_data})

    async def _begin(self, friend, day, kind, key, revision):
        async with self.store.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('diary_request:'||%s::text,0))", (friend,))
            now = datetime.now(KST)
            cursor = await conn.execute(
                """SELECT r.kind,r.result_code,r.scene_changed,r.created_at,d.diary_date
                FROM marong.diary_requests r JOIN marong.diaries d ON d.id=r.diary_id
                WHERE r.friend_id=%s AND r.idem_key=%s""", (friend, key),
            )
            prior = await cursor.fetchone()
            if prior:
                if prior["kind"] != kind or prior["diary_date"] != day:
                    raise bad(("Idempotency-Key", "bad_format"))
                code = prior["result_code"]
                if code is None and prior["created_at"] + LEASES["fix"] <= now:
                    code = "fix_failed"
                    await self._finish_request(conn, friend, key, code)
                retry = await self._retry_after(conn, friend, now) if code == "too_many_requests" else None
                return None, code or "busy", prior["scene_changed"], retry or 1

            cursor = await conn.execute(
                """SELECT * FROM marong.diaries WHERE friend_id=%s AND diary_date=%s AND diary_date<=%s FOR UPDATE""",
                (friend, day, diary_day(now)),
            )
            row = await cursor.fetchone()
            if row is None:
                return None, "not_ready", None, None

            used, limit = LIMITS[kind]
            retry = await self._retry_after(conn, friend, now)
            if retry:
                code = "too_many_requests"
            elif row["state"] != "ready":
                code = "not_ready"
            elif revision != row["revision"]:
                code = "stale_revision"
            elif row[used] >= limit:
                code = f"{kind}_limit"
            elif row["busy_until"] and row["busy_until"] > now:
                code = "busy"
            elif kind == "redraw" and not await drawing_allowed_in(conn, self.api.draw_budget, now):
                code = "drawing_budget"
            else:
                code = None
            result = code or ("ok" if kind == "redraw" else None)
            await conn.execute(
                """INSERT INTO marong.diary_requests (friend_id,idem_key,diary_id,kind,result_code,created_at,finished_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (friend, key, row["id"], kind, result, now, now if result else None),
            )
            if code:
                return None, code, None, retry
            row["busy"] = kind
            row["busy_until"] = now + LEASES[kind]
            await conn.execute(
                """UPDATE marong.diaries SET busy=%s,busy_until=%s,updated_at=now(),
                    redraw_result=CASE WHEN %s='redraw' THEN NULL ELSE redraw_result END,
                    redraw_at=CASE WHEN %s='redraw' THEN NULL ELSE redraw_at END
                WHERE id=%s""",
                (kind, row["busy_until"], kind, kind, row["id"]),
            )
            return row, "ok", None, None

    async def _retry_after(self, conn, friend, now):
        cursor = await conn.execute(
            """SELECT created_at FROM marong.diary_requests WHERE friend_id=%s AND created_at>%s
            AND result_code IS DISTINCT FROM 'too_many_requests' ORDER BY created_at DESC OFFSET 4 LIMIT 1""",
            (friend, now - timedelta(minutes=1)),
        )
        row = await cursor.fetchone()
        return max(1, ceil((row["created_at"] + timedelta(minutes=1) - now).total_seconds())) if row else None

    async def _current(self, row):
        return await self.store._one(
            """SELECT r.title,r.weather,r.body,r.scene,f.name,l.hair,l.glasses,l.top
            FROM marong.diary_revisions r JOIN marong.friends f ON f.id=%s
            LEFT JOIN marong.diary_looks l ON l.friend_id=f.id
            WHERE r.diary_id=%s AND r.revision=%s""",
            (row["friend_id"], row["id"], row["revision"]),
        )

    @staticmethod
    async def _owns_edit(conn, row):
        cursor = await conn.execute(
            """SELECT 1 FROM marong.diaries WHERE id=%s AND state='ready' AND busy=%s AND busy_until=%s
            AND busy_until>clock_timestamp() AND revision=%s FOR UPDATE""",
            (row["id"], row["busy"], row["busy_until"], row["revision"]),
        )
        return await cursor.fetchone() is not None

    @staticmethod
    async def _finish_request(conn, friend, key, code, revision=None, scene_changed=None):
        await conn.execute(
            """UPDATE marong.diary_requests SET result_code=%s,result_revision=%s,scene_changed=%s,finished_at=now()
            WHERE friend_id=%s AND idem_key=%s AND result_code IS NULL""",
            (code, revision, scene_changed, friend, key),
        )

    async def _log(self, row, kind, origin, model, trace, sent, result):
        async with self.store.pool.connection() as conn:
            return await record_run(conn, row["id"], kind, origin, 1, trace, model,
                                    "medium" if kind != "draw" else "low", sent, result)

    async def _run_fix(self, row, key, note, trace, deadline):
        draft = None
        scene_changed = False
        run_id = None
        if self.models:
            try:
                async with asyncio.timeout_at(deadline - 1):
                    current = await self._current(row)
                    look = current["hair"] is not None
                    async with self.store.pool.connection() as conn:
                        bundle = await read_day_bundle(conn, row["friend_id"], row["diary_date"])
                    old = {field: current[field] for field in ("title", "weather", "body", "scene")}
                    sent = datetime.now(KST)
                    response = await self.models.fix(current["name"], look, old, bundle.value, note)
                    response, draft, scene_changed = self._check_fix(old, response, look)
                    run_id = await self._log(row, "fix", "fix", self.models.text_model, trace, sent, response)
            except TimeoutError:
                draft = None
        code = "fix_failed"
        async with self.store.pool.connection() as conn, conn.transaction():
            revision = None
            if await self._owns_edit(conn, row):
                if draft and run_id:
                    revision = row["revision"] + 1
                    await self._add_revision(conn, row, revision, "fix", draft, run_id)
                    await conn.execute("UPDATE marong.diaries SET revision=%s,fixes_used=fixes_used+1 WHERE id=%s",
                                       (revision, row["id"]))
                    code = "ok"
                await conn.execute("UPDATE marong.diaries SET busy=NULL,busy_until=NULL,updated_at=now() WHERE id=%s",
                                   (row["id"],))
            await self._finish_request(conn, row["friend_id"], key, code, revision, scene_changed if revision else None)
        return code, scene_changed

    @staticmethod
    def _check_fix(old, response, look):
        if response.outcome != "ok":
            return response, None, False
        value = response.value
        if not isinstance(value, dict) or type(value.get("sceneChanged")) is not bool:
            return replace(response, outcome="invalid", error="schema"), None, False
        draft = {field: item for field, item in value.items() if field != "sceneChanged"}
        problem, scene_problem = validate_draft(draft, look)
        if problem:
            return replace(response, outcome="invalid", error=problem), None, False
        if scene_problem:
            draft["scene"] = old["scene"]
            response = replace(response, error=f"scene:{scene_problem}")
        return response, draft, old["scene"] != draft["scene"]

    @staticmethod
    async def _add_revision(conn, row, revision, source, draft, run_id):
        await conn.execute(
            """INSERT INTO marong.diary_revisions(diary_id,revision,source,title,weather,body,scene,ai_run_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (row["id"], revision, source, draft["title"], draft["weather"], draft["body"], draft["scene"], run_id),
        )

    async def _run_redraw(self, row, note, trace):
        try:
            await self._redraw(row, note, trace)
        except Exception as error:
            log.warning("diary_redraw_error %s", type(error).__name__)
            try:
                await self._finish_redraw(row, "draw_failed")
            except Exception as update_error:
                log.warning("diary_redraw_update_error %s", type(update_error).__name__)

    async def _redraw(self, row, note, trace):
        if not self.models or not self.models.image_key:
            await self._finish_redraw(row, "draw_failed")
            return
        current = await self._current(row)
        look = current if current["hair"] else None
        scene = current["scene"]
        scene_run = None
        if note or not scene:
            sent = datetime.now(KST)
            result = await self.models.scene(bool(look), current["body"], scene, note)
            proposed = result.value.get("scene") if isinstance(result.value, dict) else None
            if result.outcome == "ok":
                if (not isinstance(proposed, str) or set(result.value) != {"scene"}):
                    result = replace(result, outcome="invalid", error="schema")
                elif error := scene_error(proposed, has_look=bool(look)):
                    result = replace(result, outcome="invalid", error=f"scene:{error}")
            scene_run = await self._log(row, "scene", "redraw", self.models.text_model, trace, sent, result)
            if result.outcome != "ok":
                code = "scene_rejected" if (result.error or "").startswith("scene:") else "draw_failed"
                await self._finish_redraw(row, code)
                return
            scene = proposed
        if scene_error(scene, has_look=bool(look)):
            await self._finish_redraw(row, "scene_rejected")
            return
        sent = datetime.now(KST)
        if not await drawing_allowed(self.store, self.api.draw_budget, sent):
            await self._finish_redraw(row, "drawing_budget")
            return
        result = await self.models.draw(scene, look)
        run_id = await self._log(row, "draw", "redraw", self.models.image_model, trace, sent, result)
        if result.outcome == "ok":
            revision = {**current, "scene": scene} if scene != current["scene"] else None
            await self._finish_redraw(row, "done", result.value, run_id, revision, scene_run)
        else:
            await self._finish_redraw(row, "draw_refused" if result.outcome == "refused" else "draw_failed")

    async def _finish_redraw(self, row, result, picture=None, run_id=None, draft=None, scene_run=None):
        async with self.store.pool.connection() as conn, conn.transaction():
            if not await self._owns_edit(conn, row):
                return
            if picture:
                revision = row["revision"]
                if draft:
                    revision += 1
                    await self._add_revision(conn, row, revision, "redraw", draft, scene_run)
                picture_id = await insert_picture(conn, row, revision, "redraw", run_id, picture)
                await conn.execute(
                    """UPDATE marong.diaries SET revision=%s,drawing_id=%s,redraws_used=redraws_used+1 WHERE id=%s""",
                    (revision, picture_id, row["id"]),
                )
            await conn.execute(
                """UPDATE marong.diaries SET redraw_result=%s,redraw_at=now(),busy=NULL,busy_until=NULL,updated_at=now()
                WHERE id=%s""", (result, row["id"]),
            )
