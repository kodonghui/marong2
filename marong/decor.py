"""Read the versioned decor catalog and validate its repository assets."""

from dataclasses import dataclass
import csv
import json
import logging
from math import ceil, floor
from pathlib import Path
import re

from PIL import Image

from .character.graphics import TEMPLATE_IDS


log = logging.getLogger(__name__)
ROOT = Path(__file__).with_name("decor")
TEMPLATES = Path(__file__).resolve().parents[1] / "design" / "pet" / "templates"
ITEM_ID = re.compile(r"[a-z0-9-]{3,40}\Z")
SET_ID = re.compile(r"v[0-9]{1,3}\Z")
FILE_NAME = re.compile(r"[A-Za-z0-9_-]{1,40}\.(?:png|webp|woff2)\Z")
KINDS = ("hat", "top", "scarf", "background", "paper", "font", "sticker")
SLOTS = {"hat": "head", "top": "body", "scarf": "neck"}
WEAR = ("head", "body", "neck")
MARONG_SLOTS = {"head": (0.30, 0.17, 0.70, 0.398), "neck": (0.31, 0.49, 0.69, 0.63),
                "body": (0.29, 0.50, 0.71, 0.772)}
CONTENT = {".webp": "image/webp", ".png": "image/png", ".woff2": "font/woff2"}
PAPER_STYLES = {"manuscript"}


@dataclass(frozen=True)
class Item:
    id: str
    kind: str
    slot: str | None
    name: str
    prompt: str | None
    price: int
    starter: bool
    files: dict[str, Path]
    license_id: str
    paper_style: str | None


class DecorCatalog:
    def __init__(self, root=ROOT, set_name="v1", *, templates=TEMPLATES):
        self.root = Path(root).resolve() / set_name
        self.set = set_name
        self.templates = Path(templates)
        self.items = {}
        self.licenses = {}
        if not SET_ID.fullmatch(set_name):
            raise ValueError("decor_set")
        manifest = self.root / "items.json"
        if not manifest.is_file():
            return
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("set") != set_name or not isinstance(data.get("items"), list):
            raise ValueError("decor_manifest")
        for index, entry in enumerate(data["items"], 1):
            parsed = self._item(entry)
            if parsed is None:
                log.warning("decor_catalog_rejected row=%s missing=id", index)
                continue
            if parsed.id in self.items:
                raise ValueError("decor_duplicate")
            self.items[parsed.id] = parsed
        ledger = self.root / "licenses.csv"
        if ledger.is_file():
            with ledger.open(encoding="utf-8-sig", newline="") as stream:
                self.licenses = {row["id"]: row for row in csv.DictReader(stream) if row.get("id")}

    def _item(self, entry):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not ITEM_ID.fullmatch(entry["id"]):
            return None
        ident = entry["id"]
        prefix = (self.root / ident).resolve()
        files = {}
        entries = entry.get("files")
        paper_style = None
        if isinstance(entries, dict) and prefix.is_relative_to(self.root):
            for key, value in entries.items():
                if key == "paperCss" and isinstance(value, str) and value in PAPER_STYLES:
                    paper_style = value
                if FILE_NAME.fullmatch(key) and isinstance(value, str) and FILE_NAME.fullmatch(value):
                    target = (prefix / value).resolve()
                    if target.is_relative_to(prefix):
                        files[key] = target
        return Item(ident, entry.get("kind"), entry.get("slot"), entry.get("name"), entry.get("prompt"),
                    entry.get("priceKrw"), entry.get("starter", False), files, entry.get("license"), paper_style)

    def url(self, item, key):
        return f"/chat/decor/{self.set}/{item.id}/{key}" if key in item.files else None

    def check(self, item):
        missing = []
        if item.kind not in KINDS:
            return ["kind"]
        if item.slot != SLOTS.get(item.kind):
            missing.append("slot")
        if type(item.price) is not int or item.price != 0:
            missing.append("price")
        if not isinstance(item.name, str) or not 1 <= len(item.name.strip()) <= 20:
            missing.append("name")
        if type(item.starter) is not bool or (item.starter and item.kind not in {"background", "paper", "font"}):
            missing.append("starter")
        license_row = self.licenses.get(item.license_id) if isinstance(item.license_id, str) else None
        if (not license_row or license_row.get("item_id") != item.id
                or not all(license_row.get(key) for key in ("file", "source", "author", "license", "terms", "checked_at"))):
            missing.append("license")
        elif item.kind == "font" and license_row["license"] != "OFL-1.1":
            missing.append("font_license")
        if item.kind in SLOTS:
            if not isinstance(item.prompt, str) or not 1 <= len(item.prompt) <= 200 or not item.prompt.isascii():
                missing.append("prompt")
            for template in (*TEMPLATE_IDS, "marong"):
                key = f"{template}.png"
                path = item.files.get(key)
                issue = self._layer_issue(path, template, item.slot) if path else "layer"
                if issue:
                    missing.append(f"{issue}:{template}")
        if item.kind == "sticker":
            required = ["sticker.webp"]
        else:
            required = ["thumb.webp"]
            if item.kind == "background":
                required.append("bg.webp")
            if item.kind == "paper" and not item.paper_style:
                required.append("paper.webp")
            if item.kind == "font":
                required.append("font.woff2")
        for key in required:
            path = item.files.get(key)
            if path is None or not self._asset(path, key):
                missing.append("file:" + key)
        return missing

    @staticmethod
    def _asset(path, key):
        try:
            if key.endswith(".woff2"):
                with path.open("rb") as file:
                    return file.read(4) == b"wOF2"
            with Image.open(path, formats=("WEBP",)) as image:
                if key == "sticker.webp":
                    if image.size != (512, 512):
                        return False
                    extrema = image.convert("RGBA").getchannel("A").getextrema()
                    return extrema[0] == 0 and extrema[1] > 0
                image.verify()
                return True
        except (OSError, ValueError, Image.DecompressionBombError):
            return False

    def _layer_issue(self, path, template, slot):
        try:
            slots = MARONG_SLOTS if template == "marong" else json.loads((self.templates / f"{template}.json").read_text(encoding="utf-8"))["slots"]
            left, top, right, bottom = slots[slot]
            box = (floor(left * 1024), floor(top * 1024), ceil(right * 1024), ceil(bottom * 1024))
            with Image.open(path, formats=("PNG",)) as image:
                if image.size != (1024, 1024) or (template == "marong" and image.mode != "RGBA"):
                    return "layer"
                ink = image.convert("RGBA").getchannel("A").point(lambda value: 255 if value else 0)
                total = ink.histogram()[255]
                inside = ink.crop(box).histogram()[255]
                if not 0 < total < 1024**2:
                    return "layer"
                return "layer_box" if (total - inside) * 100 > total * 5 else None
        except (OSError, ValueError, KeyError, TypeError, Image.DecompressionBombError):
            return "layer"
