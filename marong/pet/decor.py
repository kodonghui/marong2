"""Member-scoped outfits and diary decoration (SPEC-349–351)."""

from datetime import date

from aiohttp import web
from psycopg.types.json import Jsonb

from .http import POOL, Problem, body_json, require_member, uuid_param
from .inventory import ASSET_NAME, contents

SLOTS = ("head", "body", "neck")
STYLE = {"themeId": "theme", "fontId": "font"}
STICKER_RANGE = {"x": (0, 1), "y": (0, 1), "scale": (.5, 2), "rotate": (-45, 45)}


def outfit_input(data):
    if set(data) != set(SLOTS):
        raise Problem("invalid_input")
    return {slot: uuid_param(data[slot]) if data[slot] is not None else None for slot in SLOTS}


async def lock_owned_pet(conn, member, pet):
    # Order and inventory operations take the member lock first.
    owner = await conn.execute("SELECT 1 FROM pet.members WHERE id=%s AND status='active' FOR UPDATE", (member,))
    if not await owner.fetchone():
        raise Problem("unauthenticated")
    found = await conn.execute("""
        SELECT p.status,p.mode,d.head_item,d.body_item,d.neck_item,d.theme_item,d.font_item
        FROM pet.pets p LEFT JOIN pet.decor d ON d.pet_id=p.id
        WHERE p.id=%s AND p.member_id=%s FOR UPDATE OF p
    """, (pet, member))
    current = await found.fetchone()
    if current is None:
        raise Problem("not_found")
    return current


async def owned_items(conn, member, wanted):
    ids = sorted(set(wanted) - {None})
    result = await conn.execute("""
        SELECT i.id,i.kind,i.slot,i.assets,i.is_default,h.order_id
        FROM pet.inventory h JOIN pet.items i ON i.id=h.item_id
        LEFT JOIN pet.orders o ON o.id=h.order_id AND o.member_id=h.member_id
        WHERE h.member_id=%s AND h.item_id=ANY(%s::uuid[]) AND h.withdrawn_at IS NULL
          AND o.status IS DISTINCT FROM 'refund_pending'
        ORDER BY h.item_id FOR UPDATE OF h
    """, (member, ids))
    owned = {row["id"]: row for row in await result.fetchall()}
    if len(owned) != len(ids):
        raise Problem("not_found")
    return owned


async def mark_used(conn, member, orders):
    if orders:
        await conn.execute("""
            UPDATE pet.orders SET used_at=coalesce(used_at,now()) WHERE member_id=%s AND id=ANY(%s::uuid[])
        """, (member, sorted(orders)))


async def apply_outfit(conn, member, pet, outfit):
    current = await lock_owned_pet(conn, member, pet)
    if current["status"] == "archived":
        raise Problem("archived")
    owned = await owned_items(conn, member, outfit.values())
    used_orders = set()
    reactions = []
    for slot in SLOTS:
        item = outfit[slot]
        if item is None:
            continue
        row = owned[item]
        if row["kind"] != "wear" or row["slot"] != slot:
            raise Problem("wrong_slot")
        if item != current[slot + "_item"] and row["order_id"] is not None:
            used_orders.add(row["order_id"])
            if current["mode"] == "living" and not row["is_default"]:
                reactions.append(item)
    await conn.execute("""
        INSERT INTO pet.decor(pet_id,head_item,body_item,neck_item) VALUES (%s,%s,%s,%s)
        ON CONFLICT(pet_id) DO UPDATE SET head_item=EXCLUDED.head_item,body_item=EXCLUDED.body_item,
            neck_item=EXCLUDED.neck_item,updated_at=now()
        WHERE (pet.decor.head_item,pet.decor.body_item,pet.decor.neck_item) IS DISTINCT FROM
              (EXCLUDED.head_item,EXCLUDED.body_item,EXCLUDED.neck_item)
    """, (pet, *(outfit[slot] for slot in SLOTS)))
    await mark_used(conn, member, used_orders)
    if reactions:
        await conn.execute("""
            INSERT INTO pet.proactive_turns(member_id,pet_id,kind,slot_at,item_id)
            SELECT %s,%s,'item_reaction',now()+interval '3 minutes',item
            FROM unnest(%s::uuid[]) AS item
            ON CONFLICT(pet_id,item_id) WHERE item_id IS NOT NULL DO NOTHING
        """, (member, pet, reactions))


def style_input(data):
    if set(data) != set(STYLE):
        raise Problem("invalid_input")
    return {kind: uuid_param(data[field]) if data[field] is not None else None for field, kind in STYLE.items()}


