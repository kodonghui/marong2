"""TC-347 with synthetic Korean scripts and isolated PostgreSQL."""

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import anthropic
from langsmith import tracing_context

from live import BUDGET_KRW, OUTPUT_LIMIT, LiveTrial, TrialError, reserve_krw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from pg import TestDB
from test_persona_schema import prepare

from marong.agent import Agent, Incoming
from marong.config import load_settings
from marong.friend_card import KST, FriendCards
from marong.friend_forget import forget_selected
from marong.friend_memory import MemoryExtraction, StructuredInference
from marong.graphs.memory import MemoryQueue, compile_graph
from marong.llm import text_of
from marong.store import Store

TRIALS = 3
ANSWER_LIMIT = 1024


def evaluate(case, rendered, dates):
    required = all(token.format_map(dates) in rendered for token in case["require"])
    rejected = any(token.format_map(dates) in rendered for token in case["reject"])
    return required and not rejected


async def play(db, store, settings, case, clock, *, trial=0, live=None):
    key = f"memory-eval:{trial}:" + case["id"]
    [(friend,)] = db.admin("INSERT INTO marong.friends(name) VALUES (%s) RETURNING id", (key,))
    db.admin("INSERT INTO marong.people(user_key,friend_id) VALUES (%s,%s)", (key, friend))
    rooms = {kind: f"{key}:{kind}" for kind in ("source", "direct", "group", "other")}
    for kind, room in rooms.items():
        db.admin("INSERT INTO marong.rooms(room_key,is_channel) VALUES (%s,%s)",
                 (room, kind in ("source", "direct")))
    now = clock.date()
    dates = {}
    for turn in case["turns"]:
        if "date_offset" in turn:
            offset = turn["date_offset"]
            dates["past" if offset < 0 else "soon"] = (now + timedelta(days=offset)).isoformat()
    scripted = {}

    async def fake_extract(payload, owner):
        assert owner == friend
        return {"ops": [scripted[statement["id"]] for statement in payload["messages"]]}

    # Advance past the text quiet period without making long trials depend on their start time.
    queue = MemoryQueue(store.pool, clock=lambda: datetime.now(KST) + timedelta(minutes=2))
    infer = fake_extract if live is None else StructuredInference(live, live.model, FriendCards(store))
    extraction = MemoryExtraction(store.pool, infer)
    graph = compile_graph(queue, extraction.prepare, extraction.persist, checkpointer=None)
    item_id = None
    operations_valid = True
    for turn in case["turns"]:
        action = turn.get("op", "add")
        if action == "forget":
            if item_id is None:
                operations_valid = False
                continue
            receipt = await forget_selected(store.pool, friend, "item", item_id, key + ":forget", via="screen")
            operations_valid &= receipt == {"forgot": 1, "messages": 1}
            continue
        room_kind = turn.get("room", "source")
        source = rooms[room_kind]
        quote = turn["say"].format_map(dates)
        ident = await store.add_message(source, "user", quote, key)
        op = {"op": action, "message_id": ident, "quote": quote}
        if action in ("supersede", "retract"):
            op["target_id"] = item_id
        if action != "retract":
            expiry = None
            if "date_offset" in turn:
                expiry = (now + timedelta(days=turn["date_offset"] + 7)).isoformat()
            private = room_kind == "source"
            op["item"] = {
                "kind": "event" if expiry else "fact",
                "text": turn["text"].format_map(dates),
                "sensitive": None,
                "scope": "friend" if private else f"room:{source}",
                "share": "self" if private else "known",
                "valid_until": expiry,
            }
        scripted[ident] = op
        state = await queue.claim("text")
        assert state and state["friend_id"] == friend and state["message_ids"] == [ident], case["id"]
        await graph.ainvoke(state)
        operations_valid &= db.admin("SELECT last_outcome FROM marong.memory_jobs WHERE friend_id=%s",
                                     (friend,)) == [("ok",)]
        if action != "retract":
            items = db.admin("SELECT id FROM marong.memory_items WHERE message_id=%s AND status='current'", (ident,))
            item_id = items[0][0] if len(items) == 1 else None
            operations_valid &= item_id is not None

    agent = Agent(settings, store, SimpleNamespace(ready=False), None)
    audience = case.get("audience", "direct")
    msg = Incoming(rooms[audience], key, case["ask"], is_channel=audience == "direct")
    # The question is the only new row, so the three modes see identical recent history.
    ident = await store.add_message(msg.room_key, "user", msg.text, key)
    db.admin("UPDATE marong.memory_jobs SET due_at=NULL WHERE friend_id=%s", (friend,))
    contexts = {}
    for mode in ("off", "shadow", "on"):
        agent.friend_memory_mode = mode
        system, messages, _ = await agent._context(msg, {"friend_id": friend}, ident, msg.text)
        contexts[mode] = json.dumps([system, messages], ensure_ascii=False)
    assert contexts["shadow"] == contexts["off"], case["id"]
    assert "# 고정 요약" not in contexts["shadow"], case["id"]
    context_pass = operations_valid and evaluate(case, contexts["on"], dates)
    if live is None:
        assert context_pass, case["id"]
        return context_pass, None
    # `on` is last. Use only the context made by the synthetic account.
    answer = await live.create_once(agent._body(system, messages, []), 45)
    answer_pass = answer.stop_reason == "end_turn" and evaluate(case, text_of(answer), dates)
    return context_pass, answer_pass


