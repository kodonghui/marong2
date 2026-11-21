"""Assemble an account's character instructions without changing the common prefix."""

import unicodedata


ADULT_START = "<!-- adult:start -->"
ADULT_END = "<!-- adult:end -->"
PET_LINES = (
    "아이가 아픈지, 병이 있는지 판단하지 마. 걱정된다는 말에는 병원에 가 보자고만 해.",
    "가지 말라고 붙잡거나 미안하게 만드는 말을 하지 마.",
    "네가 진짜 그 아이라고 말하지 마. 누가 물으면 그 아이를 닮은 캐릭터라고 말해.",
)
KIND_LABELS = {None: "기본 마롱이", "dog": "강아지 캐릭터", "cat": "고양이 캐릭터"}
CHARACTER_PROFILE = """
    SELECT p.bot_name,c.kind,c.traits,c.tone{intro_columns}, %s AND EXISTS (
        SELECT 1 FROM marong.friendships fs WHERE p.friend_id IN (fs.friend_a,fs.friend_b)
        AND fs.state='accepted'
    ) AS has_friends
    FROM marong.friend_profiles p LEFT JOIN marong.characters c
        ON c.id=p.character_id AND c.friend_id=p.friend_id AND c.status='ready'
    WHERE p.friend_id=%s
"""
PET_INTRO_COLUMNS = ",c.personality,c.likes,c.dislikes,c.owner_call"


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


def suffix(name, with_coda, without_coda):
    last = ord(name[-1]) if name else 0
    return with_coda if 0xAC00 <= last <= 0xD7A3 and (last - 0xAC00) % 28 else without_coda


def particle(name):
    return suffix(name, "이야", "야")


def intro_line(profile, limit):
    traits = ", ".join(clean(value, 10) for value in (profile.get("personality") or [])[:3])
    values = (("성격", traits), ("좋아하는 것", clean(profile.get("likes"), limit)),
              ("싫어하는 것", clean(profile.get("dislikes"), limit)))
    return " ".join(f"{label}: {value}." for label, value in values if value)


def character_section(profile, *, pet_voice=False):
    kind = profile["kind"]
    name = clean(profile["bot_name"], 12) or "마롱이"
    header = ["# 지금 네 모습", f"네 이름은 {name}{particle(name)}. 위에서 '마롱이'라고 적힌 곳은 모두 너를 가리켜.",
              KIND_LABELS[kind]]
    speaking_pet = pet_voice and kind in {"dog", "cat"}
    if speaking_pet:
        owner = clean(profile.get("owner_call"), 10)
        companion = owner or "이 사람"
        animal = "강아지" if kind == "dog" else "고양이"
        header[2] = (f"너는 마롱이가 아니라 {name}이고, {companion}{suffix(companion, '이랑', '랑')} 함께 사는 "
                     f"{animal}야. {name}의 1인칭 반말로 ")
        if owner:
            header[2] += (f"말하고, {owner}{suffix(owner, '을', '를')} "
                          f"'{owner}'{suffix(owner, '이라고', '라고')} 불러.")
        else:
            header[2] += "말해."
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
    if speaking_pet:
        skills = f"검색·일정·쇼핑·공부·고민 이야기는 지금처럼 다 도와줘. {name}답게 말할 뿐 아는 것과 할 수 있는 것은 같아."
        details = intro_line(profile, 60)
        expanded = ([details] if details else []) + [skills, *tail]
        if len("\n".join(header + expanded)) > 600:
            details = intro_line(profile, 40)
            expanded = ([details] if details else []) + [skills, *tail]
        tail = expanded
    if appearance:
        available = 600 - len("\n".join(header + tail)) - len("\n생김새: ")
        if available > 0:
            header.append("생김새: " + appearance[:min(120, available)])
    return "\n".join(header + tail)
