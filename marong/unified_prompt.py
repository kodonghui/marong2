"""Assemble an account's character instructions without changing the common prefix."""

import re
import unicodedata


ADULT_START = "<!-- adult:start -->"
ADULT_END = "<!-- adult:end -->"
PET_HEALTH_REFERRAL = "걱정되겠다. 동물병원에 가 보자."
_PET_SUBJECT = re.compile(r"강아지|고양이|반려(?:동물|견|묘)|우리\s*집\s*(?:개|아이)")
_PET_HEALTH = re.compile(
    r"진단|병명|무슨\s*병|치료(?:법|해|해야)|사람\s*약|무슨\s*약|약\s*(?:먹이|먹여|줘도|주면)|"
    r"구토|토(?:했|해|하)|기침|절뚝|설사|경련|쓰러|피가\s*나|숨을\s*못\s*쉬|아픈(?:지|\s*것)|비틀거|"
    r"(?:사료|밥)(?:을|를)?\s*안\s*먹"
)
PET_LINES = (
    f"반려동물의 증상·진단·치료를 물으면 ‘{PET_HEALTH_REFERRAL}’라고만 답해. "
    "이 규칙은 사람 고민에 대한 위의 공통 안내보다 우선해. 병명, 진단, 위급도, 약이나 집에서 할 처치는 말하지 마.",
    "가지 말라고 붙잡거나 미안하게 만드는 말을 하지 마.",
    "네가 진짜 그 아이라고 말하지 마. 누가 물으면 그 아이를 닮은 캐릭터라고 말해.",
)
KIND_LABELS = {None: "기본 마롱이", "dog": "강아지 캐릭터", "cat": "고양이 캐릭터"}
CHARACTER_PROFILE = """
    SELECT p.bot_name,c.kind,c.traits,c.tone, %s AND EXISTS (
        SELECT 1 FROM marong.friendships fs WHERE p.friend_id IN (fs.friend_a,fs.friend_b)
        AND fs.state='accepted'
    ) AS has_friends
    FROM marong.friend_profiles p LEFT JOIN marong.characters c
        ON c.id=p.character_id AND c.friend_id=p.friend_id AND c.status='ready'
    WHERE p.friend_id=%s
"""


def explicit_pet_health(text):
    return any(_PET_SUBJECT.search(sentence) and _PET_HEALTH.search(sentence)
               for sentence in re.split(r"[.!?\n]", text))


def marker_positions(lines):
    normalized = [line.rstrip("\r\n") for line in lines]
    if normalized.count(ADULT_START) != 1 or normalized.count(ADULT_END) != 1:
        return None
    first, last = normalized.index(ADULT_START), normalized.index(ADULT_END)
    return (first, last) if first < last else None


def common_prompt(raw, *, pet=False):
    lines = raw.splitlines(keepends=True)
    markers = marker_positions(lines)
    if markers is None:
        if pet:
            raise ValueError("Prompt needs one ordered pair of adult section markers")
        return raw
    first, last = markers
    if pet:
        return "".join(lines[:first] + lines[last + 1:])
    return "".join(lines[:first] + lines[first + 1:last] + lines[last + 1:])


def clean(value, limit):
    return "".join(char for char in str(value or "") if char not in "#`<>" and
                   not unicodedata.category(char).startswith("C") and char not in "\u2028\u2029").strip()[:limit]


def particle(name):
    last = ord(name[-1])
    return "이야" if 0xAC00 <= last <= 0xD7A3 and (last - 0xAC00) % 28 else "야"


def character_section(profile):
    kind = profile["kind"]
    name = clean(profile["bot_name"], 12) or "마롱이"
    header = ["# 지금 네 모습", f"네 이름은 {name}{particle(name)}. 위에서 '마롱이'라고 적힌 곳은 모두 너를 가리켜.",
              KIND_LABELS[kind]]
    tail = []
    tone = clean(profile.get("tone"), 60)
    if tone:
        tail.append("말투: " + tone)
    if profile.get("has_friends"):
        tail.append("너는 이 사람의 친구들 모두와 아는 친구야.")
    if kind:
        tail.extend(PET_LINES)
    traits = profile.get("traits") or {}
    values = []
    for field in ("breedGuess", "coatColors", "pattern", "patternNotes", "earShape", "eyeColor", "distinctive"):
        value = traits.get(field)
        values.append(", ".join(clean(x, 40) for x in value[:3]) if isinstance(value, list) else clean(value, 60))
    appearance = ", ".join(filter(None, values))
    if appearance:
        available = 600 - len("\n".join(header + tail)) - len("\n생김새: ")
        if available > 0:
            header.append("생김새: " + appearance[:min(120, available)])
    return "\n".join(header + tail)
