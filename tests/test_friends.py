"""친구들(서로 아는 사이) 시험: 진짜 Postgres + 가짜 Claude.
키 묶기(같은 이름·사람마다 1:1 키 하나·터미널 키·이름 바꾸기·옛 기록 묶기), 아는 사이(같은 단체방·말해 준 사이),
공유 메모(방별 메모 거르기·비밀 빼기·바뀌면 다시 거르기·거절·형식 오류), 다른 방 원문·요약·메모가 안 새는지,
도구(add_friendship·set_share), 선톡에는 친구 얘기 없음, 관리 명령(friends·link·unlink·share), 로그에 내용 없음.
실행(윈도우): .venv\\Scripts\\python tests\\test_friends.py   (리눅스·맥: .venv/bin/python tests/test_friends.py)"""
import asyncio
import hashlib
import itertools
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from fakes import FakeEmbeddings, ScriptedLLM, message, text, tool_use  # noqa: E402
from pg import TestDB  # noqa: E402

CHECKS = 0
LOGS: list[str] = []
LONG = "아주 긴 취미 설명 " * 8  # 60자를 넘는 공유 메모 한 줄


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def situation(body) -> str:
    return body["system"][-1]["text"]


def friends_part(body) -> str:
    """지금 상황에서 '마롱이가 아는 다른 친구들' 부분만."""
    sit = situation(body)
    return sit.split("# 마롱이가 아는 다른 친구들", 1)[1] if "# 마롱이가 아는 다른 친구들" in sit else ""


def chat_reply(body):
    """가짜 Claude(답장): 표시에 따라 도구를 부르고, 도구 결과를 그대로 답해서 시험에서 확인한다."""
    last = body["messages"][-1]
    if isinstance(last["content"], list):
        return message([text("도구:" + last["content"][0]["content"])])
    said = last["content"].splitlines()[-1]
    m = re.search(r"내 이름은 (\S+)", said)
    if m:
        return message([tool_use("set_name", {"name": m.group(1)})], "tool_use")
    m = re.search(r"사이:([^:]+):(.+)$", said)
    if m:
        return message([tool_use("add_friendship", {"name": m.group(1), "label": m.group(2)})], "tool_use")
    if "공유끄기" in said:
        return message([tool_use("set_share", {"on": False})], "tool_use")
    if "공유켜기" in said:
        return message([tool_use("set_share", {"on": True})], "tool_use")
    return message([text("응 😆")])


def summary_reply(body):
    """가짜 Claude(요약): 친구가 '메모:a|b' 로 말한 것을 그 친구의 이 방 메모로, 친구 말 전부를 요약으로."""
    said: dict[str, list[str]] = {}
    for line in body["messages"][0]["content"].splitlines():
        m = re.match(r"\[[^\]]+\] (친구\d+)\([^)]*\): (.*)$", line)
        if m:
            said.setdefault(m.group(1), []).append(m.group(2))
    notes = []
    for tag, texts in said.items():
        items = [x for t in texts if t.startswith("메모:") for x in t[3:].split("|")]
        if items:
            notes.append({"who": tag, "note": "\n".join("- " + x for x in items)})
    summary = "요약: " + " / ".join(t for texts in said.values() for t in texts)
    return message([text(json.dumps({"summary": summary[:500], "notes": notes}, ensure_ascii=False))])


def share_reply(body):
    """가짜 Claude(공유 메모): 메모 줄을 거의 다 돌려줌. '우울'만 빼고 '(비밀)'·중복·긴 줄은 그대로(코드가 걸러야 함)."""
    content = body["messages"][0]["content"]
    if "REFUSE_SHARE" in content:
        return message([], "refusal")
    if "BAD_SHARE" in content:
        return message([text("json 아님")])
    items = [line[2:] for line in content.splitlines() if line.startswith("- ") and "우울" not in line]
    if items:
        items.append("- " + items[0])
    return message([text(json.dumps({"items": items}, ensure_ascii=False))])


def respond(body):
    fmt = body.get("output_config", {}).get("format")
    if not fmt:
        return chat_reply(body)
    return share_reply(body) if "items" in fmt["schema"]["properties"] else summary_reply(body)


def is_share(body) -> bool:
    fmt = body.get("output_config", {}).get("format")
    return bool(fmt) and "items" in fmt["schema"]["properties"]


class Collect(logging.Handler):
    def emit(self, record):
        LOGS.append(record.getMessage())


