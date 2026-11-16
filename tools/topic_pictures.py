"""그림 화두의 그림 세트 만들기(docs/04-functional-spec/call-first.md SPEC-282, AI-22). 서버 밖에서 돌려요.

  draw  --candidates 후보.json --out 폴더 [--only 이름,이름] [--again]
        후보마다 그림 API(OpenAI images/edits)를 한 번 불러 1024px PNG를 <폴더>/<이름>.png에 둬요. 참고 그림은 통화
        얼굴 01-neutral, 05-excited 두 장. 후보마다 120초, 실패는 다시 하지 않고 <폴더>/draw-log.jsonl에 적어요.
        이미 그린 후보는 건너뛰어요(--again이면 다시). Git 안에는 아무것도 쓰지 않아요.
  sheet --candidates 후보.json --out 폴더
        검수용 한 장 <폴더>/sheet.jpg: 후보 번호와 이름, 네모 그림과 통화 화면처럼 원으로 자른 그림.
  pack  --candidates 후보.json --out 폴더 --approve 이름,이름 [--folder marong/topics/v1]
        검수를 통과한 그림만 512px WebP(120KB 이하, 넘으면 품질을 낮춰 다시)로 줄여 세트 폴더에 넣고 topics.json에
        reviewed로 적어요. 봇과 같은 규칙(marong/topics.py picture_of)으로 다시 읽어 확인해요.

후보 목록은 topics.json의 그림 칸(3.1)에서 status·added를 뺀 목록이에요: {"pictures": [{"name", "title", "scene",
"line", "ask", "preview", "alt", "months", "hours"}, …]}.
키: OPENAI_API_KEY. 프록시가 키를 넣는 환경이면 MARONG_OPENAI_PROXY_KEY=1(키 칸에 자리표시만 보내고 프록시가 바꿔요).
그림 API에 보내는 것은 장면 글, 그림체 지시, 마롱이 얼굴 두 장뿐이에요(친구 이름·대화·기억은 보내지 않아요)."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from marong.topics import NAME, PICTURE_BYTES, picture_of  # noqa: E402

FACES = ROOT / "marong" / "call" / "static" / "face" / "v1"
REFERENCES = ("01-neutral", "05-excited")
SET_FOLDER = ROOT / "marong" / "topics" / "v1"
API = "https://api.openai.com/v1"
MODEL = "gpt-image-2.5-flare"       # 2026-11-16 picture model research: cheapest acceptable, keeps the character
QUALITY = "medium"
TIMEOUT_S = 120.0
SIZE = 512
QUALITIES = (82, 74, 66, 58)        # WebP quality steps until the picture fits PICTURE_BYTES
KST = timezone(timedelta(hours=9))
STYLE = (
    "Draw Marong, the character in the reference images, in this scene: {scene}.\n"
    "Keep Marong's exact look from the references: a round, white, fluffy body; two small round ears with a beige "
    "patch on the right ear only; pink oval blush on both cheeks with three short lines; small dot eyes; a simple "
    "dark-brown hand-drawn outline; chibi sticker style.\n"
    "Both eyes level at the same height and the face symmetric, with a gentle happy expression.\n"
    "Keep Marong and the main object inside the central circle of the square (about 80% of its width), so a circular "
    "crop still shows everything that matters.\n"
    "A plain single soft pastel background, nothing busy at the edges.\n"
    "No text, letters, numbers or logos anywhere in the image.")
FIELDS = ("name", "title", "scene", "line", "ask", "preview", "alt", "months", "hours")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(2)


def candidates(path: Path) -> list[dict]:
    """The candidate list, checked by the rules of 3.1 (all but the file) before anything is drawn."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data["pictures"]
        assert isinstance(items, list) and items
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        fail(f"후보 목록을 읽지 못했어요: {path} ({{\"pictures\": [...]}} 모양이어야 해요)")
    seen, bad = set(), []
    for i, item in enumerate(items):
        try:
            if not isinstance(item, dict) or set(item) - set(FIELDS):
                raise ValueError("fields")
            check(item)
            if item["name"] in seen:
                raise ValueError("name")
        except ValueError as e:
            bad.append(f"{i + 1}번 {item.get('name') if isinstance(item, dict) else '?'}: {e}")
            continue
        seen.add(item["name"])
    if bad:
        fail("후보 목록에 틀린 칸이 있어요(3.1 규칙):\n  " + "\n  ".join(bad))
    return items


