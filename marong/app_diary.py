"""Authenticated read routes for one friend's diary (API-108~110, 116~117)."""

import os
import re
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

from aiohttp import web

from .app_chat import UUID, Problem, bad
from .diary import KST, diary_day, image_budget

_PREFIX = "/chat/diary/api"
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MONTH = re.compile(r"[0-9]{4}-[0-9]{2}")
_VISIBLE = "state='ready' AND NOT hidden"


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
        self.draw_budget = image_budget(os.getenv("MARONG_DIARY_IMAGE_BUDGET_USD"))

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
        now = datetime.now(KST)
        row = await self.store._one(
            f"""WITH params AS (SELECT %s::bigint AS friend, %s::date AS day, %s::date AS today)
            SELECT d.state, d.revision, d.drawing_id, d.hidden, d.stamped_at, d.busy, d.busy_until,
                   d.fixes_used, d.redraws_used, d.redraw_result, d.redraw_at,
                   r.title, r.weather, r.body,
                   (SELECT max(diary_date) FROM marong.diaries
                    WHERE friend_id=p.friend AND {_VISIBLE} AND diary_date<p.day) AS prev,
                   (SELECT min(diary_date) FROM marong.diaries
                    WHERE friend_id=p.friend AND {_VISIBLE} AND diary_date>p.day) AS next
            FROM params p
            LEFT JOIN marong.diaries d ON d.friend_id=p.friend AND d.diary_date=p.day AND p.day<=p.today
            LEFT JOIN marong.diary_revisions r ON r.diary_id=d.id AND r.revision=d.revision""",
            (friend, day, diary_day(now)),
        )
        state = row["state"] or "none"
        content = await self._content(row, now) if state == "ready" else None
        if state in ("pending", "drawing"):
            state = "writing"
        return self.chat._json(200, {"date": day.isoformat(), "state": state,
            "prev": _iso(row["prev"]), "next": _iso(row["next"]), "diary": content})

    async def _content(self, row, now):
        busy = row["busy"] if row["busy_until"] and row["busy_until"] > now else None
        fixes = 5 - row["fixes_used"]
        redraws = 2 - row["redraws_used"]
        fix_block = "fix_limit" if not fixes else "busy" if busy else None
        redraw_block = "redraw_limit" if not redraws else "busy" if busy else None
        if redraw_block is None:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            spend = await self.store._one(
                "SELECT COALESCE(sum(cost_usd),0) AS usd FROM marong.diary_ai_runs "
                "WHERE kind='draw' AND sent_at>=%s AND sent_at<=%s", (start, now),
            )
            if spend["usd"] + Decimal("0.03") > self.draw_budget:
                redraw_block = "drawing_budget"
        drawing_id = row["drawing_id"]
        last = {"result": row["redraw_result"], "at": _iso(row["redraw_at"])} if row["redraw_result"] else None
        return {
            "revision": row["revision"], "title": row["title"], "weather": row["weather"], "body": row["body"],
            "drawing": {"id": str(drawing_id) if drawing_id else None, "kind": "ai" if drawing_id else "placeholder"},
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
            raise Problem("not_found")
        row = await self.store._one(
            """SELECT g.image, g.format FROM marong.diary_drawings g JOIN marong.diaries d ON d.id=g.diary_id
            WHERE d.friend_id=%s AND g.id=%s""", (friend, drawing_id),
        )
        if row is None:
            raise Problem("not_found")
        req["cache"] = "private, max-age=31536000, immutable"
        return web.Response(body=row["image"], content_type=f"image/{row['format']}")

    def register(self, app):
        for path, handler in (("/latest", self.latest), ("/days", self.month), ("/days/{date}", self.day),
                              ("/hidden", self.hidden), ("/drawings/{id}", self.drawing)):
            app.router.add_get(_PREFIX + path, handler, allow_head=False)
