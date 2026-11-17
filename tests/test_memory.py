"""저장소·본체·뒤 작업(요약·임베딩·기억 찾기)을 진짜 Postgres 로 시험한다. Claude·임베딩은 가짜.
실행(윈도우): .venv\\Scripts\\python tests\\test_memory.py   (리눅스·맥: .venv/bin/python tests/test_memory.py)
pgserver 가 필요함: pip install pgserver"""
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import psycopg  # noqa: E402

from fakes import FakeEmbeddings, ScriptedLLM, message, text, thinking, tool_use  # noqa: E402
from pg import TestDB  # noqa: E402

CHECKS = 0


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def last_text(body) -> str:
    """요청의 마지막 친구 말(문자열 내용)."""
    for m in reversed(body["messages"]):
        if m["role"] == "user" and isinstance(m["content"], str):
            return m["content"]
    return ""


def situation(body) -> str:
    return body["system"][-1]["text"]


def chat_reply(body):
    """가짜 Claude(답장): 말에 든 표시에 따라 다르게 답한다."""
    last = body["messages"][-1]
    if last["role"] == "system":  # 빈 답 다시 쓰기
        return message([text("다시 쓴 답 ✨")])
    if isinstance(last["content"], list):  # set_name 결과를 받은 뒤
        return message([text("동희야 반가워 😆")])
    said = last_text(body)
    if "내 이름은 동희" in said:
        return message([thinking("이름을 저장하자"), tool_use("set_name", {"name": " 동희 "})], "tool_use")
    if "REFUSE" in said:
        return message([], "refusal", stop_details={"type": "refusal", "category": "general_harms", "explanation": None})
    if "EMPTY" in said:
        return message([thinking("음…")])
    if "FAIL" in said:
        return RuntimeError("boom")
    return message([text(f"응답:{said.splitlines()[-1]}")])


def summary_reply(body):
    """가짜 Claude(요약): 구조화 출력 JSON."""
    convo = body["messages"][0]["content"]
    if "REFUSE_SUM" in convo:
        return message([], "refusal")
    if "BAD_JSON" in convo:
        return message([text("json 아님")])
    tags = body["output_config"]["format"]["schema"]["properties"]["notes"]["items"]["properties"]["who"]["enum"]
    return message([text(json.dumps({"summary": "친구1이 토익 시험과 마라탕 얘기를 함",
                                     "notes": [{"who": tags[0], "note": "- 다음 주 토익 시험\n- 마라탕 좋아함"}]},
                                    ensure_ascii=False))])


def share_reply(body):
    """가짜 Claude(공유 메모 거르기): 메모에 '마라탕'이 있으면 그것만 남김."""
    return message([text(json.dumps({"items": ["마라탕 좋아함"] if "마라탕" in body["messages"][0]["content"] else []},
                                    ensure_ascii=False))])


def respond(body):
    fmt = body.get("output_config", {}).get("format")
    if not fmt:
        return chat_reply(body)
    return share_reply(body) if "items" in fmt["schema"]["properties"] else summary_reply(body)


