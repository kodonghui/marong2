"""Account-owned diary styling and transactional sticker edits (API-258–261)."""

from datetime import datetime

from .app_chat import Problem
from .app_session import one
from .diary import KST, diary_day


STYLE_FIELDS = {"backgroundId": "background", "paperId": "paper", "fontId": "font"}
STICKER_FIELDS = {"x": (0, 1000), "y": (0, 1000), "scale": (50, 200), "rotation": (-180, 180)}


class DiaryDecor:
    def __init__(self, api):
        self.api = api
        self.chat = api.chat
        self.store = api.store
        self.decor = self.chat.decor

    async def body(self, req, keys):
        try:
            data = await self.chat._body(req)
        except Problem:
            raise Problem("invalid_input", [{"field": "body", "reason": "bad_format"}]) from None
        errors = []
        if set(data) - set(keys):
            errors.append({"field": "body", "reason": "bad_format"})
        errors.extend({"field": key, "reason": "required"} for key in keys if key not in data)
        if errors:
            raise Problem("invalid_input", errors)
        return data

    async def settings(self, req):
        friend = await self.decor.friend(req)
        return self.chat._json(200, await self.decor.diary_view(friend))

    async def set_style(self, req):
        friend = await self.decor.friend(req, write=True)
        try:
            body = await self.chat._body(req)
        except Problem:
            raise Problem("invalid_input", [{"field": "body", "reason": "bad_format"}]) from None
        errors = []
        if set(body) - STYLE_FIELDS.keys():
            errors.append({"field": "body", "reason": "bad_format"})
        ids = {}
        for field, kind in STYLE_FIELDS.items():
            if field not in body or body[field] is None:
                errors.append({"field": field, "reason": "required"})
                continue
            try:
                ids[kind] = self.decor.item_key(body[field])
            except Problem:
                errors.append({"field": field, "reason": "bad_format"})
        if errors:
            raise Problem("invalid_input", errors)
        async with self.store.pool.connection() as conn, conn.transaction():
            owned = await self.decor.owned_items(conn, friend, list(ids.values()))
            if owned.keys() != set(ids.values()):
                raise Problem("not_owned")
            errors = [{"field": field, "reason": "wrong_kind"}
                      for field, kind in STYLE_FIELDS.items() if owned[ids[kind]]["kind"] != kind]
            if errors:
                raise Problem("invalid_input", errors)
            await conn.execute("""
                INSERT INTO marong.diary_decor(friend_id,background_id,paper_id,font_id) VALUES (%s,%s,%s,%s)
                ON CONFLICT (friend_id) DO UPDATE SET background_id=excluded.background_id,
                    paper_id=excluded.paper_id,font_id=excluded.font_id,updated_at=now()
                WHERE (diary_decor.background_id,diary_decor.paper_id,diary_decor.font_id)
                    IS DISTINCT FROM (excluded.background_id,excluded.paper_id,excluded.font_id)
            """, (friend, ids["background"], ids["paper"], ids["font"]))
        return self.chat._json(200, await self.decor.diary_view(friend))

    async def sticker_rows(self, conn, diary_id, friend):
        cursor = await conn.execute("""
            SELECT item_id,x,y,scale,rotation FROM marong.diary_stickers
            WHERE diary_id=%s AND friend_id=%s AND removed_at IS NULL ORDER BY z,id
        """, (diary_id, friend))
        return [{"itemId": row["item_id"], **{key: row[key] for key in STICKER_FIELDS}}
                for row in await cursor.fetchall()]

    def response(self, day, stickers):
        catalog = self.decor.catalog
        visible = []
        for entry in stickers:
            item = catalog.items.get(entry["itemId"])
            url = catalog.url(item, "sticker.webp") if item else None
            if url:
                visible.append({**entry, "imageUrl": url})
        return self.chat._json(200, {"date": day.isoformat(), "stickers": visible})

    def input_sticker(self, data, index=0):
        if not isinstance(data, dict):
            raise Problem("invalid_input", [{"field": "stickers", "index": index, "reason": "bad_format"}])
        errors = []
        if set(data) - {"itemId", *STICKER_FIELDS}:
            errors.append({"field": "stickers", "index": index, "reason": "bad_format"})
        if "itemId" not in data or data["itemId"] is None:
            errors.append({"field": "itemId", "index": index, "reason": "required"})
        else:
            try:
                self.decor.item_key(data["itemId"])
            except Problem:
                errors.append({"field": "itemId", "index": index, "reason": "bad_format"})
        for key, (low, high) in STICKER_FIELDS.items():
            if key not in data or data[key] is None:
                errors.append({"field": key, "index": index, "reason": "required"})
            elif type(data[key]) is not int:
                errors.append({"field": key, "index": index, "reason": "bad_format"})
            elif not low <= data[key] <= high:
                errors.append({"field": key, "index": index, "reason": "out_of_range"})
        if errors:
            raise Problem("invalid_input", errors[:10])
        return data

    @staticmethod
    def date(req, *, details=False):
        from .app_diary import _date

        try:
            return _date(req.match_info["date"], "date")
        except Problem:
            errors = [{"field": "date", "reason": "bad_format"}] if details else []
            raise Problem("invalid_input", errors) from None

    async def stickers(self, req):
        friend = await self.decor.friend(req)
        day = self.date(req)
        async with self.store.pool.connection() as conn:
            diary = await one(conn, """
                SELECT id,state FROM marong.diaries WHERE friend_id=%s AND diary_date=%s
            """, (friend, day))
            if not diary:
                raise Problem("not_found")
            rows = await self.sticker_rows(conn, diary["id"], friend) if diary["state"] == "ready" else []
        return self.response(day, rows)

    async def set_stickers(self, req):
        friend = await self.decor.friend(req, write=True)
        day = self.date(req, details=True)
        body = await self.body(req, {"stickers"})
        if not isinstance(body["stickers"], list):
            raise Problem("invalid_input", [{"field": "stickers", "reason": "bad_format"}])
        if len(body["stickers"]) > 10:
            raise Problem("too_many_stickers")
        updates, errors = [], []
        for index, entry in enumerate(body["stickers"]):
            try:
                updates.append(self.input_sticker(entry, index))
            except Problem as error:
                errors.extend(error.errors)
        if errors:
            raise Problem("invalid_input", errors[:10])
        async with self.store.pool.connection() as conn, conn.transaction():
            diary = await one(conn, """
                SELECT id,state FROM marong.diaries WHERE friend_id=%s AND diary_date=%s FOR UPDATE
            """, (friend, day))
            if not diary or diary["state"] != "ready" or day > diary_day(datetime.now(KST)):
                raise Problem("not_found")
            ids = {entry["itemId"] for entry in updates}
            owned = await self.decor.owned_items(conn, friend, list(ids))
            if owned.keys() != ids:
                raise Problem("not_owned")
            errors = [{"field": "itemId", "index": index, "reason": "wrong_kind"}
                      for index, entry in enumerate(updates) if owned[entry["itemId"]]["kind"] != "sticker"]
            if errors:
                raise Problem("invalid_input", errors[:10])
            current = await self.sticker_rows(conn, diary["id"], friend)
            if current != updates:
                await conn.execute("""
                    UPDATE marong.diary_stickers SET removed_at=now()
                    WHERE diary_id=%s AND friend_id=%s AND removed_at IS NULL
                """, (diary["id"], friend))
                async with conn.cursor() as cur:
                    await cur.executemany("""
                        INSERT INTO marong.diary_stickers(diary_id,friend_id,item_id,x,y,scale,rotation,z)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, [(diary["id"], friend, entry["itemId"], *(entry[key] for key in STICKER_FIELDS), z)
                          for z, entry in enumerate(updates)])
        return self.response(day, updates)

    async def page(self, req):
        return await self.decor.page(req)

    def register(self, router):
        router.add_get("/chat/diary/decor", self.page)
        router.add_get("/chat/diary/api/decor", self.settings)
        router.add_put("/chat/diary/api/decor", self.set_style)
        router.add_get("/chat/diary/api/days/{date}/stickers", self.stickers)
        router.add_put("/chat/diary/api/days/{date}/stickers", self.set_stickers)
