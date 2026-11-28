"""Mockup only: fit the shipped wearable layers onto the default 마롱이 face (way A in design/marong-wear-mockup.md).

Not product code. It shows what the zero-cost automatic fit looks like, so 사용자님 can judge it on the mockup.
The product version (TASK-600) writes marong/decor/v1/<item>/marong.png the same way and is checked by TC-760.

  python design/marong-wear-mockup/fit-layers.py <repo root> <out dir>

Each wearable item's cat_round layer is cut to its visible box, scaled to fit the 마롱이 slot box below while keeping
its shape, and placed on a 1024 transparent square at the box's anchor. The 512 WebP copies next to this file are the
same pictures halved, like the face pictures in marong/call/static/face/v1/.
"""
import json
import sys
from pathlib import Path

from PIL import Image

# 마롱이 slot boxes on the 1024 canvas: (x0, y0, x1, y1) as fractions, and which edge of the box the item keeps.
# Measured on face 01: body outline x 208-816, y 240-782; ears y 240-320; brows y about 410; cheeks end y about 536.
SLOTS = {
    "head": ((0.30, 0.17, 0.70, 0.398), "bottom"),  # the hat's brim rests just above the brows
    "neck": ((0.31, 0.49, 0.69, 0.63), "center"),   # under the cheeks
    "body": ((0.29, 0.50, 0.71, 0.772), "bottom"),  # the hem reaches the feet line
}
SOURCE = "cat_round.png"  # the biggest of the five template layers


def fit(layer, slot):
    (x0, y0, x1, y1), anchor = SLOTS[slot]
    piece = layer.crop(layer.getchannel("A").getbbox())
    scale = min((x1 - x0) * 1024 / piece.width, (y1 - y0) * 1024 / piece.height)
    piece = piece.resize((round(piece.width * scale), round(piece.height * scale)), Image.LANCZOS)
    left = round((x0 + x1) / 2 * 1024 - piece.width / 2)
    top = {"bottom": round(y1 * 1024 - piece.height), "top": round(y0 * 1024),
           "center": round((y0 + y1) / 2 * 1024 - piece.height / 2)}[anchor]
    out = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    out.alpha_composite(piece, (left, top))
    return out


def main(root, out):
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    items = json.loads((root / "marong/decor/v1/items.json").read_text(encoding="utf-8"))["items"]
    for item in items:
        if not item.get("slot"):
            continue
        layer = Image.open(root / "marong/decor/v1" / item["id"] / SOURCE).convert("RGBA")
        fitted = fit(layer, item["slot"])
        fitted.save(out / f"{item['id']}.png")
        fitted.resize((512, 512), Image.LANCZOS).save(out / f"{item['id']}.webp", lossless=True, quality=100, method=6)


if __name__ == "__main__":
    main(*sys.argv[1:3])
