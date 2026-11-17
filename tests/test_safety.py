"""TC-271–273/275: safety state transitions with a fake classifier."""

import asyncio
from datetime import datetime, timedelta, timezone

from marong.safety import ASK, ASKED, BODY_HELP, CALL_HELP, URGENT, Safety, judge, owner_private
from marong.store import Store
from tools.report import fetch
import psycopg
from psycopg.rows import dict_row
from pg import TestDB
from test_persona_schema import prepare


async def run(db):
    db.admin("INSERT INTO marong.friends(name) VALUES ('fixture-check'), ('fixture-other')")
    store = Store(db.app_url)
    await store.open(wait=True)
    now = datetime.now(timezone.utc)
    requests = []

    async def classify(mode, rows):
        requests.append((mode, len(rows)))
        assert len(rows) <= 6
        return "no" if mode == "signal" else "unknown"

    safety = Safety(store, classify)
    try:
        assert judge("오늘 밤에 청소할 거야") is None and judge("종이에 선 그었어") is None
        assert judge("지금 한강에 왔어") is None
        assert not await safety.apply(1, "아 발표 망해서 죽고 싶다 ㅋㅋ", [], now)
        assert requests == [("signal", 1)]
        assert not (await safety.active(2, now))
        move = await safety.apply(1, "일 잘렸어. 그런데 다리 중에 제일 높은 데가 어디야?", [], now)
        assert move.mark == "ask" and move.prompt == ASK
        await safety.delivered(1, move, "혹시 진짜 죽고 싶은 마음까지 들어?", now)
        follow = await safety.apply(1, "그 정도는 아니야", [], now + timedelta(minutes=1))
        assert follow.prompt == ASKED and follow.mark is None
        check = await safety.apply(1, "오늘 밤에 할 거야", [], now + timedelta(minutes=2))
        assert check.prompt == CALL_HELP and check.mark == "109"
        await safety.delivered(1, check, "같이 있을게. 상담전화 109(국번 없이)에 연락해 줘.", now)
        assert (await safety.apply(1, "고마워", [], now + timedelta(minutes=3))).mark is None
        injury = await safety.apply(1, "피가 안 멈춰", [], now + timedelta(minutes=4), via="call")
        assert injury.prompt == URGENT and injury.mark == "119"
        later = now + timedelta(days=4)
        assert not await safety.apply(1, "오늘 어땠어", [], later)
        body = await safety.apply(2, "이번 주는 하루 한 끼만 먹을 거야", [], later)
        assert body.prompt == BODY_HELP and body.mark == "body"
        await safety.delivered(2, body, "정신건강 상담전화 1577-0199에 얘기해 볼 수도 있어.", later)
        assert (await safety.apply(2, "안녕", [], later + timedelta(hours=1))).mark is None
        assert not await safety.apply(2, "안녕", [], later + timedelta(days=8))
        assert owner_private("친구가 위험해 보여")
        assert not owner_private("내일 방 청소할 거야")
        retained = str(db.admin("SELECT id,kind,friend_id,injured,answer FROM marong.safety_states"))
        assert all(text not in retained for text in ("일 잘렸어", "모아 놨어", "하루 한 끼", "피가 안 멈춰"))
        db.admin("""INSERT INTO marong.rooms(room_key,is_channel) VALUES ('fixture-safe-report',true);
            INSERT INTO marong.people(user_key,friend_id) VALUES ('fixture-safe-user',1)""", None)
        marker = "fixture-sensitive-marker 피가 안 멈춰"
        user = await store.add_message("fixture-safe-report", "user", marker, user_key="fixture-safe-user")
        await store.add_message("fixture-safe-report", "assistant", "fixture-response-marker", reply_to=user)
        await store.add_message("fixture-safe-report", "user", "일반적인 시험 이야기", user_key="fixture-safe-user")
        with psycopg.connect(db.app_url, row_factory=dict_row) as conn:
            output = fetch(conn, now-timedelta(days=1), now+timedelta(days=1), False)
        assert not any(marker in row["content"] or "fixture-response-marker" in row["content"] for row in output["messages"])
        assert any("일반적인 시험 이야기" == row["content"] for row in output["messages"])
    finally:
        await store.close()


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(run(db))
    finally:
        db.close()
    print("TC-271–273/275 partial: safety decisions, advice once, expiration, no original messages")
