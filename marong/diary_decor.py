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
            raise Problem("invalid_input") from None
        if data.keys() != keys:
            raise Problem("invalid_input")
        return data

    async def settings(self, req):
        friend = await self.decor.friend(req)
        return self.chat._json(200, await self.decor.diary_view(friend))

    async def set_style(self, req):
        friend = await self.decor.friend(req, write=True)
        body = await self.body(req, STYLE_FIELDS.keys())
        ids = {STYLE_FIELDS[key]: self.decor.item_key(value) for key, value in body.items()}
        async with self.store.pool.connection() as conn, conn.transaction():
            owned = await self.decor.owned_items(conn, friend, list(ids.values()))
            if owned.keys() != set(ids.values()):
                raise Problem("not_owned")
            if any(owned[value]["kind"] != kind for kind, value in ids.items()):
                raise Problem("invalid_input")
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

    def input_sticker(self, data):
        if not isinstance(data, dict) or data.keys() != {"itemId", *STICKER_FIELDS}:
            raise Problem("invalid_input")
        self.decor.item_key(data["itemId"])
        for key, (low, high) in STICKER_FIELDS.items():
            if type(data[key]) is not int or not low <= data[key] <= high:
                raise Problem("invalid_input")
        return data

    @staticmethod
    def date(req):
        from .app_diary import _date

        try:
            return _date(req.match_info["date"], "date")
        except Problem:
            raise Problem("invalid_input") from None

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
        day = self.date(req)
        body = await self.body(req, {"stickers"})
        if not isinstance(body["stickers"], list):
            raise Problem("invalid_input")
        if len(body["stickers"]) > 10:
            raise Problem("too_many_stickers")
        updates = [self.input_sticker(entry) for entry in body["stickers"]]
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
            if any(item["kind"] != "sticker" for item in owned.values()):
                raise Problem("invalid_input")
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
