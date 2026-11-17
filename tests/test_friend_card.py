"""Scoped storage and tool auditing for TC-257, TC-278, and TC-279."""

import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/vertex_live"))
from call_memory import MemoryStore, Principal
from call_safety import CallSafety

from marong.agent import Agent, Incoming
from marong.discord_dm import DiscordAgent, DiscordIncoming
from marong.topics import Today, Topics
from marong.friend_card import CardError, FriendCards, KST, ModelRun, card_sentence, question_choices, text_choice
from marong.persona_prompt import FriendPrompt, append_prefix
from marong.store import Store
from pg import TestDB
from test_persona_schema import prepare

TEXT = "시험문장: 야라고 부르지 말고 북극 얘기는 하지 마"


async def scenario(db, store):
    db.admin("""
        INSERT INTO marong.friends(name) VALUES ('fixture-one'),('fixture-two');
        INSERT INTO marong.rooms(room_key,is_channel) VALUES ('fixture-room-a',true),('fixture-room-b',true);
        INSERT INTO marong.people(user_key,friend_id) VALUES ('fixture-person-a',1),('fixture-person-b',2);
    """, None)
    mid = await store.add_message("fixture-room-a", "user", TEXT, user_key="fixture-person-a")
    mid2 = await store.add_message("fixture-room-b", "user", TEXT, user_key="fixture-person-b")
    cards = FriendCards(store)

    await asyncio.gather(cards.set(1, {"support": "listen"}, source="questions"),
                         cards.set(1, {"advice": "asked", "honesty": "gentle"}, source="screen"))
    result = await cards.read(1)
    assert card_sentence(result["card"]) == (
        "힘들다고 하면 일단 들을게. 조언은 네가 물어볼 때만 하고, 아닌 것 같을 땐 부드럽게 말할게."
    )
    await cards.set(1, {"support": "solve"}, source="talk")
    assert (await cards.read(1))["card"]["support"] == "solve"
    assert (await cards.read(2))["card"] is None

    args = {"op": "rule_add", "kind": "no_vocative", "text": "야", "quote": "야라고 부르지 말고"}
    first, replay = await asyncio.gather(
        cards.apply_tool(1, "fixture-room-a", mid, "fixture-request", args),
        cards.apply_tool(1, "fixture-room-a", mid, "fixture-request", args),
    )
    assert first == replay and first.outcome == "ok"
    assert db.admin("SELECT count(*) FROM marong.persona_tool_calls") == [(1,)]
    assert (await cards.apply_tool(2, "fixture-room-b", mid2, "other", {**args, "friend_id": 1})).why == "other_friend"
    assert (await cards.apply_tool(1, "fixture-room-b", mid2, "speaker", args)).why == "not_speaker"
    assert (await cards.apply_tool(1, "fixture-room-a", mid, "bad-quote", {**args, "quote": "생성된 비밀"})).why == "quote_missing"
    assert (await cards.apply_tool(1, "fixture-room-a", mid, "bad-op", {**args, "op": "unknown"})).outcome == "invalid"
    photo = await store.add_message("fixture-room-a", "user", TEXT, user_key="fixture-person-a", meta={"image": {}})
    assert (await cards.apply_tool(1, "fixture-room-a", photo, "photo-caption", args)).why == "not_speaker"
    assert await cards.remove_rule(2, first.target_id) is False
    assert not (await cards.read(2))["rules"]
    same, added = await cards.add_rule(1, "no_vocative", " 야 ")
    assert same == first and not added
    invalid, added = await cards.add_rule(1, "avoid_topic", "눈")
    assert invalid.why == "too_long" and not added
    for index in range(20):
        _, added = await cards.add_rule(1, "avoid_topic", f"시험주제 {index}")
        assert added
    restricted, added = await cards.add_rule(1, "avoid_topic", "시험주제 21")
    assert not added and restricted.why == "limit"
    await cards.add_rule(1, "call_me", "하나")
    await cards.add_rule(1, "call_me", "바다")
    active = [item["text"] for item in (await cards.read(1))["rules"] if item["kind"] == "call_me"]
    assert active == ["바다"]

    original = "시험용 지침 원문"
    rewrite = "시험용 반말 지침"
    assert await cards.write_instruction(1, original, rewrite, via="screen") == 1
    assert await cards.write_instruction(1, original, rewrite, via="screen") == 1
    assert (await cards.read(1, private=False))["instruction"] is None
    assert (await cards.read(1, private=False))["card"] is None
    assert (await cards.read(1, private=False))["rules"]
    system = [{"type": "text", "text": "고정 지침", "cache_control": {"type": "ephemeral"}},
              {"type": "text", "text": "지금 상황"}]
    now_value = [0.]
    prompt = FriendPrompt(clock=lambda: now_value[0])
    private = await cards.read(1)
    blocks = append_prefix(system, prompt.build(1, "fixture-room-a", private, private=True))
    assert len(blocks) == 3 and blocks[0]["text"] == "고정 지침" and blocks[2]["text"] == "지금 상황"
    assert "cache_control" not in blocks[0] and blocks[1]["cache_control"] == system[0]["cache_control"]
    assert rewrite in blocks[1]["text"] and original not in blocks[1]["text"]
    assert blocks[1]["text"].index("친구 약속") < blocks[1]["text"].index("친구 규칙") < blocks[1]["text"].index(rewrite)
    group = prompt.build(1, "fixture-group", private, private=False)
    assert "친구 규칙" in group and "친구 약속" not in group and rewrite not in group
    changed = {**private, "instruction": {**private["instruction"], "understood": "시험 변경"}}
    now_value[0] = 60.
    assert "시험 변경" not in prompt.build(1, "fixture-room-a", changed, private=True)
    now_value[0] += 1800.
    assert "시험 변경" in prompt.build(1, "fixture-room-a", changed, private=True)
    assert await cards.write_instruction(1, None) == 2
    removed = await cards.read(1)
    assert removed["instruction"]["text"] is None
    assert "시험 변경" not in prompt.build(1, "fixture-room-a", removed, private=True)

    agent = Agent(None, store, None, None)
    agent.friend_cards = cards
    msg = SimpleNamespace(card_actor=1, card_message=mid, room_key="fixture-room-a")
    tool = SimpleNamespace(id="fixture-tool", name="card_update",
                           input={"quote": args["quote"], "op": "want", "value": "distract"})
    assert agent._card_tools(msg)[0]["name"] == "card_update"
    assert not (await agent._run_tool(tool, msg))["is_error"]
    assert (await cards.read(1))["card"]["want"] == "distract"
    msg.card_actor = 2
    assert (await agent._run_tool(tool, msg))["is_error"]
    assert (await cards.read(2))["card"] is None

    now = datetime(2026, 11, 17, 23, 45, tzinfo=KST)
    for day in (now, now + timedelta(days=1), now + timedelta(days=2)):
        assert await cards.signal(1, "support", "listen", source="want", at=day, message_id=mid)
        assert not await cards.signal(1, "support", "listen", source="want", at=day, message_id=mid)
    assert (await cards.open_signals(1, "support"))[0]["days"] == 3
    await cards.close_signals(1, "support", "declined")
    assert await cards.open_signals(1, "support") == []

    run_id = await cards.record_run(ModelRun("card_draft", "fixture-trace", "fixture-model",
                                             "fixture-prompt", now, "ok", friend_id=1, output_tokens=20))
    assert run_id > 0
    logs = str(db.admin("SELECT * FROM marong.persona_tool_calls")) + str(db.admin("SELECT * FROM marong.persona_ai_runs"))
    for private in (TEXT, original, rewrite, args["quote"], "생성된 비밀"):
        assert private not in logs

    async def rejected(friend, id, value, code, at=now):
        try:
            await cards.answer_question(friend, id, value, room="fixture-room-a", via="button", at=at)
        except CardError as error:
            assert str(error) == code
        else:
            raise AssertionError(code)

    async def choose(question, value, via, at=now):
        return await cards.answer_question(2, question["id"], value, room="fixture-room-b", via=via, at=at)

    first, extra = await asyncio.gather(cards.first_question(2, "fixture-room-b", now),
                                        cards.first_question(2, "fixture-room-b", now))
    first, extra = (extra, first) if first is None else (first, extra)
    assert first["step"] == 1 and extra is None and len(question_choices(1)) == 6
    assert text_choice(1, "1") == "listen" and text_choice(1, "그냥 들어주기") == "listen"
    assert text_choice(1, "7") is None
    assert not await cards.attach_question(2, first["id"], mid2)  # a user message cannot carry the card
    reply = await store.add_message("fixture-room-b", "assistant", "시험 답장", reply_to=mid2)
    assert await cards.attach_question(2, first["id"], reply)
    await rejected(1, first["id"], "listen", "card_not_found")
    await rejected(2, first["id"], "wrong", "invalid_input")
    replies = await asyncio.gather(choose(first, "listen", "button"), choose(first, "listen", "screen"))
    assert {r["applied"] for r in replies} == {True, False}
    second = replies[0]["next"]
    assert second["step"] == 2 and replies[1]["next"]["id"] == second["id"]
    await rejected(2, first["id"], "solve", "card_closed")
    third = (await choose(second, text_choice(2, "물어볼 때만"), "text"))["next"]
    final = await choose(third, "gentle", "screen")
    assert final["effect"] == "card_set" and final["sentence"] == card_sentence((await cards.read(2))["card"])
    await cards.set(2, {"honesty": "direct"}, source="screen")
    assert (await choose(third, "gentle", "screen"))["sentence"] == final["sentence"]
    assert not await cards.open_question(2, "fixture-room-b", now)

    friend, = db.admin("INSERT INTO marong.friends(name) VALUES ('fixture-expire') RETURNING id")[0]
    waiting = await cards.first_question(friend, "fixture-room-a", now)
    deadline = now + timedelta(hours=24)
    assert not await cards.expire_question(friend, deadline - timedelta(seconds=1))
    await rejected(friend, waiting["id"], "solve", "card_closed", deadline)
    assert await cards.expire_question(friend, deadline)
    assert not await cards.expire_question(friend, deadline)
    fallback = (await cards.read(friend))["card"]
    assert (fallback["support"], fallback["advice"], fallback["honesty"], fallback["source"]) == (
        "ask", "asked", "gentle", "default",
    )
    person, = db.admin("INSERT INTO marong.friends(name) VALUES ('fixture-draft') RETURNING id")[0]
    await cards.draft(person, {"support": "listen", "advice": "asked", "honesty": "gentle", "lead": "follow"}, now)
    preview, sentence = await cards.draft_card(person, "fixture-room-a", now)
    assert sentence and not await cards.draft_card(person, "fixture-room-a", now)
    result = await cards.answer_draft(person, preview["id"], "yes", via="button", at=now)
    assert result["applied"] and result["effect"] == "card_set" and result["sentence"] == sentence
    assert not (await cards.answer_draft(person, preview["id"], "yes", via="screen", at=now))["applied"]

    await cards.set(1, {"proactive": "off"}, source="talk")
    assert not await cards.proactive_allowed(1, now)
    await cards.set(1, {"proactive": "normal"}, source="talk")
    assert await cards.proactive_allowed(1, now)
    await cards.write_instruction(1, "시험 지침", "아주 짧게 답할게.", via="screen")
    caller, = db.admin("INSERT INTO call.callers(friend_id) VALUES (1) RETURNING id")[0]
    voice = MemoryStore(db.admin_url.replace("postgres:@", "marong_call@", 1))
    await voice.open()
    try:
        with patch.dict("os.environ", {"MARONG_FRIEND_CARD": "on"}):
            prefix = await voice.friend_instruction(Principal(caller, 1, "fixture"))
        assert "아주 짧게 답할게." in prefix and "시험 지침" not in prefix and "친구 규칙" in prefix
        assert await voice.friend_instruction(Principal(caller, 1, "fixture")) == ""
        call, _ = await voice.start_call(Principal(caller, 1, "fixture"), "00000000-0000-4000-8000-000000000001", "fixture", "fixture")
        bridge = CallSafety(voice, Principal(caller, 1, "fixture"), call, AsyncMock(), "fixture")
        assert await bridge.caption("fixture-partial", "user", "약 모아 놨어", False) is None
        prompt = await bridge.caption("fixture-signal", "user", "약 모아 놨어", True)
        assert "109" in prompt
        await bridge.caption("fixture-answer", "assistant", "같이 있을게. 자살예방 상담전화 109", True)
        assert await bridge.caption("fixture-signal", "user", "약 모아 놨어", True) is None
        assert await bridge.caption("fixture-next", "user", "고마워", True) == ""
        with patch.dict("os.environ", {"MARONG_FRIEND_CARD": "on", "MARONG_SAFETY": "on"}):
            renewed = await voice.friend_instruction(Principal(caller, 1, "fixture"))
        assert "직접 한 번 물어봐" not in renewed and "109" not in renewed
        await voice.finish(Principal(caller, 1, "fixture"), call, True)
    finally:
        await voice.close()

    new_friend, = db.admin("INSERT INTO marong.friends(name) VALUES ('fixture-onboard') RETURNING id")[0]
    db.admin("INSERT INTO marong.people(user_key,friend_id) VALUES ('fixture-onboard',%s)", (new_friend,))
    delivery = []

    class Reply(Agent):
        async def _reply(self, *_args, **_kwargs):
            return "같이 얘기하자.", {}

    settings = SimpleNamespace(llm_timeout_s=20, reply_wait_s=0, group_triggers=(), llm_max_tokens=200,
                               anthropic_model="fixture")
    handler = Reply(settings, store, None, None)
    handler.friend_cards = cards

    async def send(value):
        delivery.append(value)
        return True

    await handler.handle(Incoming("fixture-room-a", "fixture-onboard", "안녕"), send)
    assert len(delivery) == 1 and "힘들 때 나한테 제일 바라는 건?" in delivery[0] and "1. 그냥 들어주기" in delivery[0]
    q = await cards.open_question(new_friend, "fixture-room-a", datetime.now(KST))
    assert q and q["message_id"]
    await handler.handle(Incoming("fixture-room-a", "fixture-onboard", "1"), send)
    q = await cards.open_question(new_friend, "fixture-room-a", datetime.now(KST))
    assert q["step"] == 2 and "조언은 언제 해 줄까?" in delivery[-1]

    support_friend, = db.admin("INSERT INTO marong.friends(name) VALUES ('fixture-support') RETURNING id")[0]
    await cards.set(support_friend, {"support": "ask"}, source="screen")
    support = await cards.ask_support(support_friend, "fixture-room-a", now)
    assert support and await cards.support_text(support_friend, "fixture-room-b", "1", now) is None
    assert await cards.support_text(support_friend, "fixture-room-a", "7", now) is None
    picked = await cards.support_text(support_friend, "fixture-room-a", "일단 들어 줘", now)
    assert picked["applied"] and picked["effect"] == "want_set"
    support_values = (await cards.read(support_friend))["card"]
    assert support_values["want"] == "listen" and support_values["want_until"] == now+timedelta(hours=24)
    assert await cards.support_text(support_friend, "fixture-room-a", "2", now) is None

    proposal_friend, = db.admin("INSERT INTO marong.friends(name) VALUES ('fixture-proposal') RETURNING id")[0]
    await cards.set(proposal_friend, {"support": "solve"}, source="screen")
    for offset in range(3):
        await cards.signal(proposal_friend, "support", "listen", source="want", at=now-timedelta(days=offset))
    proposals = await asyncio.gather(cards.proposal(proposal_friend, "fixture-room-a", now),
                                     cards.proposal(proposal_friend, "fixture-room-b", now))
    assert sum(value is not None for value in proposals) == 1
    proposal = next(value for value in proposals if value)
    assert proposal["field"] == "support" and proposal["value"] == "listen"
    picked = await cards.answer_proposal(proposal_friend, proposal["id"], "yes", via="screen", at=now,
                                         publish_message=True)
    assert picked["effect"] == "proposal_accepted" and picked["sentence"]
    assert not (await cards.answer_proposal(proposal_friend, proposal["id"], "yes", via="text", at=now))["applied"]
    assert not await cards.open_signals(proposal_friend, "support")
    assert (await cards.read(proposal_friend))["card"]["support"] == "listen"
    assert await cards.proposal(proposal_friend, "fixture-room-a", now+timedelta(minutes=1)) is None
    assert not await cards.may_propose(proposal_friend, "fixture-room-a", "지금은 너무 피곤해", now)
    assert not await cards.may_propose(proposal_friend, "fixture-room-a", "그냥 있어", now.replace(hour=1))
    db.admin("INSERT INTO marong.people(user_key,friend_id) VALUES ('fixture-proposal-user',%s)", (proposal_friend,))
    for text in ("응", "그래 🌰", "ㅋㅋ"):
        await store.add_message("fixture-room-a", "user", text, user_key="fixture-proposal-user")
    assert not await cards.may_propose(proposal_friend, "fixture-room-a", "응", datetime.now(KST))

    handler.llm = SimpleNamespace(create_once=AsyncMock(return_value=SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps({
            "understood": "짧게 반응할게.", "hard_rules": [], "out_of_scope": [],
        }, ensure_ascii=False))])))
    command = Incoming("fixture-room-a", "fixture-onboard", "")
    command.card_actor = new_friend
    saved, meta = await handler._instruction_reply(command, "앞으로 이렇게 대해 줘: 짧게 답해 줘")
    assert saved == "이렇게 이해했어: 짧게 반응할게." and meta["custom_instruction"] == "saved"
    assert (await cards.read(new_friend))["instruction"]["via"] == "chat"
    command.is_channel = False
    assert (await handler._instruction_reply(command, "앞으로 이렇게 대해 줘: 짧게 답해 줘"))[0] == "그건 우리 둘이 있을 때 말해 줘"
    command.is_channel = True
    await handler._instruction_reply(command, "앞으로 이렇게 대해 줘:")
    assert (await cards.read(new_friend))["instruction"]["text"] is None

    dm = DiscordAgent(settings, store, None, None)
    dm.friend_cards = cards
    for phrase, on, expected in (("선톡 끄기", False, "off"), ("선톡 켜기", True, "normal")):
        id = await store.add_message("fixture-room-a", "user", phrase, user_key="fixture-person-a")
        command = DiscordIncoming("fixture-room-a", "fixture-person-a", phrase, friend_id=1, proactive_preference=on)
        await dm._dm_command(command, {"friend_id": 1}, id, phrase, True)
        assert (await cards.read(1))["card"]["proactive"] == expected

    rule, _ = await cards.add_rule(new_friend, "avoid_topic", "바닷가")
    assert rule.outcome == "ok"
    picture = SimpleNamespace(title="바닷가", scene="fixture", line="fixture", ask="fixture", alt="fixture",
                              key="v1/fixture", fits=lambda _now: True)
    topics = Topics(SimpleNamespace(timezone="Asia/Seoul"), store,
                    pictures=SimpleNamespace(pickable=(picture,)), rng=lambda: 0)
    topics.today = AsyncMock(return_value=Today({"pictures": True}, set(), None, now))
    with patch.dict("os.environ", {"MARONG_FRIEND_CARD": "on"}):
        assert await topics.choose({"friend_id": new_friend}, now, now+timedelta(hours=1)) is None


async def run(db):
    store = Store(db.app_url)
    await store.open(wait=True)
    try:
        await scenario(db, store)
    finally:
        await store.close()


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(run(db))
    finally:
        db.close()
    print("TC-257/258 question storage, 24h default; TC-278 ownership and overlap; TC-279 numeric auditing")
