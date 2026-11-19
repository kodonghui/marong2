"""Authenticated read and answer routes for SCR-119 (API-121–123)."""

import os
from pathlib import Path

from aiohttp import web

from .app_chat import Problem, bad
from .listen import CLIP_ID, DEFAULT_DIR, MAX_CLIP_BYTES, TEST_ID, load_test, public_sentence

BASE = "/chat/listen/"
STATIC = Path(__file__).with_name("app_chat_static") / "listen"
ASSETS = {"listen.css": "text/css", "listen.js": "text/javascript"}


def _not_found():
    return Problem("not_found", title="지금 시험 묶음에 없는 소리 id")


class AppListen:
    def __init__(self, chat, directory=None):
        self.chat = chat
        self.store = chat.store
        self.root = Path(directory or os.getenv("MARONG_LISTEN_DIR", DEFAULT_DIR))

    async def test(self, req):
        friend = (await self.chat._who(req))["friend_id"]
        manifest = load_test(self.root)
        if not manifest:
            return self.chat._json(200, {"test": None})
        test_id = manifest["testId"]
        rows = await self.store._all(
            "SELECT clip_id,score,marong_like FROM marong.listen_scores WHERE test_id=%s AND friend_id=%s",
            (test_id, friend),
        )
        answers = {row["clip_id"]: row for row in rows}
        sentences = [public_sentence(test_id, friend, s, answers) for s in manifest["sentences"]]
        return self.chat._json(200, {"test": {"testId": test_id, "sentences": sentences}})

    def _sentence(self, manifest, clip):
        if CLIP_ID.fullmatch(clip) and manifest:
            for sentence in manifest["sentences"]:
                if clip in sentence["clips"]:
                    return sentence
        raise _not_found()

    async def clip(self, req):
        await self.chat._who(req)
        clip = req.match_info["clip"]
        manifest = load_test(self.root)
        self._sentence(manifest, clip)
        root = self.root.resolve()
        source = root / manifest["testId"] / f"{clip}.m4a"
        if source.resolve() != source or not source.is_file() or not 0 < source.stat().st_size <= MAX_CLIP_BYTES:
            raise _not_found()
        req["cache"] = "private, max-age=31536000, immutable"
        return web.FileResponse(source, headers={"Content-Type": "audio/mp4"})

    async def answer(self, req):
        friend = (await self.chat._who(req, write=True))["friend_id"]
        clip = req.match_info["clip"]
        data = await self.chat._body(req)
        test_id, score, like = data.get("testId"), data.get("score"), data.get("marongLike")
        if set(data) != {"testId", "score", "marongLike"}:
            raise bad(("body", "bad_format"))
        if not isinstance(test_id, str) or not TEST_ID.fullmatch(test_id):
            raise bad(("testId", "bad_format"))
        if score is not None and (type(score) is not int or not 1 <= score <= 5):
            raise bad(("score", "out_of_range"))
        if type(like) is not bool:
            raise bad(("marongLike", "bad_format"))
        if not CLIP_ID.fullmatch(clip):
            raise _not_found()
        manifest = load_test(self.root)
        if not manifest or manifest["testId"] != test_id:
            raise Problem("stale_test")
        sentence = self._sentence(manifest, clip)
        no = sentence["no"]
        async with self.store.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"listen:{test_id}:{friend}:{no}",))
            current = load_test(self.root)
            if not current or current["testId"] != test_id:
                raise Problem("stale_test")
            if like:
                await conn.execute(
                    """UPDATE marong.listen_scores SET marong_like=false,updated_at=now()
                    WHERE test_id=%s AND friend_id=%s AND sentence_no=%s AND marong_like AND clip_id<>%s""",
                    (test_id, friend, no, clip),
                )
            await conn.execute(
                """INSERT INTO marong.listen_scores(test_id,friend_id,clip_id,sentence_no,score,marong_like)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (test_id,friend_id,clip_id)
                DO UPDATE SET score=EXCLUDED.score,marong_like=EXCLUDED.marong_like,updated_at=now()""",
                (test_id, friend, clip, no, score, like),
            )
            cur = await conn.execute(
                """SELECT clip_id,score,marong_like FROM marong.listen_scores
                WHERE test_id=%s AND friend_id=%s AND sentence_no=%s""", (test_id, friend, no),
            )
            answers = {row["clip_id"]: row for row in await cur.fetchall()}
        return self.chat._json(200, public_sentence(test_id, friend, sentence, answers))

    async def page(self, req):
        return web.FileResponse(STATIC / "index.html", headers={"Content-Type": "text/html; charset=utf-8"})

    async def file(self, req):
        name = req.match_info["name"]
        return web.FileResponse(STATIC / name, headers={"Content-Type": ASSETS[name]})

    def register(self, app):
        app.router.add_get(BASE, self.page)
        app.router.add_get(BASE + r"{name:listen\.(?:js|css)}", self.file)
        app.router.add_get(BASE + "api/test", self.test, allow_head=False)
        app.router.add_get(BASE + "api/clips/{clip}", self.clip)
        app.router.add_put(BASE + "api/answers/{clip}", self.answer)
