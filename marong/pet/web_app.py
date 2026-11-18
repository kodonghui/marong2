"""Serve the pet web app and its public static documents (TASK-370)."""

from pathlib import Path

from aiohttp import web


STATIC = Path(__file__).with_name("static")
ASSETS = {
    "pet.css", "pet.js", "home.js", "creation.js", "member.js", "diary.js", "pet.webmanifest", "pet-icon.png",
    "pet-welcome.webp", "report.js",
}
LEGAL = {"terms.html", "privacy.html", "overseas.html"}
HEADERS = {
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                               "img-src 'self' blob: data:; object-src 'none'; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'self'",
}


def register(app, *, legal_dir=None):
    async def page(_request):
        return web.FileResponse(STATIC / "index.html", headers=HEADERS)

    async def asset(request):
        name = request.match_info["file"]
        path = STATIC / name
        if name not in ASSETS or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers=HEADERS)

    async def worker(_request):
        return web.FileResponse(STATIC / "pet-worker.js", headers=HEADERS)

    async def legal(request):
        name = request.match_info["file"]
        if legal_dir is None or name not in LEGAL:
            raise web.HTTPNotFound()
        path = Path(legal_dir) / name
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={**HEADERS, "Content-Type": "text/html; charset=utf-8"})

    app.router.add_get("/static/legal/{file}", legal)
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
