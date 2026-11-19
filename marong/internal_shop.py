"""Call-side shopping uses the app's allowlisted search and read tools."""

import asyncio
import hmac
import json

from aiohttp import web

from .llm import server_tool_counts, text_of
from .shopping import MALLS, guide


FAILED = {"ok": False, "reason": "failed"}
LIMIT = {"ok": False, "reason": "limit"}
LOOKUP_PATH = "/internal/shop-read"


def product_result(text):
    if not isinstance(text, str):
        return FAILED
    try:
        data = json.loads(text.strip())
    except ValueError:
        return FAILED
    if not isinstance(data, dict) or data.get("ok") is not True:
        return FAILED
    if any(not isinstance(data.get(key), str) for key in ("title", "price", "note")):
        return FAILED
    points = data.get("points")
    if not isinstance(points, list) or any(not isinstance(point, str) for point in points):
        return FAILED
    return {"ok": True, "title": data["title"][:100], "price": data["price"][:40],
            "points": [point[:105] for point in points[:3]], "note": data["note"][:80]}


class InternalShop:
    def __init__(self, llm, search, shop, model, secret):
        self.llm = llm
        self.search = search
        self.shop = shop
        self.model = model
        self.secret = secret.encode()
        self.lock = asyncio.Lock()

    async def read(self, request):
        peer = request.transport.get_extra_info("peername") if request.transport else None
        provided = request.headers.get("X-Marong-Internal", "").encode()
        if not peer or peer[0] != "127.0.0.1" or not self.secret or not hmac.compare_digest(provided, self.secret):
            raise web.HTTPForbidden()
        try:
            data = await request.json()
        except (ValueError, UnicodeError):
            return web.json_response(FAILED, status=400)
        query = data.get("query") if isinstance(data, dict) else None
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 600:
            return web.json_response(FAILED, status=400)
        try:
            async with asyncio.timeout(20), self.lock:
                result = await self.product(query.strip())
        except Exception:
            result = FAILED
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def product(self, query):
        fetch = self.shop.tool() if self.shop else None
        if fetch is None:
            return LIMIT
        search = self.search.tool() if self.search else None
        if search:
            search = {**search, "allowed_domains": list(MALLS)}
        system = (guide(bool(search), True) + "\n상품 페이지를 실제로 읽고 결과만 JSON으로 써. "
                  '형식은 {"ok":true,"title":"","price":"","points":[],"note":""}. '
                  '확인하지 못했으면 {"ok":false}라고 써.')
        reply = await self.llm.create({"model": self.model, "max_tokens": 650, "system": system,
                                       "tools": ([search] if search else []) + [fetch],
                                       "messages": [{"role": "user", "content": query}]}, 20)
        searches, fetches = server_tool_counts(reply.usage)
        self.shop.spend(fetches)
        if self.search:
            self.search.spend(searches)
        return product_result(text_of(reply)) if fetches else FAILED
