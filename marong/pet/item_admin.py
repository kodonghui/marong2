"""Validate and publish item assets in the isolated pet service (SPEC-352)."""

import csv
import json
import math
from datetime import datetime
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from .inventory import ASSET_NAME, INVENTORY_KINDS, TEMPLATES


class ItemError(ValueError):
    """Fixed reason codes safe for the operator terminal."""


def read_json(path, code):
    try:
        raw = path.read_bytes()
        if len(raw) > 32_768:
            raise ValueError
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
    except (OSError, ValueError, UnicodeError):
        raise ItemError(code) from None
    return value


def licensed(ledger, key):
    try:
        with ledger.open(encoding="utf-8-sig", newline="") as stream:
            return any(row.get("key") == key and row.get("app_sale") == "yes" for row in csv.DictReader(stream))
    except (OSError, UnicodeError, csv.Error):
        raise ItemError("license_ledger_unavailable") from None


def timestamp(data, name):
    value = data.get(name)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        raise ItemError("invalid_sale_window") from None


def required_file(folder, relative):
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        raise ItemError("missing_item_asset")
    return path


def check_image(path, *, kind, box=None):
    from PIL import Image

    try:
        with Image.open(path) as im:
            if kind == "layer":
                if im.format != "PNG" or im.size != (1024, 1024) or "A" not in im.getbands():
                    raise ItemError("invalid_layer_format")
                alpha = im.getchannel("A")
                positive = 1024 * 1024 - alpha.histogram()[0]
                inner = alpha.crop(box)
                inside = inner.width * inner.height - inner.histogram()[0]
                if not positive or (positive - inside) * 100 > positive * 2:
                    raise ItemError("layer_outside_slot")
            elif kind == "theme":
                if im.format not in {"PNG", "WEBP"} or im.width < 1080 or im.height < 1920:
                    raise ItemError("invalid_theme_size")
                im.verify()
            elif im.format != "WEBP":
                raise ItemError("invalid_thumbnail")
            else:
                im.verify()
    except (OSError, Image.DecompressionBombError):
        raise ItemError("invalid_item_image") from None


def slot_box(templates, name, slot):
    value = read_json(templates / f"{name}.json", "item_template_unavailable")
    slots = value.get("slots")
    box = slots.get(slot) if isinstance(slots, dict) else None
    if (not isinstance(box, list) or len(box) != 4
            or any(type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1 for n in box)
            or not (box[0] < box[2] and box[1] < box[3])):
        raise ItemError("invalid_template_slot")
    return tuple(math.floor(n * 1024) if index < 2 else math.ceil(n * 1024) for index, n in enumerate(box))


