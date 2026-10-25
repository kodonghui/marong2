"""run.py --check 시험: 진짜 Postgres + 가짜 Claude 서버로 점검을 돌려 종료 코드와 출력 줄을 본다.
임베딩은 기본으로 끄고, MARONG_TEST_EMBED_CACHE 에 embeddinggemma 를 받아 둔 폴더를 주면 진짜 모델로 점검한다.
실행: .venv\\Scripts\\python tests\\test_check.py"""
import asyncio
import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from fakes import FakeAnthropic, message, text  # noqa: E402
from pg import TestDB  # noqa: E402

BROKEN = {"summary": False, "share": False}


def respond(key, body):
    if key != "good":
        return 401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid key"}}
    fmt = body.get("output_config", {}).get("format")
    if fmt and "items" in fmt["schema"]["properties"]:  # 공유 메모 거르기
        if BROKEN["share"]:
            return 200, message([], "refusal")
        return 200, message([text(json.dumps({"items": ["마라탕 좋아함"]}, ensure_ascii=False))])
    if fmt:
        if BROKEN["summary"]:
            return 200, message([text("json 아님")])
        return 200, message([text(json.dumps({"summary": "동희가 토익 시험 뒤 마라탕을 먹기로 함",
                                              "notes": [{"who": "친구1", "note": "- 마라탕 좋아함"}]},
                                             ensure_ascii=False))])
    return 200, message([text("안녕! 나는 마롱이야 😆 너 이름이 뭐야?")])


async def run_check() -> tuple[int, str]:
    import run
    out = io.StringIO()
    with redirect_stdout(out):
        code = await run.main("check")
    return code, out.getvalue()


async def main():
    db = TestDB()
    fake = FakeAnthropic(respond)
    cache = os.getenv("MARONG_TEST_EMBED_CACHE")
    os.environ.update({
        "ANTHROPIC_API_KEY": "good", "ANTHROPIC_BASE_URL": fake.url, "DATABASE_URL": db.app_url,
        "PROMPT_PATH": str(ROOT / "prompt.md"), "WELCOME_PATH": str(ROOT / "welcome.txt"),
        "EMBED_MODEL": "google/embeddinggemma-300m" if cache else "", "EMBED_CACHE_DIR": cache or "",
        "BOT_TOKEN": "", "LLM_TIMEOUT_SECONDS": "10",
    })
    checks = 0

    # 1) 다 정상이면 0. BOT_TOKEN 이 비어도 점검은 통과(봇 실행 전에 넣으면 됨)
    code, out = await run_check()
    assert code == 0, out
    for line in ("모델: claude-haiku-5-5 / 답장 effort xhigh / 요약 effort low", "Claude 주 키: 정상",
                 "BOT_TOKEN: 비어 있음", "표 버전 3(코드 3)", "선톡: 꺼짐(PROACTIVE=off)", "기록 지우기·고치기 권한: 없음",
                 "답장 시험: 안녕! 나는 마롱이야", "요약 시험: 동희가 토익", "메모: - 마라탕 좋아함",
                 "공유 메모 시험(시험 얘기는 빠져야 함): - 마라탕 좋아함"):
        assert line in out, f"'{line}' 없음\n{out}"
    assert ("준비됨: 768차원" in out) if cache else ("임베딩: 꺼짐" in out), out
    checks += 1

    # 2) 요약 형식이 깨지면 1, 공유 메모를 거절하면 1
    BROKEN["summary"] = True
    code, out = await run_check()
    assert code == 1 and "요약 시험: 실패" in out and "공유 메모 시험" not in out, out
    BROKEN["summary"] = False
    BROKEN["share"] = True
    code, out = await run_check()
    assert code == 1 and "공유 메모 시험: 실패" in out, out
    BROKEN["share"] = False
    checks += 1

    # 3) 키가 틀리면 1, 키 값은 출력에 없음
    os.environ["ANTHROPIC_API_KEY"] = "wrong-key-value"
    code, out = await run_check()
    assert code == 1 and "Claude 주 키: 실패" in out and "wrong-key-value" not in out, out
    os.environ["ANTHROPIC_API_KEY"] = "good"
    checks += 1

    # 4) 봇 계정에 지우기 권한이 생기면 1(권한이 실수로 바뀐 것을 잡음)
    db.admin("GRANT DELETE ON marong.messages TO marong")
    code, out = await run_check()
    assert code == 1 and "기록을 지우거나 고칠 수 있음" in out, out
    db.admin("REVOKE DELETE ON marong.messages FROM marong")
    checks += 1

    # 5) DB 에 못 붙으면 1
    os.environ["DATABASE_URL"] = "postgresql://marong@127.0.0.1:1/marong?connect_timeout=1"
    code, out = await run_check()
    assert code == 1 and "Postgres: 실패" in out, out
    checks += 1

    fake.close()
    db.close()
    print(f"check: all {checks} checks passed")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.ERROR)
    options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    asyncio.run(main(), **options)
