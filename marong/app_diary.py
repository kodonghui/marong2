"""Authenticated routes for one friend's diary."""

import re
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path

from aiohttp import web

from .app_chat import UUID, Problem, bad
from .diary import KST, diary_day, drawing_allowed
from .diary_models import GLASSES, HAIR, WEATHER

_PREFIX = "/chat/diary/api"
_PAGE = "/chat/diary/"
_STATIC = Path(__file__).with_name("app_chat_static") / "diary"
_FILES = {"diary.css": "text/css", "tokens.css": "text/css",
          "diary.js": "text/javascript", "sheets.js": "text/javascript", "decor.js": "text/javascript",
          "Gaegu-Regular.woff2": "font/woff2", "Gaegu-OFL.txt": "text/plain"}
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MONTH = re.compile(r"[0-9]{4}-[0-9]{2}")
_VISIBLE = "state='ready' AND NOT hidden"
_LOOK = {
    "hair": HAIR,
    "glasses": GLASSES,
    "top": frozenset({"white", "black", "gray", "navy", "beige", "pink", "yellow", "green"}),
}


def _iso(value):
    return value.isoformat() if value is not None else None


def _date(value, field):
    if value and _DATE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise bad((field, "bad_format"))


class AppDiary:
    def __init__(self, chat):
        self.chat = chat
        self.store = chat.store
        self.draw_budget = chat.pet_app_settings.diary_image_budget

    async def page(self, req):
        return web.FileResponse(_STATIC / "index.html", headers={"Content-Type": "text/html; charset=utf-8"})

    async def file(self, req):
        name = req.match_info["name"]
        return web.FileResponse(_STATIC / name, headers={"Content-Type": _FILES[name]})

    async def latest(self, req):
        friend = (await self.chat._who(req))["friend_id"]
        row = await self.store._one(
            f"""SELECT
              (SELECT max(diary_date) FROM marong.diaries WHERE friend_id=%s AND {_VISIBLE}) AS date,
              COALESCE((SELECT enabled FROM marong.diary_settings
                        WHERE friend_id=%s ORDER BY id DESC LIMIT 1), false) AS enabled""",
            (friend, friend),
        )
        return self.chat._json(200, {"date": _iso(row["date"]), "enabled": row["enabled"]})

    async def month(self, req):
        friend = (await self.chat._who(req))["friend_id"]
        month = req.query.get("month", "")
        if not _MONTH.fullmatch(month):
            raise bad(("month", "bad_format"))
        start = _date(month + "-01", "month")
        last = start.replace(day=monthrange(start.year, start.month)[1])
        rows = await self.store._all(
            """SELECT d.diary_date, r.weather, d.stamped_at IS NOT NULL AS stamped
            FROM marong.diaries d JOIN marong.diary_revisions r ON r.diary_id=d.id AND r.revision=d.revision
            WHERE d.friend_id=%s AND d.state='ready' AND NOT d.hidden AND d.diary_date BETWEEN %s AND %s
            ORDER BY d.diary_date""", (friend, start, last),
        )
        return self.chat._json(200, {"month": month,
            "days": [{"date": _iso(row["diary_date"]), "weather": row["weather"], "stamped": row["stamped"]}
                     for row in rows]})

    async def day(self, req):
        friend = (await self.chat._who(req))["friend_id"]
        day = _date(req.match_info["date"], "date")
        return await self._day_response(friend, day, datetime.now(KST))

    async def _day_response(self, friend, day, now):
        return self.chat._json(200, await self.day_data(friend, day, now))

    async def day_data(self, friend, day, now):
        character_columns = ("c.id AS writer_id, c.name AS writer_name, c.kind AS writer_kind, c.status AS writer_status,"
                             if self.chat.sessions else "")
        character_join = ("LEFT JOIN marong.characters c ON c.id=d.character_id AND c.friend_id=d.friend_id"
                          if self.chat.sessions else "")
        row = await self.store._one(
            f"""WITH params AS (SELECT %s::bigint AS friend, %s::date AS day, %s::date AS today)
            SELECT d.state, d.revision, d.drawing_id, d.hidden, d.stamped_at, d.busy, d.busy_until,
                   d.fixes_used, d.redraws_used, d.redraw_result, d.redraw_at,
                   r.title, r.weather, r.body, {character_columns}
                   (SELECT max(diary_date) FROM marong.diaries
                    WHERE friend_id=p.friend AND {_VISIBLE} AND diary_date<p.day) AS prev,
                   (SELECT min(diary_date) FROM marong.diaries
                    WHERE friend_id=p.friend AND {_VISIBLE} AND diary_date>p.day) AS next
            FROM params p
            LEFT JOIN marong.diaries d ON d.friend_id=p.friend AND d.diary_date=p.day AND p.day<=p.today
            LEFT JOIN marong.diary_revisions r ON r.diary_id=d.id AND r.revision=d.revision
            {character_join}""",
            (friend, day, diary_day(now)),
        )
        state = row["state"] or "none"
        content = await self._content(row, now) if state == "ready" else None
        if state in ("pending", "drawing"):
            state = "writing"
        return {"date": day.isoformat(), "state": state,
                "prev": _iso(row["prev"]), "next": _iso(row["next"]), "diary": content}

    async def _ready(self, conn, friend, day, now):
        if day > diary_day(now):
            raise Problem("not_ready")
        cur = await conn.execute(
            """SELECT id, revision, busy_until, hidden, stamped_at FROM marong.diaries
            WHERE friend_id=%s AND diary_date=%s AND state='ready' FOR UPDATE""",
            (friend, day),
        )
        row = await cur.fetchone()
        if row is None:
            raise Problem("not_ready")
        return row

    async def put_weather(self, req):
        friend = (await self.chat._who(req, write=True))["friend_id"]
        day = _date(req.match_info["date"], "date")
        data = await self.chat._body(req)
        revision, weather = data.get("revision"), data.get("weather")
        if set(data) - {"revision", "weather"}:
            raise bad(("body", "bad_format"))
        if type(revision) is not int or not 1 <= revision <= 2_147_483_647:
            raise bad(("revision", "bad_format"))
        if not isinstance(weather, str) or weather not in WEATHER:
            raise bad(("weather", "bad_format"))
        now = datetime.now(KST)
        async with self.store.pool.connection() as conn, conn.transaction():
            diary = await self._ready(conn, friend, day, now)
            if diary["revision"] != revision:
                raise Problem("stale_revision")
            if diary["busy_until"] and diary["busy_until"] > datetime.now(KST):
                raise Problem("busy")
            cur = await conn.execute(
                """INSERT INTO marong.diary_revisions (diary_id, revision, source, title, weather, body, scene)
                SELECT diary_id, revision+1, 'weather', title, %s, body, scene
                FROM marong.diary_revisions WHERE diary_id=%s AND revision=%s AND weather<>%s
                RETURNING revision""", (weather, diary["id"], revision, weather),
            )
            changed = await cur.fetchone()
            if changed:
                await conn.execute("UPDATE marong.diaries SET revision=%s, updated_at=now() WHERE id=%s",
                                   (changed["revision"], diary["id"]))
        return await self._day_response(friend, day, now)

    async def put_hidden(self, req):
        return await self._put_flag(req, "hidden")

    async def put_stamp(self, req):
        return await self._put_flag(req, "stamped")

    async def _put_flag(self, req, field):
        friend = (await self.chat._who(req, write=True))["friend_id"]
        day = _date(req.match_info["date"], "date")
        data = await self.chat._body(req)
        if set(data) != {field} or type(data[field]) is not bool:
            raise bad((field, "bad_format"))
        value = data[field]
        now = datetime.now(KST)
        async with self.store.pool.connection() as conn, conn.transaction():
            diary = await self._ready(conn, friend, day, now)
            if field == "hidden" and diary["hidden"] != value:
                await conn.execute(
                    """UPDATE marong.diaries SET hidden=%s, updated_at=now(),
                    notice_next_at=CASE WHEN %s AND notice_state IN ('none','waiting','failed')
                                        THEN NULL ELSE notice_next_at END,
                    notice_state=CASE WHEN %s AND notice_state IN ('none','waiting','failed')
                                      THEN 'cancelled' ELSE notice_state END
                    WHERE id=%s""", (value, value, value, diary["id"]),
                )
            if field == "stamped" and (diary["stamped_at"] is not None) != value:
                await conn.execute(
                    """UPDATE marong.diaries SET stamped_at=CASE WHEN %s THEN clock_timestamp() END,
                    updated_at=now() WHERE id=%s""", (value, diary["id"]),
                )
        return await self._day_response(friend, day, now)

    async def _content(self, row, now):
        busy = row["busy"] if row["busy_until"] and row["busy_until"] > now else None
        fixes = 5 - row["fixes_used"]
        redraws = 2 - row["redraws_used"]
        fix_block = "fix_limit" if not fixes else "busy" if busy else None
        redraw_block = "redraw_limit" if not redraws else "busy" if busy else None
        scene_redraw = self.chat.diary_scenes is not None and row.get("writer_id") is not None
        if redraw_block is None and not scene_redraw and not await drawing_allowed(self.store, self.draw_budget, now):
            redraw_block = "drawing_budget"
        drawing_id = row["drawing_id"]
        writer = None
        if row.get("writer_id") is not None:
            writer = {"id": row["writer_id"], "name": row["writer_name"], "kind": row["writer_kind"],
                      "faceUrl": f"/chat/api/characters/{row['writer_id']}/images/smile",
                      "active": row["writer_status"] == "ready"}
        last = {"result": row["redraw_result"], "at": _iso(row["redraw_at"])} if row["redraw_result"] else None
        if row["busy"] == "redraw" and busy is None:
            last = {"result": "draw_failed", "at": _iso(row["busy_until"])}
        return {
            "revision": row["revision"], "title": row["title"], "weather": row["weather"], "body": row["body"],
            "drawing": {"id": str(drawing_id) if drawing_id else None, "kind": "ai" if drawing_id else "placeholder"},
            "writer": writer,
            "hidden": row["hidden"], "stampedAt": _iso(row["stamped_at"]), "busy": busy,
            "fix": {"left": fixes, "blocked": fix_block},
            "redraw": {"left": redraws, "blocked": redraw_block, "last": last},
        }

    async def hidden(self, req):
        friend = (await self.chat._who(req))["friend_id"]
        before = _date(req.query["before"], "before") if "before" in req.query else None
        rows = await self.store._all(
            """SELECT d.diary_date, r.title FROM marong.diaries d
            JOIN marong.diary_revisions r ON r.diary_id=d.id AND r.revision=d.revision
            WHERE d.friend_id=%s AND d.state='ready' AND d.hidden AND (%s::date IS NULL OR d.diary_date<%s)
            ORDER BY d.diary_date DESC LIMIT 101""", (friend, before, before),
        )
        items = [{"date": _iso(row["diary_date"]), "title": row["title"]} for row in rows[:100]]
        return self.chat._json(200, {"items": items, "nextBefore": items[-1]["date"] if len(rows) > 100 else None})

    async def drawing(self, req):
        friend = (await self.chat._who(req))["friend_id"]
        drawing_id = req.match_info["id"]
        if not UUID.fullmatch(drawing_id.lower()):
            raise Problem("not_found", title="없는 그림이거나 로그인한 친구의 그림이 아님")
        row = await self.store._one(
            """SELECT g.image, g.format FROM marong.diary_drawings g JOIN marong.diaries d ON d.id=g.diary_id
            WHERE d.friend_id=%s AND g.id=%s""", (friend, drawing_id),
        )
        if row is None:
            raise Problem("not_found", title="없는 그림이거나 로그인한 친구의 그림이 아님")
        req["cache"] = "private, max-age=31536000, immutable"
        return web.Response(body=row["image"], content_type=f"image/{row['format']}")

    async def look(self, req):
        friend = (await self.chat._who(req))["friend_id"]
        row = await self.store._one(
            "SELECT hair, glasses, top FROM marong.diary_looks WHERE friend_id=%s AND hair IS NOT NULL",
            (friend,),
        )
        return self.chat._json(200, {"look": row})

    async def put_look(self, req):
        friend = (await self.chat._who(req, write=True))["friend_id"]
        data = await self.chat._body(req)
        if set(data) != set(_LOOK) or any(not isinstance(data[field], str) or data[field] not in values
                                          for field, values in _LOOK.items()):
            raise bad(("look", "bad_format"))
        row = await self.store._one(
            """INSERT INTO marong.diary_looks (friend_id, hair, glasses, top) VALUES (%s,%s,%s,%s)
            ON CONFLICT (friend_id) DO UPDATE SET hair=EXCLUDED.hair, glasses=EXCLUDED.glasses,
                top=EXCLUDED.top, updated_at=now()
            RETURNING hair, glasses, top""", (friend, data["hair"], data["glasses"], data["top"]),
        )
        return self.chat._json(200, {"look": row})

    async def clear_look(self, req):
        friend = (await self.chat._who(req, write=True))["friend_id"]
        await self.store._one(
            """UPDATE marong.diary_looks SET hair=NULL, glasses=NULL, top=NULL, updated_at=now()
            WHERE friend_id=%s AND hair IS NOT NULL RETURNING friend_id""", (friend,),
        )
        return web.Response(status=204)

    def register(self, app):
        from .diary_edits import DiaryEdits

        for path, handler in (("/latest", self.latest), ("/days", self.month), ("/days/{date}", self.day),
                              ("/hidden", self.hidden), ("/drawings/{id}", self.drawing)):
            app.router.add_get(_PREFIX + path, handler, allow_head=False)
        for path, handler in (("weather", self.put_weather), ("hidden", self.put_hidden), ("stamp", self.put_stamp)):
            app.router.add_put(f"{_PREFIX}/days/{{date}}/{path}", handler)
        edits = DiaryEdits(self)
        app.router.add_post(_PREFIX + "/days/{date}/fixes", edits.fix)
        app.router.add_post(_PREFIX + "/days/{date}/drawings", edits.redraw)
        app.router.add_get(_PREFIX + "/look", self.look, allow_head=False)
        app.router.add_put(_PREFIX + "/look", self.put_look)
        app.router.add_delete(_PREFIX + "/look", self.clear_look)
        files = "|".join(re.escape(name) for name in _FILES)
        app.router.add_get(_PAGE + f"{{name:{files}}}", self.file)
        app.router.add_get(_PAGE, self.page)
        app.router.add_get(_PAGE + "{date}", self.page)
