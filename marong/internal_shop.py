"""Call-side shopping uses the app's allowlisted search and read tools."""

import asyncio
import hmac
import json
import logging

from aiohttp import web

from .llm import server_tool_counts, text_of
from .shopping import MALLS, guide
from .web_search import sources_of


FAILED = {"ok": False, "reason": "failed"}
LIMIT = {"ok": False, "reason": "limit"}
LOOKUP_PATH = "/internal/shop-read"
LOOKUP_TIMEOUT_S = 20
log = logging.getLogger("marong.call_shop")


def product_result(text):
    if not isinstance(text, str):
        return FAILED
    text = text.strip()
    if text.startswith(("```json\n", "```\n")) and text.endswith("\n```"):
        text = text[text.index("\n") + 1:-4]
    try:
        data = json.loads(text)
    except ValueError:
        return FAILED
    if not isinstance(data, dict) or data.get("ok") is not True:
        return FAILED
    if any(not isinstance(data.get(key), str) for key in ("title", "price", "note")):
        return FAILED
    if not data["title"].strip() or not data["price"].strip():
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
            async with asyncio.timeout(LOOKUP_TIMEOUT_S), self.lock:
                result = await self.product(query.strip())
        except TimeoutError:
            log.info("call_shop_lookup result=timeout")
            result = FAILED
        except Exception as exc:
            log.info("call_shop_lookup result=provider_error error=%s", type(exc).__name__)
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
        tools = ([search] if search else []) + [fetch]
        messages = [{"role": "user", "content": query}]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + LOOKUP_TIMEOUT_S
        fetched_page = False
        for _ in range(2):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            reply = await self.llm.create({"model": self.model, "max_tokens": 650, "system": system,
                                           "tools": tools, "messages": messages}, remaining)
            searches, fetches = server_tool_counts(reply.usage)
            self.shop.spend(fetches)
            if self.search:
                self.search.spend(searches)
            fetched_page |= bool(sources_of(block for block in reply.content if block.type == "web_fetch_tool_result"))
            if reply.stop_reason == "pause_turn":
                messages = [*messages, {"role": "assistant", "content": reply.content}]
                continue
            if reply.stop_reason not in ("end_turn", "stop_sequence"):
                break
            if not fetched_page:
                log.info("call_shop_lookup result=no_verified_page")
                return FAILED
            result = product_result(text_of(reply))
            log.info("call_shop_lookup result=%s", "ok" if result["ok"] else "invalid_summary")
            return result
        log.info("call_shop_lookup result=incomplete")
        return FAILED
