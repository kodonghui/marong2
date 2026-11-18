"""Friend-card API on isolated PostgreSQL through an aiohttp test server."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import psycopg

from aiohttp.test_utils import TestClient, TestServer

from marong import memory_consent
from marong.agent import Agent
from marong.app_chat import AppChat
from marong.discord_store import DiscordStore
from marong.friend_card import FriendCards
from marong.friend_forget import forget_selected
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
            for screen in ("/chat/persona/", "/chat/persona/instructions", "/chat/persona/memory", "/chat/persona/persona.js"):
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
            other_source = "시험 친구 지침 바꿔 줘."
            agent.llm.create_once.return_value = result({"understood": "내 지침만 바꿀게.", "hard_rules": [],
                "out_of_scope": [{"quote": "시험 친구 지침 바꿔 줘", "why": "other_friend"}]})
            await check(await http.put(path, json={"text": other_source}, headers=one), 403, "not_allowed")
            assert (await check(await http.get(path, headers=one), 200))["version"] == 2
            mixed_source = "짧게 말해 줘. 검색 기능 켜 줘."
            agent.llm.create_once.return_value = result({"understood": "짧게 답할게.", "hard_rules": [],
                "out_of_scope": [{"quote": "검색 기능 켜 줘", "why": "capability"}]})
            mixed = await check(await http.put(path, json={"text": mixed_source}, headers=one), 200)
            assert mixed["instructions"]["understood"] == "짧게 답할게."
            assert mixed["cannot"] == "그 기능은 맞춤형 지침으로 켤 수 없어."
            agent.llm.create_once.return_value = result(clean)
            await check(await http.put(path, json={"text": source}, headers=one), 200)
            await check(await http.put(path, json={"text": source}, headers=one), 429, "too_many_requests")

            memory_path = BASE + "/memories"
            await check(await http.get(memory_path, headers=one), 403, "feature_off")
            agent.friend_memory_mode = "shadow"
            await check(await http.get(memory_path, headers=one), 403, "feature_off")
            agent.friend_memory_mode = "on"
            source_one = await store.add_message(ROOM, "user", "가을이 좋아", "fixture-one")
            source_two = await store.add_message("fixture-persona-two", "user", "겨울이 좋아", "fixture-two")
            db.admin("""
                INSERT INTO marong.memory_items(friend_id,kind,text,status,heard_at,channel,message_id,quote,
                                               share,sensitive,source)
                VALUES (1,'preference','가을을 좋아함','current',now(),'app',%s,'가을이 좋아','self',NULL,'text'),
                       (1,'fact','확인 대기','pending_ok',now(),'app',%s,'가을이 좋아','self','health','text'),
                       (2,'preference','겨울을 좋아함','current',now(),'app',%s,'겨울이 좋아','self',NULL,'text')
            """, (source_one, source_one, source_two))
            response = await http.get(memory_path, headers=one)
            assert response.headers["Cache-Control"] == "no-store"
            [memory_one] = (await check(response, 200))["items"]
            [memory_two] = (await check(await http.get(memory_path, headers=two), 200))["items"]
            assert memory_one["quote"] == "가을이 좋아" and memory_two["quote"] == "겨울이 좋아"
            assert not {"room_key", "message_id", "call_turn_id"} & memory_one.keys()
            foreign = await check(await http.get(f"{memory_path}?before={memory_two['id']}", headers=one), 200)
            assert foreign == {"items": [], "loops": [], "hasMore": False}
            await check(await http.get(f"{memory_path}?before=-1", headers=one), 400, "invalid_request")
            assert (await check(await http.get(f"{memory_path}?before={2**63 - 1}", headers=one), 200))["items"] == []
            await check(await http.get(f"{memory_path}?before={2**63}", headers=one), 400, "invalid_request")
            db.admin("""
                INSERT INTO marong.memory_items(friend_id,kind,text,status,heard_at,channel,message_id,quote,share,source)
                SELECT 1,'fact','시험 항목 '||i,'current',now()-i*INTERVAL '1 day','app',%s,'가을이 좋아','self','text'
                FROM generate_series(1,100) i
            """, (source_one,))
            first_page = await check(await http.get(memory_path, headers=one), 200)
            assert len(first_page["items"]) == 100 and first_page["hasMore"]
            cursor = first_page["items"][-1]["id"]
            next_page = await check(await http.get(f"{memory_path}?before={cursor}", headers=one), 200)
            assert [row["text"] for row in next_page["items"]] == ["시험 항목 100"] and not next_page["hasMore"]

            forget = BASE + "/forgets"
            own_item = {"type": "item", "id": memory_one["id"]}
            request_key = str(uuid4())
            keyed = {**one, "Idempotency-Key": request_key}
            for body in ({}, {"type": "item", "id": True}, {"type": "item", "id": 2**63},
                         {"type": [], "id": memory_one["id"]}, {**own_item, "friend": 2}):
                await check(await http.post(forget, json=body, headers=keyed), 400, "invalid_request")
            await check(await http.post(forget, json=own_item, headers=one), 400, "invalid_request")
            await check(await http.post(forget, json=own_item, headers={**keyed, "Idempotency-Key": "invalid"}),
                        400, "invalid_request")
            await check(await http.post(forget, json={"type": "item", "id": memory_two["id"]}, headers=keyed),
                        404, "not_found")
            agent.friend_memory_mode = "shadow"
            await check(await http.post(forget, json=own_item, headers=keyed), 403, "feature_off")
            assert db.admin("SELECT count(*) FROM marong.memory_forgets") == [(0,)]
            agent.friend_memory_mode = "on"

            # The browser can lose its reply after the transaction has already committed.
            committed = asyncio.Event()
            resume_response = asyncio.Event()

            async def wait_after_commit(*args, **kwargs):
                result = await forget_selected(*args, **kwargs)
                committed.set()
                await resume_response.wait()
                return result

            with patch("marong.app_persona.forget_selected", wait_after_commit):
                lost = asyncio.create_task(http.post(forget, json=own_item, headers=keyed))
                await asyncio.wait_for(committed.wait(), 5)
                lost.cancel()
                await asyncio.gather(lost, return_exceptions=True)
                resume_response.set()

            result = await check(await http.post(forget, json=own_item, headers=keyed), 200)
            assert result == {"forgot": 102, "messages": 1}
            assert await check(await http.post(forget, json=own_item, headers=keyed), 200) == result
            assert db.admin("SELECT count(*) FROM marong.memory_forgets") == [(1,)]
            assert await check(await http.post(forget, json=own_item,
                headers={**one, "Idempotency-Key": str(uuid4())}), 200) == {"forgot": 0, "messages": 0}
            assert (await check(await http.get(memory_path, headers=one), 200))["items"] == []
            assert (await check(await http.get(memory_path, headers=two), 200))["items"] == [memory_two]

            async def add_sensitive(category, room=ROOM):
                origin = await store.add_message(room, "user", "합성 민감 자료", "fixture-one")
                [(ident,)] = db.admin("""
                    INSERT INTO marong.memory_items(friend_id,kind,text,status,heard_at,channel,
                        message_id,quote,share,sensitive,room_key,source)
                    SELECT 1,'fact','합성 민감 항목','pending_ok',now(),
                        CASE WHEN r.is_channel THEN 'app' ELSE 'kakao_group' END,m.id,
                        '합성 민감 자료','self',%s,CASE WHEN r.is_channel THEN NULL ELSE r.room_key END,'text'
                    FROM marong.messages m JOIN marong.rooms r USING(room_key) WHERE m.id=%s RETURNING id
                """, (category, origin))
                return ident

            current = datetime.now(timezone.utc)
            first_pending = await add_sensitive("health")
            db.admin("INSERT INTO marong.rooms(room_key,is_channel) VALUES ('fixture-group-consent',false)")
            assert await memory_consent.reserve(store.pool, 1, "fixture-group-consent", current) is None
            db.admin("INSERT INTO marong.safety_states(friend_id,kind,opened_via) VALUES (1,'crisis','text')")
            assert await memory_consent.reserve(store.pool, 1, ROOM, current) is None
            db.admin("UPDATE marong.safety_states SET closed_at=now(),close_reason='calm' WHERE friend_id=1")
            assert (await check(await http.get(memory_path, headers=one), 200))["items"] == []

            incoming = SimpleNamespace(card_actor=1, room_key=ROOM, via="app")
            card_reply = await Agent._with_question(agent, incoming, "시험 답장", "평소 대화")
            card = incoming.question
            assert card_reply.endswith(memory_consent.QUESTION) and card["memory_item_id"] == first_pending
            attached = await store.add_message(ROOM, "assistant", card_reply, meta={"delivered": True})
            assert await cards.attach_question(1, card["id"], attached)
            assert await memory_consent.reserve(store.pool, 1, ROOM, current) is None
            path = f"{BASE}/cards/{card['id']}/answer"
            output = (await check(await http.get("/chat/api/messages", headers=one), 200))["messages"][-1]["card"]
            assert output["kind"] == "memory_ok"
            assert output["options"] == [{"value": "keep", "label": "기억해"}, {"value": "forget", "label": "잊어"}]
            await check(await http.post(path, json={"value": "keep"}, headers=two), 404, "not_found")
            await check(await http.post(path, json={"value": "other"}, headers=one), 400, "invalid_request")
            agent.friend_memory_mode = "shadow"
            await check(await http.post(path, json={"value": "keep"}, headers=one), 403, "feature_off")
            agent.friend_memory_mode = "on"
            kept = await check(await http.post(path, json={"value": "keep"}, headers=one), 200)
            assert kept["effect"] == "memory_kept"
            assert await check(await http.post(path, json={"value": "keep"}, headers=one), 200) == kept
            assert (await check(await http.get(memory_path, headers=one), 200))["items"][0]["id"] == first_pending
            next_health = await add_sensitive("health", "fixture-group-consent")
            await memory_consent.maintain(store.pool, current)
            items = (await check(await http.get(memory_path, headers=one), 200))["items"]
            assert {row["id"] for row in items} == {first_pending, next_health}
            assert all(row["scope"] == "me" for row in items)

            decline = await add_sensitive("money")
            declined_card = await memory_consent.reserve(store.pool, 1, ROOM, current)
            await memory_consent.undelivered(store.pool, 1, declined_card["id"])
            declined_card = await memory_consent.reserve(store.pool, 1, ROOM, current)
            await cards.attach_question(1, declined_card["id"], attached)
            path = f"{BASE}/cards/{declined_card['id']}/answer"
            declined = await check(await http.post(path, json={"value": "forget"}, headers=one), 200)
            assert declined["effect"] == "memory_forgotten"
            later = await add_sensitive("money")
            await memory_consent.maintain(store.pool, current)
            assert db.admin("SELECT status,text FROM marong.memory_items WHERE id IN (%s,%s) ORDER BY id", (decline,later)) == [
                ("forgotten", None), ("forgotten", None)]
            assert await memory_consent.reserve(store.pool, 1, ROOM, current) is None

            unanswered = await add_sensitive("religion")
            expired_card = await memory_consent.reserve(store.pool, 1, ROOM, current - timedelta(hours=24))
            await cards.attach_question(1, expired_card["id"], attached)
            path = f"{BASE}/cards/{expired_card['id']}/answer"
            await check(await http.post(path, json={"value": "forget"}, headers=one), 409, "card_closed")
            await memory_consent.maintain(store.pool, current)
            assert db.admin("SELECT status FROM marong.memory_items WHERE id=%s", (unanswered,)) == [("current",)]
            assert db.admin("SELECT status FROM marong.chat_cards WHERE id=%s", (expired_card["id"],)) == [("expired",)]
            assert await memory_consent.reserve(store.pool, 1, ROOM, current) is None

            endpoints = (
                ("GET", "/card", None), ("PATCH", "/card", {"lead": "lead"}),
                ("POST", "/rules", {"kind": "avoid_topic", "text": "시험주제"}),
                ("DELETE", "/rules/999999", None), ("GET", "/instructions", None),
                ("PUT", "/instructions", {"text": "짧게 말해 줘"}), ("DELETE", "/instructions", None),
                ("POST", "/cards/999999/answer", {"value": "yes"}),
                ("GET", "/memories", None), ("POST", "/forgets", own_item),
            )
            original_login = store.app_login.side_effect
            for method, suffix, body in endpoints:
                async def send(headers):
                    return await http.request(method, BASE+suffix, json=body, headers={**headers, "Idempotency-Key": str(uuid4())})
                await check(await send({"Origin": ORIGIN}), 401, "unauthenticated")
                await check(await send({**one, "Cf-Access-Jwt-Assertion": "unlinked"}), 403, "not_allowed")
                if method != "GET":
                    await check(await send({**one, "Origin": "https://other.test"}), 403, "cross_site")
                agent.friend_cards = None
                await check(await send(one), 403, "feature_off")
                agent.friend_cards = cards
                store.app_login.side_effect = psycopg.OperationalError("fixture-private-error")
                await check(await send(one), 503, "db_unavailable")
                store.app_login.side_effect = RuntimeError("fixture-private-error")
                result = await send(one)
                assert result.status == 500
                error = await result.json()
                assert error["code"] == "internal" and len(error["traceId"]) == 16
                assert "fixture-private-error" not in json.dumps(error)
                store.app_login.side_effect = original_login
            await check(await http.put(BASE+"/instructions", json={"text": "가"*501}, headers=one), 400, "invalid_request")
            await check(await http.delete(BASE+"/rules/not-a-number", headers=one), 400, "invalid_request")
            for index in range(20):
                await check(await http.post(BASE+"/rules", json={"kind": "avoid_topic", "text": f"시험{index}"}, headers=two), 201)
            await check(await http.post(BASE+"/rules", json={"kind": "avoid_topic", "text": "한도밖"}, headers=two), 409, "rule_limit")
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
    print("TC-343: memory list status, owner isolation, inaccessible cursor and hidden consent state")

    print("TC-344: owner-only forget API, lost response recovery, same key replay and error envelopes")

    print("TC-338/345: one private sensitive-memory card, keep/forget, expiry and future choices")
