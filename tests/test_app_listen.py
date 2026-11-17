"""TC-178 listening API against isolated Postgres, fake Access and synthetic audio fixtures."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import httpx
import psycopg
from aiohttp.test_utils import TestClient, TestServer

from test_app_chat import AUD, HK_EMAIL, ORIGIN, STRANGER, TEAM, Certs, auth, prepare, problem
from marong.access import AccessConfig, AccessVerifier
from marong.app_chat import AppChat
from marong.discord_store import DiscordStore
from marong.listen import load_test, public_sentence
from pg import TestDB
from tools.listen_test import create_test, results

API = "/chat/listen/api"
TEST = "fixture-20261117"
BYTES = b"synthetic m4a response for the API fixture"


def make_fixture(path):
    sentences = path / "sentences.txt"
    sentences.write_text("\n".join(f"시험 문장 {n}을 들었어." for n in range(1, 11)), "utf-8")
    candidates = {name: path / f"candidate-{i}" for i, name in enumerate(
        ("fixture-hidden-model-a", "fixture-hidden-model-b", "fixture-hidden-model-c"))}
    for folder in candidates.values():
        folder.mkdir()
        for n in range(1, 11):
            (folder / f"{n:02d}.wav").write_bytes(b"synthetic fixture")
    root = path / "public"
    key = path / "key.json"
    with patch("tools.listen_test._encode", side_effect=lambda _source, dest, *_: dest.write_bytes(BYTES)):
        assert create_test(TEST, sentences, candidates, root, key) == 30
    manifest = load_test(root)
    assert len(manifest["sentences"]) == 10
    assert set(manifest) == {"testId", "sentences"}
    clips = [clip for row in manifest["sentences"] for clip in row["clips"]]
    assert len(set(clips)) == 30
    assert set(json.loads(key.read_text("utf-8"))["clips"]) == set(clips)
    assert len([p for p in (root / TEST).iterdir() if p.suffix == ".m4a"]) == 30
    assert "fixture-hidden-model" not in (root / "current.json").read_text("utf-8")
    assert "fixture-hidden-model" in key.read_text("utf-8")
    for number, row in enumerate(manifest["sentences"], 1):
        assert row["no"] == number
    return root, key, manifest


async def checks(http, db, store, root, key, manifest):
    path = API + "/test"
    one, two, _ = manifest["sentences"][0]["clips"]
    clip_path = f"{API}/clips/{one}"
    body = {"testId": TEST, "score": 3, "marongLike": False}
    answer_path = f"{API}/answers/{one}"
    headers = auth(write=True)

    async def answer(payload, *, clip=one, credentials=headers):
        return await http.put(f"{API}/answers/{clip}", headers=credentials, json=payload)

    db.admin("UPDATE marong.discord_dm_links SET channel_id='200000000000000010',last_incoming_at=now() "
             "WHERE friend_id=2")
    for route in (path, clip_path):
        await problem(await http.get(route), 401, "unauthenticated")
        await problem(await http.get(route, headers=auth(STRANGER)), 403, "not_allowed")
    await problem(await answer(body, credentials={"Origin": ORIGIN}), 401, "unauthenticated")
    await problem(await answer(body, credentials=auth(STRANGER, write=True)), 403, "not_allowed")
    await problem(await answer(body, credentials=auth(write=True, origin="https://other.test")), 403, "cross_site")
    for error, status, code in ((psycopg.OperationalError("synthetic"), 503, "db_unavailable"),
                                (RuntimeError("synthetic"), 500, "internal")):
        with patch.object(store, "app_login", side_effect=error):
            for route in (path, clip_path):
                await problem(await http.get(route, headers=headers), status, code)
            await problem(await answer(body), status, code)
    response = await http.get(path, headers=headers)
    assert response.status == 200 and response.headers["Cache-Control"] == "no-store"
    text = await response.text()
    assert "fixture-hidden-model" not in text
    read = json.loads(text)["test"]
    assert read["sentences"] == [public_sentence(TEST, 2, row, {}) for row in manifest["sentences"]]
    assert any(public_sentence(TEST, 1, row, {}) != public_sentence(TEST, 2, row, {}) for row in manifest["sentences"])
    assert await (await http.get(path, headers=headers)).json() == {"test": read}
    response = await http.get(clip_path, headers=headers)
    assert response.status == 200 and response.content_type == "audio/mp4" and await response.read() == BYTES
    assert response.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    partial = await http.get(clip_path, headers={**headers, "Range": "bytes=0-3"})
    assert partial.status == 206 and await partial.read() == BYTES[:4]

    for missing in ("bad", "zzzzzzzzzzzzzzzz"):
        await problem(await http.get(f"{API}/clips/{missing}", headers=headers), 404, "not_found")
        await problem(await answer(body, clip=missing), 404, "not_found")
    for bad_body in ({**body, "score": True}, {**body, "score": 6}, {**body, "marongLike": 1}, {"score": 3}):
        await problem(await answer(bad_body), 400, "invalid_request")
    await problem(await answer({**body, "testId": "fixture-old"}), 409, "stale_test")

    first = await answer({**body, "marongLike": True})
    assert first.status == 200 and sum(clip["marongLike"] for clip in (await first.json())["clips"]) == 1
    second = await answer({**body, "score": 5, "marongLike": True}, clip=two)
    second_data = {item["id"]: item for item in (await second.json())["clips"]}
    assert second_data[two]["marongLike"] and not second_data[one]["marongLike"]
    third = await answer({**body, "score": 4}, clip=two)
    assert third.status == 200
    replies = await asyncio.gather(answer({**body, "marongLike": True}),
                                   answer({**body, "score": 1, "marongLike": True}, clip=two))
    for item in replies:
        assert item.status == 200 and sum(item["marongLike"] for item in (await item.json())["clips"]) == 1
    assert db.admin("SELECT count(*) FROM marong.listen_scores WHERE marong_like") == [(1,)]
    with psycopg.connect(db.app_url) as conn:
        aggregated = results(conn, key)
    assert sum(row[2] for row in aggregated) == 2 and sum(row[3] for row in aggregated) == 1

    active = root / "current.json"
    active.rename(root / "inactive.json")
    assert await (await http.get(path, headers=headers)).json() == {"test": None}
    await problem(await answer(body), 409, "stale_test")
    await problem(await http.get(clip_path, headers=headers), 404, "not_found")


async def run(db, parent):
    root, key, manifest = make_fixture(parent)
    async with httpx.AsyncClient(transport=httpx.MockTransport(Certs())) as client:
        store = DiscordStore(db.app_url, call_bridge=True)
        await store.open(wait=True)
        access = AccessVerifier(AccessConfig(TEAM, AUD, frozenset({HK_EMAIL})), client)
        try:
            with patch.dict(os.environ, {"MARONG_LISTEN_DIR": str(root)}):
                chat = AppChat(store, None, None, access, None, origin=ORIGIN)
                async with TestClient(TestServer(chat.web_app())) as http:
                    assert (await http.get("/chat/listen/")).status == 200
                    assert (await http.get("/chat/listen/listen.js")).content_type == "text/javascript"
                    await checks(http, db, store, root, key, manifest)
        finally:
            await store.close()


if __name__ == "__main__":
    db = TestDB()
    try:
        prepare(db)
        with tempfile.TemporaryDirectory() as path:
            asyncio.run(run(db, Path(path)))
    finally:
        db.close()
    print("TC-178 listening API: blinded IDs, isolation, audio/Range, validation, concurrent answers and aggregation verified")
