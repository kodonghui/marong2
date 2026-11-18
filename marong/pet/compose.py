"""Shared canvas geometry and raster composition for exports, push and diary cards."""

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path

from PIL import Image


REGISTRY = Path(__file__).resolve().parents[2] / "design" / "pet" / "backgrounds" / "stages.json"
STAGES = json.loads(REGISTRY.read_text(encoding="utf-8"))
CANVAS = (STAGES["width"], STAGES["height"])
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


BACKGROUNDS = {
    name: Background(name, stage["centerX"], stage["floorY"], stage["height"], tuple(stage["tags"]))
    for name, stage in STAGES["stages"].items()
}


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