async def apply_style(conn, member, pet, style):
    current = await lock_owned_pet(conn, member, pet)
    owned = await owned_items(conn, member, style.values())
    orders = set()
    for kind, ident in style.items():
        if ident is None:
            continue
        row = owned[ident]
        if row["kind"] != kind:
            raise Problem("not_found")
        if ident != current[kind + "_item"] and row["order_id"] is not None:
            orders.add(row["order_id"])
    await conn.execute("""
        INSERT INTO pet.decor(pet_id,theme_item,font_item) VALUES (%s,%s,%s)
        ON CONFLICT(pet_id) DO UPDATE SET theme_item=EXCLUDED.theme_item,font_item=EXCLUDED.font_item,updated_at=now()
        WHERE (pet.decor.theme_item,pet.decor.font_item) IS DISTINCT FROM (EXCLUDED.theme_item,EXCLUDED.font_item)
    """, (pet, style["theme"], style["font"]))
    await mark_used(conn, member, orders)


def stickers_input(payload):
    if not isinstance(payload, list) or len(payload) > 10:
        raise Problem("invalid_input")
    for sticker in payload:
        if not isinstance(sticker, dict) or set(sticker) != {"packId", "sticker", *STICKER_RANGE}:
            raise Problem("invalid_input")
        uuid_param(sticker["packId"])
        name = sticker["sticker"]
        if not isinstance(name, str) or not ASSET_NAME.fullmatch(name):
            raise Problem("invalid_input")
        for field, (small, large) in STICKER_RANGE.items():
            value = sticker[field]
            if type(value) not in (float, int) or not small <= value <= large:
                raise Problem("invalid_input")
    return [{**sticker, "packId": str(uuid_param(sticker["packId"]))} for sticker in payload]


async def apply_stickers(conn, member, pet, day, payload):
    await lock_owned_pet(conn, member, pet)
    cur = await conn.execute("""
        SELECT id,status FROM pet.diary_entries
        WHERE member_id=%s AND pet_id=%s AND day=%s
        ORDER BY (kind='day') DESC,id LIMIT 1 FOR UPDATE
    """, (member, pet, day))
    diary = await cur.fetchone()
    if not diary:
        raise Problem("not_found")
    if diary["status"] != "ready":
        raise Problem("wrong_state")
    packs = await owned_items(conn, member, [uuid_param(row["packId"]) for row in payload])
    names = {str(ident): set(contents(row)) for ident, row in packs.items() if row["kind"] == "sticker_pack"}
    if any(row["sticker"] not in names.get(row["packId"], ()) for row in payload):
        raise Problem("not_found")
    result = await conn.execute("""
        UPDATE pet.diary_entries SET stickers=%s,updated_at=now() WHERE id=%s RETURNING *
    """, (Jsonb(payload), diary["id"]))
    await mark_used(conn, member, {pack["order_id"] for pack in packs.values() if pack["order_id"] is not None})
    return await result.fetchone()


async def put_outfit(req):
    member = await require_member(req)
    pet = uuid_param(req.match_info["id"])
    outfit = outfit_input(await body_json(req))
    from .pets import pet_rows, serialize

    async with req.app[POOL].connection() as conn, conn.transaction():
        await apply_outfit(conn, member["id"], pet, outfit)
        [result] = await pet_rows(conn, member["id"], pet)
    return web.json_response(serialize(result))


async def put_style(req):
    member = await require_member(req)
    pet = uuid_param(req.match_info["id"])
    style = style_input(await body_json(req))
    from .pets import pet_rows, serialize

    async with req.app[POOL].connection() as conn, conn.transaction():
        await apply_style(conn, member["id"], pet, style)
        [result] = await pet_rows(conn, member["id"], pet)
    return web.json_response(serialize(result))


async def put_stickers(req):
    member = await require_member(req)
    pet = uuid_param(req.match_info["id"])
    try:
        raw = req.match_info["date"]
        day = date.fromisoformat(raw)
        if day.isoformat() != raw:
            raise ValueError
        payload = await req.json()
    except (ValueError, UnicodeError):
        raise Problem("invalid_input") from None
    stickers = stickers_input(payload)
    from .farewell import entry_view

    async with req.app[POOL].connection() as conn, conn.transaction():
        result = await apply_stickers(conn, member["id"], pet, day, stickers)
    return web.json_response(entry_view(result))


def register(app):
    app.router.add_put("/api/pets/{id}/outfit", put_outfit)
    app.router.add_put("/api/pets/{id}/diary-style", put_style)
    app.router.add_put("/api/pets/{id}/diary/{date}/stickers", put_stickers)
