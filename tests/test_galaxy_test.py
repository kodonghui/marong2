"""갤럭시 시험 서버(tools/galaxy_test/server.py) 시험: 가짜 OpenAI로 세션 만들기·상한·기록을 본다.
진짜 OpenAI나 네트워크는 쓰지 않아요.
실행: python tests/test_galaxy_test.py"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="galaxy-test-")
os.environ.update(TEST_LOG_DIR=TMP, TEST_MAX_SESSIONS="2", OPENAI_API_KEY="", OPENAI_KEY_FILE=str(Path(TMP) / "none"))
sys.path.insert(0, str(ROOT / "tools" / "galaxy_test"))
import server as gt  # noqa: E402

PAGE = "0f8fad5b-d9cb-469f-a165-70867728950e"
OFFER = "v=0\r\no=- 1 2 IN IP4 127.0.0.1\r\ns=-\r\n"


class FakeOpenAI(BaseHTTPRequestHandler):
    seen = []
    reply = (201, {"session": {"id": "live_test_1"}, "transport": {"type": "webrtc", "sdp": "v=0 answer"}})

    def log_message(self, *a):
        return

    def do_GET(self):
        ok = self.path == "/v1/models/gpt-live-1" and self.headers.get("Authorization") == "Bearer test-key"
        self.send_response(200 if ok else 401)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOpenAI.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        status, obj = FakeOpenAI.reply
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class GalaxyTestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = serve(FakeOpenAI)
        gt.OPENAI_BASE = f"http://127.0.0.1:{cls.fake.server_port}/v1"
        gt.KEY = "test-key"
        gt.RUN = gt.Run()
        cls.app = serve(gt.Handler)
        cls.base = f"http://127.0.0.1:{cls.app.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.fake.shutdown()

    def setUp(self):
        FakeOpenAI.seen.clear()
        FakeOpenAI.reply = (201, {"session": {"id": "live_test_1"}, "transport": {"type": "webrtc", "sdp": "v=0 answer"}})
        with gt.RUN.lock:
            gt.RUN.sessions.clear()

    def post(self, path, obj, origin=True):
        data = json.dumps(obj).encode()
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = self.base
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_page_and_static_files(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            html = r.read().decode()
            self.assertIn("마롱이 갤럭시 시험", html)
            self.assertIn("script-src 'self'", r.headers["Content-Security-Policy"])
            self.assertEqual(r.headers["Cache-Control"], "no-store")
        for path in ("/app.js", "/worklet.js", "/sw.js", "/manifest.webmanifest", "/icon-192.webp", "/icon-512.webp"):
            with urllib.request.urlopen(self.base + path, timeout=5) as r:
                self.assertEqual(r.status, 200, path)

    def test_session_needs_same_site_origin(self):
        self.assertEqual(self.post("/api/session", {"page": PAGE, "kind": "start", "sdp": OFFER}, origin=False)[0], 403)
        self.assertEqual(FakeOpenAI.seen, [])

    def test_session_body_sent_to_openai(self):
        status, res = self.post("/api/session", {"page": PAGE, "kind": "start", "name": "현경", "sdp": OFFER})
        self.assertEqual(status, 201)
        self.assertEqual(res["session_id"], "live_test_1")
        self.assertEqual(res["sdp"], "v=0 answer")
        sent = FakeOpenAI.seen[0]
        self.assertEqual(sent["path"], "/v1/live/sessions")
        self.assertEqual(sent["auth"], "Bearer test-key")
        s = sent["body"]["session"]
        self.assertEqual(s["model"], "gpt-live-1")
        self.assertEqual(s["audio"], {"output": {"voice": "noeul"}})
        self.assertEqual(s["delegation"], {"type": "client", "acknowledgement_delay_ms": 800})
        self.assertIs(s["store"], False)
        self.assertIn("지금 전화하는 친구: 현경", s["instructions"])
        self.assertIn("Backchannel policy:", s["instructions"])
        self.assertEqual(s["input"][0]["role"], "developer")
        self.assertEqual(s["client"]["data_channel"]["allowed_client_events"], ["session.close", "session.commentary.append"])
        self.assertEqual(sent["body"]["transport"], {"type": "webrtc", "sdp": OFFER})
        self.assertNotIn("test-key", json.dumps(res))

    def test_bad_requests(self):
        self.assertEqual(self.post("/api/session", {"page": PAGE, "kind": "start", "sdp": "hello"})[0], 400)
        self.assertEqual(self.post("/api/session", {"page": PAGE, "kind": "boom", "sdp": OFFER})[0], 400)
        self.assertEqual(self.post("/api/session", {"page": PAGE, "kind": "start", "name": "<b>x</b>", "sdp": OFFER})[0], 400)
        self.assertEqual(self.post("/api/session", {"page": "nope", "kind": "start", "sdp": OFFER})[0], 400)
        self.assertEqual(FakeOpenAI.seen, [])

    def test_session_cap(self):
        self.assertEqual(self.post("/api/session", {"page": PAGE, "kind": "start", "sdp": OFFER})[0], 201)
        self.assertEqual(self.post("/api/session", {"page": PAGE, "kind": "again", "sdp": OFFER})[0], 201)
        status, res = self.post("/api/session", {"page": PAGE, "kind": "again", "sdp": OFFER})
        self.assertEqual((status, res["error"]), (429, "session_cap"))
        self.assertEqual(len(FakeOpenAI.seen), 2)

    def test_minute_cap(self):
        self.assertEqual(self.post("/api/session", {"page": PAGE, "kind": "start", "sdp": OFFER})[0], 201)
        with gt.RUN.lock:
            gt.RUN.sessions[0].update(closed_at=gt.now_ms(), usage=gt.MAX_TOTAL_MIN * 60)
        status, res = self.post("/api/session", {"page": PAGE, "kind": "again", "sdp": OFFER})
        self.assertEqual((status, res["error"]), (429, "minute_cap"))
        self.assertEqual(len(FakeOpenAI.seen), 1)

    def test_key_added_after_start(self):
        key_file = gt.KEY_FILE
        gt.KEY = ""
        try:
            self.assertEqual(self.post("/api/session", {"page": PAGE, "kind": "start", "sdp": OFFER})[0], 503)
            key_file.write_text("test-key\n", encoding="utf-8")
            self.assertEqual(self.post("/api/session", {"page": PAGE, "kind": "start", "sdp": OFFER})[0], 201)
            self.assertEqual(FakeOpenAI.seen[-1]["auth"], "Bearer test-key")
            self.assertEqual(gt.MODEL_CHECK, "200")
        finally:
            gt.KEY = "test-key"
            key_file.unlink()

    def test_model_check_is_free_lookup(self):
        self.assertEqual(gt.check_model("test-key"), "200")
        self.assertEqual(gt.check_model("wrong"), "401")
        self.assertEqual(gt.check_model(""), "no_key")
        self.assertEqual(FakeOpenAI.seen, [])

    def test_openai_spend_limit_is_reported(self):
        FakeOpenAI.reply = (429, {"error": {"type": "insufficient_quota", "code": "project_spend_limit_exceeded"}})
        status, res = self.post("/api/session", {"page": PAGE, "kind": "start", "sdp": OFFER})
        self.assertEqual(status, 429)
        self.assertEqual(res["code"], "project_spend_limit_exceeded")
        self.assertEqual(len(gt.RUN.sessions), 0)

    def test_beat_keeps_only_allowed_fields(self):
        events = [{"t": 1, "k": "mark", "s": "잘 들림", "delta": "비밀 이야기", "text": "자막"},
                  {"t": 2, "k": "check", "n": 1, "s": "ok", "memo": "가" * 500}, "not a dict", {"no": "kind"}]
        status, res = self.post("/api/beat", {"page": PAGE, "seq": 1, "st": "talking", "vis": "hidden",
                                              "agg": {"micMax": 0.2, "secret": "x"}, "events": events})
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        log = gt.RUN.log_path.read_text(encoding="utf-8")
        self.assertNotIn("비밀 이야기", log)
        self.assertNotIn("자막", log)
        self.assertNotIn("secret", log)
        self.assertIn('"memo": "' + "가" * 200 + '"', log)
        self.assertEqual(oct(gt.RUN.log_path.stat().st_mode & 0o777), "0o600")

    def test_end_marks_session_closed(self):
        self.post("/api/session", {"page": PAGE, "kind": "start", "sdp": OFFER})
        status, _ = self.post("/api/end", {"page": PAGE, "session_id": "live_test_1", "reason": "close_requested", "usage": 42})
        self.assertEqual(status, 200)
        rec = gt.RUN.sessions[0]
        self.assertEqual((rec["reason"], rec["usage"], rec["by"]), ("close_requested", 42, "page"))
        with urllib.request.urlopen(self.base + "/report", timeout=5) as r:
            self.assertIn("close_requested", r.read().decode())


if __name__ == "__main__":
    unittest.main(verbosity=2)
