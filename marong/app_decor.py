"""Decor files and the logged-in storefront (API-252–257)."""

import asyncio
import logging

from aiohttp import web

from .app_chat import Problem
from .app_session import COOKIE, SessionError, one
from .character.http import CharacterError, positive_id
from .decor import CONTENT, ITEM_ID, KINDS, WEAR


log = logging.getLogger(__name__)
STARTER = {"background": "starter-background", "paper": "starter-paper", "font": "starter-font"}


class AppDecor:
    def __init__(self, chat):
        self.chat = chat
        self.store = chat.store
        self.catalog = None

    def require_catalog(self):
        if self.catalog is None:
            raise Problem("not_found")
        return self.catalog

    async def seed(self):
        catalog = self.require_catalog()
        valid = []
        for item in catalog.items.values():
            if await asyncio.to_thread(catalog.check, item):
                log.info("decor_seed_skip item=%s", item.id)
            else:
                valid.append((item.id, catalog.set, item.kind, item.slot, item.starter))
        if valid:
            async with self.store.pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
                await cur.executemany("""
                    INSERT INTO marong.decor_items(id,item_set,kind,slot,starter)
                    VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING
                """, valid)

    async def file(self, req):
        catalog = self.require_catalog()
        await self.chat.profile.who(req)
        name = req.match_info
        item = catalog.items.get(name["itemId"]) if name["set"] == catalog.set else None
        path = item.files.get(name["file"]) if item else None
        if path is None or not await asyncio.to_thread(path.is_file):
            raise Problem("not_found")
        req["cache"] = "public, max-age=31536000, immutable"
        response = web.FileResponse(path)
        response.content_type = CONTENT[path.suffix]
        return response

    async def friend(self, req, *, write=False):
        self.require_catalog()
        return (await self.chat.profile.who(req, write=write))["friend_id"]

    @staticmethod
    def item_key(raw):
        if not isinstance(raw, str) or not ITEM_ID.fullmatch(raw):
            raise Problem("invalid_input")
        return raw

    def item_view(self, item, owned):
        key = "sticker.webp" if item.kind == "sticker" else "thumb.webp"
        return {"id": item.id, "kind": item.kind, "slot": item.slot, "name": item.name, "priceKrw": 0,
                "thumbUrl": self.catalog.url(item, key), "owned": owned, "starter": item.starter}

    async def items_for(self, friend, *, closet):
        rows = await self.store._all("""
            SELECT d.id, d.starter OR o.item_id IS NOT NULL AS owned FROM marong.decor_items d
            LEFT JOIN marong.decor_owned o ON o.item_id=d.id AND o.friend_id=%s
            WHERE d.item_set=%s AND (CASE WHEN %s THEN d.starter OR o.item_id IS NOT NULL ELSE d.state='listed' END)
            ORDER BY array_position(%s::text[],d.kind),d.listed_at,d.id
        """, (friend, self.catalog.set, closet, list(KINDS)))
        items = [(self.catalog.items[row['id']], row['owned']) for row in rows if row['id'] in self.catalog.items]
        def views():
            result = []
            for item, owned in items:
                view = self.item_view(item, owned)
                if item.slot and self.chat.pet_app_settings.decor and self.chat.pet_app_settings.default_wear:
                    view['marongWearable'] = self.catalog.marong_layer_issue(item) is None
                result.append(view)
            return result
        return await asyncio.to_thread(views)

    async def shop(self, req):
        friend = await self.friend(req)
        return self.chat._json(200, {"items": await self.items_for(friend, closet=False)})

    async def claim(self, req):
        friend = await self.friend(req, write=True)
        ident = self.item_key(req.match_info["itemId"])
        if ident not in self.catalog.items:
            raise Problem("not_found")
        async with self.store.pool.connection() as conn, conn.transaction():
            item = await one(conn, """
                SELECT starter FROM marong.decor_items WHERE id=%s AND item_set=%s AND state='listed' FOR SHARE
            """, (ident, self.catalog.set))
            if not item:
                raise Problem("not_found")
            start = None if item["starter"] else await one(conn, """
                INSERT INTO marong.decor_owned(friend_id,item_id) VALUES (%s,%s)
                ON CONFLICT DO NOTHING RETURNING item_id
            """, (friend, ident))
        return self.chat._json(201 if start else 200, {"itemId": ident, "owned": True})

    def outfit_view(self, row, template):
        outfit = dict.fromkeys(WEAR)
        if self.catalog and template == 'marong':
            row = self.catalog.valid_marong_outfit(row)
        for slot in WEAR:
            item = self.catalog.items.get(row[slot]) if self.catalog and row else None
            layer = self.catalog.url(item, f"{template}.png") if item else None
            if layer:
                outfit[slot] = {"id": item.id, "name": item.name, "layerUrl": layer}
        return outfit

    async def equipped(self, character, template):
        if not self.catalog:
            return dict.fromkeys(WEAR)
        sql = ("SELECT head,body,neck FROM marong.marong_outfits WHERE friend_id=%s" if template == "marong"
               else "SELECT head,body,neck FROM marong.outfits WHERE character_id=%s")
        row = await self.store._one(sql, (character,))
        return await asyncio.to_thread(self.outfit_view, row, template)

    async def closet(self, req):
        friend = await self.friend(req)
        character = await self.store._one("""
            SELECT c.id,c.template FROM marong.friend_profiles p JOIN marong.characters c
            ON c.id=p.character_id AND c.friend_id=p.friend_id AND c.status='ready' WHERE p.friend_id=%s
        """, (friend,))
        outfit = (await self.equipped(character["id"], character["template"]) if character else
                  await self.equipped(friend, "marong") if self.chat.pet_app_settings.default_wear and self.chat.pet_app_settings.decor else None)
        return self.chat._json(200, {"items": await self.items_for(friend, closet=True),
                                    "characterId": character["id"] if character else None,
                                    "outfit": outfit, "diaryDecor": await self.diary_view(friend)})

    def diary_default(self, kind):
        return next((item.id for item in self.catalog.items.values() if item.starter and item.kind == kind),
                    STARTER[kind])

    async def diary_view(self, friend):
        selected = await self.store._one("""
            SELECT background_id,paper_id,font_id FROM marong.diary_decor WHERE friend_id=%s
        """, (friend,))
        default = {kind: self.diary_default(kind) for kind in STARTER}
        ids = {kind: selected[f"{kind}_id"] if selected else default[kind] for kind in STARTER}
        bg, paper, font = (self.catalog.items.get(ids[kind]) for kind in STARTER)
        return {
            "background": {"id": ids["background"], "imageUrl": self.catalog.url(bg, "bg.webp") if bg and not bg.starter else None},
            "paper": {"id": ids["paper"], "imageUrl": self.catalog.url(paper, "paper.webp") if paper else None,
                      "style": paper.paper_style if paper and paper.paper_style else "manuscript" if not paper else None},
            "font": {"id": ids["font"], "family": font.name if font else "Gaegu",
                     "fontUrl": self.catalog.url(font, "font.woff2") if font and not font.starter else None},
        }

    async def owned_items(self, conn, friend, ids):
        if not ids:
            return {}
        cursor = await conn.execute("""
            SELECT d.id,d.kind,d.slot FROM marong.decor_items d
            LEFT JOIN marong.decor_owned o ON o.item_id=d.id AND o.friend_id=%s
            WHERE d.id=ANY(%s) AND d.item_set=%s AND (d.starter OR o.item_id IS NOT NULL)
        """, (friend, ids, self.catalog.set))
        return {row["id"]: row for row in await cursor.fetchall() if row["id"] in self.catalog.items}

    async def marong_outfit(self, req):
        if not (self.chat.pet_app_settings.decor and self.chat.pet_app_settings.default_wear):
            raise Problem("not_found")
        self.require_catalog()
        self.chat._require_app_origin(req)
        token = req.cookies.get(COOKIE)
        who = await self.chat.sessions.find_session(token) if self.chat.sessions else None
        if not who or not who.get('room_key'):
            raise Problem('login_required')
        if who.get('renewed'):
            req['session_refresh'] = token
        if who['profile_id'] is None:
            await self.chat.sessions.ensure_profile(who['friend_id'])
        friend = who['friend_id']
        try:
            picks = await self.chat._body(req)
        except Problem:
            raise Problem("invalid_input", [{"field": "request", "reason": "bad_format"}]) from None
        errors, ids = [], []
        if set(picks) - set(WEAR):
            errors.append({"field": "request", "reason": "bad_format"})
        for slot in WEAR:
            if slot not in picks:
                errors.append({"field": slot, "reason": "required"})
            elif picks[slot] is not None:
                try:
                    ids.append(self.item_key(picks[slot]))
                except Problem:
                    errors.append({"field": slot, "reason": "bad_format"})
        if errors:
            raise Problem("invalid_input", errors)
        async with self.store.pool.connection() as conn, conn.transaction():
            await one(conn, "SELECT id FROM marong.friends WHERE id=%s FOR UPDATE", (friend,))
            owned = await self.owned_items(conn, friend, ids)
            if set(ids) != owned.keys():
                raise Problem("not_owned")
            errors = [{"field": slot, "reason": "wrong_kind"} for slot in WEAR
                      if picks[slot] and owned[picks[slot]]["slot"] != slot]
            if errors:
                raise Problem("invalid_input", errors)
            for ident in ids:
                issue = await asyncio.to_thread(self.catalog.marong_layer_issue, self.catalog.items[ident])
                if issue:
                    raise Problem('item_invalid', missing=[f'{issue}:marong'])
            prior = await one(conn, "SELECT head,body,neck FROM marong.marong_outfits WHERE friend_id=%s", (friend,))
            if prior != picks:
                await conn.execute("""INSERT INTO marong.marong_outfits(friend_id,head,body,neck) VALUES (%s,%s,%s,%s)
                    ON CONFLICT (friend_id) DO UPDATE SET head=excluded.head,body=excluded.body,
                    neck=excluded.neck,updated_at=now()""", (friend, *(picks[slot] for slot in WEAR)))
                reaction = False
                for slot in WEAR:
                    item = picks[slot]
                    if item is None or (prior and prior[slot] == item):
                        continue
                    added = await one(conn, """INSERT INTO marong.outfit_firsts(friend_id,character_id,item_id,state,next_at,finished_at)
                        VALUES (%s,NULL,%s,%s,now()+interval '3 minutes',CASE WHEN %s THEN now() END)
                        ON CONFLICT (friend_id,item_id) WHERE character_id IS NULL DO NOTHING RETURNING id""",
                        (friend, item, 'skipped' if reaction else 'waiting', reaction))
                    reaction = reaction or added is not None
        return self.chat._json(200, await asyncio.to_thread(self.outfit_view, picks, 'marong'))

    async def outfit(self, req):
        friend = await self.friend(req, write=True)
        try:
            ident = positive_id(req.match_info["id"])
        except CharacterError:
            raise Problem("invalid_input", [{"field": "id", "reason": "bad_format"}]) from None
        try:
            picks = await self.chat._body(req)
        except Problem:
            raise Problem("invalid_input", [{"field": "request", "reason": "bad_format"}]) from None
        errors = []
        if set(picks) - set(WEAR):
            errors.append({"field": "request", "reason": "bad_format"})
        ids = []
        for slot in WEAR:
            if slot not in picks:
                errors.append({"field": slot, "reason": "required"})
            elif picks[slot] is not None:
                try:
                    ids.append(self.item_key(picks[slot]))
                except Problem:
                    errors.append({"field": slot, "reason": "bad_format"})
        if errors:
            raise Problem("invalid_input", errors)
        async with self.store.pool.connection() as conn, conn.transaction():
            character = await one(conn, """
                SELECT template,status FROM marong.characters WHERE id=%s AND friend_id=%s FOR UPDATE
            """, (ident, friend))
            if not character:
                raise Problem("not_found")
            if character["status"] != "ready":
                raise Problem("not_ready")
            owned = await self.owned_items(conn, friend, ids)
            if set(ids) != owned.keys():
                raise Problem("not_owned")
            errors = [{"field": slot, "reason": "wrong_kind"} for slot in WEAR
                      if picks[slot] and owned[picks[slot]]["slot"] != slot]
            if errors:
                raise Problem("invalid_input", errors)
            prior = await one(conn, "SELECT head,body,neck FROM marong.outfits WHERE character_id=%s", (ident,))
            if prior != picks:
                await conn.execute("""
                    INSERT INTO marong.outfits(character_id,head,body,neck) VALUES (%s,%s,%s,%s)
                    ON CONFLICT (character_id) DO UPDATE SET head=excluded.head,body=excluded.body,
                        neck=excluded.neck,updated_at=now()
                """, (ident, *(picks[slot] for slot in WEAR)))
                reaction = False
                for slot in WEAR:
                    item = picks[slot]
                    if item is None or (prior and prior[slot] == item):
                        continue
                    added = await one(conn, """
                        INSERT INTO marong.outfit_firsts(friend_id,character_id,item_id,state,next_at,finished_at)
                        VALUES (%s,%s,%s,%s,now()+interval '3 minutes',CASE WHEN %s THEN now() END)
                        ON CONFLICT (character_id,item_id) DO NOTHING RETURNING id
                    """, (friend, ident, item, "skipped" if reaction else "waiting", reaction))
                    reaction = reaction or added is not None
        return self.chat._json(200, self.outfit_view(picks, character["template"]))

    async def page(self, req):
        self.require_catalog()
        try:
            await self.chat.profile.who(req)
        except (Problem, SessionError) as error:
            if error.code in {"login_required", "unauthenticated"}:
                raise web.HTTPFound("/chat/login") from None
            raise
        return self.chat.unified_page("decor")

    def register(self, router):
        router.add_get("/chat/decor/{set}/{itemId}/{file}", self.file)
        router.add_get("/chat/shop", self.page)
        router.add_get("/chat/closet", self.page)
        router.add_get("/chat/api/shop", self.shop)
        router.add_post("/chat/api/shop/{itemId}/claim", self.claim)
        router.add_get("/chat/api/closet", self.closet)
        router.add_put("/chat/api/characters/{id}/outfit", self.outfit)
        router.add_put("/chat/api/marong/outfit", self.marong_outfit)
