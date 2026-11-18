"""Serve the pet web app and its public static documents (TASK-370)."""

import re
from pathlib import Path

from aiohttp import web

from .push import SENDER

STATIC = Path(__file__).with_name("static")
DIARY_STATIC = STATIC.parents[1] / "app_chat_static" / "diary"
DIARY_ASSETS = {
    "Gaegu-Regular.woff2": "font/woff2",
    "Gaegu-OFL.txt": "text/plain; charset=utf-8",
}
VOICE_STATIC = STATIC.parents[2] / "tools" / "vertex_live" / "static"
BACKGROUNDS = STATIC.parents[2] / "design" / "pet" / "backgrounds"
WORKLETS = {"call-capture.js": "capture.js", "call-playback.js": "playback.js"}
SAFE_HOST = re.compile(r"^[a-zA-Z0-9.-]+(?::[0-9]{1,5})?$")
ASSETS = {
    "pet.css", "pet.js", "home.js", "creation.js", "member.js", "diary.js", "pet.webmanifest", "pet-icon.png",
    "pet-welcome.webp", "report.js", "orders.js", "settings.js", "call.js", "closet.js", "shop.js", "diary-decor.js",
    "push-control.js",
}
LEGAL = {"terms.html", "privacy.html", "overseas.html"}
HEADERS = {
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                               "img-src 'self' blob: data:; object-src 'none'; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'self'",
}


def register(app, *, legal_dir=None, item_dir=None):
    item_root = (Path(item_dir) if item_dir else STATIC / "items").resolve()
    async def page(request):
        headers = HEADERS
        if request.path.endswith("/call") and SAFE_HOST.fullmatch(request.host):
            csp = HEADERS["Content-Security-Policy"]
            headers = {**HEADERS, "Content-Security-Policy": f"{csp}; connect-src 'self' wss://{request.host} ws://{request.host}"}
        return web.FileResponse(STATIC / "index.html", headers=headers)

    async def asset(request):
        name = request.match_info["file"]
        if name in DIARY_ASSETS:
            path = DIARY_STATIC / name
            if not path.is_file():
                raise web.HTTPNotFound()
            return web.FileResponse(path, headers={**HEADERS, "Content-Type": DIARY_ASSETS[name]})
        path = VOICE_STATIC / WORKLETS[name] if name in WORKLETS else STATIC / name
        if (name not in ASSETS and name not in WORKLETS) or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers=HEADERS)

    async def worker(_request):
        return web.FileResponse(STATIC / "pet-worker.js", headers=HEADERS)

    async def push_key(_request):
        key = getattr(app.get(SENDER), "public_key", None)
        return web.json_response({"publicKey": key}, headers={**HEADERS, "Cache-Control": "no-store"})

    async def thumbnail(request):
        path = (item_root / request.match_info["id"] / "thumb.webp").resolve()
        if not path.is_relative_to(item_root) or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={**HEADERS, "Content-Type": "image/webp"})

    async def background(request):
        path = BACKGROUNDS / (request.match_info["name"] + ".webp")
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={**HEADERS, "Content-Type": "image/webp"})

    async def stages(_request):
        path = BACKGROUNDS / "stages.json"
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={**HEADERS, "Content-Type": "application/json"})

    async def legal(request):
        name = request.match_info["file"]
        if legal_dir is None or name not in LEGAL:
            raise web.HTTPNotFound()
        path = Path(legal_dir) / name
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={**HEADERS, "Content-Type": "text/html; charset=utf-8"})

    app.router.add_get("/static/legal/{file}", legal)
    app.router.add_get(r"/static/items/{id:[0-9a-fA-F-]{36}}/thumb.webp", thumbnail)
    app.router.add_get(r"/static/backgrounds/{name:[a-z0-9_]{1,40}}.webp", background)
    app.router.add_get("/static/backgrounds/stages.json", stages)
    app.router.add_get("/static/push-key.json", push_key)
    app.router.add_get("/static/{file}", asset)
    app.router.add_get("/pet-worker.js", worker)
    app.router.add_get("/", page)
    app.router.add_get("/signup", page)
    app.router.add_get("/create", page)
    app.router.add_get(r"/create/{id:[0-9a-fA-F-]{36}}/{stage:traits|preview|candidates|name}", page)
    app.router.add_get(r"/pets/{id:[0-9a-fA-F-]{36}}", page)
    app.router.add_get(r"/pets/{id:[0-9a-fA-F-]{36}}/{screen:call|diary|closet|settings|farewell}", page)
    app.router.add_get(r"/pets/{id:[0-9a-fA-F-]{36}}/diary/{day:[0-9-]{10}}", page)
    app.router.add_get("/shop", page)
    app.router.add_get(r"/shop/{id:[0-9a-fA-F-]{36}}", page)
    app.router.add_get("/me", page)
    app.router.add_get(r"/me/{screen:plan|orders}", page)
    app.router.add_get("/pay/return", page)
