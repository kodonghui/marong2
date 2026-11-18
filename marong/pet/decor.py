"""Member-scoped outfit changes (SPEC-349)."""

from aiohttp import web

from .http import POOL, Problem, body_json, require_member, uuid_param

SLOTS = ("head", "body", "neck")


def outfit_input(data):
    if set(data) != set(SLOTS):
        raise Problem("invalid_input")
    return {slot: uuid_param(data[slot]) if data[slot] is not None else None for slot in SLOTS}


async def apply_outfit(conn, member, pet, outfit):
    # Order and inventory operations take the member lock first.
    owner = await conn.execute("SELECT 1 FROM pet.members WHERE id=%s AND status='active' FOR UPDATE", (member,))
    if not await owner.fetchone():
        raise Problem("unauthenticated")
    found = await conn.execute("""
        SELECT p.status,d.head_item,d.body_item,d.neck_item
        FROM pet.pets p LEFT JOIN pet.decor d ON d.pet_id=p.id
        WHERE p.id=%s AND p.member_id=%s FOR UPDATE OF p
    """, (pet, member))
    current = await found.fetchone()
    if current is None:
        raise Problem("not_found")
    if current["status"] == "archived":
        raise Problem("archived")
    ids = sorted(set(outfit.values()) - {None})
    result = await conn.execute("""
        SELECT i.id,i.kind,i.slot,h.order_id FROM pet.inventory h JOIN pet.items i ON i.id=h.item_id
        WHERE h.member_id=%s AND h.item_id=ANY(%s::uuid[]) AND h.withdrawn_at IS NULL
        ORDER BY h.item_id FOR UPDATE OF h
    """, (member, ids))
    owned = {row["id"]: row for row in await result.fetchall()}
    if len(owned) != len(ids):
        raise Problem("not_found")
    used_orders = set()
    for slot in SLOTS:
        item = outfit[slot]
        if item is None:
            continue
        row = owned[item]
        if row["kind"] != "wear" or row["slot"] != slot:
            raise Problem("wrong_slot")
        if item != current[slot + "_item"] and row["order_id"] is not None:
            used_orders.add(row["order_id"])
    await conn.execute("""
        INSERT INTO pet.decor(pet_id,head_item,body_item,neck_item) VALUES (%s,%s,%s,%s)
        ON CONFLICT(pet_id) DO UPDATE SET head_item=EXCLUDED.head_item,body_item=EXCLUDED.body_item,
            neck_item=EXCLUDED.neck_item,updated_at=now()
        WHERE (pet.decor.head_item,pet.decor.body_item,pet.decor.neck_item) IS DISTINCT FROM
              (EXCLUDED.head_item,EXCLUDED.body_item,EXCLUDED.neck_item)
    """, (pet, *(outfit[slot] for slot in SLOTS)))
    if used_orders:
        await conn.execute("""
            UPDATE pet.orders SET used_at=coalesce(used_at,now()) WHERE member_id=%s AND id=ANY(%s::uuid[])
        """, (member, sorted(used_orders)))


async def put_outfit(req):
    member = await require_member(req)
    pet = uuid_param(req.match_info["id"])
    outfit = outfit_input(await body_json(req))
    from .pets import pet_rows, serialize

    async with req.app[POOL].connection() as conn, conn.transaction():
        await apply_outfit(conn, member["id"], pet, outfit)
        [result] = await pet_rows(conn, member["id"], pet)
    return web.json_response(serialize(result))


def register(app):
    app.router.add_put("/api/pets/{id}/outfit", put_outfit)
