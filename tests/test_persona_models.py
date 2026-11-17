"""Offline schema and availability checks for TASK-215, TASK-217, TASK-220."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import asyncio
from anthropic import APIConnectionError
from httpx import Request

from marong.capabilities import description, text_matrix
from marong.persona_instructions import InterpretationError, interpret, validate
from tools.persona_draft import FIELDS, validate as draft
from tools import persona_draft as draft_job


async def main():
    values = draft({key: {"value": "unknown", "evidence": 0} for key in FIELDS})
    assert values == {"support": "ask", "advice": "asked", "honesty": "gentle", "lead": "follow"}
    values = {key: {"value": value, "evidence": 2} for key, value in values.items()}
    values["support"] = {"value": "listen", "evidence": 1}
    assert draft(values)["support"] == "ask"
    assert text_matrix([{"name": "schedule_add"}, {"name": "unknown"}]) == [{"name": "schedule_add"}]
    live = description("call", {"recall", "end_call"})
    assert "통화 중 기억 찾기" in live and "친구가 요청한 통화 끊기" in live and "앱으로" not in live
    source = "야라고 부르지 마. 조용히 말해 줘."
    output = {"understood": "조용히 말할게.", "hard_rules": [
        {"kind": "banned_vocative", "value": "야", "quote": "야라고 부르지 마"},
    ], "out_of_scope": []}
    assert validate(source, output)["rules"] == [("no_vocative", "야")]
    for malformed in (
        {**output, "understood": "109도 언급하지 않을게."},
        {**output, "hard_rules": [{"kind": "banned_vocative", "value": "야", "quote": "없는 인용"}]},
        {**output, "hard_rules": [{"kind": "proactive_lower", "value": "normal", "quote": "야라고"}]},
    ):
        try:
            validate(source, malformed)
        except InterpretationError:
            pass
        else:
            raise AssertionError("unsafe instruction accepted")
    llm = SimpleNamespace(create_once=AsyncMock(return_value=SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(output, ensure_ascii=False))],
    )))
    assert (await interpret(llm, "fixture", source))["understood"] == output["understood"]
    assert llm.create_once.await_count == 1
    source_store = SimpleNamespace(_all=AsyncMock(return_value=[
        {"kind": "summary", "id": 1, "content": "짧게 답을 듣는다는 합성 시험 요약"}]))
    cards = SimpleNamespace(record_run=AsyncMock(), draft=AsyncMock())
    draft_response = SimpleNamespace(stop_reason="end_turn", content=[
        SimpleNamespace(type="text", text=json.dumps(values))])
    connection_error = APIConnectionError(request=Request("POST", "https://fixture.invalid"))
    with patch.object(draft_job, "FriendCards", return_value=cards):
        llm.create_once.side_effect = [connection_error, draft_response]
        llm.create_once.reset_mock()
        assert await draft_job.make(source_store, llm, SimpleNamespace(anthropic_model="fixture"), 1)
        assert llm.create_once.await_count == 2 and cards.draft.await_count == 1
        assert [call.args[0].outcome for call in cards.record_run.call_args_list] == ["error", "ok"]
        llm.create_once.side_effect = [ValueError("fixture-invalid-output")]
        llm.create_once.reset_mock()
        assert not await draft_job.make(source_store, llm, SimpleNamespace(anthropic_model="fixture"), 1)
        assert llm.create_once.await_count == 1
    print("TC-259/265/269 partial: draft defaults, exact-quote instruction schema, and capability matrix")


if __name__ == "__main__":
    asyncio.run(main())
