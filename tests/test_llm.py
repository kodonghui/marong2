"""Claude 호출 시험: 주 키가 실패·멈추면 백업 키, 잘못된 요청(400)은 바로 실패(크레딧 부족만 백업 키), 키별 점검.
가짜 /v1/messages 서버로 진짜 anthropic SDK 를 부른다. 실행: .venv\\Scripts\\python tests\\test_llm.py"""
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import anthropic  # noqa: E402

from fakes import FakeAnthropic, message, text  # noqa: E402

MODE = {"primary": "ok", "backup": "ok"}


def respond(key, body):
    mode = MODE.get(key, "unauthorized")
    if mode == "stall":
        return "stall"
    if mode == "ok":
        return 200, message([text(f"답({key})")])
    if mode == "overloaded":
        return 529, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
    if mode == "bad":
        return 400, {"type": "error", "error": {"type": "invalid_request_error", "message": "messages: bad"}}
    if mode == "credit":
        return 400, {"type": "error", "error": {"type": "invalid_request_error",
                                                "message": "Your credit balance is too low"}}
    if mode == "billing":
        return 402, {"type": "error", "error": {"type": "billing_error", "message": "billing"}}
    return 401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}


async def main():
    fake = FakeAnthropic(respond)
    os.environ.update({"ANTHROPIC_API_KEY": "primary", "ANTHROPIC_API_KEY_BACKUP": "backup",
                       "ANTHROPIC_BASE_URL": fake.url, "BOT_TOKEN": "t"})
    from marong.config import load_settings
    from marong.llm import LLM, text_of
    llm = LLM(load_settings())
    body = {"model": "claude-haiku-5-5", "max_tokens": 100, "messages": [{"role": "user", "content": "안녕"}]}
    checks = 0

    async def ask(timeout=6.0):
        fake.calls.clear()
        resp = await llm.create(body, timeout)
        return text_of(resp), [c["key"] for c in fake.calls]

    # 1) 둘 다 정상이면 주 키만
    ok = await ask()
    assert ok == ("답(primary)", ["primary"]), ok
    checks += 1

    # 2) 주 키 과부하(529)·크레딧 부족(400 credit·402) → 백업 키
    for mode in ("overloaded", "credit", "billing"):
        MODE["primary"] = mode
        got = await ask()
        assert got == ("답(backup)", ["primary", "backup"]), (mode, got)
        checks += 1

    # 3) 주 키가 답 없이 멈추면 남은 시간을 나눠 백업 키로(전체 시간 안에서)
    MODE["primary"] = "stall"
    start = time.monotonic()
    got = await ask(timeout=4.0)
    took = time.monotonic() - start
    assert got == ("답(backup)", ["primary", "backup"]) and took < 4.5, (got, took)
    checks += 1

    # 4) 잘못된 요청(400)은 백업 키로 보내도 같으니 바로 실패
    MODE["primary"] = "bad"
    try:
        await ask()
        raise AssertionError("400 은 실패해야 함")
    except anthropic.BadRequestError:
        assert [c["key"] for c in fake.calls] == ["primary"]
    checks += 1

    # 5) 둘 다 실패하면 마지막 오류를 올림
    MODE.update(primary="overloaded", backup="overloaded")
    try:
        await ask()
        raise AssertionError("둘 다 실패면 오류")
    except anthropic.APIStatusError as e:
        assert e.status_code == 529
    checks += 1

    # 6) --check 용 키별 점검: 값은 보이지 않고 정상·실패만
    MODE.update(primary="unauthorized", backup="ok")
    out = await llm.check_keys()
    assert [n for n, _ in out] == ["주 키", "백업 키"], out
    assert out[0][1].startswith("실패") and out[1][1].startswith("정상"), out
    assert "primary" not in out[0][1], "실패 설명에 키 값이 나오면 안 됨"
    checks += 1

    await llm.close()
    fake.close()
    print(f"llm: all {checks} checks passed")


if __name__ == "__main__":
    options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    asyncio.run(main(), **options)
