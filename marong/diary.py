"""Private illustrated diary rules."""

import re

_FIRST_WORDS = frozenset(
    "The A An In On At Under Inside Outside Near Next With Together After While".split()
)
_PERSON_WORDS = frozenset(
    "person people friend friends girl boy woman man child kid human lady guy mom dad mother father "
    "family someone everyone boyfriend girlfriend baby teacher student".split()
)
_KOREAN = re.compile(r"[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff\uffa0-\uffdc]")
_CONTACT = re.compile(r"@|http|www\.", re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_]+")
_FRIEND = re.compile(r"\b[Tt]he +friend\b")


def scene_error(scene: str, *, has_look: bool = False) -> str | None:
    """Return a SPEC-154 reason code without returning any scene text."""
    if len(scene) > 400:
        return "too_long"
    if _KOREAN.search(scene):
        return "korean"
    if _CONTACT.search(scene):
        return "contact"
    if any(character.isnumeric() for character in scene):
        return "digits"

    sentences = re.split(r"[.!?]", scene)
    if not 2 <= len(sentences) <= 4 or sentences[-1].strip():
        return "first_word"
    for sentence in sentences[:-1]:
        words = _WORD.findall(sentence)
        if not words or words[0] not in _FIRST_WORDS or not all(word.isascii() for word in words):
            return "first_word"
        if any(word[0].isupper() for word in words[1:]):
            return "capital"
        person_text = _FRIEND.sub("", sentence) if has_look else sentence
        if _PERSON_WORDS.intersection(word.lower() for word in _WORD.findall(person_text)):
            return "person"
    return None
