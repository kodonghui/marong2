"""TC-178 memory bench with a synthetic connection and no external API."""

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
import json
from pathlib import Path
import tempfile

from call_tuning import parse_tuning
from make_clips import write_wave
from memory_bench import PLAN, cues, evaluate


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


if __name__ == "__main__":
    asyncio.run(main())
