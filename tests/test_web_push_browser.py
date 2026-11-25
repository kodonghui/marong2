"""TASK-570/571/573 browser mocks. The wildcard route supplies every response."""

import json
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright


STATIC = Path(__file__).resolve().parents[1] / "marong" / "app_chat_static"
ORIGIN = "https://browser-fixture.invalid"
SCRIPT = '<script defer src="/chat/web-notifications.js"></script>'
REF = "N" * 64


class WebPushBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)

    def settings_fixture(self, engine, width, theme, *, standalone, permission="default", fail=None):
        browser = engine.launch()
        self.addCleanup(browser.close)
        page = browser.new_page(viewport={"width": width, "height": 820}, user_agent="iPhone Fixture Safari")
        page.add_init_script(f"""
            window.fixture = {{permission: {json.dumps(permission)}, prompts: 0, subscriptions: 0}};
            Object.defineProperty(navigator, 'standalone', {{value: {str(standalone).lower()}}});
            window.Notification = {{
                get permission() {{ return fixture.permission; }},
                requestPermission() {{ fixture.prompts++; fixture.permission = 'granted'; return Promise.resolve('granted'); }}
            }};
            window.PushManager = function () {{}};
            const manager = {{
                getSubscription: async () => fixture.subscription,
                async subscribe() {{
                    fixture.subscriptions++;
                    return fixture.subscription = {{
                        async unsubscribe() {{ fixture.subscription = null; return true; }},
                        toJSON() {{ return {{endpoint: 'https://web.push.apple.com/fixture', keys: {{}}}}; }}
                    }};
                }}
            }};
            const worker = {{active: true, pushManager: manager}};
            Object.defineProperty(navigator, 'serviceWorker', {{value: {{register: async () => worker}}}});
        """)
        state = "not_registered"
        requests = []

        def route(handler):
            nonlocal state
            req = handler.request
            path = req.url.removeprefix(ORIGIN)
            if path in {"/chat/web-notifications.js", "/chat/unified.js", "/chat/unified.css"}:
                handler.fulfill(path=STATIC / path.rsplit("/", 1)[1])
            elif path == "/chat/me":
                handler.fulfill(content_type="text/html", body=f"""
                    <!doctype html><html data-theme="{theme}"><head><meta charset="utf-8">
                    <meta name="viewport" content="width=device-width,initial-scale=1">
                    <meta name="theme-color" content="#121729">
                    <link rel="stylesheet" href="/chat/unified.css">{SCRIPT}
                    <script defer src="/chat/unified.js"></script></head><body><main></main></body></html>
                """)
            elif "/api/web-notifications/" in path:
                requests.append((req.method, path))
                self.assertEqual(len(req.headers["x-marong-installation"]), 43)
                if req.method == "POST":
                    handler.fulfill(json={"choiceToken": "V" * 64})
                    return
                if req.method == "PUT":
                    if fail:
                        handler.fulfill(status=fail, json={"code": "state_changed"})
                        return
                    state = "active"
                if req.method == "DELETE":
                    state = "revoked"
                handler.fulfill(json={"state": state, "stateToken": "T" * 64,
                                      "vapid": {"keyId": "fixture", "publicKey": "B" + "A" * 86}})
            else:
                handler.fulfill(status=404, body="")

        page.route("**/*", route)
        page.goto(ORIGIN + "/chat/me")
        page.evaluate("""theme => {
            document.documentElement.dataset.theme = theme;
            document.querySelector('main').append(MarongWebNotifications.settings(() => {}));
        }""", theme)
        return page, requests

    def test_installation_views_two_widths_and_themes(self):
        for engine in (self.playwright.chromium, self.playwright.webkit):
            for width, theme in ((360, "chestnut"), (360, "night"), (430, "chestnut"), (430, "night")):
                with self.subTest(engine=engine.name, width=width, theme=theme):
                    page, events = self.settings_fixture(engine, width, theme, standalone=True)
                    page.get_by_text("이 기기 알림이 꺼져 있어", exact=True).wait_for()
                    self.assertEqual(page.evaluate("fixture.prompts"), 0)
                    self.assertEqual(page.evaluate("fixture.subscriptions"), 0)
                    self.assertEqual([method for method, _ in events], ["GET"])
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                    page.get_by_role("button", name="알림 켜기", exact=True).click()
                    page.get_by_text("이 기기에서 알림을 받을 수 있어", exact=True).wait_for()
                    self.assertEqual(page.evaluate("fixture.prompts"), 1)
                    self.assertEqual(page.evaluate("fixture.subscriptions"), 1)
                    page.get_by_role("button", name="알림 끄기").click()
                    page.get_by_text("이 기기에서 알림을 껐어", exact=True).wait_for()
                    self.assertEqual([method for method, _ in events], ["GET", "POST", "PUT", "POST", "DELETE"])

    def test_regular_safari_denied_and_subscription_conflict(self):
        engine = self.playwright.webkit
        page, events = self.settings_fixture(engine, 360, "night", standalone=False)
        page.get_by_text("홈 화면에 추가", exact=True).wait_for()
        self.assertEqual(events, [])
        self.assertEqual(page.evaluate("fixture.prompts"), 0)
        page, events = self.settings_fixture(engine, 430, "chestnut", standalone=True, permission="denied")
        page.get_by_text("기기에서 알림이 꺼져 있어", exact=True).wait_for()
        self.assertEqual([method for method, _ in events], ["GET"])
        self.assertEqual(page.evaluate("fixture.prompts"), 0)
        page, events = self.settings_fixture(engine, 360, "night", standalone=True, permission="granted", fail=409)
        page.get_by_text("알림 등록이 필요해", exact=True).wait_for()
        self.assertEqual(page.evaluate("fixture.subscriptions"), 0)
        page.get_by_role("button", name="알림 켜기", exact=True).click()
        page.get_by_text("알림 설정이 바뀌었어", exact=True).wait_for()
        page.get_by_role("button", name="상태 다시 확인").click()
        page.get_by_text("알림 등록이 필요해", exact=True).wait_for()
        self.assertEqual([method for method, _ in events], ["GET", "POST", "PUT", "GET"])
        self.assertEqual(page.evaluate("fixture.prompts"), 0)

    def test_worker_tags_and_click_route(self):
        browser = self.playwright.chromium.launch()
        self.addCleanup(browser.close)
        page = browser.new_page()
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body="<!doctype html><title>Fixture</title>"))
        page.goto(ORIGIN)
        result = page.evaluate("""async ({source, reference}) => {
            const events = {}, shown = [], opened = [];
            const worker = {
                location, registration: {showNotification: async (...args) => shown.push(args)},
                clients: {matchAll: async () => [], openWindow: async url => opened.push(url)},
                addEventListener: (name, listener) => { events[name] = listener; }
            };
            new Function('self', 'indexedDB', 'IDBKeyRange', source)(worker, indexedDB, IDBKeyRange);
            const good = location.origin + '/chat/#notice=' + reference;
            const push = navigate => new Promise(done => events.push({
                waitUntil: task => task.then(done),
                data: {json: () => ({web_push: 8030, notification: {
                    title: '마롱이', body: '새 답변이 있어.', lang: 'ko',
                    navigate, tag: 'a'.repeat(24), renotify: false
                }})}
            }));
            await Promise.all([push(good), push(good)]);
            await push('https://else.invalid/chat/#notice=' + reference);
            const click = navigate => new Promise(done => events.notificationclick({
                waitUntil: task => task.then(done),
                notification: {close() {}, data: {navigate}}
            }));
            await click('https://else.invalid/chat/#notice=' + reference);
            await click(good);
            return {shown: shown.length, opened: opened.length, listeners: Object.keys(events)};
        }""", {"source": (STATIC / "web-notification-worker.js").read_text(encoding="utf-8"), "reference": REF})
        self.assertEqual(result, {"shown": 1, "opened": 1,
                                  "listeners": ["push", "notificationclick", "pushsubscriptionchange"]})

    def test_notice_ref_removed_before_failed_resolution(self):
        browser = self.playwright.webkit.launch()
        self.addCleanup(browser.close)
        page = browser.new_page(user_agent="iPhone Fixture Safari")
        page.add_init_script("Object.defineProperty(navigator, 'standalone', {value: true})")
        called = []

        def route(handler):
            path = handler.request.url.removeprefix(ORIGIN).split("?", 1)[0]
            if path == "/chat/":
                html = (STATIC / "index.html").read_text(encoding="utf-8")
                handler.fulfill(content_type="text/html", body=html.replace("<script ", SCRIPT + "<script ", 1))
            elif path in {"/chat/web-notifications.js", "/chat/chat.js", "/chat/chat.css"}:
                handler.fulfill(path=STATIC / path.rsplit("/", 1)[1])
            elif path == "/chat/api/web-notifications/target/resolve":
                called.append(path)
                handler.fulfill(status=404, json={"code": "not_found"})
            elif path.startswith("/chat/api/"):
                called.append(path)
                handler.fulfill(status=500, json={"code": "internal"})
            else:
                handler.fulfill(status=404, body="")

        page.route("**/*", route)
        page.goto(ORIGIN + "/chat/#notice=" + REF)
        page.get_by_role("heading", name="이 알림을 열 수 없어").wait_for()
        self.assertEqual(page.evaluate("location.hash"), "")
        self.assertEqual(page.locator("#messages").get_by_text(REF).count(), 0)
        self.assertEqual(called, ["/chat/api/web-notifications/target/resolve"])


if __name__ == "__main__":
    unittest.main()
