"""Make blinded AAC bundles and report listening scores (SPEC-183)."""

import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.listen import CLIP_ID, DEFAULT_DIR, MAX_CLIP_BYTES, TEST_ID

_INPUT_EXTENSIONS = (".wav", ".ogg", ".m4a", ".mp3", ".flac")
_NAME = re.compile(r"[^\s=][^\r\n=]{0,79}\Z")


def _conversion(command):
    process = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    if process.returncode:
        raise ValueError("소리를 읽거나 바꿀 수 없어요")
    return process.stdout


def _encode(source, target, ffmpeg, ffprobe):
    _conversion([ffmpeg, "-nostdin", "-v", "error", "-i", str(source), "-map", "0:a:0",
                 "-map_metadata", "-1", "-map_chapters", "-1", "-af", "aformat=channel_layouts=mono,loudnorm=I=-18:TP=-1.5:LRA=11",
                 "-ac", "1", "-ar", "48000", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(target)])
    output = _conversion([ffprobe, "-v", "error", "-select_streams", "a:0",
                          "-show_entries", "stream=codec_name,sample_rate,channels,duration", "-of", "json", str(target)])
    try:
        stream, = json.loads(output)["streams"]
        valid = (stream["codec_name"] == "aac" and stream["sample_rate"] == "48000" and stream["channels"] == 1
                 and Decimal(1) <= Decimal(stream["duration"]) <= Decimal(15))
    except (ValueError, TypeError, KeyError, InvalidOperation):
        valid = False
    if not valid or not 0 < target.stat().st_size <= MAX_CLIP_BYTES:
        raise ValueError("시험 소리는 1~15초 AAC여야 해요")


def _audio(folder, no):
    candidates = [folder / f"{no:02d}{extension}" for extension in _INPUT_EXTENSIONS]
    matches = [item for item in candidates if item.is_file()]
    if len(matches) != 1:
        raise ValueError("후보마다 01부터 10까지 소리 파일이 하나씩 필요해요")
    return matches[0]


def create_test(test_id, sentence_file, candidates, public, key_file, ffmpeg="ffmpeg", ffprobe="ffprobe"):
    if not TEST_ID.fullmatch(test_id) or not 1 <= len(candidates) <= 8:
        raise ValueError("시험 이름이나 후보 수가 틀려요")
    sentences = [line.strip() for line in sentence_file.read_text(encoding="utf-8").splitlines()]
    if len(sentences) != 10 or any(not 1 <= len(line) <= 200 for line in sentences):
        raise ValueError("시험 문장은 열 개이고 각각 200자 이하여야 해요")
    if any(not _NAME.fullmatch(name) for name in candidates):
        raise ValueError("후보 이름 형식이 틀려요")
    public = public.resolve()
    key_file = key_file.resolve()
    if key_file.is_relative_to(public) or key_file.exists():
        raise ValueError("정답표는 공개 소리 폴더 밖의 새 파일이어야 해요")

    public.mkdir(parents=True, exist_ok=True)
    target = public / test_id
    if target.exists():
        raise ValueError("그 이름의 시험이 이미 있어요")
    key = {"testId": test_id, "clips": {}}
    manifest = {"testId": test_id, "sentences": []}
    with TemporaryDirectory(prefix=".listen-", dir=public) as staged:
        staging = Path(staged) / "clips"
        staging.mkdir()
        for no, text in enumerate(sentences, 1):
            clips = []
            for name, folder in candidates.items():
                clip = secrets.token_hex(8)
                while clip in key["clips"]:
                    clip = secrets.token_hex(8)
                _encode(_audio(folder, no), staging / f"{clip}.m4a", ffmpeg, ffprobe)
                clips.append(clip)
                key["clips"][clip] = name
            manifest["sentences"].append({"no": no, "text": text, "clips": sorted(clips)})

        # Publish only after all audio was checked. The private key never sits below the public root.
        key_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as private:
            json.dump(key, private, ensure_ascii=False)
        staging.rename(target)
        with NamedTemporaryFile("w", encoding="utf-8", dir=public, prefix=".current-", delete=False) as output:
            json.dump(manifest, output, ensure_ascii=False)
            active = Path(output.name)
        active.replace(public / "current.json")
    return len(key["clips"])


def results(conn, key_file):
    key = json.loads(key_file.read_text(encoding="utf-8"))
    test_id, clips = key["testId"], key["clips"]
    if not TEST_ID.fullmatch(test_id) or any(not CLIP_ID.fullmatch(clip) or not _NAME.fullmatch(name)
                                           for clip, name in clips.items()):
        raise ValueError("정답표 형식이 틀려요")
    counters = defaultdict(lambda: [0, 0, 0])
    for name in clips.values():
        counters[name]
    rows = conn.execute(
        """SELECT clip_id,count(score),coalesce(sum(score),0),count(*) FILTER (WHERE marong_like)
        FROM marong.listen_scores WHERE test_id=%s GROUP BY clip_id""", (test_id,),
    )
    for clip, count, total, likes in rows:
        name = clips.get(clip)
        if name:
            counters[name][0] += count
            counters[name][1] += total
            counters[name][2] += likes
    return [(name, total / count if count else None, count, likes)
            for name, (count, total, likes) in sorted(counters.items())]


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("make")
    make.add_argument("test_id")
    make.add_argument("--sentences", type=Path, required=True, help="시험에 지정된 UTF-8 문장 파일")
    make.add_argument("--candidate", action="append", required=True, help="운영자용 후보 이름=소리 폴더")
    make.add_argument("--out", type=Path, default=Path(os.getenv("MARONG_LISTEN_DIR", DEFAULT_DIR)))
    make.add_argument("--key-file", type=Path, required=True)
    result = commands.add_parser("result")
    result.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "make":
            candidates = {}
            for value in args.candidate:
                name, equals, folder = value.partition("=")
                if not equals or name in candidates:
                    raise ValueError("후보는 이름=소리 폴더 모양으로 하나씩 넣어요")
                candidates[name] = Path(folder)
            count = create_test(args.test_id, args.sentences, candidates, args.out, args.key_file)
            print(f"{args.test_id} 소리 {count}개 준비")
        else:
            dsn = os.getenv("DATABASE_URL")
            if not dsn:
                raise ValueError("서버의 저장소 설정이 필요해요")
            with psycopg.connect(dsn) as conn:
                print("후보\t평균 점수\t점수 수\t마롱이 같다")
                for name, average, count, likes in results(conn, args.key_file):
                    mean = f"{average:.2f}" if average is not None else "—"
                    print(f"{name}\t{mean}\t{count}\t{likes}")
    except (OSError, KeyError, TypeError, ValueError, psycopg.Error, subprocess.TimeoutExpired) as error:
        message = str(error) if type(error) is ValueError else "시험 묶음이나 저장소를 확인해 주세요"
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
