"""The call relay reaches the loopback app service for product reads."""

import asyncio
from functools import partial
import os

from aiohttp import ClientSession


DECLARATION = {"name": "shop_read", "description": "쇼핑몰의 상품, 가격과 요점 확인.",
               "parameters": {"type": "OBJECT", "properties": {"query": {"type": "STRING"}},
                              "required": ["query"]}}
FAILED = {"ok": False, "reason": "failed"}
LIMIT = {"ok": False, "reason": "limit"}
READS = 3


async def fetch_product(query, *, url, secret):
    try:
        async with asyncio.timeout(20), ClientSession() as http:
            async with http.post(url, json={"query": query}, headers={"X-Marong-Internal": secret},
                                 allow_redirects=False) as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, dict) and type(data.get("ok")) is bool:
                        return data
    except Exception:
        pass
    return FAILED


def configured_reader(env=os.environ):
    if env.get("MARONG_CALL_SHOP") != "1":
        return None
    secret = env.get("MARONG_INTERNAL_SECRET", "")
    if not secret:
        return None
    port = int(env.get("MARONG_APP_INTERNAL_PORT", "8796"))
    return partial(fetch_product, url=f"http://127.0.0.1:{port}/internal/shop-read", secret=secret)
