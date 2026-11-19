"""Verify the internal shopping contract and its call quota with local fakes."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from call_shop import FAILED, LIMIT, configured_reader, fetch_product
from live_session import LiveSession
from marong.internal_shop import InternalShop, LOOKUP_PATH
from marong.shopping import ShopFetch
from fakes import ScriptedLLM, message, text


async def main():
    with TemporaryDirectory() as temp, patch.object(Path, "home", return_value=Path(temp)):
        import server

    secret = "fixture-internal"
    product = '{"ok":true,"title":"Fixture product","price":"100","points":["fixture"],"note":""}'
    llm = ScriptedLLM(lambda _: message([text(product)], usage={
        "input_tokens": 1, "output_tokens": 1, "server_tool_use": {"web_fetch_requests": 1},
    }))
    shop = ShopFetch(daily=3)
    internal = InternalShop(llm, None, shop, "fixture", secret)
    app = web.Application()
    app.router.add_post(LOOKUP_PATH, internal.read)
    async with TestClient(TestServer(app)) as client:
        url = str(client.make_url(LOOKUP_PATH))
        assert await fetch_product("fixture", url=url, secret="wrong") == FAILED
        assert not llm.bodies
        live = LiveSession(None, "fixture", None, None, None, None, {}, {}, "fixture", "fixture", "fixture", "fixture")
        live.shop = configured_reader({"MARONG_CALL_SHOP": "1", "MARONG_INTERNAL_SECRET": secret,
                                      "MARONG_APP_INTERNAL_PORT": str(client.server.port)})
        for _ in range(3):
            result = await live.shop_read({"query": "Fixture product"})
            assert result["ok"] and result["title"] == "Fixture product"
        assert await live.shop_read({"query": "Fixture product"}) == LIMIT
        assert await fetch_product("fixture", url=url, secret=secret) == LIMIT
        assert len(llm.bodies) == shop.used == live.resume["shop_reads"] == 3

    assert configured_reader({"MARONG_CALL_SHOP": "0"}) is None
    with patch.object(server, "SHOP", None):
        parts = server.setup()["setup"]
        assert not any("shop_read" == tool["name"] for group in parts.get("tools", [])
                       for tool in group.get("functionDeclarations", []))
    with patch.object(server, "SHOP", live.shop):
        parts = server.setup()["setup"]
        assert any("shop_read" == tool["name"] for group in parts["tools"]
                   for tool in group.get("functionDeclarations", []))
        assert "못 찾았다고 말해" in parts["systemInstruction"]["parts"][0]["text"]

    await live.wait_signal("tool")
    assert live.output.empty()
    live.wait_enabled = True
    await live.wait_signal("tool")
    assert (await live.output.get())[1] == {"type": "wait", "on": True, "reason": "tool"}
    await live.wait_signal()
    assert (await live.output.get())[1] == {"type": "wait", "on": False}
    print("PASS TC-477 and TC-479 local route, secret, quota, result and audio control")


if __name__ == "__main__":
    asyncio.run(main())
