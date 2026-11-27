"""TC-539 child process: real app startup on loopback with synthetic catalog and fakes."""
import asyncio
import logging
from dataclasses import replace
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from aiohttp import ClientSession
import run_app
from fakes import FakeEmbeddings, ScriptedLLM, message, text
from marong.app_chat import AppChat
from marong.config import load_settings
from marong.decor import DecorCatalog

class FakeLLM(ScriptedLLM):
    async def close(self):
        pass

async def main():
    database, catalog_root = sys.argv[1:]
    settings = replace(load_settings(), database_url=database, timezone='Asia/Seoul')
    ready, stop = asyncio.Future(), asyncio.Event()
    listen = AppChat.serve
    async def start_http(chat):
        runner = await listen(chat)
        ready.set_result(runner.addresses[0][1])
        return runner
    fake = FakeLLM(lambda _: message([text('합성 응답')]))
    access = SimpleNamespace(check=AsyncMock(return_value=('ok', 'a' * 64)))
    with patch.dict(os.environ, {'MARONG_DECOR': '1', 'MARONG_ADMIN_EMAIL_SHA256': 'a' * 64}, clear=True), \
         patch.object(run_app, 'LLM', return_value=fake), \
         patch.object(run_app, 'Embeddings', return_value=FakeEmbeddings()), \
         patch.object(run_app, 'DecorCatalog', side_effect=lambda: DecorCatalog(catalog_root)), \
         patch.object(run_app, 'AccessVerifier', return_value=access), \
         patch.object(AppChat, 'serve', new=start_http):
        runtime = asyncio.create_task(run_app.serve(settings, ROOT / 'tests',
            {'origin': 'https://fixture.invalid', 'port': 0, 'ring': False, 'fcm': None, 'access': None},
            b's' * 32, 'session', 'bot', stop))
        try:
            port = await asyncio.wait_for(ready, 15)
            async with ClientSession(base_url=f'http://127.0.0.1:{port}') as client:
                async with client.get('/chat/admin/api/items', headers={'Cf-Access-Jwt-Assertion':'fixture'}) as response:
                    assert response.status == 200
                    items = (await response.json())['items']
                    assert len(items) == 8
                    assert sum(item['state'] == 'listed' for item in items) == 7
                    assert next(item for item in items if item['id'] == 'bad-fixture')['state'] == 'new'
            print('TC-539 child: listed=7 new=1')
        finally:
            stop.set()
            await asyncio.wait_for(runtime, 15)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
