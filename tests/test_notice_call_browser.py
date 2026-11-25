"""TASK-573/576/577 with real browser navigation, app scripts and worker, on a mock loopback server."""

import asyncio
from concurrent.futures import Future
from pathlib import Path
from threading import Event, Thread
import unittest

from aiohttp import WSMsgType, web
from playwright.sync_api import expect, sync_playwright

from marong.app_chat import HEADERS
from marong.web_notice_call_protocol import SUBPROTOCOL


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / 'marong' / 'app_chat_static'
CALL = ROOT / 'tools' / 'vertex_live' / 'static'
REF = 'N' * 64
PROOF = 'A' * 43
TOKEN = 'C' * 64
CALL_ID = '11111111-2222-4333-8444-555555555555'

MEDIA = """
    Object.defineProperty(navigator, 'standalone', {value: true, configurable: true});
    const f = window.fixture = {prompts: 0, stopped: 0, permission: 'allow', lag: false};
    localStorage.setItem('marong.web-notifications.installation', 'A'.repeat(43));
    const node = () => ({connect() {}, disconnect() {}});
    window.AudioContext = class {
      state = 'running'; sampleRate = 24000; destination = {};
      audioWorklet = {async addModule() {}};
      async resume() {} async close() {} async decodeAudioData() {}
      createMediaStreamSource() { return node(); }
    };
    window.AudioWorkletNode = class {
      port = new MessageChannel().port1;
      connect() {} disconnect() {}
    };
    Object.defineProperty(navigator, 'mediaDevices', {configurable: true, value: {getUserMedia: async () => {
      f.prompts++;
      if (f.lag) await new Promise(resolve => {
        f.releaseMic = resolve;
        document.documentElement.dataset.testMic = 'waiting';
      });
      if (f.permission === 'deny') throw new DOMException('Fixture refusal', 'NotAllowedError');
      const track = {enabled: true, stop() { document.documentElement.dataset.testStopped = ++f.stopped; }};
      return {getTracks: () => [track], getAudioTracks: () => [track]};
    }}});
"""


