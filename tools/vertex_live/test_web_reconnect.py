"""TC-643: overlap the previous server connection with a browser reconnect."""

import asyncio
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
import uuid

from aiohttp import web, WSMsgType
from aiohttp.test_utils import TestClient, TestServer


class VoiceTestServer(TestServer):
    async def _make_runner(self, **options):
        # Match web.run_app: a disconnected transport does not cancel the handler.
        options['handler_cancellation'] = False
        return await super()._make_runner(**options)


class FixtureLive:
    def __init__(self, ws, owner, store, person, setup, headers, resume, diagnostics, location, model,
                 voice, client_id, **options):
        self.ws = ws
        self.owner = owner
        self.p = person
        self.resume = resume
        self.d = diagnostics
        self.voice = voice
        self.call_id = resume.get('call_id') or str(uuid.uuid4())
        self.stop = asyncio.Event()
        self.explicit = False
        self.rtc = None
        self.hold_close = False

    async def read(self):
        async for frame in self.ws:
            if frame.type == WSMsgType.TEXT and frame.json().get('type') == 'stop':
                self.explicit = True
                return
        # The browser sees its socket close while this handler still owns the slot.
        if self.hold_close:
            await self.stop.wait()

    async def run(self):
        await self.ws.send_json({'type': 'ready', 'callId': self.call_id, 'memoryConnected': True})
        reader = asyncio.create_task(self.read())
        stopped = asyncio.create_task(self.stop.wait())
        try:
            await asyncio.wait((reader, stopped), return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (reader, stopped):
                task.cancel()
            await asyncio.gather(reader, stopped, return_exceptions=True)
            self.resume.update(owner=self.owner, call_id=self.call_id, updated=time.time())


async def test_api(client, server, headers):
    client_id = str(uuid.uuid4())
    first = await client.ws_connect('/live', params={'client': client_id}, headers=headers)
    original = await first.receive_json(timeout=3)
    previous = server.active_calls[1].session
    previous.hold_close = True
    await asyncio.gather(previous.ws.close(), first.receive())

    async with client.ws_connect('/live', params={'client': str(uuid.uuid4())}, headers=headers) as other:
        duplicate = await other.receive_json(timeout=3)
        assert duplicate['type'] == 'call_busy', duplicate
    async with client.ws_connect('/live', params={'client': client_id}, headers=headers) as replacement:
        resumed = await replacement.receive_json(timeout=3)
        assert resumed['type'] == 'ready', f"same client got {resumed['type']}"
        assert resumed['callId'] == original['callId']
        assert not previous.explicit
        assert server.active_calls[1].session.ws is not previous.ws
        status = await (await client.get('/status', headers=headers)).json()
        assert status['active']
        await replacement.send_json({'type': 'stop'})
    print('PASS TC-643 API: different client excluded, same client admitted at capacity, same call ID')


async def test_browsers(client, server, end_requests):
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        profiles = (
            ('iPhone WebKit', playwright.webkit, playwright.devices['iPhone 15']),
            ('Android Chrome profile', playwright.chromium, playwright.devices['Pixel 7']),
            ('desktop Chromium', playwright.chromium, playwright.devices['Desktop Chrome']),
        )
        errors = []
        for index, (label, engine, profile) in enumerate(profiles, 2):
            async with await engine.launch() as browser:
                context = await browser.new_context(**profile)
                await context.add_cookies([{'name': 'fixture_account', 'value': str(index), 'url': str(client.make_url('/'))}])
                # Windows WebKit ships without Web Audio. Keep the worker and WebSocket real.
                await context.add_init_script('''
                    if (!window.AudioContext && !window.webkitAudioContext) {
                        window.fixtureAudio = true;
                        window.AudioContext = class {
                            state = 'running';
                            sampleRate = 48000;
                            audioWorklet = { addModule: async () => {} };
                            async resume() {}
                            async close() { this.state = 'closed'; }
                        };
                        window.AudioWorkletNode = class {
                            port = new MessageChannel().port1;
                            connect() {}
                            disconnect() { this.port.close(); }
                        };
                    }
                ''')
                page = await context.new_page()
                try:
                    await page.goto(str(client.make_url('/')))
                    await page.locator('#conversation summary').click()
                    await page.locator('#message').fill('시험 통화')
                    await page.locator('#text-form button[type="submit"]').click()
                    await page.wait_for_function('ready && intended', timeout=8000)
                    original = await page.evaluate('callId')
                    previous = server.active_calls[index].session
                    previous.hold_close = True
                    await previous.ws.close()
                    async with asyncio.timeout(8):
                        while server.active_calls[index].session is previous and not end_requests:
                            await asyncio.sleep(.01)
                    assert not end_requests, 'rejected reconnect sent a call-end POST'
                    await page.wait_for_function('intended && ready', timeout=5000)
                    assert await page.evaluate('callId') == original
                    assert not previous.explicit
                    await page.locator('#stop').click()
                    async with asyncio.timeout(3):
                        while len(end_requests) == 0:
                            await asyncio.sleep(.01)
                    assert end_requests == [original]
                    audio = 'stub' if await page.evaluate('Boolean(window.fixtureAudio)') else 'browser'
                    print(f'PASS TC-643 {label}: 1 resumed call, 0 automatic end POSTs, 1 explicit end POST (audio={audio})')
                except Exception as error:
                    print(f'FAIL TC-643 {label}: {error}; status={await page.locator("#status").inner_text(timeout=2000)}')
                    errors.append(error)
                finally:
                    slot = server.active_calls.get(index)
                    if slot and slot.session:
                        slot.session.stop.set()
                    await context.close()
                    end_requests.clear()
        if errors:
            raise AssertionError(f'{len(errors)} of {len(profiles)} browser cases failed')


async def main():
    with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'home', return_value=Path(directory)):
        import server

    async def identity(req):
        index = int(req.headers.get('X-Fixture-Account') or req.cookies['fixture_account'])
        return {'owner': f'fixture:{index}', 'principal': server.Principal(index, index, '시험친구 가')}

    end_requests = []

    async def end_request(req):
        end_requests.append(req.match_info['id'])
        return web.json_response({'ok': True})

    site = web.Application()
    site.router.add_get('/live', server.live)
    site.router.add_get('/status', server.status)
    site.router.add_post('/api/calls/{id}/end', end_request)
    site.router.add_get('/', server.static)
    site.router.add_get('/face/v1/{name}', server.face)
    site.router.add_get('/{file}', server.static)
    with patch.object(server, 'identity', identity), patch.object(server, 'LiveSession', FixtureLive), (
        patch.object(server, 'CALL_MAX', 1)
    ), patch.object(server.rtc_transport, 'enabled', return_value=False):
        async with TestClient(VoiceTestServer(site)) as client:
            try:
                if '--browser' in sys.argv:
                    await test_browsers(client, server, end_requests)
                else:
                    origin = str(client.make_url('/')).rstrip('/')
                    await test_api(client, server, {'Origin': origin, 'X-Fixture-Account': '1'})
            finally:
                for slot in server.active_calls.values():
                    if slot.session:
                        slot.session.stop.set()


if __name__ == '__main__':
    asyncio.run(main())
