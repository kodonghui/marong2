"""Finish a finished sheet into an owned pet, with safe profile editing."""

import asyncio
import re
from datetime import timedelta

from aiohttp import web
from psycopg.types.json import Jsonb

from .account import require_overseas
from .creations import media_url, owned
from .http import POOL, Problem, body_json, require_member, uuid_param
from .sheet import EXPRESSIONS

NAME = re.compile(r"[가-힣A-Za-z0-9 -]{1,12}\Z")
PERSONALITY = ("활발함", "얌전함", "겁이 많음", "먹보", "애교 많음", "고집 셈", "호기심 많음", "느긋함")
INTRO = {"personality", "likes", "dislikes", "callMe"}


def text_field(value, maximum, *, required=False):
    if not isinstance(value, str) or any(ord(ch) < 32 or 0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise Problem("invalid_input")
    value = value.strip()
    if len(value) > maximum or required and not value:
        raise Problem("invalid_input")
    return value


def changes(data, *, complete=False):
    if set(data) - {"name", "intro"} or (complete and set(data) != {"name", "intro"}):
        raise Problem("invalid_input")
    result = {}
    if "name" in data:
        name = text_field(data["name"], 12, required=True)
        if not NAME.fullmatch(name):
            raise Problem("invalid_input")
        result["name"] = name
    if "intro" in data:
        intro = data["intro"]
        if not isinstance(intro, dict) or set(intro) != INTRO:
            raise Problem("invalid_input")
        personality = intro["personality"]
        if (not isinstance(personality, list) or len(personality) > 3
                or any(value not in PERSONALITY for value in personality) or len(set(personality)) != len(personality)):
            raise Problem("invalid_input")
        result["intro"] = {"personality": personality, "likes": text_field(intro["likes"], 60),
                           "dislikes": text_field(intro["dislikes"], 60),
                           "callMe": text_field(intro["callMe"], 10, required=True)}
    return result


def serialize(row):
    def ident(column):
        return str(row[column]) if row[column] is not None else None

    since = row["memorial_since"]
    living = row["mode"] == "living" and row["status"] == "active"
    return {
        "id": str(row["id"]), "name": row["name"], "species": row["species"], "template": row["template"],
        "mode": row["mode"], "status": row["status"], "intro": row["intro"],
        "sheet": {name: media_url(value) for name, value in row["sheet"].items()},
        "outfit": {"head": ident("head_item"), "body": ident("body_item"), "neck": ident("neck_item")},
        "diaryStyle": {"themeId": ident("theme_item"), "fontId": ident("font_item")},
        "memorialSince": since.isoformat() if since else None,
        "passedOn": row["passed_on"].isoformat() if row["passed_on"] else None,
        "revertUntil": (since + timedelta(days=7)).isoformat() if since and row["status"] == "active" else None,
        "shopEntry": living, "rechargePrompt": living, "farewellDone": False,
    }


async def pet_rows(conn, member, pet_id=None):
    sql = """
        SELECT p.*,d.head_item,d.body_item,d.neck_item,d.theme_item,d.font_item
        FROM pet.pets p LEFT JOIN pet.decor d ON p.id=d.pet_id WHERE p.member_id=%s
    """
    cur = await (conn.execute(sql + " AND p.id=%s", (member, pet_id)) if pet_id
                 else conn.execute(sql + " ORDER BY p.created_at,p.id LIMIT 5", (member,)))
    return await cur.fetchall()


async def greeting(renderer, profile, mode, species):
    named = profile["intro"]["callMe"]
    fallback = f"{named}, 나 왔어!" if mode == "living" else f"{named}, 나 놀러 왔어"
    if renderer:
        try:
            text = await asyncio.wait_for(renderer(name=profile["name"], intro=profile["intro"],
                                                  mode=mode, species=species), timeout=8)
            if isinstance(text, str) and named in text and 1 <= len(text) <= 120 and text.isprintable():
                return text
        except Exception:
            pass
    return fallback


async def finish(conn, member, creation_id, profile, renderer):
    cur = await conn.execute("SELECT 1 FROM pet.members WHERE id=%s AND status='active' FOR UPDATE", (member,))
    if not await cur.fetchone():
        raise Problem("unauthenticated")
    creation = await owned(conn, member, creation_id, lock=True)
    if creation["state"] == "done":
        return (await pet_rows(conn, member, creation["pet_id"]))[0]
    if creation["state"] != "sheet_ready":
        raise Problem("wrong_state")
    count = await conn.execute("SELECT count(*) AS n FROM pet.pets WHERE member_id=%s", (member,))
    if (await count.fetchone())["n"] >= 5:
        raise Problem("pet_limit")
    cur = await conn.execute("""
        SELECT id,kind,meta FROM pet.media WHERE member_id=%s AND creation_id=%s
          AND kind IN ('sheet_front','sheet_expression') ORDER BY created_at,id
    """, (member, creation_id))
    sheet = {row["meta"].get("expression", "front"): str(row["id"]) for row in await cur.fetchall()}
    if set(sheet) != {"front", *EXPRESSIONS}:
        raise Problem("wrong_state")
    mode = creation["kind"]
    species = "dog" if creation["template"].startswith("dog_") else "cat"
    # A fallback greeting is permitted even if transfer permissions changed after the sheet was drawn.
    if renderer:
        try:
            await require_overseas(conn, member)
        except Problem:
            renderer = None
    line = await greeting(renderer, profile, mode, species)
    cursor = await conn.execute("""
        INSERT INTO pet.pets(member_id,creation_id,name,intro,species,template,sheet,mode,memorial_since)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CASE WHEN %s='memorial' THEN now() END) RETURNING id
    """, (member, creation_id, profile["name"], Jsonb(profile["intro"]), species, creation["template"], Jsonb(sheet),
          mode, mode))
    new_id = (await cursor.fetchone())["id"]
    await conn.execute("INSERT INTO pet.decor(pet_id) VALUES (%s)", (new_id,))
    await conn.execute("""
        UPDATE pet.media SET pet_id=%s WHERE member_id=%s AND creation_id=%s AND id=ANY(%s::uuid[])
    """, (new_id, member, creation_id, list(sheet.values())))
    await conn.execute("INSERT INTO pet.messages(member_id,pet_id,role,kind,content) VALUES (%s,%s,'pet','greeting',%s)",
                       (member, new_id, line))
    await conn.execute("UPDATE pet.creations SET state='done',updated_at=now() WHERE id=%s", (creation_id,))
    return (await pet_rows(conn, member, new_id))[0]


def register(app, renderer):
    async def finish_route(req):
        member = await require_member(req)
        ident = uuid_param(req.match_info["id"])
        profile = changes(await body_json(req), complete=True)
        async with app[POOL].connection() as conn, conn.transaction():
            row = await finish(conn, member["id"], ident, profile, renderer)
        return web.json_response(serialize(row), status=201)

    async def listing(req):
        member = await require_member(req)
        async with app[POOL].connection() as conn:
            rows = await pet_rows(conn, member["id"])
        return web.json_response({"items": [serialize(row) for row in rows]})

    async def pet_route(req):
        member = await require_member(req)
        ident = uuid_param(req.match_info["id"])
        profile = changes(await body_json(req)) if req.method == "PATCH" else {}
        async with app[POOL].connection() as conn, conn.transaction():
            if profile:
                await conn.execute("""
                    UPDATE pet.pets SET name=coalesce(%s,name),intro=coalesce(%s,intro),updated_at=now()
                    WHERE member_id=%s AND id=%s
                """, (profile.get("name"), Jsonb(profile["intro"]) if "intro" in profile else None, member["id"], ident))
            rows = await pet_rows(conn, member["id"], ident)
            if not rows:
                raise Problem("not_found")
        return web.json_response(serialize(rows[0]))

    app.router.add_post("/api/creations/{id}/finish", finish_route)
    app.router.add_get("/api/pets", listing, allow_head=False)
    app.router.add_get("/api/pets/{id}", pet_route, allow_head=False)
    app.router.add_patch("/api/pets/{id}", pet_route)
