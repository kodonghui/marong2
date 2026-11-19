"""Compare tuning settings with synthetic audio, without a production database (SPEC-182)."""

import argparse
import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import wave

from call_tuning import parse_tuning
from call_usage import decode, dollars

PLAN = Path(__file__).with_name("bench") / "lines.json"
SAMPLE_RATE = 16000
CHECKPOINTS = (240, 480)


@dataclass(frozen=True)
class Cue:
    second: int
    pcm: bytes
    answer: str | None


def cues(folder):
    result = []
    for row in json.loads(PLAN.read_text(encoding="utf-8")):
        at = row["second"]
        with wave.open(str(folder / f"{at:03}.wav"), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, SAMPLE_RATE):
                raise ValueError("expected mono 16 kHz PCM")
            if not 0 < wav.getnframes() < SAMPLE_RATE * 20:
                raise ValueError("each fixture must be under 20 seconds")
            pcm = wav.readframes(wav.getnframes())
        result.append(Cue(at, pcm, row.get("answer")))
    return result


def normalized(value):
    return re.sub(r"[^가-힣0-9a-z]", "", value.lower())


async def evaluate(factory, plan, tuning, runs, rates, mode, *, pace=True):
    complete = []
    for _ in range(runs):
        first = asyncio.get_running_loop().time()
        try:
            async with asyncio.timeout(600), factory(tuning) as ws:
                successes = {}
                cost = Decimal("0")
                previous = (0,) * 9
                reported = False
                for cue in plan:
                    if pace:
                        await asyncio.sleep(max(0, first + cue.second - asyncio.get_running_loop().time()))
                    answer = await ws.exchange(cue.pcm, pace)
                    if cue.answer:
                        successes[cue.second] = normalized(cue.answer) in normalized(answer["text"])
                    for report in answer["metadata"]:
                        reported = True
                        usage, _, _ = decode(report)
                        count = usage
                        if mode == "cumulative" and usage[-1] >= previous[-1]:
                            count = tuple(max(0, value - older) for value, older in zip(usage, previous))
                        previous = usage
                        cost += dollars(count, rates)
                if tuple(successes) != CHECKPOINTS:
                    raise ValueError("missing checkpoint")
                if not reported:
                    raise ConnectionError("usage metadata is missing")
                seconds = asyncio.get_running_loop().time() - first if pace else CHECKPOINTS[-1]
                complete.append((successes, cost / Decimal(max(1, seconds) / 60)))
        except (OSError, ConnectionError, TimeoutError):
            continue
    n = len(complete)
    return {"attempts": runs, "valid": n, "invalid": runs - n,
            "correct_4m": sum(row[0][240] for row in complete), "correct_8m": sum(row[0][480] for row in complete),
            "rate_4m": round(sum(row[0][240] for row in complete) / n, 4) if n else None,
            "rate_8m": round(sum(row[0][480] for row in complete) / n, 4) if n else None,
            "usd_per_minute": round(float(sum(row[1] for row in complete) / n), 6) if n else None}


class LiveBench:
    def __init__(self, socket):
        self.socket = socket

    async def exchange(self, pcm, pace):
        from aiohttp import WSMsgType
        ws = self.socket

        async def send():
            for first in range(0, len(pcm), 640):
                await ws.send_json({"realtimeInput": {"audio": {"mimeType": "audio/pcm;rate=16000",
                    "data": base64.b64encode(pcm[first:first + 640]).decode("ascii")}}})
                if pace:
                    await asyncio.sleep(.02)
            await ws.send_json({"realtimeInput": {"audioStreamEnd": True}})

        async def receive():
            text, metadata = [], []
            async for frame in ws:
                if frame.type not in (WSMsgType.TEXT, WSMsgType.BINARY):
                    break
                data = json.loads(frame.data)
                if data.get("goAway") or data.get("error"):
                    raise ConnectionError("fixture connection ended")
                usage = data.get("usageMetadata")
                if isinstance(usage, dict):
                    metadata.append(usage)
                content = data.get("serverContent") or {}
                text.append(content.get("outputTranscription", {}).get("text", ""))
                if content.get("turnComplete"):
                    return {"text": "".join(text), "metadata": metadata}
            raise ConnectionError("fixture connection closed")

        rx = asyncio.create_task(receive())
        try:
            await send()
            return await asyncio.wait_for(rx, 30)
        finally:
            rx.cancel()
            await asyncio.gather(rx, return_exceptions=True)


async def live(args, tuning, prices, plan):
    from contextlib import asynccontextmanager
    from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType
    import server

    url = (f"wss://{server.LOCATION}-aiplatform.googleapis.com/ws/"
           "google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent")

    @asynccontextmanager
    async def session(settings):
        try:
            async with ClientSession(timeout=ClientTimeout(total=None, connect=10)) as http:
                async with http.ws_connect(url, headers=await server.google_headers(), heartbeat=20) as ws:
                    await ws.send_json(server.setup(tuning=settings))
                    hello = await ws.receive(timeout=10)
                    if hello.type not in (WSMsgType.TEXT, WSMsgType.BINARY) or "setupComplete" not in json.loads(hello.data):
                        raise ConnectionError("setup rejected")
                    yield LiveBench(ws)
        except ClientError:
            raise ConnectionError("fixture connection failed") from None

    at = datetime.now(timezone.utc)
    chosen = max((row for row in prices if row["model"] == server.MODEL
                  and datetime.fromisoformat(row["starts_at"]) <= at), key=lambda row: row["starts_at"])
    rates = {key: Decimal(str(chosen[key])) for key in ("text_in", "audio_in", "image_in", "text_out", "audio_out")}
    return await evaluate(session, plan, tuning, args.runs, rates, args.usage_mode)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tuning", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True, help="export from call-tuning list")
    parser.add_argument("--prices", type=Path, required=True, help="export from call-price list")
    parser.add_argument("--usage-mode", required=True, choices=("turn", "cumulative"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.runs <= 0:
        parser.error("--runs must be positive")
    try:
        entries = json.loads(args.settings.read_text(encoding="utf-8"))["tunings"]
        row = next(row for row in entries if row["name"] == args.tuning)
        options = [f"{key}={('on' if val else 'off') if type(val) is bool else val}"
                   for key, val in row.items() if key not in ("name", "created_at")]
        tuning = parse_tuning(args.tuning, options)
        prices = json.loads(args.prices.read_text(encoding="utf-8"))
        result = asyncio.run(live(args, tuning, prices, cues(args.audio_dir)))
        with args.out.open("x", encoding="utf-8") as file:
            json.dump(result, file, indent=2)
    except (OSError, ValueError, KeyError, TypeError, StopIteration, RuntimeError, wave.Error):
        raise SystemExit("기억 시험을 준비하거나 연결하지 못했습니다.") from None
    print(json.dumps(result))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
