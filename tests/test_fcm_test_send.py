"""시험 발송기(tools/fcm_test_send.py) 시험: 가짜 OAuth·FCM(httpx MockTransport)으로 종류마다 봇과 같은 메시지가 가는지,
출력에 FID와 글이 없는지 봐요(docs/app-chat.md TC-135, docs/app-ring.md TC-147 준비). 실제 키와 네트워크는 쓰지 않아요.
실행: python tests/test_fcm_test_send.py"""
import asyncio
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from marong import fcm  # noqa: E402

spec = importlib.util.spec_from_file_location("fcm_test_send", ROOT / "tools" / "fcm_test_send.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

FID = "fid-synthetic-0001"
TEXT = "[시험] 만든 글이에요"
RING = "0f8fad5b-d9cb-469f-a165-70867728950e"


class FcmTestSendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        cls.dir = tempfile.TemporaryDirectory()
        cls.key = Path(cls.dir.name) / "fixture-key.json"
        cls.key.write_text(json.dumps({
            "type": "service_account", "token_uri": fcm.TOKEN_URL, "project_id": "fixture-project",
            "client_email": "marong-fcm@fixture.iam.gserviceaccount.com", "private_key_id": "kid-1",
            "private_key": pem}), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def run_tool(self, *args, stdin=FID + "\n", status=200):
        sent = []

        def handler(request):
            if str(request.url) == fcm.TOKEN_URL:
                return httpx.Response(200, json={"access_token": "oauth-fixture", "expires_in": 3600})
            self.assertEqual(str(request.url), fcm.SEND_URL.format(project="fixture-project"))
            sent.append(json.loads(request.content)["message"])
            return httpx.Response(status, json={"name": "projects/fixture-project/messages/1"})

        real = fcm.FCM
        fake = lambda account: real(account, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))  # noqa: E731
        out, err = io.StringIO(), io.StringIO()
        with patch.object(tool.fcm, "FCM", fake), patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = asyncio.run(tool.main([str(self.key), *args]))
        printed = out.getvalue() + err.getvalue()
        self.assertNotIn(FID, printed)
        self.assertNotIn(TEXT, printed)
        self.assertNotIn("oauth-fixture", printed)
        return code, out.getvalue(), err.getvalue(), sent

    def test_each_kind_sends_what_the_bot_sends(self):
        for kind, channel, ttl, open_path in (("proactive", "marong_talk", 7200, "/chat/"),
                                              ("reply", "marong_talk", 3600, "/chat/"),
                                              ("reminder", "marong_reminder", 3600, "/chat/"),
                                              ("missed_call", "marong_talk", 3600, "/")):
            with self.subTest(kind=kind):
                code, out, _, sent = self.run_tool(kind, *TEXT.split(" "))
                self.assertEqual((code, out), (0, f"{kind} ok\n"))
                self.assertEqual(sent, [fcm.notice(FID, kind, TEXT, channel=channel, ttl_s=ttl, open_path=open_path)])

    def test_ring_is_data_only_with_the_given_or_a_new_id(self):
        code, out, _, sent = self.run_tool("ring", RING.upper())
        self.assertEqual((code, out), (0, f"ring {RING}\nring ok\n"))
        self.assertEqual(sent, [fcm.ring(FID, RING)])
        self.assertNotIn("notification", sent[0])
        code, out, _, sent = self.run_tool("ring")
        new = out.split("\n")[0].split(" ")[1]
        self.assertEqual((code, str(uuid.UUID(new)), sent[0]["data"]["ringId"]), (0, new, new))

    def test_hello_ring_carries_its_line(self):
        line = "나 털모자 샀다! 🧶"
        code, out, _, sent = self.run_tool("hello", *line.split(" "))
        new = out.split("\n")[0].split(" ")[1]
        self.assertEqual((code, out), (0, f"ring {new}\nhello ok\n"))
        self.assertEqual(sent, [fcm.ring(FID, new, "hello", line)])
        self.assertEqual((sent[0]["data"]["reason"], sent[0]["data"]["line"]), ("hello", line))
        self.assertNotIn("notification", sent[0])
        code, out, _, sent = self.run_tool("hello", "x" * 31)  # longer than the ring line: the ring goes without it
        self.assertEqual((code, sent[0]["data"]["reason"], "line" in sent[0]["data"]), (0, "hello", False))

    def test_failures_and_wrong_input(self):
        code, out, _, _ = self.run_tool("proactive", "x", status=404)
        self.assertEqual((code, out), (1, "proactive gone\n"))
        code, _, err, sent = self.run_tool("proactive", "x", stdin="\n")
        self.assertEqual((code, sent), (2, []))
        self.assertIn("no FID", err)
        code, _, err, sent = self.run_tool("ring", "not-a-uuid")
        self.assertEqual((code, sent), (2, []))
        self.assertIn("not a UUID", err)
        for args in (("hello",), ("call", "x"), ("proactive",), ()):
            with self.subTest(args=args):
                code, _, err, sent = self.run_tool(*args)
                self.assertEqual((code, sent), (2, []))
                self.assertIn("fcm_test_send.py KEY_FILE", err)


if __name__ == "__main__":
    unittest.main()