def validate(folder, templates, ledger):
    folder = folder.resolve()
    data = read_json(required_file(folder, "item.json"), "invalid_item")
    kind, name, key = (data.get(field) for field in ("kind", "name", "licenseKey"))
    if (not isinstance(kind, str) or kind not in INVENTORY_KINDS or not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 30 or not name.isprintable()):
        raise ItemError("invalid_item")
    if not isinstance(key, str) or not licensed(ledger, key):
        raise ItemError("missing_approved_license")
    slot, price = data.get("slot"), data.get("priceKrw")
    flags = tuple(data.get(field, False) for field in ("isDefault", "sellable", "limited"))
    if any(type(flag) is not bool for flag in flags):
        raise ItemError("invalid_item_flags")
    default, sellable, limited = flags
    if (isinstance(slot, str) and slot in {"head", "body", "neck"}) != (kind == "wear") or (kind != "wear" and slot is not None):
        raise ItemError("invalid_item_slot")
    if ((price is not None and (type(price) is not int or not 1 <= price <= 100000))
            or sellable and (price is None or default or kind == "font")):
        raise ItemError("invalid_item_price")
    starts, ends = (timestamp(data, field) for field in ("saleStartsAt", "saleEndsAt"))
    if (sellable and starts is None) or (limited and ends is None) or (starts is not None and ends is not None and starts >= ends):
        raise ItemError("invalid_sale_window")
    tags = data.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not ASSET_NAME.fullmatch(tag) for tag in tags):
        raise ItemError("invalid_item_tags")
    children = data.get("contents", [])
    if not isinstance(children, list) or len(children) > 40 or (kind != "theme_package" and children):
        raise ItemError("invalid_item_contents")
    try:
        contents = list(dict.fromkeys(UUID(value) for value in children))
    except (TypeError, ValueError, AttributeError):
        raise ItemError("invalid_item_contents") from None

    files = {"thumb.webp": required_file(folder, "thumb.webp")}
    check_image(files["thumb.webp"], kind="thumb")
    assets = {"thumb": "thumb.webp"}
    if kind == "wear":
        assets["layers"] = {}
        for template in sorted(TEMPLATES):
            layer = f"layers/{template}.png"
            files[layer] = required_file(folder, layer)
            check_image(files[layer], kind="layer", box=slot_box(templates, template, slot))
            assets["layers"][template] = layer
    elif kind == "theme":
        files["background.webp"] = required_file(folder, "background.webp")
        check_image(files["background.webp"], kind="theme")
        assets["background"] = "background.webp"
    elif kind == "font":
        path = required_file(folder, "font.woff2")
        with path.open("rb") as stream:
            if stream.read(4) != b"wOF2" or (not default and data.get("packageOnly") is not True):
                raise ItemError("invalid_font_asset")
        files["font.woff2"] = path
        assets["font"] = "font.woff2"
    elif kind == "sticker_pack":
        names = data.get("stickers", [])
        if not isinstance(names, list) or not 1 <= len(names) <= 40 or any(
                not isinstance(value, str) or not ASSET_NAME.fullmatch(value) for value in names):
            raise ItemError("invalid_sticker_names")
        assets["contents"] = list(dict.fromkeys(names))
        for sticker in assets["contents"]:
            file = f"stickers/{sticker}.webp"
            files[file] = required_file(folder, file)
            check_image(files[file], kind="thumb")
    if kind == "theme_package":
        assets["contents"] = [value.hex for value in contents]
    values = {"kind": kind, "name": name.strip(), "slot": slot, "price": price,
              "default": default, "sellable": sellable, "limited": limited, "starts": starts, "ends": ends,
              "license": key, "tags": tags, "contents": contents, "assets": Jsonb(assets)}
    return values, files


def add_item(conn, settings, folder, templates, ledger):
    values, files = validate(folder, templates, ledger)
    item = uuid4()
    root = (settings.media_dir / "items").resolve()
    root.mkdir(parents=True, exist_ok=True)
    output = root / str(item)
    with TemporaryDirectory(prefix=".staging-", dir=root) as staging:
        source = Path(staging) / str(item)
        for relative, path in files.items():
            to = source / relative
            to.parent.mkdir(parents=True, exist_ok=True)
            copyfile(path, to)
        try:
            with conn.transaction():
                if values["contents"]:
                    match = conn.execute("SELECT count(*) FROM pet.items WHERE id=ANY(%s::uuid[])", (values["contents"],))
                    if match.fetchone()[0] != len(values["contents"]):
                        raise ItemError("unknown_package_item")
                conn.execute("""
                    INSERT INTO pet.items(id,kind,name,slot,price_krw,is_default,sellable,limited,
                                          sale_starts_at,sale_ends_at,license_key,tags,contents,assets)
                    VALUES (%(id)s,%(kind)s,%(name)s,%(slot)s,%(price)s,%(default)s,%(sellable)s,%(limited)s,
                            %(starts)s,%(ends)s,%(license)s,%(tags)s,%(contents)s,%(assets)s)
                """, {"id": item, **values})
                source.rename(output)
        except Exception:
            if output.is_dir() and not source.exists():
                output.rename(source)
            raise
    return item


def end_item(conn, item):
    return conn.execute("""
        UPDATE pet.items SET sellable=false,ended_at=coalesce(ended_at,now())
        WHERE id=%s RETURNING id
    """, (item,)).fetchone()


def reopen_item(conn, item):
    row = conn.execute("""
        UPDATE pet.items SET sellable=true,ended_at=NULL,sale_starts_at=now()
        WHERE id=%s AND kind<>'font' AND NOT limited AND NOT is_default AND price_krw IS NOT NULL
          AND (sale_ends_at IS NULL OR sale_ends_at>now()) RETURNING id
    """, (item,)).fetchone()
    if row is None:
        raise ItemError("item_cannot_reopen")
    return row
