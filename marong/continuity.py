"""Select and report recent conversation context (SPEC-480, SPEC-487)."""

import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import json
from typing import Literal

from marong.relative_time import relative_time


Mode = Literal["off", "shadow", "on"]
Segment = Literal["start", "reconnect", "wake", "takeover", "renew", "handoff", "text"]
Result = Literal["ok", "empty", "timeout", "error", "fallback"]
Origin = Literal["text", "call"]
GAP = timedelta(minutes=30)
LOOKBACK = timedelta(days=7)
SIGNAL_TEXTS = (
    "통화를 막 시작했어. 한국어로 짧고 편안하게 인사해 줘.",
    "(전화 연결됨)",
    "(이번 달 통화를 더 할 수 없어서 곧 끊어야 해. 금액은 말하지 말고, 다음에 또 얘기하자고 한 문장으로 인사해.)",
)


def _startup_mode() -> Mode:
    mode = os.getenv("MARONG_CONTINUITY")
    if mode == "shadow" or mode == "on":
        return mode
    return "off"


MODE = _startup_mode()


@dataclass(frozen=True)
class Turn:
    source_id: int
    origin: Origin
    at: datetime
    role: str
    text: str
    question: bool | None = None


@dataclass(frozen=True)
class Span:
    start: datetime
    end: datetime
    origin: Origin
    call_id: str | None = None


def unanswered(turn: Turn) -> bool:
    question = turn.question if turn.question is not None else turn.text.rstrip().endswith("?")
    return turn.origin == "text" and turn.role == "assistant" and question


def shortened(text: str, cap: int) -> str:
    return text if len(text) <= cap else text[:cap - 1] + "…"


def recent_turns(turns: list[Turn], now: datetime, *, max_turns: int = 20, max_chars: int = 2000) -> list[Turn]:
    ordered = sorted(turns, key=lambda turn: (turn.at, turn.origin, turn.source_id), reverse=True)
    recent = []
    last = now
    for turn in ordered:
        if not turn.text.strip() or turn.text in SIGNAL_TEXTS or turn.text.startswith("[알림]"):
            continue
        if last - turn.at > GAP:
            break
        text = shortened(turn.text, 300)
        if len(recent) == max_turns or len(text) > max_chars:
            break
        recent.append(replace(turn, text=text))
        last = turn.at
        max_chars -= len(text)
    return recent[::-1]


def older_conversations(spans: list[Span], now: datetime) -> list[list[Span]]:
    groups = []
    end = None
    for span in sorted(spans, key=lambda candidate: (candidate.start, candidate.end)):
        if end is None or span.start - end > GAP:
            groups.append([])
            end = span.end
        groups[-1].append(span)
        end = max(end, span.end)
    return [
        group for group in reversed(groups)
        if GAP < now - max(span.end for span in group) <= LOOKBACK
    ][:3]


def display_turns(turns: list[Turn], name: str, *, limit: int = 100, mark_question: bool = False) -> list[dict]:
    rows = [
        {"who": "마롱이" if turn.role == "assistant" else name, "text": shortened(turn.text, limit)}
        for turn in turns
    ]
    if rows and mark_question and unanswered(turns[-1]):
        rows[-1]["unanswered"] = True
    return rows


def length_label(start: datetime, end: datetime) -> str:
    return f"{max(0, (end - start) // timedelta(minutes=1))}분"


def fit_conversations(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        if len(json.dumps([*result, row], ensure_ascii=False)) > 1500:
            break
        result.append(row)
    return result


def record_pick(
    segment: Segment, *, turns: int, chars: int, conversations: int, ms: int, result: Result,
) -> dict:
    diagnostic = {"mode": MODE, "segment": segment, "turns": turns, "chars": chars,
                  "conversations": conversations, "ms": ms, "result": result}
    fields = " ".join(f"{key}={value}" for key, value in diagnostic.items())
    print(f"continuity_pick {fields}", flush=True)
    return diagnostic
