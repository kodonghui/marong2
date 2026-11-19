"""Exercise the opt-in TC-347 path without sending any API requests."""

import asyncio
import json
from contextlib import redirect_stdout
from io import StringIO
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from live import BUDGET_KRW, INPUT_ESTIMATE_LIMIT, LiveTrial, TrialError, reserve_krw
from run import HERE, TestDB, load_settings, prepare, run


class FixtureMessages:
    def __init__(self):
        self.extractions = 0
        self.answers = 0
        self.estimate = 100

    async def count_tokens(self, **request):
        assert not request.get("tools")
        return SimpleNamespace(input_tokens=self.estimate)

    async def create(self, **request):
        user = request["messages"][-1]["content"]
        output_config = request.get("output_config", {})
        if "format" in output_config:
            self.extractions += 1
            source = json.loads(user)["messages"][0]
            text = json.dumps({"ops": [{
                "op": "add", "message_id": source["id"], "quote": source["text"],
                "item": {"kind": "fact", "text": "프로젝트 별명은 모래유리", "scope": "friend",
                         "share": "self", "sensitive": None, "valid_until": None},
            }]})
        else:
            self.answers += 1
            assert "모래유리" in json.dumps(request, ensure_ascii=False)
            text = "기억이 흐릿해." if self.answers == 2 else "모래유리였어."
        usage = SimpleNamespace(input_tokens=100, output_tokens=8,
                                cache_creation_input_tokens=None, cache_read_input_tokens=None)
        return SimpleNamespace(stop_reason="end_turn", usage=usage, content=[SimpleNamespace(type="text", text=text)])


async def test(database):
    settings = load_settings()
    provider = FixtureMessages()
    trial = LiveTrial(SimpleNamespace(messages=provider), settings.anthropic_model)
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))[:1]
    printed = StringIO()
    with TemporaryDirectory() as path, redirect_stdout(printed):
        await run(database, cases, path, live=trial)
    report = json.loads(printed.getvalue())
    assert report["cases_per_trial"] == 1
    assert [row["context_pass"] for row in report["trials"]] == [1, 1, 1]
    assert [row["answer_pass"] for row in report["trials"]] == [1, 0, 1]
    assert report["passed_all_three"] == 0
    assert report["joint_accuracy_pct"] == 66.7
    assert report["provider_calls"] == 6
    assert report["cost_reservation_krw"] == 3 * (reserve_krw(6000) + reserve_krw(1024))
    assert provider.extractions == provider.answers == 3

    request = {"model": trial.model, "max_tokens": 10, "system": "fixture",
               "messages": [{"role": "user", "content": "fixture"}]}
    provider.estimate = INPUT_ESTIMATE_LIMIT + 1
    try:
        await trial.create_once(request, 5)
    except TrialError as error:
        assert str(error) == "input_estimate_exceeds_limit"
    else:
        raise AssertionError("an oversized prompt was accepted")
    trial.reserved_krw = BUDGET_KRW
    try:
        await trial.create_once(request, 5)
    except TrialError as error:
        assert str(error) == "trial_budget_exhausted"
    else:
        raise AssertionError("an over-budget request was accepted")
    assert provider.extractions == provider.answers == 3


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(test(db))
    finally:
        db.close()
    print("THREE_TRIALS_GRADED=PASS INPUT_CAP=PASS BUDGET_CAP=PASS LIVE_CALLS=0")