async def run(db, cases, folder, *, live=None):
    root = Path(folder)
    prompt = root / "prompt.md"
    prompt.write_text("한국어 기억 시험이야. 아는 것만 한 문장으로 답해. 날짜와 시각은 YYYY-MM-DD와 HH:MM으로 써.",
                      encoding="utf-8")
    with patch.dict(os.environ, {
        "MARONG_FRIEND_MEMORY": "shadow", "MARONG_FRIEND_CARD": "off", "MARONG_SAFETY": "off",
        "BOT_TOKEN": "fixture", "ANTHROPIC_API_KEY": "fixture", "ANTHROPIC_API_KEY_BACKUP": "",
        "ANTHROPIC_EFFORT": "", "LLM_MAX_TOKENS": str(ANSWER_LIMIT),
        "DATABASE_URL": db.app_url, "PROMPT_PATH": str(prompt), "KNOWLEDGE_DIR": str(root / "empty"),
    }, clear=True):
        settings = load_settings()
        store = Store(db.app_url, call_bridge=False)
    if live is not None:
        assert settings.anthropic_model == live.model

    await store.open(wait=True)
    passed = Counter()
    trial_counts = []
    cases_passing = Counter()
    try:
        clock = datetime.now(KST)
        with patch.dict(os.environ, {"MARONG_FRIEND_CARD": "off", "MARONG_SAFETY": "off"}), tracing_context(enabled=False):
            for trial in range(TRIALS if live else 1):
                contexts = answers = joint = 0
                for case in cases:
                    context_pass, answer_pass = await play(db, store, settings, case, clock, trial=trial, live=live)
                    contexts += context_pass
                    answers += bool(answer_pass)
                    if context_pass:
                        passed[case["kind"]] += 1
                    if context_pass and answer_pass:
                        joint += 1
                        cases_passing[case["id"]] += 1
                trial_counts.append({"context_pass": contexts, "answer_pass": answers, "joint_pass": joint})
    finally:
        await store.close()

    if live is None:
        print(json.dumps({"synthetic_context_pass": sum(passed.values()), "by_kind": passed,
                          "shadow_equals_off": len(cases), "provider_calls": 0}))
    else:
        attempts = len(cases) * TRIALS
        repeated_passes = sum(result == TRIALS for result in cases_passing.values())
        print(json.dumps({"cases_per_trial": len(cases), "trials": trial_counts,
                          "shadow_equals_off": attempts,
                          "passed_all_three": repeated_passes,
                          "answer_accuracy_pct": round(100 * sum(row["answer_pass"] for row in trial_counts) / attempts, 1),
                          "joint_accuracy_pct": round(100 * sum(cases_passing.values()) / attempts, 1),
                          "all_three_pct": round(100 * repeated_passes / len(cases), 1),
                          **live.totals()}))


async def verify(cases, key):
    database = TestDB()
    try:
        prepare(database)
        with TemporaryDirectory(prefix="marong-memory-eval-") as folder:
            if key is None:
                await run(database, cases, folder)
                return
            with patch.dict(os.environ, {}, clear=True):
                default_model = load_settings().anthropic_model
            async with anthropic.AsyncAnthropic(api_key=key, base_url="https://api.anthropic.com", max_retries=0) as client:
                live = LiveTrial(client, default_model)
                try:
                    await run(database, cases, folder, live=live)
                except TrialError as error:
                    print(json.dumps({"incomplete": str(error), **live.totals()}), file=sys.stderr)
                    raise SystemExit(2) from None
    finally:
        database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--real", action="store_true", help="use the dedicated evaluation key")
    mode.add_argument("--estimate", action="store_true", help="print the cost reservation without API calls")
    args = parser.parse_args()
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["kind"] for case in cases} == {"fact", "correction", "withdrawal", "time", "scope"}
    extractions = TRIALS * sum(turn.get("op") != "forget" for case in cases for turn in case["turns"])
    answers = TRIALS * len(cases)
    reserve = extractions * reserve_krw(OUTPUT_LIMIT) + answers * reserve_krw(ANSWER_LIMIT)
    if args.estimate:
        print(json.dumps({"extractions": extractions, "answers": answers, "cost_reservation_krw": reserve,
                          "budget_krw": BUDGET_KRW, "provider_calls": 0}))
        raise SystemExit(0)
    key = os.getenv("MARONG_MEMORY_EVAL_ANTHROPIC_KEY", "").strip() if args.real else None
    if args.real and not key:
        parser.error("MARONG_MEMORY_EVAL_ANTHROPIC_KEY is absent")
    if args.real and reserve > BUDGET_KRW:
        parser.error("trial cost reservation exceeds the approved budget")
    asyncio.run(verify(cases, key))
