"""Grant published free defaults once when a member signs up or signs in (SPEC-346)."""

import re

from aiohttp import web

from .http import CONFIG, POOL, Problem, require_member, uuid_param


SHOP_KINDS = {"wear", "sticker_pack", "theme", "theme_package"}
INVENTORY_KINDS = SHOP_KINDS | {"font"}
TEMPLATES = {"dog_small", "dog_large", "dog_long", "cat", "cat_round"}
ASSET_NAME = re.compile(r"[a-z0-9_]{1,40}")
ON_SALE = """i.sellable AND i.ended_at IS NULL AND i.sale_starts_at<=now()
              AND (i.sale_ends_at IS NULL OR i.sale_ends_at>now())"""


async def sync_defaults(conn, member_id):
    await conn.execute(
        """INSERT INTO pet.inventory(member_id,item_id,source)
        SELECT %s,id,'free_default' FROM pet.items WHERE is_default
        ON CONFLICT (member_id,item_id) WHERE withdrawn_at IS NULL DO NOTHING""", (member_id,),
    )
    await conn.execute("UPDATE pet.members SET defaults_synced_at=now() WHERE id=%s", (member_id,))


def query_parameter(req, name, values, *, required=False):
    found = req.query.getall(name, [])
    if not found and not required:
        return None
    if len(found) != 1 or found[0] not in values:
        raise Problem("invalid_input")
    return found[0]


def contents(row):
    manifest = row["assets"]
    values = manifest.get("contents") if isinstance(manifest, dict) else None
    if row["kind"] not in {"sticker_pack", "theme_package"} or not isinstance(values, list):
        return []
    return [value for value in values[:40] if isinstance(value, str) and ASSET_NAME.fullmatch(value)]


async def list_inventory(req):
    member = await require_member(req)
    kind = query_parameter(req, "kind", INVENTORY_KINDS)
    async with req.app[POOL].connection() as conn:
        result = await conn.execute("""
            SELECT i.id,i.kind,i.name,i.slot,i.assets,h.source,
                   ARRAY(SELECT p.id FROM pet.pets p JOIN pet.decor d ON d.pet_id=p.id
                         WHERE p.member_id=h.member_id AND i.id IN (d.head_item,d.body_item,d.neck_item)
                         ORDER BY p.created_at,p.id LIMIT 5) AS worn_by,
                   CASE WHEN o.status='fulfilled' AND o.used_at IS NULL AND o.paid_at+interval '7 days'>now()
                        THEN o.paid_at+interval '7 days' END AS withdrawable_until
            FROM pet.inventory h JOIN pet.items i ON i.id=h.item_id
            LEFT JOIN pet.orders o ON o.id=h.order_id AND o.member_id=h.member_id
            WHERE h.member_id=%s AND h.withdrawn_at IS NULL
              AND (%s::text IS NULL OR i.kind=%s)
            ORDER BY h.acquired_at DESC,i.id LIMIT 500
        """, (member["id"], kind, kind))
        rows = await result.fetchall()
    return web.json_response({"items": [{
        "itemId": str(row["id"]), "kind": row["kind"], "name": row["name"], "slot": row["slot"],
        "source": row["source"], "wornBy": [str(pet) for pet in row["worn_by"]], "contents": contents(row),
        "withdrawableUntil": row["withdrawable_until"].isoformat() if row["withdrawable_until"] else None,
    } for row in rows]})


async def list_shop(req):
    member = await require_member(req)
    kind = query_parameter(req, "kind", SHOP_KINDS)
    async with req.app[POOL].connection() as conn:
        result = await conn.execute(f"""
            SELECT i.id,i.kind,i.name,i.slot,i.price_krw,i.limited,i.sale_ends_at,i.assets,
                   h.id IS NOT NULL AS owned,
                   coalesce((SELECT value='true'::jsonb FROM pet.settings WHERE key='payments_enabled'),false)
                   AND h.id IS NULL AS purchasable
            FROM pet.items i LEFT JOIN pet.inventory h
              ON h.member_id=%(member)s AND h.item_id=i.id AND h.withdrawn_at IS NULL
            WHERE {ON_SALE} AND i.kind<>'font' AND i.price_krw<=100000
              AND (%(kind)s::text IS NULL OR i.kind=%(kind)s)
              AND EXISTS (
                  SELECT 1 FROM pet.pets p WHERE p.member_id=%(member)s AND p.mode='living' AND p.status='active'
              )
            ORDER BY i.sale_starts_at DESC,i.id LIMIT 500
        """, {"member": member["id"], "kind": kind})
        rows = await result.fetchall()
    return web.json_response({"items": [{
        "id": str(row["id"]), "kind": row["kind"], "name": row["name"], "slot": row["slot"],
        "priceKrw": row["price_krw"], "limited": row["limited"],
        "saleEndsAt": row["sale_ends_at"].isoformat() if row["sale_ends_at"] else None,
        "owned": row["owned"], "purchasable": row["purchasable"], "contents": contents(row),
    } for row in rows]})


async def layer(req):
    member = await require_member(req)
    item = uuid_param(req.match_info["id"])
    template = query_parameter(req, "template", TEMPLATES, required=True)
    async with req.app[POOL].connection() as conn:
        result = await conn.execute(f"""
            SELECT 1 FROM pet.items i
            WHERE i.id=%(item)s AND i.kind='wear' AND (
                EXISTS (SELECT 1 FROM pet.inventory h WHERE h.member_id=%(member)s
                        AND h.item_id=i.id AND h.withdrawn_at IS NULL)
                OR ({ON_SALE} AND EXISTS (
                    SELECT 1 FROM pet.pets p
                    WHERE p.member_id=%(member)s AND p.mode='living' AND p.status='active'
                ))
            )
        """, {"item": item, "member": member["id"]})
        if not await result.fetchone():
            raise Problem("not_found")
    root = (req.app[CONFIG].media_dir / "items").resolve()
    image = (root / str(item) / "layers" / (template + ".png")).resolve()
    if not image.is_relative_to(root) or not image.is_file():
        raise Problem("not_found")
    return web.FileResponse(image, headers={"Content-Type": "image/png", "Cache-Control": "private, no-store"})


def register(app):
    app.router.add_get("/api/me/inventory", list_inventory, allow_head=False)
    app.router.add_get("/api/shop", list_shop, allow_head=False)
    app.router.add_get("/api/items/{id}/layer", layer, allow_head=False)