def check(item: dict, folder: Path | None = None, file: Path | None = None) -> None:
    """picture_of with a stand-in file when the WebP does not exist yet."""
    if folder is None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            stand = Path(tmp)
            name = item.get("name") if isinstance(item.get("name"), str) and NAME.fullmatch(item["name"]) else "x"
            (stand / f"{name}.webp").write_bytes(b"RIFF\0\0\0\0WEBP")
            picture_of({**item, "status": "reviewed"}, "v1", stand)
        return
    picture_of({**item, "status": "reviewed"}, folder.name, folder)


def key() -> str:
    found = os.environ.get("OPENAI_API_KEY", "").strip()
    if found:
        return found
    if os.environ.get("MARONG_OPENAI_PROXY_KEY") == "1":
        return "proxy-supplied"
    fail("OPENAI_API_KEY가 없어요. 그림을 그리기 전에 멈췄어요"
         "(프록시가 키를 넣는 환경이면 MARONG_OPENAI_PROXY_KEY=1).")
    return ""


def references() -> list[tuple[str, bytes]]:
    """The two faces as PNG on white (the images API takes PNG, JPEG or WebP; white keeps the outline clear)."""
    from PIL import Image
    files = []
    for name in REFERENCES:
        face = Image.open(FACES / f"{name}.webp").convert("RGBA")
        white = Image.new("RGBA", face.size, (255, 255, 255, 255))
        white.alpha_composite(face)
        out = io.BytesIO()
        white.convert("RGB").save(out, "PNG")
        files.append((f"{name}.png", out.getvalue()))
    return files


def draw(args) -> int:
    items = candidates(args.candidates)
    only = set(filter(None, (args.only or "").split(",")))
    unknown = only - {i["name"] for i in items}
    if unknown:
        fail("후보 목록에 없는 이름: " + ", ".join(sorted(unknown)))
    secret = key()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    refs = references()
    drawn, failed = [], []
    with httpx.Client(timeout=args.timeout) as client, (out / "draw-log.jsonl").open("a", encoding="utf-8") as logf:
        for item in items:
            name = item["name"]
            target = out / f"{name}.png"
            if (only and name not in only) or (target.exists() and not args.again):
                continue
            began = time.monotonic()
            record = {"name": name, "model": args.model, "quality": args.quality,
                      "at": datetime.now(KST).isoformat(timespec="seconds")}
            try:
                r = client.post(f"{args.api.rstrip('/')}/images/edits", headers={"Authorization": f"Bearer {secret}"},
                                data={"model": args.model, "prompt": STYLE.format(scene=item["scene"]), "n": "1",
                                      "size": "1024x1024", "quality": args.quality},
                                files=[("image[]", (fname, data, "image/png")) for fname, data in refs])
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                body = r.json()
                png = base64.b64decode(body["data"][0]["b64_json"])
                size = picture_size(png)
                if size[0] != size[1] or size[0] < SIZE:
                    raise RuntimeError(f"size {size[0]}x{size[1]}")
                target.write_bytes(png)
                record.update(ok=True, seconds=round(time.monotonic() - began, 1), usage=body.get("usage"))
                drawn.append(name)
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError, IndexError, TypeError, OSError) as e:
                why = str(e) if isinstance(e, RuntimeError) else type(e).__name__
                record.update(ok=False, seconds=round(time.monotonic() - began, 1), error=why)
                failed.append(f"{name} ({why})")
            logf.write(json.dumps(record, ensure_ascii=False) + "\n")
            logf.flush()
            print(("그림 " if record["ok"] else "실패 ") + name + f" {record['seconds']}초", flush=True)
    print(f"그린 것 {len(drawn)}장, 실패 {len(failed)}장" + (": " + ", ".join(failed) if failed else ""))
    return 1 if failed and not drawn else 0


def picture_size(data: bytes) -> tuple[int, int]:
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        return image.size


