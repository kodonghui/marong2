"""Generate the original front-facing pet template artwork and mask (SPEC-322, SPEC-324)."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw


SIZE = 1024
SCALE = 2
OUTLINE = "#563b30"
EMPLATES = {
    "dog_small": {"species": "dog", "body": (315, 456, 705, 849), "head": (308, 214, 716, 594),
                  "ears": (275, 238, 749, 506), "coat": "#c9945e", "ear": "#9d623b", "cream": "#f5dfbc"},
    "dog_large": {"species": "dog", "body": (235, 439, 789, 880), "head": (263, 181, 761, 605),
                  "ears": (221, 220, 803, 521), "coat": "#b48464", "ear": "#79533e", "cream": "#ecd2b2"},
    "dog_long": {"species": "dog", "body": (303, 477, 721, 863), "head": (334, 184, 690, 568),
                 "ears": (253, 229, 771, 626), "coat": "#c1855a", "ear": "#874e34", "cream": "#f2cf9c"},
    "cat": {"species": "cat", "body": (335, 455, 689, 821), "head": (322, 252, 702, 572),
            "ears": (329, 167, 695, 445), "coat": "#c58960", "ear": "#dc9b85", "cream": "#f6dfbf"},
    "cat_round": {"species": "cat", "body": (253, 451, 771, 858), "head": (274, 226, 750, 599),
                  "ears": (298, 163, 726, 452), "coat": "#aa968a", "ear": "#d5a196", "cream": "#f2dece"},
}


def art(spec):
    canvas = Image.new("RGBA", (SIZE * SCALE,) * 2)
    painter = ImageDraw.Draw(canvas)
    bx0, by0, bx1, by1 = spec["body"]
    hx0, hy0, hx1, hy1 = spec["head"]
    ex0, ey0, ex1, ey1 = spec["ears"]
    width, height = hx1 - hx0, hy1 - hy0
    coat, ear, cream = (spec[key] for key in ("coat", "ear", "cream"))
    cat = spec["species"] == "cat"

    def ellipse(box, fill, *, border=OUTLINE, stroke=8):
        painter.ellipse(tuple(round(value * SCALE) for value in box), fill, border, stroke * SCALE)

    def polygon(points, fill, *, border=OUTLINE):
        points = [(round(x * SCALE), round(y * SCALE)) for x, y in points]
        painter.polygon(points, fill=fill)
        if border:
            painter.line(points + [points[0]], fill=border, width=8 * SCALE, joint="curve")

    def line(points, color=OUTLINE, stroke=6):
        painter.line([(round(x * SCALE), round(y * SCALE)) for x, y in points],
                     fill=color, width=stroke * SCALE, joint="curve")

    # Tail, seated body and paired paws form the same pose under each silhouette.
    if cat:
        ellipse((bx1 - 88, by1 - 173, bx1 + 126, by1 - 41), coat)
        ellipse((bx1 + 7, by1 - 222, bx1 + 126, by1 - 91), coat)
    else:
        ellipse((bx1 - 88, by1 - 220, bx1 + 85, by1 - 90), coat)
    ellipse(spec["body"], coat)
    ellipse((bx0 + 85, by0 + 116, bx1 - 85, by1 - 20), cream, border=None)
    for x in (bx0 + 7, bx1 - 145):
        ellipse((x, by1 - 72, x + 138, by1 + 31), coat)
        for offset in (50, 78):
            line(((x + offset, by1 + 14), (x + offset - 3, by1 + 24)), stroke=4)

    if cat:
        for side in (-1, 1):
            def reflect(x, side=side):
                return 512 + side * (512 - x)
            points = [(ex0 + 4, ey1), (ex0, ey0 + 46), (ex0 + 15, ey0),
                      (ex0 + 124, ey0 + 96), (ex0 + 164, ey1)]
            polygon([(reflect(x), y) for x, y in points], coat)
            points = [(ex0 + 31, ey1 - 64), (ex0 + 25, ey0 + 46),
                      (ex0 + 98, ey0 + 102), (ex0 + 125, ey1 - 51)]
            polygon([(reflect(x), y) for x, y in points], ear, border=None)
    else:
        spread = max(130, hx0 - ex0 + 66)
        ellipse((ex0, ey0, ex0 + spread, ey1), ear)
        ellipse((ex1 - spread, ey0, ex1, ey1), ear)

    ellipse(spec["head"], coat)
    eye_y = hy0 + height * .51
    muzzle = hy0 + height * .72
    eye_gap = width * .22
    ellipse((512 - width * .35, muzzle - 54, 512 + width * .35, hy1 - 10), cream, border=None)
    for side in (-1, 1):
        x = 512 + side * eye_gap
        ellipse((x - 13, eye_y - 21, x + 13, eye_y + 20), "#392621", border=None)
        ellipse((x - 6, eye_y - 14, x + 2, eye_y - 6), "#fff3dd", border=None)
        cheek = x + side * 27
        ellipse((cheek - 25, muzzle - 27, cheek + 25, muzzle - 9), "#deaa87", border=None)
        if cat:
            for shift in (-8, 8):
                line(((cheek + side * 8, muzzle + shift), (cheek + side * 53, muzzle + shift - 6)), stroke=3)
    polygon([(491, muzzle - 8), (533, muzzle - 8), (512, muzzle + 13)], "#664137", border=None)
    line(((512, muzzle + 10), (512, muzzle + 23), (499, muzzle + 35), (486, muzzle + 34)), stroke=5)
    line(((512, muzzle + 23), (525, muzzle + 35), (538, muzzle + 34)), stroke=5)
    if cat:
        for side in (-1, 1):
            line(((512 + side * 28, hy0 + 20), (512 + side * 22, hy0 + 58)), ear, 10)
    return canvas.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def write_templates(root):
    root.mkdir(parents=True, exist_ok=True)
    for ident, spec in EMPLATES.items():
        image = art(spec)
        image_name, mask_name = f"{ident}.png", f"{ident}-mask.png"
        image.save(root / image_name, optimize=True)
        image.getchannel("A").save(root / mask_name, optimize=True)
        hx0, hy0, hx1, hy1 = spec["head"]
        ex0, ey0, ex1, _ = spec["ears"]
        boxes = {"head": (min(ex0, hx0), min(ey0, hy0), max(ex1, hx1), hy1),
                 "body": spec["body"], "neck": (hx0 + 47, hy1 - 16, hx1 - 47, hy1 + 103)}
        manifest = {"id": ident, "species": spec["species"], "width": SIZE, "height": SIZE,
                    "image": image_name, "mask": mask_name,
                    "slots": {name: [round(value / SIZE, 7) for value in box] for name, box in boxes.items()}}
        (root / f"{ident}.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n",
        )


def write_web_art(root):
    root.mkdir(parents=True, exist_ok=True)
    welcome = Image.new("RGBA", (720, 540), (0, 0, 0, 0))
    for name, offset in (("dog_small", (102, 25)), ("cat", (373, 64))):
        animal = art(EMPLATES[name])
        animal = animal.crop(animal.getbbox())
        animal.thumbnail((246, 442), Image.Resampling.LANCZOS)
        welcome.alpha_composite(animal, offset)
    welcome.save(root / "pet-welcome.webp", lossless=True)
    icon = Image.new("RGBA", (512, 512), "#f1e6d6")
    animal = art(EMPLATES["dog_small"])
    animal = animal.crop(animal.getbbox())
    animal.thumbnail((440, 432), Image.Resampling.LANCZOS)
    icon.alpha_composite(animal, ((512 - animal.width) // 2, (512 - animal.height) // 2))
    icon.save(root / "pet-icon.png", optimize=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "design/pet/templates")
    parser.add_argument("--web-assets", type=Path)
    arguments = parser.parse_args()
    write_templates(arguments.output)
    if arguments.web_assets:
        write_web_art(arguments.web_assets)