class CallFixture:
    def __init__(self):
        self.ring = 'ring_ready'
        self.post_login = False
        self.resolve_login = False
        self.lose_response = False
        self.break_nonce = False
        self.right_call = True
        self.accepts = []
        self.connections = []
        self.posts = []
        self.resolved = 0
        self.frames = []
        self.call_stopped = Event()
        self.origin_ready = Future()
        self.thread = Thread(target=lambda: asyncio.run(self.run(), loop_factory=asyncio.SelectorEventLoop), daemon=True)
        self.thread.start()
        self.origin = self.origin_ready.result(timeout=10)

    def close(self):
        self.loop.call_soon_threadsafe(self.stop.set)
        self.thread.join(timeout=12)

    def drop_socket(self):
        asyncio.run_coroutine_threadsafe(self.connections[-1].close(), self.loop).result(timeout=5)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.stop = asyncio.Event()
        app = web.Application()
        app.router.add_get('/chat/', self.chat)
        app.router.add_post('/chat/notice-call', self.open_call)
        app.router.add_post('/chat/api/web-notifications/target/resolve', self.resolve)
        app.router.add_post('/chat/api/web-notifications/call/accept', self.accept)
        app.router.add_get('/live/web-notification', self.socket)
        app.router.add_get('/chat/login', lambda _: web.FileResponse(CHAT / 'account.html'))
        app.router.add_post('/chat/api/login/code', self.login)
        app.router.add_get('/chat/api/web-notifications/subscription', lambda _: web.json_response({'state': 'active'}))
        app.router.add_get('/chat/api/me', lambda _: web.json_response({'name': 'Fixture', 'textMax': 1000,
                          'delivery': {'to': 'discord'}, 'ring': {'to': 'discord'}}))
        app.router.add_get('/chat/api/messages', lambda _: web.json_response({'messages': [], 'hasMore': False}))
        app.router.add_get('/status', lambda _: web.json_response({'ready': True, 'canCall': True, 'webRTC': False}))
        app.router.add_get(r'/chat/{asset:[a-z-]+\.(?:js|css)}', lambda req: web.FileResponse(CHAT / req.match_info['asset']))
        app.router.add_get(r'/{asset:[a-z-]+\.(?:js|wav)}', lambda req: web.FileResponse(CALL / req.match_info['asset']))
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        self.origin_ready.set_result('http://127.0.0.1:' + str(runner.addresses[0][1]))
        await self.stop.wait()
        await asyncio.gather(*(ws.close() for ws in self.connections))
        await runner.cleanup()

    async def chat(self, _):
        headers = HEADERS | {
            'Content-Security-Policy': HEADERS['Content-Security-Policy'].replace(
                "form-action 'none'", f'form-action {self.origin}/chat/notice-call'),
            'Referrer-Policy': 'same-origin',
        }
        body = (CHAT / 'index.html').read_text(encoding='utf-8').replace(
            '<script ', '<script defer src="/chat/web-notifications.js"></script><script ', 1).replace(
            '<body', '<body data-notice-call-enabled="true"', 1)
        return web.Response(text=body, content_type='text/html', headers=headers)

    async def open_call(self, req):
        form = dict(await req.post())
        self.posts.append((req.headers.get('Origin'), req.headers.get('Referer'), form))
        if self.post_login:
            from marong.app_chat import AppChat
            self.post_login = False
            return AppChat._notice_call_failure('login', 401)
        navigation = form['navigation'] if not self.break_nonce else 'f' * 32
        body = (CHAT / 'notice-call.html').read_text(encoding='utf-8').replace('@NAVIGATION@', navigation)
        headers = HEADERS | {'Permissions-Policy': 'camera=(), microphone=(self), geolocation=()'}
        return web.Response(text=body, content_type='text/html', headers=headers)

    async def login(self, _):
        self.resolve_login = False
        return web.json_response({'status': 'ok'})

    async def resolve(self, req):
        if await req.json() != {'targetRef': REF}:
            return web.json_response({'code': 'not_found'}, status=404)
        self.resolved += 1
        if self.resolve_login:
            return web.json_response({'code': 'login_required'}, status=401)
        return web.json_response({'state': self.ring})

    async def accept(self, req):
        body = await req.json()
        before = list(self.accepts)
        self.accepts.append(body)
        if self.lose_response:
            self.lose_response = False
            self.ring = 'ring_answered'
            partial = web.StreamResponse(headers={'Content-Type': 'application/json', 'Content-Length': '128'})
            await partial.prepare(req)
            await partial.write(b'{')
            req.transport.abort()
            return partial
        if before and body == before[-1] and self.ring == 'ring_answered' and self.right_call:
            return web.json_response({'state': 'accepted', 'callId': CALL_ID, 'connectToken': TOKEN})
        if self.ring != 'ring_ready':
            return web.json_response({'state': self.ring})
        self.ring = 'ring_answered'
        return web.json_response({'state': 'accepted', 'callId': CALL_ID, 'connectToken': TOKEN})

    async def socket(self, req):
        ws = web.WebSocketResponse(protocols=(SUBPROTOCOL,))
        await ws.prepare(req)
        self.connections.append(ws)
        frame = await ws.receive_json(timeout=4)
        self.frames.append(frame)
        if ws.ws_protocol != SUBPROTOCOL or req.query_string:
            await ws.send_json({'type': 'invalid_input'})
            return ws
        await ws.send_json({'type': 'ready', 'ring': frame['type'] == 'start_notified', 'memoryConnected': True,
                            'callId': CALL_ID if self.right_call else '22222222-2222-4333-8444-555555555555'})
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                self.frames.append(message.json())
                if message.json().get('type') == 'stop':
                    self.call_stopped.set()
                    break
        return ws


class NoticeCallBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)

    def page(self, engine, fixture, *, width=360, standalone=True):
        browser = engine.launch()
        self.addCleanup(browser.close)
        page = browser.new_page(viewport={'width': width, 'height': 820}, user_agent='iPhone Fixture Safari')
        page.set_default_timeout(6000)
        page.add_init_script(MEDIA.replace('value: true, configurable', f'value: {str(standalone).lower()}, configurable'))
        page.goto(fixture.origin + '/chat/#notice=' + REF)
        return page

    def heading(self, page, title):
        result = page.get_by_role('heading', name=title, exact=True)
        expect(result).to_be_visible()
        return result

    def test_same_window_form_focus_denied_microphone_and_expired_during_prompt(self):
        for engine, width in ((self.playwright.chromium, 360), (self.playwright.webkit, 430)):
            with self.subTest(engine=engine.name):
                fixture = CallFixture()
                self.addCleanup(fixture.close)
                page = self.page(engine, fixture, width=width)
                expect(self.heading(page, '약속 전화가 와 있어')).to_be_focused()
                self.assertEqual(page.url, fixture.origin + '/chat/notice-call')
                self.assertEqual(len(page.context.pages), 1)
                origin, referrer, form = fixture.posts[0]
                self.assertEqual(origin, fixture.origin)
                self.assertEqual(referrer, fixture.origin + '/chat/')
                self.assertEqual({k: form[k] for k in ('targetRef', 'installationProof')},
                                 {'targetRef': REF, 'installationProof': PROOF})
                self.assertGreaterEqual(fixture.resolved, 2)
                self.assertEqual(fixture.accepts, [])
                self.assertEqual(page.evaluate('fixture.prompts'), 0)
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.evaluate("() => { fixture.permission = 'deny'; }")
                page.get_by_role('button', name='받기', exact=True).click()
                self.heading(page, '마이크를 허용해야 통화할 수 있어')
                self.assertEqual(fixture.accepts, [])
                page.evaluate("() => { fixture.permission = 'allow'; fixture.lag = true; }")
                retry = page.get_by_role('button', name='다시 해 볼게')
                retry.focus()
                retry.click()
                expect(page.locator('html')).to_have_attribute('data-test-mic', 'waiting')
                expect(page.get_by_role('button', name='받는 중')).to_be_focused()
                self.assertEqual(fixture.accepts, [])
                fixture.ring = 'ring_expired'
                page.evaluate('() => { fixture.lag = false; fixture.releaseMic(); }')
                expect(self.heading(page, '약속 전화 시간이 지났어')).to_be_focused()
                expect(page.locator('html')).to_have_attribute('data-test-stopped', '1')
                self.assertEqual(len(fixture.accepts), 1)
                self.assertEqual(fixture.frames, [])
                page.get_by_role('button', name='일반 통화').click()
                self.heading(page, '통화 중이야')
                self.assertEqual(fixture.frames[0]['type'], 'start_ordinary')
                self.assertEqual(len(fixture.accepts), 1)
                page.get_by_role('button', name='끊기').click()
                self.heading(page, '통화가 끝났어')
                page.get_by_role('link', name='글 대화로').click()
                expect(self.heading(page, '글 대화')).to_be_focused()

    def test_lost_response_exact_retry_reconnect_and_other_device_wins(self):
        for engine in (self.playwright.chromium, self.playwright.webkit):
            with self.subTest(engine=engine.name):
                losing = CallFixture()
                self.addCleanup(losing.close)
                page = self.page(engine, losing)
                self.heading(page, '약속 전화가 와 있어')
                page.evaluate('() => { fixture.lag = true; }')
                page.get_by_role('button', name='받기', exact=True).click()
                expect(page.locator('html')).to_have_attribute('data-test-mic', 'waiting')
                losing.ring, losing.right_call = 'ring_answered', False
                page.evaluate('() => fixture.releaseMic()')
                self.heading(page, '이미 받은 전화야')
                self.assertEqual(len(losing.accepts), 1)
                self.assertEqual(losing.frames, [])
                expect(page.locator('html')).to_have_attribute('data-test-stopped', '1')
                fixture = CallFixture()
                self.addCleanup(fixture.close)
                fixture.lose_response = True
                page = self.page(engine, fixture)
                page.get_by_role('button', name='받기', exact=True).click()
                self.heading(page, '전화 받기 결과를 확인해 줘')
                self.assertEqual(fixture.frames, [])
                page.get_by_role('button', name='결과 확인', exact=True).click()
                self.heading(page, '통화 중이야')
                self.assertEqual(fixture.accepts[0], fixture.accepts[1])
                self.assertEqual(fixture.frames[0]['clientId'], fixture.accepts[0]['clientId'])
                stop = page.get_by_role('button', name='끊기')
                stop.focus()
                fixture.drop_socket()
                self.heading(page, '같은 통화에 다시 연결 중이야')
                expect(stop).to_be_focused()
                self.heading(page, '통화 중이야')
                starts = [frame for frame in fixture.frames if frame['type'] == 'start_notified']
                self.assertEqual(starts, [starts[0], starts[0]])
                self.assertEqual(len(fixture.accepts), 2)
                fixture.right_call = False
                fixture.drop_socket()
                self.heading(page, '지금 통화 연결을 확인할 수 없어')
                self.assertFalse(any(frame['type'] == 'stop' for frame in fixture.frames))
                fixture.right_call = True
                page.get_by_role('button', name='연결 확인').click()
                self.heading(page, '통화 중이야')
                fixture.drop_socket()
                self.heading(page, '같은 통화에 다시 연결 중이야')
                page.get_by_role('button', name='끊기').click()
                self.heading(page, '통화가 끝났어')
                self.assertTrue(fixture.call_stopped.wait(3))
                self.assertEqual(sum(frame['type'] == 'stop' for frame in fixture.frames), 1)

    def test_reauthentication_mismatched_navigation_and_regular_safari(self):
        for engine in (self.playwright.chromium, self.playwright.webkit):
            with self.subTest(engine=engine.name):
                fixture = CallFixture()
                self.addCleanup(fixture.close)
                # The initial lookup succeeds and the session expires at the document POST.
                fixture.post_login = True
                page = self.page(engine, fixture)
                self.heading(page, '로그인한 뒤 알림을 확인할게')
                self.assertEqual(fixture.accepts, [])
                page.get_by_role('link', name='들어가기').click()
                page.get_by_role('textbox', name='기기 추가 코드').fill('555555')
                page.get_by_role('button', name='들어가기').click()
                self.heading(page, '약속 전화가 와 있어')
                self.assertEqual(len(fixture.posts), 2)
                self.assertEqual(fixture.accepts, [])
                invalid = CallFixture()
                self.addCleanup(invalid.close)
                invalid.break_nonce = True
                page = self.page(engine, invalid)
                self.heading(page, '이 알림을 열 수 없어')
                self.assertEqual(invalid.resolved, 1)
                self.assertEqual(invalid.frames, [])
                self.assertEqual(page.evaluate('fixture.prompts'), 0)
                safari = CallFixture()
                self.addCleanup(safari.close)
                page = self.page(engine, safari, standalone=False)
                self.assertEqual(safari.resolved, 0)
                self.assertEqual(safari.posts, [])
                self.assertEqual(page.evaluate('fixture.prompts'), 0)
                self.assertEqual(page.url, safari.origin + '/chat/')
                page.evaluate("""() => {
                    document.addEventListener('securitypolicyviolation', event => {
                        document.body.dataset.rejectedDirective = event.violatedDirective;
                    });
                    const child = document.createElement('iframe');
                    child.name = 'rejected-form';
                    child.hidden = true;
                    const form = document.createElement('form');
                    form.action = '/chat/other';
                    form.method = 'POST';
                    form.target = child.name;
                    document.body.append(child, form);
                    form.submit();
                }""")
                expect(page.locator('body')).to_have_attribute('data-rejected-directive', 'form-action')


if __name__ == '__main__':
    unittest.main()