async def main():
    db = TestDB()
    tmp = Path(tempfile.mkdtemp())
    os.environ.update({
        "BOT_TOKEN": "t", "ANTHROPIC_API_KEY": "k", "DATABASE_URL": db.app_url,
        "PROMPT_PATH": str(ROOT / "prompt.md"), "KNOWLEDGE_DIR": str(tmp / "knowledge"),
        "RECENT_TURNS": "2", "SUMMARY_TURNS": "2", "EMBED_MODEL": "fake-bigram",
        "REPLY_TURNS": "2", "REPLY_MAX_ROWS": "4",
    })
    from marong.agent import (CALLED_TEXT, EMPTY_NUDGE, EMPTY_TEXT, FALLBACK_TEXT, LATE_TEXT, REFUSAL_TEXT, Agent,
                              Incoming, clean_name)
    from marong.config import load_settings
    from marong.memory import BadOutput, MemoryWorker
    from marong.store import Store

    s = replace(load_settings(), recall_min_similarity=0.2)
    ok(s.problems() == [], s.problems())
    ok(s.anthropic_model == "claude-haiku-5-5" and s.anthropic_effort == "xhigh", "기본 모델·effort")
    store = Store(s.database_url)
    await store.open(wait=True)
    emb = FakeEmbeddings()
    llm = ScriptedLLM(respond)
    worker = MemoryWorker(s, store, emb, llm)
    agent = Agent(s, store, emb, llm)
    sent: list[str] = []

    async def send(t):
        sent.append(t)
        return True

    async def say(room, user, t, channel=True, kakao_id=None, deadline=None, send_fn=send):
        return await agent.handle(Incoming(room, user, t, is_channel=channel, kakao_id=kakao_id), send_fn, deadline)

    # ── 저장소 ──
    ok(await store.schema_version() == 9, "표 버전")
    ok(await store.can_delete() is False, "봇 계정은 기록을 지우거나 고칠 수 없음(can_delete)")
    ok(clean_name("  동희  ") == "동희" and clean_name("") == "" and clean_name("가" * 21) == "", "이름 다듬기")

    # 봇 계정으로 지우기·고치기·비우기·표 지우기를 직접 해 봐도 모두 막힘
    await say("r1", "u1", "안녕", kakao_id="k1")
    for sql in ("DELETE FROM marong.messages", "UPDATE marong.messages SET content = 'x'",
                "TRUNCATE marong.messages", "DELETE FROM marong.people", "DELETE FROM marong.summaries",
                "DROP TABLE marong.messages", "UPDATE marong.notes SET content = 'x'",
                "DELETE FROM marong.friends", "DELETE FROM marong.friendships", "DELETE FROM marong.shared_notes",
                "UPDATE marong.shared_notes SET content = 'x'", "TRUNCATE marong.shared_notes"):
        try:
            with psycopg.connect(db.app_url, autocommit=True) as c:
                c.execute(sql)
            ok(False, f"막혀야 함: {sql}")
        except psycopg.errors.InsufficientPrivilege:
            ok(True, sql)

    # ── 본체: 이름 묻기 → set_name → 이름으로 부르기 ──
    b = llm.bodies[-1]
    ok(b["model"] == "claude-haiku-5-5" and b["max_tokens"] == 16000 and b["output_config"] == {"effort": "xhigh"},
       "모델·최대 출력·effort 전달")
    ok(b["tools"][0]["name"] == "set_name" and "temperature" not in b, "set_name 도구, temperature 없음")
    ok(b["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"} and "마롱이" in b["system"][0]["text"],
       "말투 지시문은 캐시 블록")
    ok("이름을 아직 몰라" in situation(b) and "1:1" in situation(b), "이름 모를 때 물어보라고 알려 줌")
    ok("다시 묻지 말고" in situation(b) and "조르지 말고" in b["system"][0]["text"], "이름은 한 번만 묻고 조르지 않음")
    ok("# 마롱이 취향" in b["system"][0]["text"] and "군밤" in b["system"][0]["text"], "좋아하는 음식·간식·취미")
    ok("# 마롱이 일상" in b["system"][0]["text"], "사람 친구처럼 먹고 노는 일상")
    ok(b["messages"][0]["content"].startswith("(") and b["messages"][0]["content"].endswith(") 안녕"),
       "첫 말 앞에 시각")
    ok(await say("r1", "u1", "안녕", kakao_id="k1") is None, "같은 카카오 메시지는 한 번만 답함")

    n = len(llm.bodies)
    reply = await say("r1", "u1", "내 이름은 동희야")
    ok(reply == "동희야 반가워 😆", reply)
    first, second = llm.bodies[n], llm.bodies[n + 1]
    ok(second["messages"][-2]["role"] == "assistant" and second["messages"][-2]["content"][0].type == "thinking",
       "생각 블록을 그대로 돌려줌")
    res = second["messages"][-1]["content"][0]
    ok(res["type"] == "tool_result" and res["tool_use_id"] == "toolu_1" and "동희" in res["content"], "도구 결과")
    ok(db.admin("SELECT name FROM marong.people WHERE user_key = 'u1'") == [("동희",)], "이름 저장(앞뒤 빈칸 제거)")
    ok(first is not second and len(first["messages"]) < len(second["messages"]), "요청 기록이 서로 섞이지 않음")

    await say("r1", "u1", "나 마라탕 좋아해")
    ok("지금 말 건 친구: 동희" in situation(llm.bodies[-1]), "다음부터 이름을 앎")

    # ── '초기화'·'처음부터'는 그냥 대화: 기록이 지워지지 않음 ──
    before = db.admin("SELECT count(*), min(id) FROM marong.messages WHERE room_key = 'r1'")[0]
    calls = len(llm.bodies)
    r_a = await say("r1", "u1", "초기화")
    r_b = await say("r1", "u1", "처음부터 다시 얘기하자 초기화 해줘")
    after = db.admin("SELECT count(*), min(id) FROM marong.messages WHERE room_key = 'r1'")[0]
    ok(r_a == "응답:초기화" and r_b.startswith("응답:") and len(llm.bodies) == calls + 2, "초기화도 보통 대화로 답함")
    ok(after[0] == before[0] + 4 and after[1] == before[1], f"기록은 늘기만 함 {before} → {after}")

    # ── 거절·빈 답·오류·시간 부족 ──
    ok(await say("r1", "u1", "REFUSE 해 봐") == REFUSAL_TEXT, "거절이면 정해진 문구")
    meta = db.admin("SELECT meta FROM marong.messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1")[0][0]
    ok(meta.get("refusal") == "general_harms" and meta.get("delivered") is True, meta)
    ok(await say("r1", "u1", "EMPTY 답") == "다시 쓴 답 ✨", "빈 답이면 한 번 다시 쓰게 함")
    ok(llm.bodies[-1]["messages"][-1] == {"role": "system", "content": EMPTY_NUDGE}, "다시 쓰기 안내는 system 메시지")
    ok(await say("r1", "u1", "FAIL 해 봐") == FALLBACK_TEXT, "오류면 대체 문구")
    calls = len(llm.bodies)
    loop = asyncio.get_running_loop()
    ok(await say("r1", "u1", "늦은 말", deadline=loop.time() + 5) == LATE_TEXT and len(llm.bodies) == calls,
       "콜백 시간이 모자라면 Claude 를 부르지 않고 다시 말해 달라고 함")

    # 전달 못 한 답은 다음 대화에 넣지 않음
    async def fail_send(t):
        return False
    await say("r1", "u1", "전달 실패 시험", send_fn=fail_send)
    await say("r1", "u1", "그다음 말")
    ok("응답:전달 실패 시험" not in json.dumps(llm.bodies[-1]["messages"], ensure_ascii=False, default=str),
       "전달 못 한 답은 대화에서 뺌")

    # ── 단체방: 이름 표시, 부르는 말 ──
    await say("g1", "u1", "다들 안녕", channel=False)
    await say("g1", "u9", "마롱이 안녕", channel=False)
    b = llm.bodies[-1]
    convo = json.dumps(b["messages"], ensure_ascii=False)
    ok("동희: 다들 안녕" in convo and "친구-" in convo and "단체 채팅방" in situation(b), "단체방은 말한 친구 표시")
    ok("이름을 아직 몰라(대화에서는 '친구-" in situation(b), "단체방에서 이름 모르는 친구 표시를 알려 줌")
    trig = Agent(replace(s, group_triggers=("마롱",)), store, emb, llm)
    calls = len(llm.bodies)
    r = await trig.handle(Incoming("g2", "u1", "오늘 뭐해", is_channel=False), send)
    ok(r is None and len(llm.bodies) == calls, "GROUP_TRIGGER: 부르지 않으면 저장만")
    r = await trig.handle(Incoming("g2", "u1", "마롱아 오늘 뭐해", is_channel=False), send)
    ok(r is not None and "오늘 뭐해\\n" in json.dumps(llm.bodies[-1]["messages"], ensure_ascii=False),
       "부르면 앞의 말까지 보고 답함")
    ok("태그한 메시지만" in situation(llm.bodies[-1]) and "태그 없이 한 말은 마롱이가 못 봐" in situation(llm.bodies[-1]),
       "단체방은 태그한 말만 온다고 알려 줌(태그 안 해도 된다고 하지 않게)")

    # 단체방에서 태그만 하면 카카오가 태그 글자를 빼서 빈 글로 옴 → 부른 것으로 받음. 1:1 빈 글은 그대로
    calls = len(llm.bodies)
    r = await say("g1", "u1", "  ", channel=False)
    ok(r == f"응답:동희: {CALLED_TEXT}" and len(llm.bodies) == calls + 1, f"태그만 → 부른 것으로 답함: {r}")
    ok(db.admin("SELECT content FROM marong.messages WHERE room_key = 'g1' AND role = 'user' ORDER BY id DESC LIMIT 1")
       == [(CALLED_TEXT,)], "태그만 한 말은 '@마롱이'로 저장")
    ok(await trig.handle(Incoming("g2", "u1", "", is_channel=False), send) is not None, "GROUP_TRIGGER 가 '마롱'이어도 태그만 하면 답함")
    ok(await say("r6", "u6", "") == EMPTY_TEXT and len(llm.bodies) == calls + 2, "1:1 빈 글은 다시 보내 달라고 함")
    ok(agent.answers(Incoming("g2", "u1", "오늘 뭐해", is_channel=False))
       and not trig.answers(Incoming("g2", "u1", "오늘 뭐해", is_channel=False))
       and not agent.answers(Incoming("r6", "u6", "")), "answers: 답할 말인지")

    # 연달아 온 말: 뒤에 답할 말이 더 왔으면 저장만 하고, 마지막 말에 한 번에 답함
    calls = len(llm.bodies)
    r = await agent.handle(Incoming("r7", "u7", "첫 마디", kakao_id="b1"), send, superseded=lambda: True)
    ok(r is None and len(llm.bodies) == calls, "뒤에 말이 더 왔으면 답하지 않음(Claude 도 안 부름)")
    ok(db.admin("SELECT content FROM marong.messages WHERE room_key = 'r7'") == [("첫 마디",)], "그래도 저장은 함")
    r = await agent.handle(Incoming("r7", "u7", "둘째 마디", kakao_id="b2"), send, superseded=lambda: False)
    last = llm.bodies[-1]["messages"][-1]["content"]
    ok(r == "응답:둘째 마디" and "첫 마디" in last and last.endswith("둘째 마디"), f"마지막 말에 앞 말까지 묶어 답함: {last}")
    waiting = Agent(replace(s, reply_wait_s=0.3), store, emb, llm)
    later = {"v": False}
    asyncio.get_running_loop().call_later(0.1, later.__setitem__, "v", True)
    calls = len(llm.bodies)
    r = await waiting.handle(Incoming("r7", "u7", "셋째", kakao_id="b3"), send, superseded=lambda: later["v"])
    ok(r is None and len(llm.bodies) == calls, "답하기 전에 잠깐 기다리는 사이 말이 더 오면 묶음")
    t0 = asyncio.get_running_loop().time()
    r = await waiting.handle(Incoming("r7", "u7", "넷째", kakao_id="b4"), send, superseded=lambda: False)
    ok(r == "응답:넷째" and asyncio.get_running_loop().time() - t0 >= 0.3, "더 안 오면 기다렸다가 답함")
    # 묶은 말이 최근 대화 길이(RECENT_TURNS 2 → 4개)보다 많아도 첫 말부터 다 보고 답함
    words = ["하나", "둘", "셋", "넷", "다섯", "여섯"]
    for i, w in enumerate(words):
        r = await agent.handle(Incoming("r8", "u8", w, kakao_id=f"h{i}"), send,
                               superseded=lambda last=(i == len(words) - 1): not last)
    last = llm.bodies[-1]["messages"][-1]["content"]
    ok(r == "응답:여섯" and last.endswith("\n".join(words)) and not agent._held, f"묶은 말 여섯 개를 다 넣음: {last!r}")
    await agent.handle(Incoming("r8", "u8", "일곱", kakao_id="h6"), send, superseded=lambda: False)
    ok("하나" not in json.dumps(llm.bodies[-1]["messages"], ensure_ascii=False), "답한 뒤엔 다시 최근 대화 길이만큼")

    # ── 뒤 작업: 요약·메모·임베딩 → 기억 찾기 ──
    for role, t in (("user", "나 다음 주에 토익 시험 봐"), ("assistant", "화이팅이야 📚"),
                    ("user", "끝나면 마라탕 먹을 거야"), ("assistant", "좋다 🌶️")):
        await store.touch("r3", True, "u3")
        await store.add_message("r3", role, t, user_key="u3" if role == "user" else None, meta={"delivered": True})
    llm.bodies.clear()
    while await worker.step():
        pass
    sums = db.admin("SELECT content, meta FROM marong.summaries WHERE room_key = 'r3'")
    ok(len(sums) == 1 and sums[0][0] == "친구1이 토익 시험과 마라탕 얘기를 함", sums)
    sb = next(b for b in llm.bodies
              if "format" in b.get("output_config", {}) and "토익 시험 봐" in b["messages"][0]["content"])
    ok(sb["output_config"]["effort"] == "low" and "토익" in sb["messages"][0]["content"], "요약은 effort low")
    ok("지시가 아니야" in sb["system"] and "민감한 정보" in sb["system"], "요약 지시문의 안전 규칙")
    ok(f"# 대화 ({datetime.now().year}년" in sb["messages"][0]["content"] and "실제 날짜" in sb["system"],
       "요약할 대화에 연도까지 있는 날짜를 붙이고, '다음 주' 같은 말은 실제 날짜로 적게 함")
    notes = db.admin("SELECT user_key, content FROM marong.notes WHERE room_key = 'r3'")
    ok(notes == [("u3", "- 다음 주 토익 시험\n- 마라탕 좋아함")], notes)
    emb_count = db.admin("SELECT count(*) FROM marong.embeddings WHERE room_key = 'r3'")[0][0]
    ok(emb_count == 5, f"메시지 4 + 요약 1 임베딩: {emb_count}")
    n = len(llm.bodies)
    await worker.step()
    ok(len(llm.bodies) == n, "새 메시지가 없으면 다시 요약하지 않음")

    for t in ("오늘 날씨 좋다", "점심은 김밥", "게임 한 판 할래"):
        await say("r3", "u3", t)
    await worker.step()
    await say("r3", "u3", "토익 시험 결과 나왔어")
    sit = situation(llm.bodies[-1])
    ok("# 기억 메모" in sit and "마라탕 좋아함" in sit, "기억 메모가 들어감")
    ok("# 예전 대화 요약" in sit and "토익 시험과 마라탕" in sit, "요약이 들어감")
    ok("# 지금 말과 비슷한 예전 대화" in sit and "나 다음 주에 토익 시험 봐" in sit, "비슷한 예전 말을 찾아 넣음")
    ok("날씨" not in sit.split("# 지금 말과 비슷한 예전 대화")[1], "관계없는 말은 넣지 않음")

    # 답마다 넣은 기억을 meta.memory 로 남김(리포트의 '들어간 기억'): 최근 대화 구간, 요약·메모 id, 찾은 후보와 넣은 것
    def memory_of(room):
        return db.admin("SELECT meta->'memory' FROM marong.messages WHERE room_key = %s AND role = 'assistant' "
                        "ORDER BY id DESC LIMIT 1", (room,))[0][0]

    mem = memory_of("r3")
    asked = db.admin("SELECT max(id) FROM marong.messages WHERE room_key = 'r3' AND role = 'user'")[0][0]
    toeic = db.admin("SELECT id FROM marong.messages WHERE room_key = 'r3' AND content = '나 다음 주에 토익 시험 봐'")[0][0]
    shown = [r[0] for r in db.admin("SELECT id FROM marong.summaries WHERE room_key = 'r3' AND content <> '' "
                                    "ORDER BY last_id")]
    note = db.admin("SELECT max(id) FROM marong.notes WHERE room_key = 'r3'")[0][0]
    ok(mem["recall"] == "ok" and mem["recent"][1] == asked and mem["summaries"] == shown[-3:] and shown
       and mem["notes"] == [note] and mem["friends"] == [], mem)
    ok(any(h["type"] == "message" and h["id"] == toeic for h in mem["recalled"])
       and all(h in mem["candidates"] for h in mem["recalled"])
       and all(isinstance(h["similarity"], float) for h in mem["candidates"]), f"찾은 후보와 실제로 넣은 것: {mem}")
    first = db.admin("SELECT meta->'memory' FROM marong.messages WHERE room_key = 'r1' AND role = 'assistant' "
                     "ORDER BY id LIMIT 1")[0][0]
    ok(first["recall"] == "short" and first["candidates"] == [] and first["recalled"] == [],
       f"짧은 말('안녕')로는 예전 대화를 찾지 않았다고 남김: {first}")

    # 다른 방의 기억은 섞이지 않음
    await say("r4", "u3", "토익 시험 얘기 기억나?")
    sit = situation(llm.bodies[-1])
    ok("마라탕" not in sit and "토익 시험 봐" not in sit, "다른 방(1:1 ↔ 단체방)의 기억은 안 보임")

    # 요약 거절 → 빈 요약으로 넘김(임베딩·화면에서 빠짐), 형식이 깨지면 한 번 더 해 보고 넘김
    for i in range(4):
        await store.touch("r5", True, "u5")
        await store.add_message("r5", "user", "REFUSE_SUM 메시지" if i == 0 else f"보통 메시지 {i}", user_key="u5")
    await worker.step()
    ok(db.admin("SELECT content, meta->>'skipped' FROM marong.summaries WHERE room_key = 'r5'") == [("", "refusal")],
       "요약 거절 → 빈 요약")
    ok(db.admin("SELECT count(*) FROM marong.embeddings e JOIN marong.summaries s ON e.source_type = 'summary' "
                "AND e.source_id = s.id WHERE s.room_key = 'r5'")[0][0] == 0, "빈 요약은 임베딩하지 않음")
    for i in range(4):
        await store.add_message("r5", "user", "BAD_JSON 메시지" if i == 0 else f"다음 메시지 {i}", user_key="u5")
    try:
        await worker.step()
        ok(False, "첫 번째 형식 오류는 다시 시도해야 함")
    except BadOutput:
        ok(True, "형식 오류 1번째 → 다시 시도")
    await worker.step()
    ok(db.admin("SELECT count(*) FROM marong.summaries WHERE room_key = 'r5' AND content = ''")[0][0] == 2,
       "형식 오류 2번째 → 빈 요약으로 넘김")

    # ── 기억 넉넉하게(2026-11-16, Notion RAG 연구: 필받음 6장 최근 15턴, M10 낱말+임베딩+RRF·짧은 되물음,
    #    R04 최소 관련성·임베딩 1.5초 넘으면 낱말만, LangGraph 실측 원문 문답 쌍) ──
    from marong.store import keyword_terms, pick_recent
    ok(keyword_terms("뭔코트? 울 코트 Musinsa 2만원 ㅋㅋ") == ["뭔코", "코트", "musinsa", "만원"],
       "낱말 조각: 한글은 두 글자씩, 영문은 낱말, 한 글자·자모는 뺌")
    ok(replace(s, reply_turns=0).problems() and replace(s, reply_max_rows=1).problems(), "REPLY_TURNS·REPLY_MAX_ROWS 검사")

    def turns(spec):  # u 친구, a 마롱이 답, p 선톡. id 는 1부터
        return [{"id": i + 1, "role": "user" if c == "u" else "assistant", "proactive": c == "p"}
                for i, c in enumerate(spec)]

    def ids(rows):
        return [r["id"] for r in rows]

    convo = turns("uapuappppu")  # 3번 선톡엔 친구가 답함, 6~9번 선톡 넷 중 6번은 답 없이 묻힘
    ok(ids(pick_recent(convo, 3, 60)) == [1, 2, 3, 4, 5, 7, 8, 9, 10], "답 없는 선톡은 최근 3개만, 답한 선톡은 남김")
    ok(ids(pick_recent(convo, 2, 60)) == [4, 5, 7, 8, 9, 10], "친구 말 turns 번까지만 거슬러 올라감")
    ok(ids(pick_recent(convo, 3, 4)) == [7, 8, 9, 10], "그래도 한도를 넘으면 오래된 줄부터 뺌")
    ok(ids(pick_recent(convo, 1, 2, since_id=4)) == [4, 5, 6, 7, 8, 9, 10], "묶어 답할 첫 말부터는 한도와 상관없이 다 넣음")
    ok(ids(pick_recent(turns("ua" + "p" * 40), 15, 60)) == [1, 2, 40, 41, 42],
       "선톡 40개가 몰려도 친구와 나눈 말이 남음(11/16 최근 20줄이 다 선톡이던 일)")

    # 짧은 되물음('뭔코트?')은 앞 말을 붙여 낱말로도 찾고, 찾은 친구 말은 마롱이 답과 한 쌍으로 넣음.
    # 임베딩이 1.5초를 넘기면 그 답에서는 낱말 검색만 씀
    class SlowEmbeddings(FakeEmbeddings):
        async def query(self, s):
            await asyncio.sleep(3)
            return self.vec(s)

    await store.touch("r11", True, "u11")

    async def put(role, t, room="r11", user="u11", meta=None):
        await store.add_message(room, role, t, user_key=user if role == "user" else None,
                                meta=meta or {"delivered": True})

    await put("user", "마롱아 안녕")
    await put("assistant", "안녕! 반가워")
    await put("user", "나 요즘 울 코트 하나 사고 싶어")
    await put("assistant", "울 코트 사고 싶으면 베이지색이 예쁘던데 같이 골라 볼까?")
    for _ in range(60):
        await put("user", "ㅋㅋㅋ")
        await put("assistant", "ㅎㅎ")
    await put("user", "오늘 쇼핑몰 갔다 왔어")
    await put("assistant", "오 그때 사고 싶다던 거 샀어?")
    t0 = asyncio.get_running_loop().time()
    await Agent(s, store, SlowEmbeddings(), llm).handle(Incoming("r11", "u11", "마롱아 뭔코트?"), send)
    sit = situation(llm.bodies[-1])
    recalled_part = sit.split("# 지금 말과 비슷한 예전 대화")[1] if "# 지금 말과 비슷한 예전 대화" in sit else ""
    ok("울 코트 하나 사고 싶어" in recalled_part and "\n  마롱이: 울 코트 사고 싶으면" in recalled_part
       and recalled_part.count("베이지색") == 1,
       f"짧은 되물음으로 예전 친구 말과 마롱이 답을 한 쌍으로 찾음(둘 다 찾혀도 한 번만): {recalled_part!r}")
    ok("마롱아 안녕" not in recalled_part, "'마롱아'처럼 부르는 말로는 예전 대화를 찾지 않음")
    mem = memory_of("r11")
    coat, beige = (db.admin("SELECT id FROM marong.messages WHERE room_key = 'r11' AND content = %s", (t,))[0][0]
                   for t in ("나 요즘 울 코트 하나 사고 싶어", "울 코트 사고 싶으면 베이지색이 예쁘던데 같이 골라 볼까?"))
    hit = next((h for h in mem["recalled"] if h["id"] == coat), None)
    ok(mem["recall"] == "slow" and hit and hit["similarity"] is None and hit["keyword"] > 0 and hit["pair"] == beige
       and asyncio.get_running_loop().time() - t0 < 3, f"임베딩이 늦으면 낱말 검색만(R04): {mem}")

    # 선톡 표시(meta.proactive)를 DB 에서 읽어, 답 없는 선톡은 최근 3개만 넣고 앞의 친구 말은 남김
    roomy = Agent(replace(s, reply_turns=15, reply_max_rows=60), store, emb, llm)
    await store.touch("r12", True, "u12")
    await put("user", "내일 영어 시험이라 떨려", room="r12", user="u12")
    await put("assistant", "잘 볼 거야! 끝나고 뭐 먹을래?", room="r12")
    for i in range(6):
        await put("assistant", f"선톡 {i}번", room="r12", meta={"delivered": True, "proactive": True})
    await roomy.handle(Incoming("r12", "u12", "아 미안 이제 봤어"), send)
    convo = json.dumps(llm.bodies[-1]["messages"], ensure_ascii=False)
    ok("영어 시험" in convo and all(f"선톡 {i}번" in convo for i in (3, 4, 5))
       and not any(f"선톡 {i}번" in convo for i in (0, 1, 2)), f"답 없는 선톡은 최근 3개만: {convo}")

    # 요약할 때 선톡은 '마롱이(먼저 보낸 말)'로 따로 보여 줘서 답 없는 선톡을 한 줄로 줄이게 함
    llm.bodies.clear()
    while await worker.step():
        pass
    told = [b["messages"][0]["content"] for b in llm.bodies
            if "format" in b.get("output_config", {}) and "선톡 0번" in b["messages"][0]["content"]]
    ok(told and "마롱이(먼저 보낸 말): 선톡 0번" in told[0], f"요약에서 선톡 구분: {told}")
    from marong.memory import NOTE_RULE, SUMMARY_SYSTEM
    ok("먼저 보낸 말" in SUMMARY_SYSTEM and "답 없음" in SUMMARY_SYSTEM and "약속" in SUMMARY_SYSTEM,
       "요약 지시문: 남길 것(약속·부탁 등)을 적고, 답 없는 선톡은 한 줄로")
    ok("예전엔" in NOTE_RULE and "들은 날" in NOTE_RULE, "메모: 바뀐 취향은 지우지 말고 고쳐 적고 들은 날을 붙임")

    # ── 기록 보기(tools/admin.py, 읽기만) ──
    def admin(*args):
        env = {**os.environ, "DATABASE_URL": db.app_url, "PYTHONIOENCODING": "utf-8"}
        p = subprocess.run([sys.executable, str(ROOT / "tools" / "admin.py"), *args],
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        return p.returncode, p.stdout + p.stderr

    def short(k):
        return "#" + hashlib.sha1(k.encode()).hexdigest()[:8]

    code, out = admin("people")
    ok(code == 0 and "동희" in out and "(이름 모름)" in out, out)
    code, out = admin("rooms")
    r1_line = next((line for line in out.splitlines() if line.startswith(short("r1"))), "")
    ok(code == 0 and "단체" in out and r1_line.endswith("  동희"), f"방 목록(마롱이 답은 친구로 안 셈): {out}")
    code, out = admin("show", "동희", "6")
    ok(code == 0 and "동희: 그다음 말" in out and "(전달 안 됨)" in out and "마롱이: " in out, out)
    code, out = admin("show", short("u3"))
    ok(code == 0 and "[기억 메모" in out and "마라탕 좋아함" in out, out)
    code, out = admin("stats")
    ok(code == 0 and "messages" in out and "최근 7일" in out, out)
    code, out = admin()
    ok(code == 1 and "people" in out, "명령이 없으면 사용법")

    # 임베딩 모델이 아직 안 떴으면 찾지 않았다고 남김
    cold = FakeEmbeddings()
    cold.ready = False
    await Agent(s, store, cold, llm).handle(Incoming("r10", "u10", "임베딩 모델이 아직 안 떴을 때"), send)
    mem = memory_of("r10")
    ok(mem["recall"] == "off" and mem["candidates"] == [] and len(mem["recent"]) == 2, mem)

    # 저장소가 죽어 있어도 답은 함(기억 없이)
    dead = Store("postgresql://marong@127.0.0.1:1/marong?connect_timeout=1", timeout=1)
    await dead.open(wait=False)
    lonely = Agent(s, dead, emb, llm)
    r = await lonely.handle(Incoming("r9", "u9", "DB 없이 말"), send)
    ok(r == "응답:DB 없이 말", f"DB 없이도 답함: {r}")
    await dead.close()

    await store.close()
    db.close()
    print(f"memory: all {CHECKS} checks passed")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    asyncio.run(main(), **options)
