"""Friend-card API on isolated PostgreSQL through an aiohttp test server."""

import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer

from marong.app_chat import AppChat
from marong.discord_store import DiscordStore
from marong.friend_card import FriendCards
from pg import TestDB
from test_persona_schema import prepare

ORIGIN = "https://marong.test"
BASE = "/chat/persona/api"
ROOM = "fixture-persona-one"


async def scenario(db):
    db.admin("""INSERT INTO marong.friends(name) VALUES ('fixture-one'), ('fixture-two');
        INSERT INTO marong.rooms(room_key,is_channel) VALUES ('fixture-persona-one',true), ('fixture-persona-two',true);
        INSERT INTO marong.people(user_key,friend_id) VALUES ('fixture-one',1), ('fixture-two',2)""", None)
    store = DiscordStore(db.app_url)
    await store.open(wait=True)
    try:
        identities = {"one": {"enabled": True, "room_key": ROOM, "channel_id": 1, "friend_id": 1, "user_key": "fixture-one"},
                      "two": {"enabled": True, "room_key": "fixture-persona-two", "channel_id": 2,
                              "friend_id": 2, "user_key": "fixture-two"}}

        async def verify(assertion):
            status = "ok" if assertion else "unauthenticated"
            return status, assertion

        store.app_login = AsyncMock(side_effect=lambda key: identities.get(key))
        cards = FriendCards(store)
        agent = SimpleNamespace(friend_cards=None)
        agent.s = SimpleNamespace(anthropic_model="fixture")
        agent.llm = SimpleNamespace(create_once=AsyncMock())
        chat = AppChat(store, agent, SimpleNamespace(room_lock=lambda _: asyncio.Lock()),
                       SimpleNamespace(check=verify), None, origin=ORIGIN)
        one = {"Cf-Access-Jwt-Assertion": "one", "Origin": ORIGIN}
        two = {**one, "Cf-Access-Jwt-Assertion": "two"}
        async with TestClient(TestServer(chat.web_app())) as http:
            async def check(result, expected, code=None):
                assert result.status == expected, await result.text()
                if code:
                    assert (await result.json())["code"] == code
                    assert result.content_type == "application/problem+json"
                elif expected != 204:
                    return await result.json()

            path = BASE + "/card"
            await check(await http.get(path), 401, "unauthenticated")
            await check(await http.get(path, headers=one), 403, "feature_off")
            agent.friend_cards = cards
            assert (await check(await http.get(path, headers=one), 200))["state"] == "none"
            for screen in ("/chat/persona/", "/chat/persona/instructions", "/chat/persona/persona.js"):
                page = await http.get(screen, headers=one)
                assert page.status == 200 and page.headers["Cache-Control"] == "no-store"
            invalid = {"support": "listen"}
            await check(await http.patch(path, json=invalid, headers=one), 400, "invalid_request")
            await check(await http.patch(path, json=invalid, headers={**one, "Origin": "https://other.test"}),
                        403, "cross_site")

            now = datetime.now(timezone.utc)
            question = await cards.first_question(1, ROOM, now)
            message = await store.add_message(ROOM, "assistant", "시험 질문", meta={"transport": "app", "delivered": True})
            await cards.attach_question(1, question["id"], message)
            path = f"{BASE}/cards/{question['id']}/answer"
            await check(await http.post(path, json={"value": "listen"}, headers=two), 404, "not_found")
            await check(await http.post(path, json={"value": "fake"}, headers=one), 400, "invalid_request")
            first = await check(await http.post(path, json={"value": "listen"}, headers=one), 200)
            repeat = await check(await http.post(path, json={"value": "listen"}, headers=one), 200)
            assert first == repeat and first["effect"] == "next_question" and first["card"]["answer"] == "listen"
            await check(await http.post(path, json={"value": "solve"}, headers=one), 409, "card_closed")
            response = await check(await http.get("/chat/api/messages", headers=one), 200)
            assert len(response["messages"]) == 2
            assert [row["card"]["status"] for row in response["messages"]] == ["answered", "open"]
            assert (await check(await http.get("/chat/api/messages", headers=two), 200))["messages"] == []

            next_id = response["messages"][-1]["card"]["id"]
            card_data = {"support": "listen", "advice": "asked", "honesty": "gentle", "proactive": "less"}
            set_card = await check(await http.patch(BASE + "/card", json=card_data, headers=one), 200)
            assert set_card["state"] == "set" and set_card["proactive"] == "less" and set_card["sentence"]
            await check(await http.patch(BASE + "/card", json={"proactive": "normal"}, headers=one), 403, "needs_owner")
            await check(await http.post(f"{BASE}/cards/{next_id}/answer", json={"value": "asked"}, headers=one),
                        409, "card_closed")
            path = BASE + "/rules"
            data = {"kind": "no_vocative", "text": "야"}
            rule = await check(await http.post(path, json=data, headers=one), 201)
            assert await check(await http.post(path, json=data, headers=one), 200) == rule
            await check(await http.post(path, json={"kind": "no_vocative", "text": "다섯글자넘어"}, headers=one),
                        400, "invalid_request")
            path += f"/{rule['id']}"
            await check(await http.delete(path, headers=two), 404, "not_found")
            await check(await http.delete(path, headers=one), 204)
            await check(await http.delete(path, headers=one), 204)
            assert (await check(await http.get(BASE + "/card", headers=one), 200))["rules"] == []
            path = BASE + "/instructions"
            assert (await check(await http.get(path, headers=one), 200))["version"] == 0
            await check(await http.put(path, json={"text": "  "}, headers=one), 400, "invalid_request")
            source = "야라고 부르지 말고 109도 말하지 마."
            clean = {"understood": "조용히 답할게.", "hard_rules": [
                {"kind": "banned_vocative", "value": "야", "quote": "야라고 부르지 말고"},
            ], "out_of_scope": [{"quote": "109도 말하지 마", "why": "safety"}]}

            def result(data):
                return SimpleNamespace(stop_reason="end_turn",
                                       content=[SimpleNamespace(type="text", text=json.dumps(data, ensure_ascii=False))])

            agent.llm.create_once.return_value = result({**clean, "understood": "109 얘기를 안 할게."})
            await check(await http.put(path, json={"text": source}, headers=one), 503, "ai_unavailable")
            assert (await check(await http.get(path, headers=one), 200))["text"] is None
            agent.llm.create_once.return_value = result(clean)
            saved = await check(await http.put(path, json={"text": source}, headers=one), 200)
            assert saved["instructions"]["understood"] == clean["understood"] and saved["moved"]["rules"]
            assert saved["cannot"] == "위험할 때 하는 말은 바꿀 수 없어."
            assert (await check(await http.get(path, headers=two), 200))["text"] is None
            await check(await http.delete(path, headers=one), 204)
            cleared = await check(await http.get(path, headers=one), 200)
            assert cleared["text"] is None and cleared["version"] == 2
            assert (await check(await http.get(BASE + "/card", headers=one), 200))["rules"]
            for _ in range(3):
                await check(await http.put(path, json={"text": source}, headers=one), 200)
            await check(await http.put(path, json={"text": source}, headers=one), 429, "too_many_requests")
    finally:
        await store.close()


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(scenario(db))
    finally:
        db.close()
    print("TC-280–284 partial: friend card, writes, rule idempotency and question DTO with test Access")
