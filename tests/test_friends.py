"""친구들(서로 아는 사이) 시험: 진짜 Postgres + 가짜 Claude.
키 묶기(새 이름만 묶고 같은 이름이면 묶기 요청·터미널 키·이름 바꾸기·옛 기록 묶기), 아는 사이(같은 단체방·관리자가 정한 사이),
공유 메모(방별 메모 거르기·비밀 빼기·가벼운 얘기와 근황 나누기·바뀌면 다시 거르기·거절·형식 오류), 다른 방 원문·요약·메모가
안 새는지, 설정은 관리자만(친구 말은 ask_owner 로 요청만 남고 공유·관계가 안 바뀜), 가까운 사이에게만 1:1 에서 근황, 관계를
지금 친구 쪽에서 보여 주기, 선톡에는 친구 얘기 없음, 관리 명령(friends·link·unlink·share·friendship), 표 버전 7 옮기기
(옛 사이는 가까운 사이 아님), 로그에 내용 없음.
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
LONG = "아주 긴 취미 설명 " * 8  # 60자를 넘는 공유 메모(가벼운 얘기) 한 줄


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
    m = re.search(r"사이:([^:]+):([^:]+?)(:close)?$", said)
    if m:
        return message([tool_use("ask_owner", {"kind": "friendship", "name": m.group(1), "label": m.group(2)})],
                       "tool_use")
    if "공유끄기" in said:
        return message([tool_use("ask_owner", {"kind": "share_off"})], "tool_use")
    if "공유켜기" in said:
        return message([tool_use("ask_owner", {"kind": "share_on"})], "tool_use")
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
    """가짜 Claude(공유 메모): 메모 줄을 거의 다 돌려줌. '근황 '으로 시작하는 줄은 close(가까운 사이에게만)로, 나머지는 items 로.
    '우울'만 빼고 '(비밀)'·중복·긴 줄·막는 낱말은 그대로(코드가 걸러야 함)."""
    content = body["messages"][0]["content"]
    if "REFUSE_SHARE" in content:
        return message([], "refusal")
    if "BAD_SHARE" in content:
        return message([text("json 아님")])
    lines = [line[2:] for line in content.splitlines() if line.startswith("- ") and "우울" not in line]
    items = [x for x in lines if not x.startswith("근황 ")]
    close = [x[3:] for x in lines if x.startswith("근황 ")]
    if items:
        items.append("- " + items[0])
    return message([text(json.dumps({"items": items, "close": close}, ensure_ascii=False))])


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
    from marong import memory
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

    def close_of(friend_id):
        """가까운 사이에게만 하는 요즘 근황(가장 최근 공유 메모)."""
        rows = db.admin("SELECT close_content FROM marong.shared_notes WHERE friend_id = %s ORDER BY id DESC LIMIT 1",
                        (friend_id,))
        return rows[0][0] if rows else None

    def last_memory(room):
        """그 방 마지막 마롱이 답에 넣은 기억 기록(meta.memory)."""
        return db.admin("SELECT meta->'memory' FROM marong.messages WHERE room_key = %s AND role = 'assistant' "
                        "ORDER BY id DESC LIMIT 1", (room,))[0][0]

    def short(k):
        return "#" + hashlib.sha1(k.encode()).hexdigest()[:8]

    def asks(user_key):
        """그 키가 대화로 남긴 요청(종류, 내용, 방)."""
        return db.admin("SELECT kind, detail, room_key FROM marong.requests WHERE user_key = %s ORDER BY id", (user_key,))

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

    # 방: c1 동희 1:1(d1), c2 현경 1:1(h1), c3 이름만 같은 다른 동희 1:1(x1), g1 단체방(동희 d2·현경 h2),
    #     g2 단체방(동희라고 한 d3 혼자), term 터미널 대화(t1), c4 민수 1:1(m1)·g3 단체방(m2)은 옛 기록
    # ── 키 묶기: 새 이름이면 새 친구로, 같은 이름 친구가 있으면 묶지 않고 묶기 요청(이름은 누구나 댈 수 있어서 관리자가 정함) ──
    ok(await store.schema_version() == 7, "표 버전 7")
    await say("c1", "d1", "안녕 내 이름은 동희")
    f_dh = fid("d1")
    ok(f_dh is not None and asks("d1") == [], "1:1 에서 처음 듣는 이름을 알려 주면 친구 한 명으로 저장")
    await say("g1", "d2", "내 이름은 동희", channel=False)
    ok(fid("d2") is None and asks("d2") == [("link", {"name": "동희"}, "g1")],
       "같은 이름 친구가 있으면 단체방 키도 바로 묶지 않고 묶기 요청으로 남김")
    await say("g1", "d2", "내 이름은 동희", channel=False)
    ok(len(asks("d2")) == 1, "같은 말을 또 하면 다시 남기지 않음")
    code, out = admin("link", short("d2"), "동희")
    ok(code == 0 and fid("d2") == f_dh, f"관리자가 묶음: {out}")
    await say("c2", "h1", "내 이름은 현경")
    await say("g1", "h2", "내 이름은 현경", channel=False)
    f_hk = fid("h1")
    ok(f_hk not in (None, f_dh) and fid("h2") is None, "현경 단체방 키도 요청만")
    code, out = admin("link", short("h2"), "현경")
    ok(code == 0 and fid("h2") == f_hk, out)
    await say("c3", "x1", "내 이름은 동희")
    ok(fid("x1") is None and asks("x1") == [("link", {"name": "동희"}, "c3")],
       "1:1 키도 같은 이름 친구가 있으면 묶지 않음(이름만 대서 남의 친구 자리에 못 들어감)")
    code, out = admin("unlink", short("x1"))
    f_x = fid("x1")
    ok(code == 0 and f_x not in (None, f_dh) and "새 친구로 따로" in out, f"이름만 같은 다른 사람은 관리자가 따로 둠: {out}")
    await say("g2", "d3", "내 이름은 동희", channel=False)
    ok(fid("d3") is None and asks("d3") == [("link", {"name": "동희"}, "g2")], "같은 이름 친구가 여럿이어도 묶지 않음")
    code, out = admin("unlink", short("d3"))
    f_d3 = fid("d3")
    ok(code == 0 and f_d3 not in (None, f_dh, f_x), out)
    await say("term", "t1", "내 이름은 동희", kakao=False)
    ok(fid("t1") is None and asks("t1") == [], "터미널 대화 키는 묶지 않고 요청도 안 남김")
    await say("c2", "h1", "내 이름은 경이")
    ok(db.admin("SELECT name FROM marong.friends WHERE id = %s", (f_hk,)) == [("경이",)], "이름을 바꾸면 친구 이름도 바뀜")
    await say("c2", "h1", "내 이름은 현경")

    # 표 버전 3 전에 이름만 저장된 옛 기록(민수 1:1·단체방)은 뒤 작업이 묶음
    for room, user, channel in (("c4", "m1", True), ("g3", "m2", False)):
        await store.touch(room, channel, user)
        await store.add_message(room, "user", "옛날 말", user_key=user, kakao_id=f"old-{user}")
    db.admin("UPDATE marong.people SET name = '민수' WHERE user_key IN ('m1', 'm2')")
    ok(await store.link_unlinked() == 1 and fid("m1") is not None and fid("m2") is None
       and asks("m2") == [("link", {"name": "민수"}, None)], "옛 기록: 처음 이름은 묶고, 같은 이름 키는 묶기 요청만")
    ok(await store.link_unlinked() == 0 and len(asks("m2")) == 1, "다시 돌려도 요청을 또 남기지 않음")
    f_ms = fid("m1")
    code, out = admin("link", short("m2"), "민수")
    ok(code == 0 and fid("m2") == f_ms, out)
    ok(await store.link_unlinked() == 0 and fid("t1") is None, "다시 돌려도 그대로(터미널 키는 계속 안 묶음)")
    ok((await store.counts())["friends"] == 5 and (await store.counts())["people"] == 9, await store.counts())

    # ── 방별 메모 → 공유 메모(아는 친구 누구에게나 하는 가벼운 얘기 + 가까운 사이에게만 하는 근황) ──
    await say("c2", "h1", "메모:마라탕 좋아함|(비밀) 이직 준비 중|요즘 우울함 SECRET_RAW_TEXT|토익 시험 끝나면 마라탕 먹으러 갈 계획"
                          "|근황 팀장 때문에 야근이 잦음|근황 (비밀) 지역 옮긴 게 힘듦|근황 다이어트 중 48kg 목표|근황 다음 달 시험 준비 중")
    await say("g1", "h2", "메모:보드게임 좋아함", channel=False)
    await say("g1", "d2", "메모:군밤 좋아함", channel=False)
    llm.bodies.clear()
    await settle()
    hk_note = db.admin("SELECT content FROM marong.notes WHERE room_key = 'c2' ORDER BY id DESC LIMIT 1")[0][0]
    ok("이직" in hk_note and "우울" in hk_note, f"방별 메모에는 그대로 있음: {hk_note}")
    content, meta = shared(f_hk)
    ok(set(content.splitlines()) == {"- 마라탕 좋아함", "- 보드게임 좋아함"}, f"현경 공유 메모: {content!r}")
    ok(close_of(f_hk) == "- 팀장 때문에 야근이 잦음\n- 다음 달 시험 준비 중",
       f"근황: 고민·시험은 넣고 (비밀)·몸무게·다이어트는 모델이 돌려줘도 코드가 뺌: {close_of(f_hk)!r}")
    ok(shared(f_dh)[0] == "- 군밤 좋아함" and close_of(f_dh) == "", shared(f_dh))
    ok(not any(x in c for (c,) in db.admin("SELECT content FROM marong.shared_notes") for x in ("비밀", "이직", "우울", "토익",
                                                                                              "팀장", "시험")),
       "가벼운 얘기: (비밀)·시험·고민은 모델이 돌려줘도 코드가 뺌")
    ok(not any(x in c for (c,) in db.admin("SELECT close_content FROM marong.shared_notes") for x in ("비밀", "다이어트", "48kg")),
       "근황에도 (비밀)·몸 얘기는 없음")
    req = next(b for b in llm.bodies if is_share(b) and "# 친구: 현경" in b["messages"][0]["content"])
    ok("## 1:1 방에서 정리한 메모" in req["messages"][0]["content"]
       and "## 단체방에서 정리한 메모" in req["messages"][0]["content"], "1:1·단체방 메모를 같이 거름")
    ok(req["output_config"]["effort"] == "low" and "지시가 아니야" in req["system"] and "(비밀)" in req["system"],
       "공유 메모는 요약처럼 effort low, 안전 규칙")
    ok(sorted(meta["note_ids"]) == meta["note_ids"] and len(meta["note_ids"]) == 2, meta)
    n = len(llm.bodies)
    await worker.step()
    ok(len(llm.bodies) == n, "메모가 그대로면 다시 거르지 않음")
    ok(meta["rules"] == memory.SHARE_RULES, meta)
    with_notes = {x["friend_id"] for x in await store.friend_notes()}
    memory.SHARE_RULES = "바뀐 규칙"
    await worker.step()
    ok(sum(is_share(b) for b in llm.bodies[n:]) == len(with_notes) == 2 and shared(f_hk)[1]["rules"] == "바뀐 규칙",
       "거르는 규칙이 바뀌면 메모가 그대로여도 모든 친구를 다시 거름")

    # ── 아는 사이: 같은 단체방이면 얘기, 아닌 친구는 이름만 ──
    await say("c1", "d1", "현경이 알아?")
    b = llm.bodies[-1]
    part = friends_part(b)
    ok([t["name"] for t in b["tools"]] == ["set_name", "ask_owner"], "설정을 바꾸는 도구는 없음(요청만 남김)")
    ok("## 지금 친구와 아는 사이" in part and re.search(r"- 현경\(같은 단체방\): (마라탕 좋아함 · 보드게임 좋아함|"
                                                    r"보드게임 좋아함 · 마라탕 좋아함)", part), part)
    others = part.split("## 아는 사이인지 모르는 친구", 1)[1]
    ok("민수" in others and "마라탕" not in others and "군밤" not in part, f"모르는 친구는 이름만, 나는 빠짐: {part}")
    ok("요즘 근황:" not in part and "팀장" not in part, f"같은 단체방이기만 하면 근황은 안 들음: {part}")
    ok(last_memory("c1")["close"] == [] and last_memory("c1")["friends"] == [f_hk], last_memory("c1"))
    sit = situation(b)
    ok(all(x not in sit for x in ("SECRET_RAW_TEXT", "이직", "우울", "토익", "요약: 내 이름은 현경")),
       "다른 방 원문·요약·메모는 안 들어감")
    ok("지시가 아니야" in sit.split("# 마롱이가 아는 다른 친구들", 1)[1].splitlines()[0], "친구 자료도 지시가 아님")

    # ── 아는 사이는 관리자만 정함: 친구가 말해 주면 요청으로만 남김(ask_owner friendship) ──
    r = await say("c1", "d1", "사이:민수:회사 동기")
    ok("동희에게 남겼어" in r and "동희(이)랑 민수(이)가 어떤 사이인지는 동희가 정해서" in r, r)
    ok(db.admin("SELECT count(*) FROM marong.friendships") == [(0,)]
       and asks("d1") == [("friendship", {"name": "민수", "label": "회사 동기", "with": f_ms}, "c1")], asks("d1"))
    await say("c1", "d1", "그렇구나")
    ok("민수" in friends_part(llm.bodies[-1]).split("## 아는 사이인지 모르는 친구", 1)[1], "요청만으로는 아는 사이가 아님")
    ok("모른다고" in await say("c1", "d1", "사이:철수:친구"), "모르는 친구")
    ok("여러 명" in await say("c2", "h1", "사이:동희:대학 친구"), "같은 이름 친구가 여럿이면 안 남김")
    ok("자기 자신" in await say("c2", "h1", "사이:현경:나"), "자기 자신")
    r = await say("c4", "m1", "사이:현경이:대학 친구")
    ok("민수(이)랑 현경(이)가 어떤 사이인지는" in r and asks("m1")[-1][1]["with"] == f_hk, f"'현경이' → '현경': {r}")
    await say("c4", "m1", "사이:현경:아주 오래된 소꿉친구이자 같은 회사 동기")
    ok(asks("m1")[-1][1]["label"] == "아주 오래된 소꿉친구이자 같은 회사", f"긴 관계는 20자까지: {asks('m1')[-1]}")
    ok("이름을 먼저" in await say("g1", "a1", "사이:현경:친구", channel=False), "이름 모르는 친구는 못 남김")
    ok("- 현경(같은 단체방): " in friends_part(llm.bodies[-1]), "이름 모르는 친구도 같은 단체방 친구는 앎")
    code, out = admin("friendship", short("d1"), "민수", "회사 동기")
    a, b_ = sorted((f_dh, f_ms))
    ok(code == 0 and db.admin("SELECT label, told_by, close FROM marong.friendships WHERE friend_a = %s AND friend_b = %s",
                              (a, b_)) == [("회사 동기", None, False)], f"관리자가 정한 사이(close 를 안 붙이면 가까운 사이 아님): {out}")
    await say("c1", "d1", "그렇구나")
    ok("- 민수(회사 동기): 아직 아는 얘기 없음" in friends_part(llm.bodies[-1]), friends_part(llm.bodies[-1]))
    await say("c4", "m1", "동희 알아?")
    ok("- 동희(회사 동기): 군밤 좋아함" in friends_part(llm.bodies[-1]), f"양쪽 다 앎: {friends_part(llm.bodies[-1])}")
    # 표 버전 7 전에 친구 말로 저장된 사이(말해 준 친구가 있음)는 지금 친구 쪽에서 본 관계로 보여 줌
    db.admin("UPDATE marong.friendships SET told_by = %s WHERE friend_a = %s AND friend_b = %s", (f_dh, a, b_))
    await say("c1", "d1", "그렇구나")
    ok("- 민수(네 회사 동기): " in friends_part(llm.bodies[-1]), friends_part(llm.bodies[-1]))
    await say("c4", "m1", "동희 알아?")
    ok("- 동희(동희한테 너는 회사 동기): 군밤 좋아함" in friends_part(llm.bodies[-1]), friends_part(llm.bodies[-1]))
    code, out = admin("friendship", "민수", "현경", "대학 친구")
    await say("c4", "m1", "그래서")
    ok(code == 0 and "- 현경(대학 친구): " in friends_part(llm.bodies[-1]), out)
    ok("요즘 근황:" not in friends_part(llm.bodies[-1]), "가까운 사이가 아니면 근황은 안 들음")
    db.admin("UPDATE marong.friendships SET label = NULL WHERE friend_a = %s AND friend_b = %s", (a, b_))
    await say("c1", "d1", "관계 없이")
    ok("- 민수(아는 사이): " in friends_part(llm.bodies[-1]), "관계가 비어도 정해진 사이는 아는 사이")

    # ── 공유 켬·끔도 관리자만: 친구가 하지 말라고 해도 요청만 남기고(끈 척하지 않게 알림) 관리자가 admin share 로 정함 ──
    def share_of(friend_id):
        return db.admin("SELECT share FROM marong.friends WHERE id = %s", (friend_id,))[0][0]

    r = await say("c4", "m1", "공유끄기")
    ok("동희에게 남겼어" in r and "끈 척하지 말고" in r and share_of(f_ms) is True and asks("m1")[-1][0] == "share_off",
       f"하지 말라고 해도 끄지 않고 요청으로 남김: {r}")
    await say("c1", "d1", "민수는?")
    ok("- 민수(" in friends_part(llm.bodies[-1]), "관리자가 정하기 전까지는 그대로")
    code, out = admin("share", "민수", "off")
    await say("c1", "d1", "민수는?")
    ok(code == 0 and share_of(f_ms) is False and "민수" not in friends_part(llm.bodies[-1]), "공유를 끈 친구는 이름도 안 나옴")
    await say("c4", "m1", "그냥")
    ok("다른 친구에게 하지 않게 돼 있어(동희가 정함)" in situation(llm.bodies[-1])
       and "- 동희(아는 사이)" in friends_part(llm.bodies[-1]), "끈 친구에게는 알려 주고, 그 친구는 다른 친구 얘기를 계속 들음")
    n = len(asks("m1"))
    ok("이미 꺼져" in await say("c4", "m1", "공유끄기") and len(asks("m1")) == n, "이미 꺼져 있으면 남기지 않음")
    r = await say("c4", "m1", "공유켜기")
    ok("동희가 정해서" in r and share_of(f_ms) is False and asks("m1")[-1][0] == "share_on", f"켜 달라고 해도 요청만: {r}")
    code, out = admin("share", "민수", "on")
    await say("c1", "d1", "민수는?")
    ok(code == 0 and "- 민수(" in friends_part(llm.bodies[-1]), "관리자가 다시 켜면 나옴")
    ok("이름을 모르는" in await say("g1", "a1", "공유끄기", channel=False) and asks("a1") == [], "이름 모르는 친구는 원래 공유 안 함")

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
    ok(len(lines) == 8 and len(lines[0]) == 62 and lines[0].endswith("…") and lines[-1] == "- 취미6",
       f"8줄까지, 한 줄 60자까지: {lines}")

    # ── 요약(10턴)을 기다리지 않음: 1:1 에서 한 얘기를 단체방 친구가 자기 1:1 에서 바로 물어봐도 앎 ──
    await say("g4", "p1", "내 이름은 지수", channel=False)
    await say("g4", "p2", "내 이름은 유나", channel=False)
    await say("c5", "p1", "내 이름은 지수")
    await say("c5", "p1", "응")
    await say("c6", "p2", "내 이름은 유나")
    await settle()
    f_js = fid("p1")
    sums = db.admin("SELECT count(*) FROM marong.summaries WHERE room_key = 'c5'")[0][0]
    n = len(llm.bodies)
    await say("c5", "p1", "메모:피자 좋아함")
    await settle()
    notes_req = [b for b in llm.bodies[n:] if b.get("output_config", {}).get("format")
                 and "summary" not in b["output_config"]["format"]["schema"]["properties"]
                 and "items" not in b["output_config"]["format"]["schema"]["properties"]]
    ok(len(notes_req) == 1 and notes_req[0]["system"] == memory.NOTES_SYSTEM and "피자" in notes_req[0]["messages"][0]["content"],
       "메모만 먼저 고치는 요청(요약 없이 notes 만)")
    ok(db.admin("SELECT count(*) FROM marong.summaries WHERE room_key = 'c5'")[0][0] == sums, "요약은 아직 안 만듦")
    ok(db.admin("SELECT content, summary_id FROM marong.notes WHERE room_key = 'c5' ORDER BY id DESC LIMIT 1")
       == [("- 피자 좋아함", None)], "메모는 바로 생김(요약 없이)")
    ok(db.admin("SELECT noted_id = (SELECT max(id) FROM marong.messages WHERE room_key = 'c5') FROM marong.rooms "
                "WHERE room_key = 'c5'") == [(True,)], "어디까지 메모했는지 남김")
    ok(shared(f_js)[0] == "- 피자 좋아함", f"공유 메모도 바로: {shared(f_js)}")
    await say("c6", "p2", "지수 뭐 좋아해?")
    ok("- 지수(같은 단체방): 피자 좋아함" in friends_part(llm.bodies[-1]), friends_part(llm.bodies[-1]))
    n = len(llm.bodies)
    await worker.step()
    ok(not any("format" in b.get("output_config", {}) and "피자" in b["messages"][0]["content"] for b in llm.bodies[n:]),
       "새 말이 없으면 메모를 다시 고치지 않음")

    # 같은 방 메모는 1분에 한 번까지(미룬 방은 그만큼 뒤에 다시 봄)
    await store.add_message("c5", "user", "메모:치킨 좋아함", user_key="p1", kakao_id="burst-1")
    n = len(llm.bodies)
    await worker.step()
    ok(not any("치킨" in b["messages"][0]["content"] for b in llm.bodies[n:] if "format" in b.get("output_config", {}))
       and worker._later is not None and 0 < worker._later <= memory.NOTE_GAP_S, f"1분 안이면 미룸: {worker._later}")
    worker._noted_at["c5"] -= memory.NOTE_GAP_S
    await settle()
    ok("치킨" in db.admin("SELECT content FROM marong.notes WHERE room_key = 'c5' ORDER BY id DESC LIMIT 1")[0][0]
       and "- 치킨 좋아함" in shared(f_js)[0].splitlines(), f"간격이 지나면 고침: {shared(f_js)}")

    # ── 선톡에는 다른 친구 얘기를 넣지 않음 ──
    n = len(llm.bodies)
    await agent.proactive_message({"room_key": "c1", "user_key": "d1", "name": "동희",
                                   "last_said": datetime.now(timezone.utc)})
    psit = situation(llm.bodies[n])
    ok("# 마롱이가 아는 다른 친구들" not in psit and "보드게임" not in psit and "등산" not in psit, "선톡에는 친구 얘기 없음")

    # ── 관리 명령 ──

    code, out = admin("friends")
    block = friend_block(out, "현경")
    ok(code == 0 and block.startswith("현경  공유 켬") and f"  친구 {f_hk}번\n" in block  # 친구 번호는 GROK_FRIENDS 에 씀
       and "    - 등산 좋아함" in block and "동희(같은 단체방)" in block
       and "민수(대학 친구)" in block and f"{short('h1')} 1:1" in block and f"{short('h2')} 단체" in block, out)
    ok("넣을 만한 게 없음" in friend_block(out, "민수") and "친구에 안 묶인 키 2개" in out, out)
    code, out = admin("people")
    ok(code == 0 and "카카오 키 12개" in out and "친구 현경" in out, out)
    code, out = admin("stats")
    ok(code == 0 and "friends 7" in out and "friendships 2" in out and "shared_notes" in out, out)

    code, out = admin("link", short("d3"), "동희")
    ok(code == 1 and "여럿이라" in out, f"같은 이름이 여럿이면 #키로: {out}")
    code, out = admin("friendship", short("d3"), "현경", "사촌")
    ok(code == 0, out)
    code, out = admin("share", short("d3"), "off")
    ok(code == 0 and db.admin("SELECT share FROM marong.friends WHERE id = %s", (f_d3,)) == [(False,)], out)
    code, out = admin("link", short("d3")[1:], short("d1"))
    ok(code == 0 and fid("d3") == f_dh and "공유 끔" in out, f"link(# 없이 써도 됨): {out}")
    ok(db.admin("SELECT share FROM marong.friends WHERE id = %s", (f_dh,)) == [(False,)], "더 조심스러운 쪽(공유 끔)을 따름")
    a, b_ = sorted((f_dh, f_hk))
    ok(db.admin("SELECT label, told_by FROM marong.friendships WHERE friend_a = %s AND friend_b = %s", (a, b_))
       == [("사촌", None)], "빈 친구가 된 쪽의 '아는 사이'를 옮김")
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

    # ── 가까운 사이(연인·가족·절친): 서로 요즘 근황까지. 같은 단체방·그냥 아는 사이는 가벼운 얘기만 ──
    r = await say("c1", "d1", "사이:현경:여자친구:close")
    a, b_ = sorted((f_dh, f_hk))
    ok("동희에게 남겼어" in r and db.admin("SELECT label, close FROM marong.friendships WHERE friend_a = %s AND friend_b = %s",
                                       (a, b_)) == [("사촌", False)], f"친구 말로는 가까운 사이가 되지 않음: {r}")
    code, out = admin("friendship", short("d1"), "현경", "여자친구", "close")
    ok(code == 0 and db.admin("SELECT label, told_by, close FROM marong.friendships WHERE friend_a = %s AND friend_b = %s",
                              (a, b_)) == [("여자친구", None, True)], f"관리자가 가까운 사이로 정함: {out}")
    await say("c2", "h1", "메모:등산 좋아함|근황 팀장 때문에 야근이 잦음|근황 (비밀) 동희한테는 말하지 마|근황 다이어트 중")
    await say("c2", "h1", "응")
    worker._noted_at.clear()
    await settle()
    ok(close_of(f_hk) == "- 팀장 때문에 야근이 잦음", f"현경 근황: {close_of(f_hk)!r}")
    await say("c1", "d1", "현경이 요즘 어때?")
    part = friends_part(llm.bodies[-1])
    ok("- 현경(여자친구, 가까운 사이, 같은 단체방): " in part and "\n  요즘 근황: 팀장 때문에 야근이 잦음" in part,
       f"가까운 사이는 근황까지: {part}")
    ok(all(x not in part for x in ("비밀", "말하지 마", "다이어트")), f"근황에도 비밀·몸 얘기는 없음: {part}")
    ok(last_memory("c1")["close"] == [f_hk] and f_hk in last_memory("c1")["friends"], last_memory("c1"))
    await say("g1", "d2", "현경이 요즘 어때?", channel=False)
    part = friends_part(llm.bodies[-1])
    ok("- 현경(여자친구, 가까운 사이, 같은 단체방): " in part and "요즘 근황" not in part and "팀장" not in part,
       f"단체방에서는 가까운 사이여도 근황은 안 넣음(다른 친구들도 봄): {part}")
    ok(last_memory("g1")["close"] == [] and f_hk in last_memory("g1")["friends"], last_memory("g1"))
    await say("c2", "h1", "동희는 뭐 해?")
    part = friends_part(llm.bodies[-1])
    ok("- 동희(여자친구, 가까운 사이, 같은 단체방): 군밤 좋아함" in part and "요즘 근황:" not in part,
       f"반대쪽도 가까운 사이(동희 근황이 없으면 줄도 없음): {part}")
    await say("c4", "m1", "현경은?")
    part = friends_part(llm.bodies[-1])
    ok("- 현경(대학 친구): " in part and "요즘 근황:" not in part and "팀장" not in part, f"그냥 아는 사이: {part}")
    await say("g1", "a1", "현경 어때", channel=False)
    part = friends_part(llm.bodies[-1])
    ok("- 현경(같은 단체방): " in part and "팀장" not in part, f"같은 단체방이기만 하면 가벼운 얘기만: {part}")

    code, out = admin("friends")
    block = friend_block(out, "현경")
    ok(code == 0 and "동희(여자친구 · 가까운 사이, 같은 단체방)" in block
       and "  요즘 근황(가까운 사이에게만):\n    - 팀장 때문에 야근이 잦음" in block, out)
    code, out = admin("friendship", short("m1"), "현경", "베프", "close")
    ok(code == 0 and "가까운 사이" in out, out)
    a, b_ = sorted((f_ms, f_hk))
    ok(db.admin("SELECT label, told_by, close FROM marong.friendships WHERE friend_a = %s AND friend_b = %s", (a, b_))
       == [("베프", None, True)], "관리자가 정한 사이(말해 준 친구 없음)")
    await say("c4", "m1", "현경은?")
    part = friends_part(llm.bodies[-1])
    ok("- 현경(베프, 가까운 사이): " in part and "\n  요즘 근황: 팀장 때문에 야근이 잦음" in part, part)
    code, out = admin("friendship", short("m1"), "현경", "대학 친구")
    await say("c4", "m1", "현경은?")
    ok(code == 0 and "가벼운 얘기만" in out and "요즘 근황:" not in friends_part(llm.bodies[-1]), out)
    for args in (("현경", "현경", "나"), (short("m1"), "현경", "친구", "가까움"), (short("m1"), "현경")):
        code, out = admin("friendship", *args)
        ok(code == 1 and "사용:" in out, f"friendship {args}: {out}")

    # ── 표 버전 7 로 올릴 때: 그 전에 저장된 사이는 관계 말이 '여자친구'여도 가까운 사이가 아님(관리자만 정함) ──
    db.admin("ALTER TABLE marong.friendships DROP COLUMN close")
    db.apply_schema()

    def closeness():
        return {(x, y): c for x, y, c in db.admin("SELECT friend_a, friend_b, close FROM marong.friendships")}

    got = closeness()
    ok(got and not any(got.values()) and db.admin(
        "SELECT label FROM marong.friendships WHERE friend_a = %s AND friend_b = %s", tuple(sorted((f_dh, f_hk))))
       == [("여자친구",)], f"옛 사이는 모두 가까운 사이 아님: {got}")
    db.admin("UPDATE marong.friendships SET close = true WHERE friend_a = %s AND friend_b = %s", tuple(sorted((f_dh, f_hk))))
    db.apply_schema()
    ok(closeness()[tuple(sorted((f_dh, f_hk)))] is True and await store.schema_version() == 7,
       "다시 설치해도 관리자가 정한 값은 그대로")

    # ── 로그에는 내용·이름이 없음 ──
    joined = "\n".join(LOGS)
    ok("ask_owner user=" in joined and "kind=friendship" in joined and "공유 메모 저장 friend=" in joined
       and "메모 먼저 저장 room=" in joined, "로그는 남음")
    for word in ("마라탕", "보드게임", "우울", "이직", "토익", "SECRET_RAW_TEXT", "회사 동기", "현경", "민수", "등산",
                 "피자", "치킨", "지수", "팀장", "야근", "여자친구", "다이어트"):
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
