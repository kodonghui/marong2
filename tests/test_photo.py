"""사진 시험: 카카오 CDN 주소 알아보기·사진 종류·내려받기(가짜 CDN)·큰 사진 줄이기·설명 저장·답할 때 사진 보여 주기·
묶어 답하기·BotApp 경로(받은 순서·주소가 저장·로그에 안 남음). 진짜 Postgres + 가짜 Claude.
실행(윈도우): .venv\\Scripts\\python tests\\test_photo.py   (리눅스·맥: .venv/bin/python tests/test_photo.py)"""
import asyncio
import base64
import io
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import httpx  # noqa: E402

from fakes import FakeEmbeddings, ScriptedLLM, message, text  # noqa: E402
from pg import TestDB  # noqa: E402

CHECKS = 0
LOGS: list[str] = []
CAPTION = {"mode": "ok"}  # 가짜 Claude 의 사진 설명: ok | refuse | fail

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 60
GIF = b"GIF89a" + b"\x02" * 20
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x03" * 20
SECRET = "SECRETCRED"
URL = f"https://talk.kakaocdn.net/dna/abc/def/img.jpg?credential={SECRET}&expires=1&signature=SIGSIG"


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def said(content) -> str:
    """messages 의 내용(글이나 블록 목록)에서 글만."""
    if isinstance(content, str):
        return content
    return "\n".join(b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text")


def images(content) -> list[dict]:
    return [b for b in content if isinstance(b, dict) and b.get("type") == "image"] if isinstance(content, list) else []


def noise_photo(w: int, h: int, fmt: str, orientation: int = 0) -> bytes:
    """잡음 사진(잘 안 줄어드는 진짜 사진 파일). orientation 은 폰이 적어 두는 EXIF 회전 정보(6: 세워서 볼 것)."""
    from PIL import Image
    im = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
    buf = io.BytesIO()
    if fmt == "JPEG":
        exif = Image.Exif()
        if orientation:
            exif[0x0112] = orientation
        im.save(buf, "JPEG", quality=95, exif=exif.tobytes())
    else:
        im.save(buf, fmt)
    return buf.getvalue()


def opened(data: bytes) -> tuple:
    """사진 파일을 열어 (종류, 크기, 색 방식)."""
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        return im.format, im.size, im.mode


def respond(body):
    """가짜 Claude: 사진 설명 요청이면 설명, 아니면 '응답:마지막 줄'."""
    from marong.agent import CAPTION_PROMPT
    last = body["messages"][-1]
    if CAPTION_PROMPT in said(last["content"]):
        if CAPTION["mode"] == "fail":
            return RuntimeError("boom")
        if CAPTION["mode"] == "refuse":
            return message([], "refusal", stop_details={"type": "refusal", "category": "general_harms",
                                                        "explanation": None})
        return message([text("  접시에 국물 떡볶이랑\n  튀김이 담겨 있어  ")])
    return message([text(f"응답:{said(last['content']).splitlines()[-1]}")])


class Collect(logging.Handler):
    def emit(self, record):
        LOGS.append(record.getMessage())


async def main():
    import marong.photo as photo_mod
    from marong.photo import MAX_BYTES, MAX_DOWNLOAD, MAX_SIDE, Photo, download, photo_url, shrink, sniff
    from PIL import Image

    # ── 카카오 CDN 주소 하나만 온 말이 사진 ──
    ok(photo_url(URL) == URL and photo_url(f"  {URL}\n") == URL.strip()
       and photo_url("https://dn-m.talk.kakaocdn.net/a/b.png") and photo_url("https://kakaocdn.net/x.jpg"),
       "카카오 CDN https 주소")
    for bad in (None, "", "안녕", f"이거 봐 {URL}", URL.replace("https://", "http://"),
                "https://kakaocdn.net.evil.com/a.jpg", "https://evilkakaocdn.net/a.jpg", "https://example.com/a.jpg",
                "https://talk.kakaocdn.net/", "https://talk.kakaocdn.net", "https://[::1/a.jpg"):
        ok(photo_url(bad) is None, f"사진 주소 아님: {bad!r}")

    # ── 사진 종류는 파일 앞부분으로 ──
    ok(sniff(JPEG) == "image/jpeg" and sniff(PNG) == "image/png" and sniff(GIF) == "image/gif"
       and sniff(b"GIF87a" + b"\x00") == "image/gif" and sniff(WEBP) == "image/webp", "jpeg·png·gif·webp")
    ok(sniff(b"<html>") is None and sniff(b"") is None and sniff(b"RIFF\x00\x00\x00\x00WAVE") is None, "사진 아님")
    ok(Photo().block() is None and Photo(problem="big").block() is None, "못 연 사진은 블록 없음")
    ok(Photo("image/png", PNG).block() == {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                                       "data": base64.b64encode(PNG).decode()}},
       "Claude 사진 블록(base64)")

    # ── 내려받기(가짜 CDN) ──
    seen: list[str] = []

    def cdn(routes: dict):
        """주소 경로 → 응답. 경로가 없으면 404. 받은 주소를 seen 에 적음."""
        def handle(request: httpx.Request):
            seen.append(str(request.url))
            out = routes.get(request.url.path)
            if isinstance(out, Exception):
                raise out
            return out or httpx.Response(404)
        return httpx.AsyncClient(transport=httpx.MockTransport(handle))

    async def fetch(routes, url=URL):
        seen.clear()
        async with cdn(routes) as http:
            return await download(http, url)

    p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(200, content=JPEG, headers={"content-type": "text/plain"})})
    ok(p.media == "image/jpeg" and p.data == JPEG and not p.problem and seen == [URL],
       "서명된 주소 그대로 받고, 종류는 서버 말 대신 파일로 정함")
    p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(200, content=b"\xff\xd8\xff" + b"0" * (MAX_BYTES - 3))})
    ok(p.media == "image/jpeg" and p.data == b"\xff\xd8\xff" + b"0" * (MAX_BYTES - 3), "3.75MB 까지는 손대지 않고 그대로")
    p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(200, content=b"\xff\xd8\xff" + b"0" * MAX_BYTES)})
    ok(p.problem == "error" and p.block() is None, "그보다 큰데 깨진 사진이면 error")
    p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(200, content=b"\xff\xd8\xff" + b"0" * MAX_DOWNLOAD)})
    ok(p.problem == "big" and p.block() is None, "30MB 보다 크면 big")

    # ── 큰 사진은 서버에서 줄여서(긴 변 1568px JPEG) ──
    big = noise_photo(2600, 2000, "JPEG", orientation=6)  # 폰이 눕혀 저장하고 '세워서 보라'고 적어 둔 원본 사진
    ok(len(big) > MAX_BYTES, f"시험 사진이 3.75MB 보다 큼({len(big)})")
    p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(200, content=big)})
    fmt, size, mode = opened(p.data)
    ok(p.media == "image/jpeg" and not p.problem and len(p.data) <= MAX_BYTES and fmt == "JPEG" and mode == "RGB"
       and max(size) == MAX_SIDE and size[0] < size[1], f"폰 원본 사진은 줄여서 세운 채로 보냄: {size} {len(p.data)}")
    clear = Image.new("RGBA", (3000, 1500), (255, 0, 0, 255))
    clear.paste((0, 0, 0, 0), (0, 0, 1500, 1500))  # 왼쪽 반은 투명
    buf = io.BytesIO()
    clear.save(buf, "PNG")
    with Image.open(io.BytesIO(shrink(buf.getvalue()))) as small:
        left, right = small.getpixel((10, 10)), small.getpixel((small.width - 10, 10))
        ok(small.format == "JPEG" and small.size == (1568, 784) and min(left) > 240
           and right[0] > 200 and max(right[1:]) < 50, f"투명한 곳은 흰색으로: {small.size} {left} {right}")
    gif = io.BytesIO()
    Image.new("P", (2000, 1000), 3).save(gif, "GIF")
    ok(opened(shrink(gif.getvalue()))[:2] == ("JPEG", (1568, 784)), "GIF 도 첫 장을 JPEG 로")
    pixels, photo_mod.MAX_PIXELS = photo_mod.MAX_PIXELS, 100
    ok(shrink(gif.getvalue()) is None, "JPEG 가 아닌데 화소가 너무 많으면 None(메모리)")
    noise_png = noise_photo(1200, 1200, "PNG")
    ok(len(noise_png) > MAX_BYTES, f"시험 PNG 가 3.75MB 보다 큼({len(noise_png)})")
    p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(200, content=noise_png)})
    ok(p.problem == "big" and p.block() is None, "줄이지 못할 만큼 화소가 많으면 big")
    photo_mod.MAX_PIXELS = pixels
    p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(200, content=b"<html>login</html>")})
    ok(p.problem == "type", "사진이 아니면 type")
    for status in (403, 404, 500):
        p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(status, content=JPEG)})
        ok(p.problem == "error", f"HTTP {status} → error")
    p = await fetch({"/dna/abc/def/img.jpg": httpx.ConnectError("down")})
    ok(p.problem == "error", "연결 오류 → error")
    p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(302, headers={"location": "/dna/moved.jpg?credential=x"}),
                     "/dna/moved.jpg": httpx.Response(200, content=PNG)})
    ok(p.media == "image/png" and seen == [URL, "https://talk.kakaocdn.net/dna/moved.jpg?credential=x"],
       "카카오 CDN 안에서 옮긴 주소(상대 주소도)는 따라감")
    p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(301, headers={"location": "https://dn-m.talk.kakaocdn.net/b"}),
                     "/b": httpx.Response(200, content=GIF)})
    ok(p.media == "image/gif" and len(seen) == 2, "카카오 CDN 다른 주소로도")
    for outside in ("https://evil.example.com/x.jpg", "http://talk.kakaocdn.net/x.jpg", "https://127.0.0.1/x.jpg"):
        p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(302, headers={"location": outside}),
                         "/x.jpg": httpx.Response(200, content=JPEG)})
        ok(p.problem == "error" and seen == [URL], f"카카오 CDN 밖으로는 안 따라감: {outside}")
    p = await fetch({"/dna/abc/def/img.jpg": httpx.Response(302, headers={"location": "/a"}),
                     "/a": httpx.Response(302, headers={"location": "/b"}),
                     "/b": httpx.Response(302, headers={"location": "/c"}),
                     "/c": httpx.Response(200, content=JPEG)})
    ok(p.problem == "error" and len(seen) == 3, "옮기기는 두 번까지")

    # ── 본체: 사진 설명을 저장하고 답할 때 사진을 보여 줌 ──
    db = TestDB()
    tmp = Path(tempfile.mkdtemp())
    os.environ.update({
        "BOT_TOKEN": "tok-secret", "ANTHROPIC_API_KEY": "k", "DATABASE_URL": db.app_url,
        "PROMPT_PATH": str(ROOT / "prompt.md"), "KNOWLEDGE_DIR": str(tmp / "knowledge"), "EMBED_MODEL": "",
        "RECENT_TURNS": "3", "SUMMARY_TURNS": "10", "REPLY_WAIT_SECONDS": "0", "KAKAO_API_URL": "https://kapi.test",
    })
    from marong.agent import CAPTION_PROMPT, PHOTO_PROBLEMS, PHOTOS_KEPT, Agent, Incoming
    from marong.app import BotApp
    from marong.config import load_settings
    from marong.store import Store

    s = load_settings()
    store = Store(s.database_url)
    await store.open(wait=True)
    llm = ScriptedLLM(respond)
    agent = Agent(s, store, FakeEmbeddings(), llm)
    replies: list[str] = []

    async def send(t):
        replies.append(t)
        return True

    def rows(room):
        return db.admin("SELECT id, role, content, meta, reply_to FROM marong.messages WHERE room_key = %s ORDER BY id",
                        (room,))

    caption = "[사진] 접시에 국물 떡볶이랑 튀김이 담겨 있어"
    n = len(llm.bodies)
    r = await agent.handle(Incoming("r1", "u1", "", kakao_id="k1", photo=Photo("image/jpeg", JPEG)), send)
    cap, reply = llm.bodies[n], llm.bodies[n + 1]
    ok(len(llm.bodies) == n + 2 and cap["max_tokens"] == 4000 and cap["output_config"] == {"effort": "low"}
       and "system" not in cap and "tools" not in cap and cap["model"] == s.anthropic_model, "설명은 effort low 로 짧게")
    content = cap["messages"][0]["content"]
    ok(content[0] == Photo("image/jpeg", JPEG).block() and content[1] == {"type": "text", "text": CAPTION_PROMPT},
       "설명 요청에 사진과 설명 지시")
    (uid, role, saved, meta, _), (aid, arole, answer, ameta, reply_to) = rows("r1")
    ok(role == "user" and saved == caption, f"기록은 '[사진] 설명'(줄바꿈·빈칸 정리): {saved!r}")
    ok(meta == {"image": {"type": "image/jpeg", "bytes": len(JPEG), "tokens": [100, 20]}}, meta)
    last = reply["messages"][-1]["content"]
    ok(images(last) == [Photo("image/jpeg", JPEG).block()] and said(last).endswith(caption),
       "답할 때는 사진 자체와 설명을 같이 보여 줌")
    ok(r.startswith("응답:(") and r.endswith(caption) and arole == "assistant" and reply_to == uid and answer == r
       and not agent._photos, f"답한 뒤엔 들고 있던 사진을 버림: {r}")
    await agent.handle(Incoming("r1", "u1", "맛있겠지", kakao_id="k2"), send)
    msgs = llm.bodies[-1]["messages"]
    ok(all(isinstance(m["content"], str) for m in msgs) and caption in msgs[0]["content"],
       "지난 사진은 '[사진] 설명'으로만 보임")
    ok(all(URL not in str(x) and SECRET not in str(x) for x in rows("r1")), "사진 주소는 기록에 없음")

    # 못 연 사진: 설명을 부르지 않고 이유를 남김
    for photo, problem in ((Photo(problem="big"), "big"), (Photo(problem="type"), "type"), (Photo(), "error")):
        n = len(llm.bodies)
        await agent.handle(Incoming("r2", "u2", "", kakao_id=f"b{problem}", photo=photo), send)
        uid, role, saved, meta, _ = rows("r2")[-2]
        ok(len(llm.bodies) == n + 1 and saved == f"[사진] {PHOTO_PROBLEMS[problem]}" and meta == {"image": {"problem": problem}}
           and said(llm.bodies[-1]["messages"][-1]["content"]).endswith(PHOTO_PROBLEMS[problem])
           and not images(llm.bodies[-1]["messages"][-1]["content"]), f"못 연 사진({problem})은 그 까닭으로 답함")

    # 설명을 못 받으면(거절·오류) 그렇게 남기고, 답할 때는 사진을 그대로 보여 줌
    for mode in ("refuse", "fail"):
        CAPTION["mode"] = mode
        await agent.handle(Incoming("r3", "u3", "", kakao_id=f"c{mode}", photo=Photo("image/webp", WEBP)), send)
        uid, role, saved, meta, _ = rows("r3")[-2]
        ok(saved == f"[사진] {PHOTO_PROBLEMS['caption']}" and meta["image"]["problem"] == "caption"
           and meta["image"]["type"] == "image/webp" and images(llm.bodies[-1]["messages"][-1]["content"]),
           f"설명 {mode}: 기록엔 못 남겼다고, 답할 땐 사진을 봄 {meta}")
    CAPTION["mode"] = "ok"

    # 연달아 온 사진·말: 저장만 해 두었다가 마지막 말에 사진까지 한 번에
    await agent.handle(Incoming("r4", "u4", "", kakao_id="d1", photo=Photo("image/png", PNG)), send,
                       superseded=lambda: True)
    ok(len(agent._photos) == 1, "묶어 답할 사진은 잠깐 들고 있음")
    await agent.handle(Incoming("r5", "u5", "다른 방 말", kakao_id="e1"), send)
    ok(not images(llm.bodies[-1]["messages"][-1]["content"]) and len(agent._photos) == 1, "다른 방 답에는 안 보여 줌")
    await agent.handle(Incoming("r4", "u4", "이거 봐봐", kakao_id="d2"), send, superseded=lambda: False)
    last = llm.bodies[-1]["messages"][-1]["content"]
    ok(images(last) == [Photo("image/png", PNG).block()] and said(last).endswith(f"{caption}\n이거 봐봐")
       and not agent._photos, f"사진과 뒤의 말을 한 번에: {said(last)!r}")
    for i in range(PHOTOS_KEPT + 2):
        await agent.handle(Incoming("r6", "u6", "", kakao_id=f"f{i}", photo=Photo("image/gif", GIF)), send,
                           superseded=lambda: True)
    ok(len(agent._photos) == PHOTOS_KEPT, "들고 있는 사진 수에는 한도")
    await agent.handle(Incoming("r6", "u6", "다 봤어?", kakao_id="f99"), send, superseded=lambda: False)
    last = llm.bodies[-1]["messages"][-1]["content"]
    ok(len(images(last)) == PHOTOS_KEPT and said(last).count("[사진]") == PHOTOS_KEPT + 2 and not agent._photos,
       "한도를 넘은 앞 사진은 설명으로만")

    # ── BotApp: 사진 주소로 오면 바로 내려받기 시작, 답은 받은 순서대로, 주소는 저장·로그에 안 남김 ──
    callbacks: list[dict] = []
    gets: list[str] = []
    cdn_mode = {"v": "ok"}

    async def kakao(request: httpx.Request):
        if request.url.host.endswith("kakaocdn.net"):
            gets.append(str(request.url))
            await asyncio.sleep(0.3)  # 사진 받는 동안 친구가 말을 더 보냄
            if cdn_mode["v"] == "boom":
                raise RuntimeError("unexpected")
            return httpx.Response(200, content=JPEG)
        if request.url.path == "/v1/bot/callback":
            callbacks.append({"token": request.headers["X-Bot-Callback-Token"], "body": json.loads(request.content)})
            return httpx.Response(200, json={})
        return httpx.Response(404)

    def event(mid, room, content, token):
        return {"id": mid, "botGroupKey": room, "botUserKey": "u7", "content": content, "callbackToken": token,
                "isChannelChatroom": True}

    async def later(seconds, coro):
        await asyncio.sleep(seconds)
        await coro

    async with httpx.AsyncClient(transport=httpx.MockTransport(kakao)) as http:
        app = BotApp(s, agent, http)
        await asyncio.gather(app.on_dispatch("MESSAGE_CREATE", event("m1", "r7", URL, "cb1")),
                             later(0.05, app.on_dispatch("MESSAGE_CREATE", event("m2", "r7", "어때 맛있어 보여?", "cb2"))))
        got = rows("r7")
        ok([(x[1], x[2]) for x in got] == [("user", caption), ("user", "어때 맛있어 보여?"), ("assistant", "응답:어때 맛있어 보여?")],
           f"사진을 받는 동안 온 말도 받은 순서대로 저장하고 한 번에 답함: {got}")
        ok(gets == [URL] and [c["token"] for c in callbacks] == ["cb2"], f"사진은 한 번 받고, 답은 마지막 말에: {callbacks}")
        last = llm.bodies[-1]["messages"][-1]["content"]
        ok(images(last) == [Photo("image/jpeg", JPEG).block()] and said(last).endswith(f"{caption}\n어때 맛있어 보여?"),
           "답에 사진 자체도 보여 줌")
        cdn_mode["v"] = "boom"
        await app.on_dispatch("MESSAGE_CREATE", event("m3", "r8", URL, "cb3"))
        ok(rows("r8")[0][2] == f"[사진] {PHOTO_PROBLEMS['error']}" and callbacks[-1]["token"] == "cb3",
           "내려받다 예상 못 한 오류가 나도 안 열렸다고 답함")
        n = len(gets)
        await app.on_dispatch("MESSAGE_CREATE", event("m4", "r8", "https://example.com/a.jpg", "cb4"))
        ok(len(gets) == n and rows("r8")[-2][2] == "https://example.com/a.jpg", "다른 곳 주소는 그냥 말")

    joined = "\n".join(LOGS)
    for secret in (SECRET, "kakaocdn", "SIGSIG", "떡볶이", "맛있어", "tok-secret"):
        ok(secret not in joined, f"로그에 '{secret}'이(가) 남음")
    ok("photo=True" in joined and "photo_error RuntimeError" in joined and "photo_download status=404" in joined
       and "photo_shrunk image/jpeg" in joined and "photo_shrink_error" in joined
       and "photo_shrink too_many_pixels" in joined, "로그 자체는 남음(상태 코드·오류 종류·크기만)")

    await store.close()
    db.close()
    print(f"photo: all {CHECKS} checks passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    root = logging.getLogger()
    root.setLevel(logging.INFO)  # 서버와 같은 INFO 로그까지 모아서 주소·내용이 새지 않는지 봄
    for h in root.handlers:
        h.setLevel(logging.WARNING)
    root.addHandler(Collect())
    for noisy in ("httpx", "httpcore"):  # run.py 와 같게(요청 주소가 찍히는 줄은 숨김)
        logging.getLogger(noisy).setLevel(logging.WARNING)
    options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    asyncio.run(main(), **options)
