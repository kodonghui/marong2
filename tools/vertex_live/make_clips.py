"""Generate the approved listener clips or the fixed Discord notice."""

import argparse
import asyncio
import difflib
from pathlib import Path
import subprocess
import tempfile
import wave

NOTICE = "미안, 이번 달 통화는 여기까지야. 다음 달에 또 걸어 줘! 글로는 계속 얘기할 수 있어."


def write_wave(file, pcm):
    if len(pcm) < 32000 or len(pcm) > 960000 or len(pcm) % 2:
        raise ValueError("invalid clip duration")
    with wave.open(str(file), "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(pcm)


async def create(args, speak, plain):
    if args.budget_notice:
        lines = [NOTICE]
    else:
        lines = args.sentences.read_text(encoding="utf-8").splitlines()
        if len(lines) != 10 or any(not 1 <= len(line.strip()) <= 200 for line in lines):
            raise ValueError("expected ten approved lines")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    names = ["budget-notice.ogg"] if args.budget_notice else [f"{i:02}.wav" for i in range(1, 11)]
    if any((output / name).exists() for name in names):
        raise ValueError("output already exists")
    with tempfile.TemporaryDirectory(prefix=".clips-", dir=output) as tmp:
        staging = Path(tmp)
        for name, line in zip(names, lines, strict=True):
            pcm, readback = await asyncio.wait_for(speak(line.strip()), 90)
            if difflib.SequenceMatcher(None, plain(line), plain(readback)).ratio() < 0.95:
                raise ValueError("readback differs from the approved line")
            wav = staging / (name if not args.budget_notice else "notice.wav")
            write_wave(wav, pcm)
            if args.budget_notice:
                subprocess.run([args.ffmpeg, "-nostdin", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", "48000",
                                "-c:a", "libopus", "-b:a", "32k", str(staging / name)],
                               check=True, capture_output=True, timeout=20)
        for name in names:
            (staging / name).rename(output / name)
    return len(names)


def main():
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--budget-notice", action="store_true")
    choice.add_argument("--sentences", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    from probe_hangup import plain, speech
    try:
        count = asyncio.run(create(args, speech, plain))
    except (OSError, ValueError, AssertionError, RuntimeError, TimeoutError, subprocess.SubprocessError):
        raise SystemExit("안내 음원을 만들지 못했습니다. 연결·문장 확인·출력 경로를 확인해 주세요.") from None
    print(f"{count}개 음원 저장")


if __name__ == "__main__":
    main()
