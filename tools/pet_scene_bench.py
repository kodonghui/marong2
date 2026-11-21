"""Opt-in TC-537 with two licensed public photos and an output folder outside the checkout."""

import argparse
import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from time import monotonic
from types import SimpleNamespace

from aiohttp import ClientSession
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from marong.character.artwork import ImageEditor
from marong.character.graphics import EXPRESSIONS, MATCH, Templates, alpha, fit_score, head_in_box, preview_png
from marong.character.photos import crop_pick, sanitize
from marong.character.traits import EDITABLE, TEXT_LIMITS, template_for, valid_result
from marong.character.vision import VisionExtractor
from marong.character.worker import photo_selection
from marong.config import load_settings
from marong.diary_models import DiaryModels
from marong.pet.cost import microusd
from marong.pet.settings import PriceBook
from marong.scene_picture import ScenePictures


MAX_COST = Decimal("3")
MODEL = "gpt-image-2.5-flare"
TOPICS = (
    "The pet character sits beside a snowman.",
    "The pet character looks up at falling cherry blossoms.",
    "The pet character curls up beside a soft blanket.",
    "The pet character sits on a hill under a starry sky.",
    "The pet character looks at a patch of autumn leaves.",
    "The pet character wears a soft striped scarf.",
    "The pet character looks out of a rainy window.",
    "The pet character naps next to a small flowerpot.",
    "The pet character sits beside a little sled.",
    "The pet character watches snow fall outside.",
)
DIARIES = (
    ("sunny", "The pet character sits in a warm sunny room."),
    ("cloudy", "The pet character looks at the clouds from a window."),
    ("rain", "The pet character rests next to a window in the rain."),
    ("snow", "The pet character watches falling snow near a wooden bench."),
    ("rainbow", "The pet character sits beside a flowerpot in the sunshine."),
)


class Meter:
    def __init__(self, limit):
        self.prices = PriceBook.read(ROOT / "marong" / "pet" / "prices.json")
        self.limit = limit
        self.cost = Decimal(0)
        self.times = []

    def reserve(self):
        if self.cost + Decimal(".15") > self.limit:
            raise RuntimeError("benchmark budget reached")

    async def record(self, job_id, run):
        self.cost += Decimal(microusd(self.prices, run)) / 1_000_000

    async def measure(self, action):
        self.reserve()
        begin = monotonic()
        try:
            return await action()
        finally:
            self.times.append(round(monotonic() - begin, 3))


class LocalMedia:
    def __init__(self, files):
        self.files = files

    async def read(self, conn, ident, filename):
        return self.files[filename]


@asynccontextmanager
async def local_connection():
    yield None


