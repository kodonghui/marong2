"""Fit wearable PNGs into the default character's 1024-pixel slot boxes."""
import argparse
import json
from pathlib import Path

from PIL import Image

SLOTS = {
    "head": ((0.30, 0.17, 0.70, 0.398), "bottom"),
    "neck": ((0.31, 0.49, 0.69, 0.63), "center"),
    "body": ((0.29, 0.50, 0.71, 0.772), "bottom"),
}


def fit(image, slot):
    (x0, y0, x1, y1), anchor = SLOTS[slot]
    image = image.convert("RGBA")
    bounds = image.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("empty layer")
    piece = image.crop(bounds)
    scale = min((x1 - x0) * 1024 / piece.width, (y1 - y0) * 1024 / piece.height)
    piece = piece.resize((round(piece.width * scale), round(piece.height * scale)), Image.Resampling.LANCZOS)
    left = round((x0 + x1) / 2 * 1024 - piece.width / 2)
    top = round(y1 * 1024 - piece.height) if anchor == "bottom" else round((y0 + y1) / 2 * 1024 - piece.height / 2)
    result = Image.new("RGBA", (1024, 1024))
    result.alpha_composite(piece, (left, top))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("marong/decor/v1"))
    parser.add_argument("--redrawn-dir", type=Path, help="Directory of transparent redrawn body PNGs named by item ID")
    args = parser.parse_args()
    data = json.loads((args.catalog / "items.json").read_text(encoding="utf-8"))
    for item in data["items"]:
        if not item.get("slot"):
            continue
        if item["slot"] == "body":
            if args.redrawn_dir is None:
                continue
            source = args.redrawn_dir / (item["id"] + ".png")
        else:
            source = args.catalog / item["id"] / "cat_round.png"
        with Image.open(source) as image:
            fit(image, item["slot"]).save(args.catalog / item["id"] / "marong.png")
        item["files"]["marong.png"] = "marong.png"
    (args.catalog / "items.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
