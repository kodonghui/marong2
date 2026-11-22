"""Transparent images, template validation, and silhouette checks from SPEC-320–324."""

from io import BytesIO
import json
from math import ceil
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops


IMAGE_MAX = 5 * 1024 * 1024


class InvalidArtwork(ValueError):
    """An image was returned but failed the format or transparency checks."""


def preview_png(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= IMAGE_MAX:
        raise InvalidArtwork("invalid_image_bytes")
    with Image.open(BytesIO(raw)) as image:
        if image.format != "PNG" or image.size != (1024, 1024) or getattr(image, "n_frames", 1) != 1:
            raise InvalidArtwork("invalid_image_format")
        clean = image.convert("RGBA")
        min_alpha, max_alpha = clean.getchannel("A").getextrema()
        if min_alpha != 0 or max_alpha == 0:
            raise InvalidArtwork("unexpected_alpha")
        clean.info.clear()
        result = BytesIO()
        clean.save(result, "PNG")
    png = result.getvalue()
    if len(png) > IMAGE_MAX:
        raise InvalidArtwork("invalid_image_bytes")
    return png


MATCH = 0.75


def silhouette(image):
    return image.point(lambda value: 255 if value >= 128 else 0, mode="1")


def fit_score(png, reference):
    with Image.open(BytesIO(png)) as image:
        generated = silhouette(image.getchannel("A"))
    if reference.mode != "L" or reference.size != generated.size:
        raise ValueError("invalid_template_mask")
    expected = silhouette(reference)
    counts = ImageChops.logical_or(generated, expected).histogram()
    if not counts[255]:
        return 0.0
    return ImageChops.logical_and(generated, expected).histogram()[255] / counts[255]


EXPRESSIONS = ("smile", "excited", "sleepy", "surprised", "sad", "pout")


def alpha(png):
    with Image.open(BytesIO(png)) as graphic:
        return graphic.getchannel("A")


def head_in_box(mask, box):
    if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
        raise ValueError("invalid_template_head_box")
    y, x = np.nonzero(np.asarray(mask) >= 128)
    if not len(y):
        return False
    top = y < y.min() + ceil((y.max() - y.min() + 1) * 0.4)
    center_x = (x[top].mean() + 0.5) / mask.width
    center_y = (y[top].mean() + 0.5) / mask.height
    return box[0] <= center_x <= box[2] and box[1] <= center_y <= box[3]


ROOT = Path(__file__).resolve().parents[2]


TEMPLATES = ROOT / "design/pet/templates"


STYLE_REFERENCE = ROOT / "marong/topics/v1/roasted-chestnuts.webp"


TEMPLATE_IDS = ("dog_small", "dog_large", "dog_long", "cat", "cat_round")


class Templates:
    def __init__(self, root=TEMPLATES, style=STYLE_REFERENCE):
        self._fronts, self._masks, self._boxes = {}, {}, {}
        for name in TEMPLATE_IDS:
            row = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
            image_name, mask_name = f"{name}.png", f"{name}-mask.png"
            if (row["id"], row["image"], row["mask"], row["width"], row["height"]) != (name, image_name, mask_name, 1024, 1024):
                raise ValueError("pet_template_manifest")
            boxes = row["slots"]
            if set(boxes) != {"head", "body", "neck"} or any(not self._valid_box(box) for box in boxes.values()):
                raise ValueError("pet_template_slots")
            front = preview_png((root / image_name).read_bytes())
            with Image.open(BytesIO(front)) as picture, Image.open(root / mask_name) as mask:
                if mask.mode != "L" or mask.size != picture.size:
                    raise ValueError("pet_template_mask")
                if ImageChops.difference(picture.getchannel("A"), mask).getbbox():
                    raise ValueError("pet_template_alpha")
                self._masks[name] = mask.copy()
            self._fronts[name] = front
            self._boxes[name] = boxes
        self.style = style.read_bytes()
        with Image.open(BytesIO(self.style)) as image:
            if image.format != "WEBP" or len(self.style) > IMAGE_MAX:
                raise ValueError("pet_style_reference")

    @staticmethod
    def _valid_box(box):
        return (isinstance(box, list) and len(box) == 4
                and all(type(coord) in {float, int} and 0 <= coord <= 1 for coord in box)
                and box[0] < box[2] and box[1] < box[3])

    def front(self, name):
        return self._fronts[name]

    def mask(self, name):
        return self._masks[name].copy()

    def head(self, name):
        return tuple(self._boxes[name]["head"])