def contact_sheet(folder, title):
    files = [folder / "reference.png", folder / "preview.png", folder / "front.png"]
    files += [folder / (slot + ".png") for slot in EXPRESSIONS]
    files += list(sorted(folder.glob("topic-*.*"))) + list(sorted(folder.glob("diary-*.*")))
    cells = [(path.stem, path) for path in files if path.is_file()]
    canvas = Image.new("RGB", (1024, 46 + ((len(cells) + 4) // 5) * 202), "#fff8ec")
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 16), title, fill="#432619", font_size=20)
    for index, (label, path) in enumerate(cells):
        x, y = (index % 5) * 204 + 4, (index // 5) * 202 + 45
        with Image.open(path) as raw:
            image = raw.convert("RGBA")
            image.thumbnail((192, 172))
            canvas.paste(image, (x + (192 - image.width) // 2, y), image)
        draw.text((x + 8, y + 176), label, fill="#432619", font_size=15)
    canvas.save(folder / "comparison.png")


async def fitted(meter, generate, mask, minimum, head=None):
    reasons = []
    for _ in range(3):
        try:
            image = preview_png(await meter.measure(generate))
        except ValueError as exc:
            if str(exc) not in {"unexpected_alpha", "invalid_image_format", "invalid_image_bytes"}:
                raise
            reasons.append(str(exc))
            continue
        score = fit_score(image, mask)
        head_fits = head is None or head_in_box(alpha(image), head)
        if score >= minimum and head_fits:
            return image
        reasons.append(f"template_mismatch iou={score:.3f} head={head_fits}")
    raise RuntimeError(f"portrait fit check failed ({', '.join(reasons)})")


async def draw_reference(kind, path, out, number, vision, editor, templates, meter, models, counts):
    folder = out / kind
    folder.mkdir()
    job = {"id": number}
    raw = sanitize(path.read_bytes(), 1, lambda _: []).png
    (folder / "reference.png").write_bytes(raw)
    observed = await meter.measure(lambda: vision([raw], job))
    if not valid_result(observed) or not observed["petVisible"] or observed["species"] != kind:
        print(json.dumps({"kind": kind, "valid": valid_result(observed),
                          "species_match": observed.get("species") == kind,
                          "pet_visible": observed.get("petVisible"),
                          "field_lengths": {field: len(str(observed.get(field) or ""))
                                            for field in TEXT_LIMITS}}, ensure_ascii=False), flush=True)
        raise RuntimeError("public reference did not pass vision validation")
    traits = {key: value for key, value in observed.items() if key in EDITABLE}
    template = template_for(traits)
    selected = photo_selection(number, ["photo_1"], observed["bestPhoto"], observed["petBox"])
    photo = crop_pick(raw, selected["box"])
    mask, head = templates.mask(template), templates.head(template)
    preview = await meter.measure(lambda: editor.preview(
        model=MODEL, template=template, traits=traits, photo=photo, job=job))
    (folder / "preview.png").write_bytes(preview)
    front = await fitted(meter, lambda: editor.candidate(
        model=MODEL, template=template, traits=traits, note=None, slot=1, photo=photo, job=job), mask, MATCH)
    refs = {"front": front}
    front_mask = alpha(front)
    (folder / "front.png").write_bytes(front)
    for expression in EXPRESSIONS:
        refs[expression] = await fitted(meter, lambda: editor.expression(
            model=MODEL, template=template, front=front, expression=expression, job=job), front_mask, .85, head)
        (folder / (expression + ".png")).write_bytes(refs[expression])
    art = ScenePictures(SimpleNamespace(pool=SimpleNamespace(connection=local_connection)),
                        LocalMedia(refs), models, MODEL)
    character = {"id": number, "kind": kind, "template": template, "traits": traits}
    for purpose, cases in (("topic", [("sunny", scene) for scene in TOPICS]), ("diary", DIARIES)):
        for index, (weather, scene) in enumerate(cases, 1):
            result = await art.draw(purpose, character, (), scene, weather=weather)
            if not result.picture:
                raise RuntimeError(f"{purpose} returned {result.reason}")
            (folder / f"{purpose}-{index:02}.{result.picture.format}").write_bytes(result.picture.data)
            counts[kind] += 1
    contact_sheet(folder, kind)


async def trial(dog, cat, out, budget):
    settings = load_settings()
    image_key = os.getenv("MARONG_DIARY_IMAGE_API_KEY", "")
    if not settings.anthropic_api_key or not image_key:
        raise SystemExit("benchmark model settings are unavailable")
    templates = Templates()
    meter = Meter(budget)
    models = DiaryModels(settings, os.environ)
    original_edit = models.edit_picture

    async def edit(*args, **kwargs):
        result = await meter.measure(lambda: original_edit(*args, **kwargs))
        meter.cost += result.cost or Decimal(".025")
        return result

    models.edit_picture = edit
    counts = {"dog": 0, "cat": 0}
    failed = []
    try:
        async with ClientSession() as client:
            vision = VisionExtractor(client, settings.anthropic_api_key,
                                    SimpleNamespace(vision_model="claude-sonnet-5-5"), meter)
            editor = ImageEditor(client, image_key, templates, meter)
            for number, (kind, path) in enumerate((("dog", dog), ("cat", cat)), 1):
                try:
                    await draw_reference(kind, path, out, number, vision, editor, templates, meter, models, counts)
                except (RuntimeError, ValueError) as error:
                    print(json.dumps({"kind": kind, "error": str(error)}), flush=True)
                    failed.append(kind)
    finally:
        for kind in ("dog", "cat"):
            if (out / kind).is_dir() and not (out / kind / "comparison.png").exists():
                contact_sheet(out / kind, kind + " partial")
        sheets = [Image.open(path) for path in sorted(out.glob("*/comparison.png"))]
        if sheets:
            comparison = Image.new("RGB", (1024, sum(sheet.height for sheet in sheets)), "#fff8ec")
            top = 0
            for sheet in sheets:
                with sheet:
                    comparison.paste(sheet, (0, top))
                    top += sheet.height
            comparison.save(out / "comparison.png")
        await models.close()
        print(json.dumps({"scenes": counts, "estimated_usd": str(meter.cost), "request_seconds": meter.times}),
              flush=True)
    if failed:
        raise SystemExit("incomplete benchmark: " + ", ".join(failed))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dog", type=Path, required=True)
    parser.add_argument("--cat", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--budget", type=Decimal, default=MAX_COST)
    options = parser.parse_args()
    if os.getenv("MARONG_REAL_MODEL_TESTS") != "1" or options.out.resolve().is_relative_to(ROOT):
        raise SystemExit("choose external output and explicitly opt into real models")
    if not options.budget.is_finite() or not 0 < options.budget <= MAX_COST:
        parser.error("--budget must be above zero and at most 3 USD")
    options.out.mkdir(parents=True)
    asyncio.run(trial(options.dog, options.cat, options.out, options.budget))
