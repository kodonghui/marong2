"""TC-178 memory bench with a synthetic connection and no external API."""

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
import json
from pathlib import Path
import tempfile

from call_tuning import parse_tuning
from make_clips import write_wave
from memory_bench import PLAN, Cue, cues, evaluate, fixture_context


async def main():
    lines = json.loads(PLAN.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        for row in lines:
            write_wave(directory / f"{row['second']:03}.wav", b"\0" * 32000)
        plan = cues(directory)
    prices = {name: Decimal("3") for name in ("text_in", "audio_in", "image_in", "text_out", "audio_out")}

    class Fixture:
        def __init__(self, tuning):
            self.tuning = tuning
            self.count = 0

        async def exchange(self, pcm, pace):
            assert len(pcm) == 32000 and not pace
            self.count += 1
            mode = self.tuning["name"]
            if mode == "fixture-drop":
                raise ConnectionError("fixture drop")
            cue = plan[self.count - 1]
            caption = cue.answer if cue.second == 240 or mode == "fixture-second" else "잘 모르겠어"
            usage = {"promptTokenCount": self.count * 1000, "totalTokenCount": self.count * 1000}
            return {"text": caption or "", "metadata": [usage]}

    @asynccontextmanager
    async def factory(tuning):
        yield Fixture(tuning)

    numbers = []
    for name in ("base-20261116", "fixture-second", "fixture-drop"):
        result = await evaluate(factory, plan, parse_tuning(name, []), 3, prices, "cumulative", pace=False)
        numbers.append(result)
        assert "민들레" not in json.dumps(result, ensure_ascii=False)
    first, second, lost = numbers
    assert (first["rate_4m"], first["rate_8m"]) == (1, 0)
    assert (second["rate_4m"], second["rate_8m"]) == (1, 1)
    assert first["usd_per_minute"] == second["usd_per_minute"] == 0.00375
    assert lost["valid"] == 0 and lost["invalid"] == 3 and lost["usd_per_minute"] is None
    print("TC-178: two tunings, 4/8-minute scores, cumulative pricing, closed sessions and number-only output")

    for script, phase in (("previous", "main"), ("date", "main"), ("compression", "main")):
        fixture = fixture_context(script, phase, "on", 20, 2000)
        self_test = fixture.history["clientContent"]["turns"]
        assert sum(not part["parts"][0]["text"].startswith("[알림]") for part in self_test) == 20
        assert json.loads(fixture.seed).get("as_of") == "2026-11-24 화 16:00"
        if script == "date":
            assert "처음 부분은 글 대화(" in self_test[0]["parts"][0]["text"]
            assert json.loads(fixture.seed)["call_cards"][0]["when"].startswith("어제 ")
        off = fixture_context(script, phase, "off", 20, 2000)
        assert off.history is None and "'when'" not in off.seed and '"as_of"' not in off.seed

    for good in (True, False):
        class Scripted:
            async def exchange(self, pcm, pace):
                return {"text": "어제" if good else "모르겠어", "first_audio_ms": 25,
                        "metadata": [{"promptTokenCount": 10, "totalTokenCount": 10}]}

        @asynccontextmanager
        async def scripted_factory(tuning, fixture):
            assert fixture.history is not None
            yield Scripted()

        result = await evaluate(scripted_factory, [Cue(0, b"\0" * 32, ("어제", "23일"), label="date")],
                                parse_tuning("base-20261116", []), 1, prices, "turn",
                                pace=False, script="date", continuity_mode="on")
        assert result["scores"] == {"date": float(good)}
        assert result["samples"][0]["turn_prompt_tokens"] == [10]
        assert result["samples"][0]["first_audio_ms"] is not None
    dense = json.loads(fixture_context("compression", "main", "on", 20, 2000, stress=True).seed)
    assert len(dense["current_call"]) > 10 and len(dense["shared_friends"]) == 20
    assert dense["recent_conversations"] and len(json.dumps(dense, ensure_ascii=False)) < 14000
    print("TC-685: 6 mode/script fixtures and 100%/0% score cases passed")


if __name__ == "__main__":
    asyncio.run(main())
