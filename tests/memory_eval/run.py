"""TC-347 with synthetic Korean scripts, a fake extractor, and isolated PostgreSQL."""

import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from pg import ROOT, TestDB
from test_persona_schema import prepare

from marong.agent import Agent, Incoming
from marong.config import load_settings
from marong.friend_card import KST
from marong.friend_forget import forget_selected
from marong.friend_memory import MemoryExtraction
from marong.graphs.memory import MemoryQueue, compile_graph
from marong.store import Store


def evaluate(case, rendered, dates):
    required = all(token.format_map(dates) in rendered for token in case["require"])
    rejected = any(token.format_map(dates) in rendered for token in case["reject"])
    return required and not rejected


async def play(db, store, settings, case, clock):
    key = "memory-eval:" + case["id"]
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

    queue = MemoryQueue(store.pool, clock=lambda: clock)
    extraction = MemoryExtraction(store.pool, fake_extract)
    graph = compile_graph(queue, extraction.prepare, extraction.persist, checkpointer=None)
    item_id = None
    for turn in case["turns"]:
        action = turn.get("op", "add")
        if action == "forget":
            receipt = await forget_selected(store.pool, friend, "item", item_id, key + ":forget", via="screen")
            assert receipt == {"forgot": 1, "messages": 1}
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
        assert state["friend_id"] == friend and state["message_ids"] == [ident]
        await graph.ainvoke(state)
        assert db.admin("SELECT last_outcome FROM marong.memory_jobs WHERE friend_id=%s", (friend,)) == [("ok",)]
        if action != "retract":
            [(item_id,)] = db.admin("SELECT id FROM marong.memory_items WHERE message_id=%s", (ident,))

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
    assert evaluate(case, contexts["on"], dates), case["id"]
    return case["kind"]


async def run(db, cases):
    with patch.dict("os.environ", {
        "MARONG_FRIEND_MEMORY": "shadow",
        "BOT_TOKEN": "fixture",
        "ANTHROPIC_API_KEY": "fixture",
        "DATABASE_URL": db.app_url,
        "PROMPT_PATH": str(ROOT / "prompt.md"),
    }):
        settings = load_settings()
        store = Store(db.app_url, call_bridge=False)
    await store.open(wait=True)
    try:
        clock = datetime.now(KST) + timedelta(minutes=2)
        counts = Counter([await play(db, store, settings, case, clock) for case in cases])
    finally:
        await store.close()
    assert set(counts) == {"fact", "correction", "withdrawal", "time", "scope"}
    print(json.dumps({"synthetic_context_pass": sum(counts.values()), "by_kind": counts,
                      "shadow_equals_off": len(cases), "provider_calls": 0}))


if __name__ == "__main__":
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    assert len({case["id"] for case in cases}) == len(cases)
    database = TestDB()
    try:
        prepare(database)
        asyncio.run(run(database, cases))
    finally:
        database.close()
