"""Local-only unified account screen fixture with a temporary Postgres database."""

import argparse
import asyncio
from datetime import timedelta
import hashlib
from pathlib import Path
import secrets
import sys
from types import SimpleNamespace

from aiohttp import web


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions
from marong.unified_store import UnifiedStore
from pg import TestDB
from run_app import RoomLocks


async def serve(port):
    db = TestDB()
    store = UnifiedStore(db.app_url)
    runner = chat = None
    try:
        db.apply_unified_prerequisites()
        db.apply_unified()
        await store.open(wait=True)
        origin = f"http://127.0.0.1:{port}"
        admin_hash = hashlib.sha256(b"test-browser").hexdigest()
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22))
        fresh, _ = await sessions.create_invite("join")
        used, _ = await sessions.create_invite("join")
        await sessions.join(used, "시험친구 가", "웹")
        expired, _ = await sessions.create_invite("join")
        async with store.pool.connection() as conn:
            await conn.execute("UPDATE marong.invites SET expires_at=created_at+interval '1 second' "
                               "WHERE used_at IS NULL AND id=(SELECT max(id) FROM marong.invites)")
        legacy = db.admin("INSERT INTO marong.friends(name) VALUES ('시험친구 나') RETURNING id")[0][0]
        link, _ = await sessions.create_invite("link", legacy)
        code, _ = await sessions.create_device_code(1)

        async def verify(token):
            return ("ok", admin_hash) if token == "test-browser" else ("not_allowed", None)

        async def reply(msg, delivered):
            line = "합성 대답이야."
            await store.add_message(msg.room_key, "assistant", line, reply_to=msg.presaved_id,
                                    meta={"delivered": True, "transport": "app"})
            chat.pulse()
            return line

        agent = SimpleNamespace(friend_cards=None, handle=reply)
        chat = AppChat(store, agent, RoomLocks(), SimpleNamespace(check=verify), AppPush(store), origin=origin,
                       sessions=sessions, authentication="session", admin_email_hash=admin_hash)
        app = chat.web_app()

        @web.middleware
        async def local_admin(req, handler):
            if req.path.startswith("/chat/admin/") and req.cookies.get("fixture_admin") == "on":
                req = req.clone(headers={**req.headers, "Cf-Access-Jwt-Assertion": "test-browser"})
            return await handler(req)

        app.middlewares.insert(0, local_admin)

        async def index(req):
            body = '\n'.join(
                f'<li><a href="/chat/join/{token}">{label}</a></li>'
                for label, token in (("새 가입", fresh), ("기존 계정", link), ("사용 완료", used),
                                     ("기간 지남", expired), ("없는 주소", "missing"))
            )
            return web.Response(content_type="text/html", text=f"""<!doctype html>
                <html lang="ko"><meta charset="utf-8"><h1>마롱이 합성 시험</h1><ul>{body}</ul>
                <a href="/chat/login">기기 로그인</a> <p>시험 코드 {code}</p>
                <a href="/chat/admin/">관리자 권한 없음</a>
                <a href="/fixture-admin">관리자 시험 열기</a></html>""")

        async def admin(req):
            response = web.HTTPFound("/chat/admin/")
            response.set_cookie("fixture_admin", "on", httponly=True, samesite="Strict", path="/chat/admin/")
            return response

        async def face(req):
            path = ROOT / "marong" / "call" / "static" / "face" / "v1" / req.match_info["file"]
            return web.FileResponse(path)

        app.router.add_get("/", index)
        app.router.add_get("/fixture-admin", admin)
        app.router.add_get("/face/v1/{file:(?:01-neutral|13-concerned)\\.webp}", face)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        print("unified browser fixture ready", flush=True)
        await asyncio.sleep(timedelta(minutes=20).total_seconds())
    finally:
        if runner:
            await runner.cleanup()
        if chat:
            await chat.close()
        await store.close()
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18796)
    asyncio.run(serve(parser.parse_args().port))
