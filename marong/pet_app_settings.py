"""Feature flags and settings shared by the pet app workers and HTTP handlers."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
import json

from .diary import image_budget


def pet_voice_enabled(env: Mapping[str, str]) -> bool:
    return env.get("MARONG_PET_VOICE") == "1"


@dataclass(frozen=True)
class PetAppSettings:
    pet_voice: bool = False
    voice_recommend: dict[str, dict[str, str]] = field(default_factory=dict)
    scene_pictures: bool = False
    scene_model: str = "gpt-image-2.5-flare"
    diary_image_budget: Decimal | None = Decimal(5)
    decor: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "PetAppSettings":
        try:
            choices = json.loads(env.get("MARONG_VOICE_RECOMMEND") or "{}")
        except ValueError:
            choices = {}
        rules = {}
        if isinstance(choices, dict):
            for kind in ("dog", "cat"):
                mapping = choices.get(kind)
                if isinstance(mapping, dict):
                    rules[kind] = {name: voice for name, voice in mapping.items() if isinstance(voice, str)}
        return cls(
            pet_voice=pet_voice_enabled(env),
            voice_recommend=rules,
            scene_pictures=env.get("MARONG_SCENE_PICTURES") == "1",
            scene_model=env.get("MARONG_SCENE_MODEL", "").strip() or cls.scene_model,
            diary_image_budget=image_budget(env.get("MARONG_DIARY_IMAGE_BUDGET_USD")),
            decor=env.get("MARONG_DECOR") == "1",
        )
