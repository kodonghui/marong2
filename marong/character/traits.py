"""Validate a character trait sheet without database or account dependencies."""


COLORS = ("흰색", "검은색", "갈색", "크림", "회색", "황토", "주황", "은색")
MAX_COAT_COLORS = 3


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
            not isinstance(value, list) or not 1 <= len(value) <= MAX_COAT_COLORS
            or any(color not in COLORS for color in value) or len(set(value)) != len(value)
        ):
            return False
    return True


def valid_result(data):
    if not isinstance(data, dict) or data.keys() != EDITABLE | FLAGS | {"confidence", "bestPhoto", "petBox"}:
        return False
    return (all(type(data[key]) is bool for key in FLAGS) and data["confidence"] in CONFIDENCE
            and valid_edits({key: data[key] for key in EDITABLE}))


def output_schema():
    # The provider supports minItems but leaves maximum lengths and uniqueness to the server.
    # Describe those constraints in the schema so the model can satisfy the same checks.
    fields = {key: {"type": "string", "enum": list(values)} for key, values in CHOICES.items()}
    fields.update({
        key: {
            "type": "string",
            "description": f"공백과 문장 부호를 포함해 {limit}자 이하로 써. 잘 모르겠으면 빈 문자열을 줘.",
        }
        for key, limit in TEXT_LIMITS.items()
    })
    fields.update({key: {"type": "boolean"} for key in FLAGS})
    fields["coatColors"] = {
        "type": "array",
        "minItems": 1,
        "items": {"type": "string", "enum": list(COLORS)},
        "description": f"가장 두드러진 색부터 서로 다른 색을 1개에서 {MAX_COAT_COLORS}개까지 골라.",
    }
    fields["confidence"] = {"type": "string", "enum": list(CONFIDENCE)}
    fields["bestPhoto"] = {"type": "integer", "description": "아이가 가장 크고 또렷하게 나온 사진 번호, 1부터"}
    fields["petBox"] = {"type": "array", "items": {"type": "number"},
                        "description": "그 사진에서 아이를 감싸는 상자 [x, y, w, h], 사진 크기에 대한 0~1 비율"}
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
