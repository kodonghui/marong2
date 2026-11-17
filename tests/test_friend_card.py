"""Scoped storage and tool auditing for TC-257, TC-278, and TC-279."""

import asyncio
from datetime import datetime, timedelta

from marong.friend_card import CardError, FriendCards, KST, ModelRun, card_sentence, question_choices, text_choice
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
    assert await cards.write_instruction(1, None) == 2
    assert (await cards.read(1))["instruction"]["text"] is None

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
