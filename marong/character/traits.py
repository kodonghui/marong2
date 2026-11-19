"""Validate a character trait sheet without database or account dependencies."""


COLORS = ("흰색", "검은색", "갈색", "크림", "회색", "황토", "주황", "은색")


CHOICES = {
    "species": ("dog", "cat", "other"),
    "pattern": ("단색", "얼룩", "줄무늬", "턱시도", "포인트", "삼색", "브린들"),
    "earShape": ("선 귀", "접힌 귀", "늘어진 귀", "반쯤 선 귀"),
    "eyeColor": ("갈색", "검은색", "파란색", "초록색", "노란색", "짝눈"),
    "build": ("작음", "중간", "큼", "긴 몸", "통통함"),
    "furLength": ("짧음", "중간", "긺", "곱슬"),
}


TEXT_LIMITS = {"breedGuess": 30, "patternNotes": 60, "distinctive": 60}


EDITABLE = CHOICES.keys() | TEXT_LIMITS.keys() | {"coatColors"}


FLAGS = {"petVisible", "multiplePets"}


CONFIDENCE = ("low", "medium", "high")


def valid_edits(data):
    if not isinstance(data, dict) or not data.keys() <= EDITABLE:
        return False
    for key, value in data.items():
        if key in CHOICES and value not in CHOICES[key]:
            return False
        if key in TEXT_LIMITS and (not isinstance(value, str) or len(value) > TEXT_LIMITS[key]
                                   or "\x00" in value):
            return False
        if key == "coatColors" and (
            not isinstance(value, list) or not 1 <= len(value) <= 3
            or any(color not in COLORS for color in value) or len(set(value)) != len(value)
        ):
            return False
    return True


def valid_result(data):
    if not isinstance(data, dict) or data.keys() != EDITABLE | FLAGS | {"confidence"}:
        return False
    return (all(type(data[key]) is bool for key in FLAGS) and data["confidence"] in CONFIDENCE
            and valid_edits({key: data[key] for key in EDITABLE}))


def output_schema():
    # The server enforces string lengths, array lengths and uniqueness after parsing.
    fields = {key: {"type": "string", "enum": list(values)} for key, values in CHOICES.items()}
    fields.update({key: {"type": "string"} for key in TEXT_LIMITS})
    fields.update({key: {"type": "boolean"} for key in FLAGS})
    fields["coatColors"] = {"type": "array", "items": {"type": "string", "enum": list(COLORS)}}
    fields["confidence"] = {"type": "string", "enum": list(CONFIDENCE)}
    return {"type": "object", "properties": fields, "required": sorted(fields), "additionalProperties": False}


def template_for(traits):
    large = traits["build"] in {"큼", "통통함"}
    if traits["species"] == "cat":
        return "cat_round" if large else "cat"
    if traits["species"] != "dog":
        raise ValueError("invalid_species")
    if traits["build"] == "긴 몸":
        return "dog_long"
    return "dog_large" if large else "dog_small"
