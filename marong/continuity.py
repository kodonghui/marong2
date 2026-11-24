"""Select and report recent conversation context (SPEC-480, SPEC-487)."""

import os
from typing import Literal


Mode = Literal["off", "shadow", "on"]
Segment = Literal["start", "reconnect", "wake", "takeover", "renew", "handoff", "text"]
Result = Literal["ok", "empty", "timeout", "error", "fallback"]


def _startup_mode() -> Mode:
    mode = os.getenv("MARONG_CONTINUITY")
    if mode == "shadow" or mode == "on":
        return mode
    return "off"


MODE = _startup_mode()


def record_pick(
    segment: Segment, *, turns: int, chars: int, conversations: int, ms: int, result: Result,
) -> dict:
    diagnostic = {"mode": MODE, "segment": segment, "turns": turns, "chars": chars,
                  "conversations": conversations, "ms": ms, "result": result}
    fields = " ".join(f"{key}={value}" for key, value in diagnostic.items())
    print(f"continuity_pick {fields}", flush=True)
    return diagnostic
