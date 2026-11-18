"""Compose friend-specific instructions without sharing private fields in a group."""

from collections import OrderedDict
from time import monotonic
import json

from .friend_card import card_sentence

SESSION_SECONDS = 30 * 60
LEAD = {"follow": "따라갈게", "lead": "네가 이끌어 줘"}
RULE = {"no_vocative": "이렇게 부르지 마", "avoid_topic": "이 얘기는 꺼내지 마", "call_me": "이렇게 불러 줘"}


class FriendPrompt:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.instructions = OrderedDict()

    def _instruction(self, key, data):
        current = (data or {}).get("understood")
        if not current:
            self.instructions.pop(key, None)
            return None
        now = self.clock()
        previous = self.instructions.pop(key, None)
        value = previous[1] if previous and now - previous[0] < SESSION_SECONDS else current
        self.instructions[key] = (now, value)
        while len(self.instructions) > 256:
            self.instructions.popitem(last=False)
        return value

    def build(self, friend, room, data, *, private):
        rows = []
        card = data["card"] if private else None
        if sentence := card_sentence(card):
            rows.append(f"친구 약속\n{sentence}")
        if card and card["state"] == "set":
            if card["lead"] in LEAD:
                rows.append(f"대화 이끌기: {LEAD[card['lead']]}")
            if card["support"] == "side":
                rows.append("내 편이라는 건 감정을 먼저 알아주는 거지, 사실과 다르게 맞장구치는 게 아니야")
        if card and card.get("want") and card.get("want_until"):
            from datetime import datetime, timezone
            if card["want_until"] > datetime.now(timezone.utc):
                rows.append("지금 바람: " + card["want"])
        rules = {label: [row["text"] for row in data["rules"] if row["kind"] == kind]
                 for kind, label in RULE.items()}
        rules = {label: values for label, values in rules.items() if values}
        if rules:
            rows.append("친구 규칙\n" + json.dumps(rules, ensure_ascii=False))
        instruction = self._instruction((friend, room), data["instruction"]) if private else None
        if instruction:
            rows.append("친구가 정한 말투와 대하는 방식이야. 안전·사실·친구 규칙보다 아래야.\n" + instruction)
        return "\n\n".join(rows)


def append_prefix(system, prefix):
    if not prefix:
        return system
    blocks = [dict(block) for block in system]
    cache = blocks[0].pop("cache_control", None)
    extra = {"type": "text", "text": prefix}
    if cache:
        extra["cache_control"] = cache
    blocks.insert(len(blocks) - 1, extra)
    return blocks