def sheet(args) -> int:
    """One review page: number, name, the square picture and the circle the call page shows (09 A)."""
    from PIL import Image, ImageDraw
    items = candidates(args.candidates)
    cells = [(i + 1, item["name"]) for i, item in enumerate(items) if (args.out / f"{item['name']}.png").exists()]
    if not cells:
        fail(f"{args.out}에 그린 그림이 없어요(draw 먼저)")
    square, circle, pad, label = 300, 200, 16, 28
    width, height = square + circle + pad * 3, max(square, circle) + label + pad * 2
    cols = 3
    rows = (len(cells) + cols - 1) // cols
    page = Image.new("RGB", (cols * width, rows * height), (246, 242, 235))
    mask = Image.new("L", (circle, circle), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, circle - 1, circle - 1), fill=255)
    pen = ImageDraw.Draw(page)
    for n, (number, name) in enumerate(cells):
        x, y = (n % cols) * width, (n // cols) * height
        with Image.open(args.out / f"{name}.png") as image:
            picture = image.convert("RGB")
        page.paste(picture.resize((square, square), Image.LANCZOS), (x + pad, y + pad))
        page.paste(picture.resize((circle, circle), Image.LANCZOS), (x + pad * 2 + square, y + pad), mask)
        pen.text((x + pad, y + pad + square + 6), f"{number:02d} {name}", fill=(60, 40, 25))
    target = args.out / "sheet.jpg"
    page.save(target, "JPEG", quality=85)
    print(f"검수 시트: {target} ({len(cells)}장)")
    return 0


def webp(png: Path) -> bytes:
    """512px WebP within PICTURE_BYTES: quality steps down until it fits. ValueError when it never does."""
    from PIL import Image
    with Image.open(png) as image:
        picture = image.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
    for quality in QUALITIES:
        out = io.BytesIO()
        picture.save(out, "WEBP", quality=quality, method=6)
        if out.tell() <= PICTURE_BYTES:
            return out.getvalue()
    raise ValueError(f"{out.tell() // 1024}KB")


def pack(args) -> int:
    items = {item["name"]: item for item in candidates(args.candidates)}
    approve = [name for name in (args.approve or "").split(",") if name]
    unknown = [name for name in approve if name not in items]
    missing = [name for name in approve if name in items and not (args.out / f"{name}.png").exists()]
    if not approve or unknown or missing:
        fail("--approve에 검수를 통과한 후보 이름을 쉼표로 주세요"
             + (f". 목록에 없음: {', '.join(unknown)}" if unknown else "")
             + (f". 그림 없음: {', '.join(missing)}" if missing else ""))
    folder = args.folder
    folder.mkdir(parents=True, exist_ok=True)
    listing = folder / "topics.json"
    data = json.loads(listing.read_text(encoding="utf-8")) if listing.exists() else {"set": folder.name, "pictures": []}
    if data.get("set") != folder.name:
        fail(f"{listing}의 set이 폴더 이름({folder.name})과 달라요")
    today = datetime.now(KST).date().isoformat()
    pictures = {p["name"]: p for p in data["pictures"]}   # kept in their order; new ones go at the end
    packed, failed = [], []
    for name in approve:
        try:
            body = webp(args.out / f"{name}.png")
            (folder / f"{name}.webp").write_bytes(body)
            entry = {**{k: items[name][k] for k in FIELDS}, "status": "reviewed",
                     "added": pictures.get(name, {}).get("added", today)}
            check(entry, folder)
        except (ValueError, OSError) as e:
            failed.append(f"{name} ({e})")
            continue
        pictures[name] = entry
        packed.append(f"{name} {len(body) // 1024}KB")
    data["pictures"] = list(pictures.values())
    listing.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"넣은 것 {len(packed)}장: {', '.join(packed)}" + (f"\n실패 {len(failed)}장: " + ", ".join(failed)
                                                         if failed else ""))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("draw", "sheet", "pack"):
        p = sub.add_parser(name)
        p.add_argument("--candidates", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True, help="Git 밖 폴더(그린 PNG, 기록, 검수 시트)")
        if name == "draw":
            p.add_argument("--only")
            p.add_argument("--again", action="store_true")
            p.add_argument("--model", default=MODEL)
            p.add_argument("--quality", default=QUALITY, choices=("low", "medium", "high"))
            p.add_argument("--timeout", type=float, default=TIMEOUT_S)
            p.add_argument("--api", default=API)
        if name == "pack":
            p.add_argument("--approve")
            p.add_argument("--folder", type=Path, default=SET_FOLDER)
    args = parser.parse_args(argv)
    if args.command in ("draw", "sheet") and args.out.resolve().is_relative_to(ROOT.resolve()):
        fail("그린 그림은 Git 밖 폴더에 둬요(--out). 세트에 넣는 것은 pack뿐이에요.")
    return {"draw": draw, "sheet": sheet, "pack": pack}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
