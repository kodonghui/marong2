"""The picture set tool (tools/topic_pictures.py, docs/04-functional-spec/call-first.md SPEC-282, AI-22,
docs/10-wbs/call-first.md TASK-174) against a fake images API on 127.0.0.1. No network, no real key.

- draw: one request per candidate with the two faces and the style; HTTP errors, a timeout and a wrong size fail only
  that candidate; drawn ones are skipped on the next run; no key or a wrong list stops before any request; never
  inside the repository
- sheet: one review page
- pack: 512px WebP within 120KB (quality steps down), topics.json the bot reads (load_set), the date of the first
  pack kept, a picture that never fits fails alone
Run: .venv/bin/python tests/test_topic_pictures.py"""
import base64
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import threading
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import topic_pictures  # noqa: E402
from marong.topics import load_set  # noqa: E402

CHECKS = 0
KST = timezone(timedelta(hours=9))


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


@lru_cache(maxsize=8)
def png(size: int, noise: bool = False) -> bytes:
    if noise:
        rng = random.Random(size)
        image = Image.frombytes("RGB", (size, size), bytes(rng.getrandbits(8) for _ in range(size * size * 3)))
    else:
        image = Image.new("RGB", (size, size), (250, 236, 220))
        for x in range(size // 4, size * 3 // 4):
            for y in range(size // 4, size * 3 // 4, 8):
                image.putpixel((x, y), (120, 80, 60))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


class Fake(BaseHTTPRequestHandler):
    """POST /v1/images/edits. The scene decides: FAIL → 500, SLOW → too late, SMALL → 256px, NOISE → noise."""
    seen: list = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Fake.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if b"FAIL" in body:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "boom"}}')
            return
        if b"SLOW" in body:
            time.sleep(1.5)
        picture = png(256) if b"SMALL" in body else png(1024, noise=b"NOISE" in body)
        reply = json.dumps({"data": [{"b64_json": base64.b64encode(picture).decode()}],
                            "usage": {"input_tokens": 2314, "output_tokens": 343}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        try:
            self.wfile.write(reply)
        except (BrokenPipeError, ConnectionResetError):
            pass


def item(name, scene, title="털모자", **more):
    return {"name": name, "title": title, "scene": scene, "line": "나 털모자 샀다! 🧶", "ask": "어때, 잘 어울려?",
            "preview": "나 털모자 샀다!", "alt": "털모자를 쓰고 웃는 마롱이", "months": [11, 12, 1, 2], "hours": [9, 22],
            **more}


def run(*argv, env=None):
    """main() in this process: (exit code, printed text)."""
    out = io.StringIO()
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(env if env is not None else saved)
    try:
        with redirect_stdout(out), redirect_stderr(out):
            try:
                code = topic_pictures.main(list(argv))
            except SystemExit as e:
                code = e.code
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return code, out.getvalue()


def main():
    # The 0.5-second HTTP deadline tests a slow response, so prepare the image fixtures beforehand.
    png(256)
    png(1024)
    png(1024, noise=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{server.server_address[1]}/v1"
    git_before = subprocess.run(["git", "status", "--porcelain", "marong/topics"], cwd=ROOT, capture_output=True,
                                text=True).stdout
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        out, folder = tmp / "drawn", tmp / "set" / "v1"
        listing = tmp / "candidates.json"
        listing.write_text(json.dumps({"pictures": [
            item("winter-hat", "Marong wearing a new knitted winter hat, smiling"),
            item("chicken-skewer", "Marong eating a chicken skewer at a street stall", title="닭꼬치"),
            item("broken", "FAIL this one"), item("slow", "SLOW this one"), item("tiny", "SMALL this one"),
            item("noisy", "NOISE that needs a lower WebP quality"),
        ]}, ensure_ascii=False), encoding="utf-8")
        key_env = {**os.environ, "OPENAI_API_KEY": "test-key", "NO_PROXY": "127.0.0.1,localhost"}
        bare_env = {k: v for k, v in key_env.items() if k not in ("OPENAI_API_KEY", "MARONG_OPENAI_PROXY_KEY")}

        # Nothing is asked without a key, with a wrong list or into the repository.
        code, text = run("draw", "--candidates", str(listing), "--out", str(out), "--api", api, env=bare_env)
        ok(code == 2 and "OPENAI_API_KEY가 없어요" in text and not Fake.seen, text)
        wrong = tmp / "wrong.json"
        for bad, why in (([item("a", "x", ask="어울려")], "ask"), ([item("a", "x"), item("a", "y")], "name"),
                         ([{**item("a", "x"), "extra": 1}], "fields"), ([item("a", "한국어 장면")], "scene")):
            wrong.write_text(json.dumps({"pictures": bad}, ensure_ascii=False), encoding="utf-8")
            code, text = run("draw", "--candidates", str(wrong), "--out", str(out), "--api", api, env=key_env)
            ok(code == 2 and f": {why}" in text and not Fake.seen, (why, text))
        code, text = run("draw", "--candidates", str(listing), "--out", str(ROOT / "drawn"), "--api", api,
                         env=key_env)
        ok(code == 2 and "Git 밖" in text and not Fake.seen and not (ROOT / "drawn").exists(), text)

        # One request per candidate; failures stay with their candidate.
        code, text = run("draw", "--candidates", str(listing), "--out", str(out), "--api", api, "--timeout", "0.5",
                         env=key_env)
        ok(code == 0 and "그린 것 3장, 실패 3장" in text, text)
        ok(sorted(p.name for p in out.glob("*.png")) == ["chicken-skewer.png", "noisy.png", "winter-hat.png"],
           list(out.iterdir()))
        ok(len(Fake.seen) == 6 and all(s["path"] == "/v1/images/edits" and s["auth"] == "Bearer test-key"
                                       for s in Fake.seen), [s["path"] for s in Fake.seen])
        first = Fake.seen[0]["body"]
        ok(first.count(b'name="image[]"') == 2 and b"01-neutral.png" in first and b"05-excited.png" in first,
           "the two faces go with every request")
        ok(b"gpt-image-2.5-flare" in first and b"medium" in first and b"1024x1024" in first, "model, quality, size")
        ok(b"Marong wearing a new knitted winter hat" in first and b"No text, letters" in first
           and b"circular" in first and b"same height" in first, "the scene and the style (AI-22)")
        ok("털모자".encode() not in first and "어울려".encode() not in first, "only the scene goes, not the words")
        records = [json.loads(line) for line in (out / "draw-log.jsonl").read_text(encoding="utf-8").splitlines()]
        errors = {r["name"]: r.get("error") for r in records if not r["ok"]}
        ok(errors == {"broken": "HTTP 500", "slow": "ReadTimeout", "tiny": "size 256x256"}, errors)
        ok(all(r["ok"] and r["usage"]["output_tokens"] == 343 for r in records if r["name"] == "winter-hat"), records)

        # A second run skips what is drawn; --only and --again draw one again.
        before = len(Fake.seen)
        code, text = run("draw", "--candidates", str(listing), "--out", str(out), "--api", api, "--timeout", "0.5",
                         "--only", "winter-hat", env=key_env)
        ok(code == 0 and len(Fake.seen) == before and "그린 것 0장, 실패 0장" in text, text)
        code, text = run("draw", "--candidates", str(listing), "--out", str(out), "--api", api, "--only",
                         "winter-hat", "--again", env=key_env)
        ok(code == 0 and len(Fake.seen) == before + 1 and "그린 것 1장" in text, text)
        code, text = run("draw", "--candidates", str(listing), "--out", str(out), "--api", api, "--only", "nobody",
                         env=key_env)
        ok(code == 2 and "nobody" in text, text)
        proxy_env = {**bare_env, "MARONG_OPENAI_PROXY_KEY": "1"}
        code, text = run("draw", "--candidates", str(listing), "--out", str(out), "--api", api, "--only",
                         "chicken-skewer", "--again", env=proxy_env)
        ok(code == 0 and Fake.seen[-1]["auth"] == "Bearer proxy-supplied", "a proxy that adds the key")

        # The review page.
        code, text = run("sheet", "--candidates", str(listing), "--out", str(out))
        ok(code == 0 and (out / "sheet.jpg").exists(), text)
        with Image.open(out / "sheet.jpg") as page:
            ok(page.size == (3 * 548, 360), page.size)  # three drawn, one row

        # Pack: 512px WebP within 120KB, the list the bot reads.
        code, text = run("pack", "--candidates", str(listing), "--out", str(out), "--folder", str(folder),
                         "--approve", "winter-hat,chicken-skewer,noisy")
        ok(code == 0 and "넣은 것 3장" in text, text)
        for name in ("winter-hat", "chicken-skewer", "noisy"):
            data = (folder / f"{name}.webp").read_bytes()
            with Image.open(folder / f"{name}.webp") as image:
                ok(image.format == "WEBP" and image.size == (512, 512) and len(data) <= 120 * 1024,
                   (name, image.format, image.size, len(data)))
        found = load_set(folder)
        ok(found and [p.name for p in found.pickable] == ["winter-hat", "chicken-skewer", "noisy"], found)
        today = datetime.now(KST).date().isoformat()
        entries = json.loads((folder / "topics.json").read_text(encoding="utf-8"))
        ok(entries["set"] == "v1" and all(p["status"] == "reviewed" and p["added"] == today
                                          for p in entries["pictures"]), entries)
        ok(entries["pictures"][1]["title"] == "닭꼬치" and entries["pictures"][0]["preview"] == "나 털모자 샀다!",
           "the fields of 3.1 as written")

        # Packing again keeps the first date and the order; a picture that never fits fails alone.
        entries["pictures"][0]["added"] = "2026-11-17"
        (folder / "topics.json").write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        topic_pictures.PICTURE_BYTES = 50 * 1024
        try:
            code, text = run("pack", "--candidates", str(listing), "--out", str(out), "--folder", str(folder),
                             "--approve", "winter-hat,noisy")
        finally:
            topic_pictures.PICTURE_BYTES = 120 * 1024
        ok(code == 1 and "넣은 것 1장" in text and "noisy (" in text, text)
        again = json.loads((folder / "topics.json").read_text(encoding="utf-8"))
        ok([p["name"] for p in again["pictures"]] == ["winter-hat", "chicken-skewer", "noisy"]
           and again["pictures"][0]["added"] == "2026-11-17", again)
        for argv, why in ((("--approve", "nobody"), "목록에 없음"), (("--approve", "broken"), "그림 없음"),
                          ((), "--approve")):
            code, text = run("pack", "--candidates", str(listing), "--out", str(out), "--folder", str(folder), *argv)
            ok(code == 2 and why in text, (argv, text))
    server.shutdown()
    git_after = subprocess.run(["git", "status", "--porcelain", "marong/topics"], cwd=ROOT, capture_output=True,
                               text=True).stdout
    ok(git_after == git_before, "nothing written into the repository's set")
    print("PASS TASK-174 draw (one request each with the faces and the style, failures alone, skip and again, no key, "
          "wrong list, never inside Git), sheet, pack (512px WebP within 120KB, the list the bot reads, dates kept, "
          "a picture that never fits fails alone)")


if __name__ == "__main__":
    main()
    print(f"OK {CHECKS} checks")
