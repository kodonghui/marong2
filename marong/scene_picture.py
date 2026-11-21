"""Draw a pet character's scene from its portrait and expression (AI-42)."""

from dataclasses import dataclass
from decimal import Decimal
import re

from .character.records import CharacterError
from .diary_models import DRAW_PROMPT, DiaryPicture, ModelResult, draw_prompt


VERSION = "scene-v1"
TOPIC_STYLE = (
    "Dark brown hand-drawn outline, warm chibi sticker style. Keep the subject within the middle 80% of the square. "
    "Fill the square edge to edge with one soft pastel background color."
)
COAT_EN = {"흰색": "white", "검은색": "black", "갈색": "brown", "크림": "cream",
           "회색": "gray", "황토": "tan", "주황": "orange", "은색": "silver"}
BUILD_EN = {"작음": "small", "중간": "medium", "큼": "large", "긴 몸": "long-bodied", "통통함": "round"}
BREED_EN = {"푸들": "poodle", "말티즈": "Maltese", "시바": "Shiba Inu", "치와와": "Chihuahua", "코숏": "shorthair"}
WEATHER_FACE = {"sunny": "smile", "rainbow": "smile", "cloudy": "sleepy", "rain": "sad", "snow": "surprised"}
LEGACY_SUBJECT = re.compile(r"the little white character|\bMarong\b|마롱이", re.IGNORECASE)


@dataclass(frozen=True)
class SceneResult:
    outcome: str
    reason: str | None
    picture: DiaryPicture | None
    cost: Decimal
    estimated: bool
    model: str
    prompt_version: str = VERSION
    measurement: ModelResult | None = None


def subject(character):
    traits = character.get("traits") or {}
    coat = next((COAT_EN[value] for value in traits.get("coatColors", []) if value in COAT_EN), "")
    breed = BREED_EN.get(traits.get("breedGuess"), character["kind"])
    return " ".join(word for word in ("a", BUILD_EN.get(traits.get("build"), "small"), coat, breed) if word)


def scene_prompt(purpose, character, outfit, scene, *, look=None, friend_name=None):
    scene = LEGACY_SUBJECT.sub("the pet character", scene)
    for label, replacement in ((character.get("name"), "the pet character"), (friend_name, "the friend")):
        if label:
            scene = re.sub(re.escape(label), replacement, scene, flags=re.IGNORECASE)
    style = "\n".join(DRAW_PROMPT.splitlines()[:2]) if purpose == "diary" else TOPIC_STYLE
    lines = [style, f"Main character: {subject(character)}. Keep the face, colors and markings exactly as in the reference pictures."]
    if outfit:
        lines.append("Wearing: " + ", ".join(outfit) + ".")
    lines.append("Scene: " + " ".join(scene.split()))
    if purpose == "diary" and look:
        look_line = draw_prompt(scene, look).splitlines()[-2]
        if look_line:
            lines.append(look_line)
    lines.append("No text, letters or numbers anywhere in the picture. Only one animal character.")
    return "\n".join(lines)


class ScenePictures:
    def __init__(self, store, media, models, model, *, catalog=None):
        self.store = store
        self.media = media
        self.models = models
        self.model = model
        self.catalog = catalog

    def outfit_prompts(self, ids):
        if not self.catalog:
            return []
        return [self.catalog.items[ident].prompt for ident in ids
                if ident in self.catalog.items and self.catalog.items[ident].prompt]

    async def diary_art(self, row, scene, look, weather, friend_name):
        character = await self.store._one("""
            SELECT c.id,c.kind,c.template,c.traits,c.name,o.body,o.neck,o.head FROM marong.characters c
            LEFT JOIN marong.outfits o ON o.character_id=c.id
            WHERE c.id=%s AND c.friend_id=%s AND c.status='ready'
        """, (row["character_id"], row["friend_id"]))
        if character is None:
            return ModelResult(outcome="error", error="references")
        outfit = self.outfit_prompts([character[slot] for slot in ("body", "neck", "head") if character[slot]])
        result = await self.draw("diary", character, outfit, scene, look=look, weather=weather, friend_name=friend_name)
        return result.measurement or ModelResult(outcome="error", error="references")

    async def draw(self, purpose, character, outfit, scene, *, look=None, weather=None, friend_name=None):
        if purpose not in {"topic", "reaction", "diary"}:
            raise ValueError("invalid_scene_purpose")
        expression = {"topic": "smile", "reaction": "excited", "diary": WEATHER_FACE.get(weather, "smile")}[purpose]
        try:
            async with self.store.pool.connection() as conn:
                refs = [("image[]", (f"{slot}.png", await self.media.read(conn, character["id"], slot), "image/png"))
                        for slot in ("front", expression)]
        except (CharacterError, OSError):
            return SceneResult("failed", "check_failed", None, Decimal(0), False, self.model)
        prompt = scene_prompt(purpose, character, outfit, scene, look=look, friend_name=friend_name)
        size = "1536x1024" if purpose == "diary" else "1024x1024"
        cost, estimated = Decimal(0), False
        for _ in range(1 if purpose == "diary" else 2):
            result = await self.models.edit_picture(prompt, refs, model=self.model,
                                                    size=size, output_format="webp", deadline=90, estimate_errors=True)
            cost += result.cost or Decimal(0)
            estimated |= result.estimated
            if result.outcome == "ok":
                return SceneResult("ok", None, result.value, cost, estimated, self.model, measurement=result)
            if result.outcome == "refused":
                return SceneResult("refused", "refused", None, cost, estimated, self.model, measurement=result)
            if result.outcome == "invalid":
                return SceneResult("failed", "check_failed", None, cost, estimated, self.model, measurement=result)
        reason = "timeout" if result.outcome == "timeout" else "model_error"
        return SceneResult("failed", reason, None, cost, estimated, self.model, measurement=result)