async def main():
    db = TestDB()
    tmp = Path(tempfile.mkdtemp())
    os.environ.update({
        "BOT_TOKEN": "t", "ANTHROPIC_API_KEY": "k", "DATABASE_URL": db.app_url,
        "PROMPT_PATH": str(ROOT / "prompt.md"), "KNOWLEDGE_DIR": str(tmp / "knowledge"),
        "RECENT_TURNS": "2", "SUMMARY_TURNS": "2", "EMBED_MODEL": "fake-bigram",
    })
    os.environ.pop("PROACTIVE", None)
    from marong.agent import Agent, Incoming
    from marong.config import load_settings
    from marong.memory import BadOutput, MemoryWorker
    from marong.store import Store

    s = load_settings()
    store = Store(s.database_url)
    await store.open(wait=True)
    llm = ScriptedLLM(respond)
    agent = Agent(s, store, FakeEmbeddings(), llm)
    worker = MemoryWorker(s, store, FakeEmbeddings(), llm)
    kids = itertools.count(1)

    async def send(t):
        return True

    async def say(room, user, t, channel=True, kakao=True):
        kid = f"kid-{next(kids)}" if kakao else None
        return await agent.handle(Incoming(room, user, t, is_channel=channel, kakao_id=kid), send)

    async def settle():
        while await worker.step():
            pass

    def fid(user_key):
        return db.admin("SELECT friend_id FROM marong.people WHERE user_key = %s", (user_key,))[0][0]

    def shared(friend_id):
        rows = db.admin("SELECT content, meta FROM marong.shared_notes WHERE friend_id = %s ORDER BY id DESC LIMIT 1",
                        (friend_id,))
        return rows[0] if rows else (None, None)

    def short(k):
        return "#" + hashlib.sha1(k.encode()).hexdigest()[:8]

    # 방: c1 동희 1:1(d1), c2 현경 1:1(h1), c3 이름만 같은 다른 동희 1:1(x1), g1 단체방(동희 d2·현경 h2),
    #     g2 단체방(동희라고 한 d3 혼자), term 터미널 대화(t1), c4 민수 1:1(m1)·g3 단체방(m2)은 옛 기록
    # ── 키 묶기 ──
    ok(await store.schema_version() == 3, "표 버전 3")
    await say("c1", "d1", "안녕 내 이름은 동희")
    f_dh = fid("d1")
    ok(f_dh is not None, "1:1 에서 이름을 알려 주면 친구 한 명으로 저장")
    await say("g1", "d2", "내 이름은 동희", channel=False)
    ok(fid("d2") == f_dh, "단체방 키도 이름이 같으면 같은 친구")
    await say("c2", "h1", "내 이름은 현경")
    await say("g1", "h2", "내 이름은 현경", channel=False)
    f_hk = fid("h1")
    ok(f_hk not in (None, f_dh) and fid("h2") == f_hk, "현경도 1:1·단체방 키가 한 친구")
    await say("c3", "x1", "내 이름은 동희")
    f_x = fid("x1")
    ok(f_x not in (None, f_dh), "1:1 키가 이미 있는 친구에게는 다른 1:1 키를 묶지 않음(이름만 같은 다른 사람)")
    await say("g2", "d3", "내 이름은 동희", channel=False)
    f_d3 = fid("d3")
    ok(f_d3 not in (None, f_dh, f_x), "같은 이름 친구가 여럿이면 새 친구로 둠(아무 쪽에나 묶지 않음)")
    await say("term", "t1", "내 이름은 동희", kakao=False)
    ok(fid("t1") is None, "터미널 대화 키는 묶지 않음")
    await say("c2", "h1", "내 이름은 경이")
    ok(db.admin("SELECT name FROM marong.friends WHERE id = %s", (f_hk,)) == [("경이",)], "이름을 바꾸면 친구 이름도 바뀜")
    await say("c2", "h1", "내 이름은 현경")

    # 표 버전 3 전에 이름만 저장된 옛 기록(민수 1:1·단체방)은 뒤 작업이 묶음
    for room, user, channel in (("c4", "m1", True), ("g3", "m2", False)):
        await store.touch(room, channel, user)
        await store.add_message(room, "user", "옛날 말", user_key=user, kakao_id=f"old-{user}")
    db.admin("UPDATE marong.people SET name = '민수' WHERE user_key IN ('m1', 'm2')")
    ok(await store.link_unlinked() == 2 and fid("m1") == fid("m2") is not None, "옛 기록: 이름이 같은 키를 묶음")
    f_ms = fid("m1")
    ok(await store.link_unlinked() == 0 and fid("t1") is None, "다시 돌려도 그대로(터미널 키는 계속 안 묶음)")
    ok((await store.counts())["friends"] == 5 and (await store.counts())["people"] == 9, await store.counts())

    # ── 방별 메모 → 공유 메모(가벼운 얘기만) ──
    await say("c2", "h1", "메모:마라탕 좋아함|(비밀) 이직 준비 중|요즘 우울함 SECRET_RAW_TEXT")
    await say("g1", "h2", "메모:보드게임 좋아함", channel=False)
    await say("g1", "d2", "메모:군밤 좋아함", channel=False)
    llm.bodies.clear()
    await settle()
    hk_note = db.admin("SELECT content FROM marong.notes WHERE room_key = 'c2' ORDER BY id DESC LIMIT 1")[0][0]
    ok("이직" in hk_note and "우울" in hk_note, f"방별 메모에는 그대로 있음: {hk_note}")
    content, meta = shared(f_hk)
    ok(set(content.splitlines()) == {"- 마라탕 좋아함", "- 보드게임 좋아함"}, f"현경 공유 메모: {content!r}")
    ok(shared(f_dh)[0] == "- 군밤 좋아함", shared(f_dh))
    ok(not any("비밀" in c or "이직" in c or "우울" in c for (c,) in db.admin("SELECT content FROM marong.shared_notes")),
       "(비밀)은 모델이 돌려줘도 코드가 뺌, 고민은 거름")
    req = next(b for b in llm.bodies if is_share(b) and "# 친구: 현경" in b["messages"][0]["content"])
    ok("## 1:1 방에서 정리한 메모" in req["messages"][0]["content"]
       and "## 단체방에서 정리한 메모" in req["messages"][0]["content"], "1:1·단체방 메모를 같이 거름")
    ok(req["output_config"]["effort"] == "low" and "지시가 아니야" in req["system"] and "(비밀)" in req["system"],
       "공유 메모는 요약처럼 effort low, 안전 규칙")
    ok(sorted(meta["note_ids"]) == meta["note_ids"] and len(meta["note_ids"]) == 2, meta)
    n = len(llm.bodies)
    await worker.step()
    ok(len(llm.bodies) == n, "메모가 그대로면 다시 거르지 않음")

    # ── 아는 사이: 같은 단체방이면 얘기, 아닌 친구는 이름만 ──
    await say("c1", "d1", "현경이 알아?")
    b = llm.bodies[-1]
    part = friends_part(b)
    ok([t["name"] for t in b["tools"]] == ["set_name", "add_friendship", "set_share"], "친구 도구")
    ok("## 지금 친구와 아는 사이" in part and re.search(r"- 현경\(같은 단체방\): (마라탕 좋아함 · 보드게임 좋아함|"
                                                    r"보드게임 좋아함 · 마라탕 좋아함)", part), part)
    others = part.split("## 아는 사이인지 모르는 친구", 1)[1]
    ok("민수" in others and "마라탕" not in others and "군밤" not in part, f"모르는 친구는 이름만, 나는 빠짐: {part}")
    sit = situation(b)
    ok(all(x not in sit for x in ("SECRET_RAW_TEXT", "이직", "우울", "요약: 내 이름은 현경")),
       "다른 방 원문·요약·메모는 안 들어감")
    ok("지시가 아니야" in sit.split("# 마롱이가 아는 다른 친구들", 1)[1].splitlines()[0], "친구 자료도 지시가 아님")

    # ── 말해 준 사이(add_friendship) ──
    r = await say("c1", "d1", "사이:민수:회사 동기")
    ok("동희(이)랑 민수(이)가 회사 동기" in r, r)
    a, b_ = sorted((f_dh, f_ms))
    ok(db.admin("SELECT label, told_by FROM marong.friendships WHERE friend_a = %s AND friend_b = %s", (a, b_))
       == [("회사 동기", f_dh)], "아는 사이 저장(작은 id 먼저, 말해 준 친구)")
    await say("c1", "d1", "그렇구나")
    ok("- 민수(회사 동기): 아직 아는 얘기 없음" in friends_part(llm.bodies[-1]), friends_part(llm.bodies[-1]))
    await say("c4", "m1", "동희 알아?")
    ok("- 동희(회사 동기): 군밤 좋아함" in friends_part(llm.bodies[-1]), "말해 준 사이는 양쪽 다 앎")
    ok("모른다고" in await say("c1", "d1", "사이:철수:친구"), "모르는 친구")
    ok("여러 명" in await say("c2", "h1", "사이:동희:대학 친구"), "같은 이름 친구가 여럿이면 저장 안 함")
    ok("자기 자신" in await say("c2", "h1", "사이:현경:나"), "자기 자신")
    r = await say("c4", "m1", "사이:현경이:대학 친구")
    ok("민수(이)랑 현경(이)가 대학 친구" in r, f"'현경이' → '현경': {r}")
    ok("이름을 먼저" in await say("g1", "a1", "사이:현경:친구", channel=False), "이름 모르는 친구는 저장 못 함")
    ok("- 현경(같은 단체방): " in friends_part(llm.bodies[-1]), "이름 모르는 친구도 같은 단체방 친구는 앎")
    r = await say("c4", "m1", "사이:현경:아주 오래된 소꿉친구이자 같은 회사 동기")
    ok("현경(이)가 아주 오래된 소꿉친구이자 같은 회사인 걸" in r, f"긴 관계는 20자까지: {r}")
    await say("c4", "m1", "사이:현경:대학 친구")
    await say("c4", "m1", "그래서")
    ok("- 현경(대학 친구): " in friends_part(llm.bodies[-1]), "다시 말하면 관계를 고침")
    db.admin("UPDATE marong.friendships SET label = NULL WHERE friend_a = %s AND friend_b = %s", (a, b_))
    await say("c1", "d1", "관계 없이")
    ok("- 민수(아는 사이): " in friends_part(llm.bodies[-1]), "관계가 비어도 말해 준 사이는 아는 사이")

    # ── 공유 끄기·켜기(set_share) ──
    ok("껐어" in await say("c4", "m1", "공유끄기"), "공유 끄기")
    ok(db.admin("SELECT share FROM marong.friends WHERE id = %s", (f_ms,)) == [(False,)], "share=false")
    await say("c1", "d1", "민수는?")
    ok("민수" not in friends_part(llm.bodies[-1]), "공유를 끈 친구는 이름도 안 나옴")
    await say("c4", "m1", "그냥")
    ok("하지 말라고 했어" in situation(llm.bodies[-1]) and "- 동희(아는 사이)" in friends_part(llm.bodies[-1]),
       "끈 친구에게는 알려 주고, 그 친구는 다른 친구 얘기를 계속 들음")
    ok("켰어" in await say("c4", "m1", "공유켜기"), "공유 켜기")
    await say("c1", "d1", "민수는?")
    ok("- 민수(" in friends_part(llm.bodies[-1]), "다시 켜면 나옴")
    ok("이름을 모르는" in await say("g1", "a1", "공유끄기", channel=False), "이름 모르는 친구는 원래 공유 안 함")

    # ── 메모가 바뀌면 다시 거름, 거절·형식 오류는 빈 공유 메모로 ──
    await say("c2", "h1", "메모:등산 좋아함")
    await say("c2", "h1", "요즘 날씨 좋다")
    await settle()
    ok("- 등산 좋아함" in shared(f_hk)[0].splitlines(), f"새 메모 → 다시 거름: {shared(f_hk)}")
    await say("c4", "m1", "메모:REFUSE_SHARE 낚시 좋아함")
    await say("c4", "m1", "그래")
    await settle()
    ok(shared(f_ms)[0] == "" and shared(f_ms)[1].get("skipped") == "refusal", f"거절 → 빈 공유 메모: {shared(f_ms)}")
    await say("c3", "x1", "메모:BAD_SHARE 캠핑 좋아함")
    await say("c3", "x1", "응")
    try:
        await settle()
        ok(False, "첫 형식 오류는 다시 시도해야 함")
    except BadOutput:
        ok(True, "형식 오류 1번째 → 다시 시도")
    await settle()
    ok(shared(f_x)[0] == "" and "JSON" in shared(f_x)[1].get("skipped", ""), f"형식 오류 2번째 → 빈 공유 메모 {shared(f_x)}")
    await say("g2", "d3", "메모:" + "|".join([LONG] + [f"취미{i}" for i in range(8)]), channel=False)
    await settle()
    lines = shared(f_d3)[0].splitlines()
    ok(len(lines) == 6 and len(lines[0]) == 62 and lines[0].endswith("…") and lines[-1] == "- 취미4",
       f"6줄까지, 한 줄 60자까지: {lines}")

    # ── 선톡에는 다른 친구 얘기를 넣지 않음 ──
    n = len(llm.bodies)
    await agent.proactive_message({"room_key": "c1", "user_key": "d1", "name": "동희",
                                   "last_said": datetime.now(timezone.utc)})
    psit = situation(llm.bodies[n])
    ok("# 마롱이가 아는 다른 친구들" not in psit and "보드게임" not in psit and "등산" not in psit, "선톡에는 친구 얘기 없음")

    # ── 관리 명령 ──
    def admin(*args):
        env = {**os.environ, "DATABASE_URL": db.app_url, "PYTHONIOENCODING": "utf-8"}
        p = subprocess.run([sys.executable, str(ROOT / "tools" / "admin.py"), *args],
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        return p.returncode, p.stdout + p.stderr

    def friend_block(out, name):
        lines, on = [], False
        for line in out.splitlines():
            if not line.startswith(" "):
                on = line.startswith(name + "  ")
            if on:
                lines.append(line)
        return "\n".join(lines)

    code, out = admin("friends")
    block = friend_block(out, "현경")
    ok(code == 0 and block.startswith("현경  공유 켬") and "    - 등산 좋아함" in block and "동희(같은 단체방)" in block
       and "민수(대학 친구)" in block and f"{short('h1')} 1:1" in block and f"{short('h2')} 단체" in block, out)
    ok("넣을 만한 게 없음" in friend_block(out, "민수") and "친구에 안 묶인 키 2개" in out, out)
    code, out = admin("people")
    ok(code == 0 and "카카오 키 10개" in out and "친구 현경" in out, out)
    code, out = admin("stats")
    ok(code == 0 and "friends 5" in out and "friendships 2" in out and "shared_notes" in out, out)

    code, out = admin("link", short("d3"), "동희")
    ok(code == 1 and "여럿이라" in out, f"같은 이름이 여럿이면 #키로: {out}")
    await say("g2", "d3", "사이:현경:사촌", channel=False)
    code, out = admin("share", short("d3"), "off")
    ok(code == 0 and db.admin("SELECT share FROM marong.friends WHERE id = %s", (f_d3,)) == [(False,)], out)
    code, out = admin("link", short("d3")[1:], short("d1"))
    ok(code == 0 and fid("d3") == f_dh and "공유 끔" in out, f"link(# 없이 써도 됨): {out}")
    ok(db.admin("SELECT share FROM marong.friends WHERE id = %s", (f_dh,)) == [(False,)], "더 조심스러운 쪽(공유 끔)을 따름")
    a, b_ = sorted((f_dh, f_hk))
    ok(db.admin("SELECT label, told_by FROM marong.friendships WHERE friend_a = %s AND friend_b = %s", (a, b_))
       == [("사촌", f_dh)], "빈 친구가 된 쪽의 '아는 사이'를 옮김")
    code, out = admin("share", short("d1"), "on")
    ok(code == 0 and db.admin("SELECT share FROM marong.friends WHERE id = %s", (f_dh,)) == [(True,)], out)
    code, out = admin("unlink", short("d3"))
    ok(code == 0 and fid("d3") not in (None, f_dh, f_d3), f"unlink → 새 친구로 따로: {out}")
    await settle()
    ok(await store.link_unlinked() == 0 and fid("d3") not in (f_dh,), "뒤 작업이 다시 묶지 않음")
    code, out = admin("unlink", short("x1"))
    ok(code == 0 and "이미 따로" in out and fid("x1") == f_x, out)
    code, out = admin("link", short("a1"), "현경")
    ok(code == 0 and fid("a1") == f_hk, out)
    code, out = admin("unlink", short("a1"))
    ok(code == 0 and fid("a1") is None, f"이름 모르는 키는 친구 없이 둠: {out}")
    code, out = admin("share", "철수", "on")
    ok(code == 1 and "없음" in out, out)
    code, out = admin("link", "동희", "현경")
    ok(code == 1 and "사용:" in out, "link 첫 칸은 #키")

    # ── 로그에는 내용·이름이 없음 ──
    joined = "\n".join(LOGS)
    ok("add_friendship user=" in joined and "set_share user=" in joined and "공유 메모 저장 friend=" in joined, "로그는 남음")
    for word in ("마라탕", "보드게임", "우울", "이직", "SECRET_RAW_TEXT", "회사 동기", "현경", "민수", "등산"):
        ok(word not in joined, f"로그에 '{word}' 없음")

    await store.close()
    db.close()
    print(f"friends: all {CHECKS} checks passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger().addHandler(Collect())
    for name in ("agent", "memory", "store"):
        logging.getLogger(name).setLevel(logging.INFO)
    options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    asyncio.run(main(), **options)
