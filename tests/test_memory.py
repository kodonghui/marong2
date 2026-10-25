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


def respond(body):
    return summary_reply(body) if "format" in body.get("output_config", {}) else chat_reply(body)


async def main():
    db = TestDB()
    tmp = Path(tempfile.mkdtemp())
    os.environ.update({
        "BOT_TOKEN": "t", "ANTHROPIC_API_KEY": "k", "DATABASE_URL": db.app_url,
        "PROMPT_PATH": str(ROOT / "prompt.md"), "KNOWLEDGE_DIR": str(tmp / "knowledge"),
        "RECENT_TURNS": "2", "SUMMARY_TURNS": "2", "EMBED_MODEL": "fake-bigram",
    })
    from marong.agent import (EMPTY_NUDGE, FALLBACK_TEXT, LATE_TEXT, REFUSAL_TEXT, Agent, Incoming, clean_name)
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
    ok(await store.schema_version() == 1, "표 버전")
    ok(await store.can_delete() is False, "봇 계정은 기록을 지우거나 고칠 수 없음(can_delete)")
    ok(clean_name("  동희  ") == "동희" and clean_name("") == "" and clean_name("가" * 21) == "", "이름 다듬기")

    # 봇 계정으로 지우기·고치기·비우기·표 지우기를 직접 해 봐도 모두 막힘
    await say("r1", "u1", "안녕", kakao_id="k1")
    for sql in ("DELETE FROM marong.messages", "UPDATE marong.messages SET content = 'x'",
                "TRUNCATE marong.messages", "DELETE FROM marong.people", "DELETE FROM marong.summaries",
                "DROP TABLE marong.messages", "UPDATE marong.notes SET content = 'x'"):
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
    ok(b["system"][0]["cache_control"] == {"type": "ephemeral"} and "마롱이" in b["system"][0]["text"],
       "말투 지시문은 캐시 블록")
    ok("이름을 아직 몰라" in situation(b) and "1:1" in situation(b), "이름 모를 때 물어보라고 알려 줌")
    ok("다시 묻지 말고" in situation(b) and "조르지 말고" in b["system"][0]["text"], "이름은 한 번만 묻고 조르지 않음")
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
