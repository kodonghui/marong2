"""The public half of a blind listening test. Candidate labels live in a separate file."""

from hashlib import sha256
import json
from pathlib import Path
import re

TEST_ID = re.compile(r"[a-z0-9-]{3,40}\Z")
CLIP_ID = re.compile(r"[a-z0-9]{8,32}\Z")
MAX_CLIP_BYTES = 2_097_152
DEFAULT_DIR = "/var/lib/marong/listen"


def load_test(root: Path) -> dict | None:
    try:
        with (root / "current.json").open("rb") as file:
            raw = file.read(65_537)
    except FileNotFoundError:
        return None
    try:
        if len(raw) > 65_536:
            raise ValueError
        test = json.loads(raw)
        if set(test) != {"testId", "sentences"} or not TEST_ID.fullmatch(test["testId"]):
            raise ValueError
        if not isinstance(test["sentences"], list) or len(test["sentences"]) != 10:
            raise ValueError
        used = set()
        for no, sentence in enumerate(test["sentences"], 1):
            if (set(sentence) != {"no", "text", "clips"} or type(sentence["no"]) is not int
                    or sentence["no"] != no or not isinstance(sentence["text"], str)
                    or not 1 <= len(sentence["text"]) <= 200):
                raise ValueError
            clips = sentence["clips"]
            if not isinstance(clips, list) or not 1 <= len(clips) <= 8:
                raise ValueError
            for clip in clips:
                if not CLIP_ID.fullmatch(clip) or clip in used:
                    raise ValueError
                used.add(clip)
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError("invalid listening test manifest") from None
    return test


def public_sentence(test_id, friend, sentence, answers):
    def position(clip):
        return sha256(f"{test_id}:{friend}:{sentence['no']}:{clip}".encode("ascii")).digest()

    clips = []
    for clip in sorted(sentence["clips"], key=position):
        answer = answers.get(clip)
        clips.append({"id": clip, "score": answer["score"] if answer else None,
                      "marongLike": answer["marong_like"] if answer else False})
    return {"no": sentence["no"], "text": sentence["text"], "clips": clips}
