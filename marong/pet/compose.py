"""Shared canvas geometry and raster composition for exports, push and diary cards."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image


CANVAS = (1536, 1024)
SPRITE = (1024, 1024)
SLOTS = ("body", "neck", "head")


@dataclass(frozen=True)
class Background:
    name: str
    center_x: int
    floor_y: int
    height: int
    tags: tuple[str, ...]

    def asset(self, directory):
        return Path(directory) / f"{self.name}.webp"


BACKGROUNDS = {item.name: item for item in (
    Background("home_livingroom", 768, 876, 708, ("home",)),
    Background("home_sofa", 903, 879, 694, ("home",)),
    Background("home_window", 791, 888, 690, ("home",)),
    Background("walking_path", 787, 887, 674, ("walk",)),
    Background("park", 768, 888, 681, ("park", "walk")),
    Background("beach", 818, 888, 661, ("beach", "walk")),
    Background("snow", 771, 877, 683, ("snow",)),
    Background("rain_window", 764, 886, 686, ("rain", "home")),
    Background("night_blanket", 765, 865, 714, ("night", "home")),
    Background("birthday", 768, 869, 663, ("birthday", "home")),
    Background("autumn_leaves", 788, 887, 657, ("autumn", "walk")),
    Background("rainbow_meadow", 766, 886, 680, ("memorial_ok",)),
)}


def background_for(name=None, *, memorial=False, tag=None):
    allowed = [item for item in BACKGROUNDS.values() if ("memorial_ok" in item.tags) == memorial]
    if name in BACKGROUNDS and BACKGROUNDS[name] in allowed:
        return BACKGROUNDS[name]
    if tag:
        match = next((item for item in allowed if tag in item.tags), None)
        if match:
            return match
    return allowed[0]


def checked_image(source, size, *, alpha=False):
    image = Image.open(source if not isinstance(source, bytes) else BytesIO(source))
    with image:
        if image.size != size or (alpha and "A" not in image.getbands()):
            raise ValueError("invalid_composition_layer")
        return image.convert("RGBA")


def compose(background, stage, expression, *, outfit=None):
    """Align the visible body, then reuse that transform for every 1024px outfit layer."""
    result = checked_image(background, CANVAS)
    pet = checked_image(expression, SPRITE, alpha=True)
    silhouette = pet.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    bounds = silhouette.getbbox()
    if bounds is None:
        raise ValueError("empty_pet_layer")
    left, top, right, bottom = bounds
    ratio = stage.height / (bottom - top)
    extent = round(SPRITE[0] * ratio)
    if not 1 <= extent <= 4096:
        raise ValueError("invalid_stage_height")
    x = round(stage.center_x - (left + right) * ratio / 2)
    y = round(stage.floor_y - bottom * ratio)
    result.alpha_composite(pet.resize((extent, extent), Image.Resampling.LANCZOS), (x, y))
    for slot in SLOTS:
        source = (outfit or {}).get(slot)
        if source is not None:
            layer = checked_image(source, SPRITE, alpha=True)
            result.alpha_composite(layer.resize((extent, extent), Image.Resampling.LANCZOS), (x, y))
    output = BytesIO()
    result.save(output, format="PNG")
    return output.getvalue()
