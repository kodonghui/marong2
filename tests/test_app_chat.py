"""마롱이 앱 2단계 시험(docs/app-chat.md TC-119~131): 진짜 Postgres(pgserver), 가짜 Access 서명 키, 가짜 FCM,
가짜 Claude, 가짜 디스코드. 네트워크와 실제 키는 쓰지 않아요.

- TC-119 Access 증명(서명·aud·iss·만료·허용 목록·키 목록 못 읽음)과 친구 찾기, Access 값이 없으면 꺼짐
- TC-120 다른 사이트의 쓰기, TC-121 같은 clientId, TC-122 같은 방·같은 잠금·선톡 말·보내기 한도
- TC-123 기다리기(바로·신호·DB 확인·늦은 커밋·4개 한도·쓰는 중), TC-124 대화 읽기(뺄 것·페이지)
- TC-125 알림 받을 기기, TC-126 FCM 응답별 처리(가짜 FCM 서버), TC-127 선톡, TC-128 일정 알림
- TC-129 답 알림, TC-130 기기 등록, TC-131 로그에 글·FID·installId·이메일·토큰 없음
- TC-155 읽음(답이 맡은 말까지, 답한 말은 빠짐, 옛 화면), TC-156 대답 중(연달아 보낸 두 번째 말에도, BUG-106)
실행: .venv/bin/python tests/test_app_chat.py"""
import asyncio
from collections import deque
from datetime import datetime, timedelta
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
from urllib.parse import parse_qsl
import uuid
from zoneinfo import ZoneInfo

from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import jwt
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tools/vertex_live")]
from fakes import FakeEmbeddings, ScriptedLLM, message, text  # noqa: E402
from marong import app_chat as chat_module, fcm as fcm_module  # noqa: E402
from marong.access import AccessConfig, AccessVerifier, email_hash  # noqa: E402
from marong.app_chat import AppChat  # noqa: E402
from marong.app_push import REMINDER, TALK, AppPush  # noqa: E402
from marong.config import load_settings  # noqa: E402
from marong.discord_dm import APP_GOOGLE_TEXT, DiscordAgent, DiscordProactive, DiscordReminders  # noqa: E402
from marong.discord_store import DiscordStore  # noqa: E402
from marong.google_calendar import LINK_MARK  # noqa: E402
from pg import TestDB  # noqa: E402
from test_discord_dm import DH, DM_DH, DM_HK, HK, Client, event, prepare as prepare_dm  # noqa: E402
import run_discord  # noqa: E402

TZ = ZoneInfo("Asia/Seoul")
TEAM = "fixture.cloudflareaccess.com"
AUD = "f" * 64
ORIGIN = "https://marong.example.test"
HK_EMAIL, DH_EMAIL, STRANGER = "hk@example.test", "dh@example.test", "who@example.test"
HK_ROOM = f"discord-dm:{HK}"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=TZ)   # inside HK's proactive hours (7–24)
INSTALL_A, INSTALL_B = str(uuid.uuid4()), str(uuid.uuid4())
FID_A, FID_B = "fidA" + "x" * 30, "fidB" + "y" * 30
CHAIN = ("marong/call/migrations/003_transport_reporting.sql", "marong/call/migrations/004_transcript_reporting.sql",
         "marong/call/migrations/005_discord_voice.sql", "marong/call/migrations/006_discord_shared_callers.sql",
         "marong/migrations/013_google_calendar.sql", "marong/migrations/014_app_chat.sql",
         "marong/migrations/015_app_ring.sql", "marong/migrations/018_call_first.sql")
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
WRONG_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())), "kid": "k1", "alg": "RS256", "use": "sig"}
TOKENS = []   # every token handed out: none may reach the logs
CHECKS = 0


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def prepare(db):
    """test_discord_dm's friends and DM links (현경 is a call friend), then the whole migration chain up to 018."""
    prepare_dm(db)
    with psycopg.connect(db.admin_url, autocommit=True) as conn:
        for name in CHAIN:
            conn.execute((ROOT / name).read_text(encoding="utf-8"))
        conn.execute("INSERT INTO call.caller_logins(email_sha256, caller_id, email_hint) "
                     "SELECT %s, id, 'h***@example.test' FROM call.callers WHERE friend_id = 2", (email_hash(HK_EMAIL),))


def token(email=HK_EMAIL, *, key=KEY, kid="k1", aud=AUD, iss=f"https://{TEAM}", life=600, drop=(), alg="RS256"):
    now = int(time.time())
    claims = {"aud": aud, "iss": iss, "iat": now, "exp": now + life, "sub": "sub-" + email.split("@")[0],
              "email": email}
    for name in drop:
        claims.pop(name)
    signer = key if alg == "RS256" else "shared-secret-shared-secret-shared-secret"
    out = jwt.encode(claims, signer, algorithm=alg, headers={"kid": kid})
    TOKENS.append(out)
    return out


def auth(email=HK_EMAIL, *, write=False, origin=ORIGIN, **kw):
    headers = {"Cf-Access-Jwt-Assertion": token(email, **kw)}
    if write and origin:
        headers["Origin"] = origin
    return headers


class Certs:
    """Access's published keys (https://<team>/cdn-cgi/access/certs)."""

    def __init__(self):
        self.fetches = 0
        self.fail = False

    def __call__(self, request):
        assert str(request.url) == f"https://{TEAM}/cdn-cgi/access/certs", request.url
        self.fetches += 1
        return httpx.Response(503) if self.fail else httpx.Response(200, json={"keys": [JWK]})


class FakeFCM:
    """AppPush's sender: keeps each message and answers from a script (ok by default)."""

    def __init__(self):
        self.sent = []
        self.answers = deque()

    async def send(self, msg):
        self.sent.append(msg)
        return self.answers.popleft() if self.answers else "ok"


async def settle(chat):
    while chat.tasks:
        await asyncio.gather(*list(chat.tasks), return_exceptions=True)


async def problem(r, status, code, field=None, reason=None):
    body = await r.json(content_type=None)
    ok(r.status == status and body["code"] == code, f"{status} {code}: {r.status} {body}")
    ok(r.headers["Content-Type"].startswith("application/problem+json"), "problem media type")
    ok(len(body["traceId"]) == 16 and int(body["traceId"], 16) >= 0, "trace id")
    ok(body["type"] == f"{ORIGIN}/problems/{code.replace('_', '-')}", body["type"])
    if field:
        ok({"field": field, "reason": reason} in body.get("errors", []), f"{field} {reason}: {body}")
    return body


def rows(db, sql, params=()):
    return db.admin(sql, params)


# ── TC-126: the FCM sender against a fake FCM and OAuth server ───────────────

async def fcm_checks():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    account = fcm_module.ServiceAccount("marong-fcm@fixture.iam.gserviceaccount.com", "kid-1", pem, "fixture-project")
    script, sent, issued = deque(), [], []

    def handler(request):
        if str(request.url) == fcm_module.TOKEN_URL:
            form = dict(parse_qsl(request.content.decode()))
            ok(form["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer", "jwt-bearer grant")
            claims = jwt.decode(form["assertion"], key.public_key(), algorithms=["RS256"], audience=fcm_module.TOKEN_URL)
            ok(claims["scope"] == fcm_module.SCOPE and claims["iss"] == account.email, "service account claims")
            ok(jwt.get_unverified_header(form["assertion"])["kid"] == "kid-1", "key id in the header")
            if script and script[0] == "token_refused":
                script.popleft()
                return httpx.Response(400, json={"error": "invalid_grant"})
            issued.append(f"oauth-{len(issued) + 1}")
            return httpx.Response(200, json={"access_token": issued[-1], "expires_in": 3600})
        ok(str(request.url) == fcm_module.SEND_URL.format(project="fixture-project"), request.url)
        ok(request.headers["Authorization"] == f"Bearer {issued[-1]}", "current OAuth token")
        sent.append(json.loads(request.content))
        answer = script.popleft()
        if answer == "timeout":
            raise httpx.ReadTimeout("fixture")
        return answer

    clock = [0.0]
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    def fresh():
        return fcm_module.FCM(account, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                              monotonic=lambda: clock[0], sleep=sleep)

    sender = fresh()
    msg = fcm_module.notice("f" * 20, "proactive", "안녕\n오늘   어때?", channel=TALK, ttl_s=7200)
    script.append(httpx.Response(200, json={"name": "projects/fixture-project/messages/1"}))
    ok(await sender.send(msg) == "ok" and sent[-1] == {"message": msg}, "200 is sent")
    ok(msg["notification"] == {"title": "마롱이", "body": "안녕 오늘 어때?"} and msg["android"]["ttl"] == "7200s"
       and msg["android"]["notification"] == {"channel_id": TALK, "visibility": "PRIVATE"}
       and msg["data"] == {"kind": "proactive", "open": "/chat/"}, msg)
    script.append(httpx.Response(200, json={}))
    ok(await sender.send(msg) == "ok" and len(issued) == 1, "the OAuth token is reused")
    gone = {"error": {"status": "NOT_FOUND", "details": [
        {"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": "UNREGISTERED"}]}}
    script.append(httpx.Response(404, json=gone))
    ok(await sender.send(msg) == "gone", "404 UNREGISTERED drops the device")
    script.append(httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}}))
    ok(await sender.send(msg) == "gone", "400 INVALID_ARGUMENT drops the device")
    script.extend([httpx.Response(429, headers={"Retry-After": "3"}, json={}), httpx.Response(200, json={})])
    ok(await sender.send(msg) == "ok" and waits[-1] == 3, f"429 follows Retry-After: {waits}")
    waits.clear()
    script.extend([httpx.Response(503, json={})] * 3)
    ok(await sender.send(msg) == "failed" and waits == [1, 2], f"503 twice more after 1 s and 2 s: {waits}")
    waits.clear()
    script.append(httpx.Response(429, headers={"Retry-After": "30"}, json={}))
    ok(await sender.send(msg) == "failed" and waits == [], "a wait past the 10 s budget is not taken")
    script.extend(["timeout"] * 3)
    waits.clear()
    ok(await sender.send(msg) == "failed" and waits == [1, 2], "timeouts are retried twice")
    log = logging.getLogger("marong.fcm")
    seen = io.StringIO()
    handler_ = logging.StreamHandler(seen)
    log.addHandler(handler_)
    try:
        script.append(httpx.Response(401, json={}))
        ok(await sender.send(msg) == "auth" and sender.token is None, "401 is a key problem and drops the token")
        script.append(httpx.Response(200, json={}))
        ok(await sender.send(msg) == "ok" and len(issued) == 2, "the next send gets a new token")
        script.extend([httpx.Response(403, json={}), httpx.Response(403, json={})])
        ok(await sender.send(msg) == "auth" and await sender.send(msg) == "auth", "403 is a permission problem")
    finally:
        log.removeHandler(handler_)
    ok(seen.getvalue().count("fcm_auth_failed") == 1, f"one warning an hour: {seen.getvalue()!r}")
    other = fresh()
    script.append("token_refused")
    ok(await other.send(msg) == "auth", "a refused OAuth exchange is a key problem")
    ok(not script, f"every scripted answer used: {script}")
    for client in (sender, other):
        await client.close()

    ring = fcm_module.ring("g" * 20, "6f1c1d2e-3b4a-4c5d-8e9f-0a1b2c3d4e5f")
    ok("notification" not in ring and ring["data"] == {"kind": "ring", "ringId": "6f1c1d2e-3b4a-4c5d-8e9f-0a1b2c3d4e5f",
                                                       "v": "1", "reason": "promise"}
       and ring["android"]["ttl"] == "45s", ring)
    # A hello call (docs/04-functional-spec/call-first.md 3.4): reason hello and the preview line, 1~30, one line.
    ring = fcm_module.ring("g" * 20, "6f1c1d2e-3b4a-4c5d-8e9f-0a1b2c3d4e5f", "hello", " 나 털모자 샀다! ")
    ok(ring["data"] == {"kind": "ring", "ringId": "6f1c1d2e-3b4a-4c5d-8e9f-0a1b2c3d4e5f", "v": "1",
                        "reason": "hello", "line": "나 털모자 샀다!"}, ring)
    for line in ("가" * 31, "한 줄\n두 줄", "", None):
        ok("line" not in fcm_module.ring("g" * 20, "x", "hello", line)["data"], f"no line: {line!r}")
    ok(fcm_module.ring("g" * 20, "x", "odd", "줄")["data"]["reason"] == "promise"
       and "line" not in fcm_module.ring("g" * 20, "x", "promise", "줄")["data"], "only hello calls carry a line")
    ok(fcm_module.preview("가" * 130) == "가" * 119 + "…" and fcm_module.preview("가" * 120) == "가" * 120, "preview")
    with tempfile.TemporaryDirectory() as tmp:
        ok(fcm_module.FCM.from_credentials(None) is None and fcm_module.FCM.from_credentials(tmp) is None,
           "no key: no FCM")
        path = Path(tmp) / "fcm-service-account.json"
        path.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
        try:
            fcm_module.FCM.from_credentials(tmp)
            ok(False, "a key of the wrong type is refused")
        except ValueError:
            ok(True, "wrong key type")
        path.write_text(json.dumps({"type": "service_account", "token_uri": fcm_module.TOKEN_URL,
                                    "client_email": account.email, "private_key_id": "kid-1", "private_key": pem,
                                    "project_id": "from-key"}), encoding="utf-8")
        loaded = fcm_module.FCM.from_credentials(tmp, {"FCM_PROJECT_ID": "from-env"})
        ok(loaded.project == "from-env" and fcm_module.FCM.from_credentials(tmp, {}).project == "from-key",
           "FCM_PROJECT_ID overrides the key's project")
        await loaded.close()
    print("PASS FCM HTTP v1: OAuth with the service account, 200, UNREGISTERED, INVALID_ARGUMENT, 429 Retry-After, "
          "503, timeouts, 10 s budget, 401 and 403 with one warning an hour, key loading")


# ── the in-app chat against the database ─────────────────────────────────────

async def main(db):
    chat_module.WAIT_S, chat_module.WAIT_POLL_S = 1.5, 0.2
    logs = io.StringIO()
    capture = logging.StreamHandler(logs)
    capture.setLevel(logging.DEBUG)
    capture.setFormatter(logging.Formatter("%(name)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(capture)
    root.setLevel(logging.INFO)

    settings = load_settings()
    store = DiscordStore(db.app_url, call_bridge=True)
    await store.open(wait=True)
    answers = deque()
    llm = ScriptedLLM(lambda body: message([text(answers.popleft() if answers else "APP_REPLY_TEXT 그랬구나!")]))
    agent = DiscordAgent(settings, store, FakeEmbeddings(), llm)
    client = Client(agent, store)
    certs = Certs()
    access = AccessVerifier(AccessConfig(TEAM, AUD, frozenset({HK_EMAIL, DH_EMAIL})),
                            httpx.AsyncClient(transport=httpx.MockTransport(certs)))
    sender = FakeFCM()
    push = AppPush(store, sender)
    clock = [1000.0]
    chat = AppChat(store, agent, client, access, push, origin=ORIGIN, clock=lambda: clock[0])
    agent.on_saved = chat.pulse
    try:
        # The test server writes its own access log ('aiohttp.access'); the bot's runner writes none (checked below).
        async with TestClient(TestServer(chat.web_app())) as http:
            await sign_in_checks(db, http, chat, client, certs, access)
            await send_checks(db, http, chat, client, llm, store)
            await wait_checks(db, http, chat, client)
            await read_checks(db, http, chat, client, llm)
            await device_checks(db, http, chat, client, push, store)
            await reply_notice_checks(db, http, chat, client, sender)
            await delivery_checks(db, settings, store, agent, client, push, sender)
            await page_checks(http)
            await list_checks(db, http)
        await settle(chat)
        await own_runner_checks(store, agent, client, access, push, logs)
    finally:
        root.removeHandler(capture)
        await access.http.aclose()
        await store.close()
    text_logs = logs.getvalue()
    secrets = [HK_EMAIL, DH_EMAIL, STRANGER, FID_A, FID_B, INSTALL_A, INSTALL_B, "APP_HELLO_MARKER",
               "APP_REPLY_TEXT", "LOCKED_MARKER"] + TOKENS
    leaked = [line[:160] for line in text_logs.splitlines()
              if not line.startswith("aiohttp.access ") and any(s in line for s in secrets)]
    ok(not leaked, f"logs carry no text, FID, installId, email or token: {leaked}")
    ok("app_chat_sent" in text_logs and "fcm_send kind=reply" in text_logs, "result names are logged")
    print("PASS TC-131 logs: result names and counts only")


async def sign_in_checks(db, http, chat, client, certs, access):
    r = await http.get("/chat/healthz")
    ok(r.status == 200 and await r.text() == "ok", "healthz needs no sign-in")
    r = await http.get("/chat/api/me")
    await problem(r, 401, "unauthenticated")
    ok(r.headers["Cache-Control"] == "no-store" and r.headers["X-Frame-Options"] == "DENY"
       and "default-src 'self'" in r.headers["Content-Security-Policy"], "security headers on problems")
    for bad, why in ((dict(key=WRONG_KEY), "signature"), (dict(aud="other"), "aud"),
                     (dict(iss="https://other.cloudflareaccess.com"), "iss"), (dict(life=-120), "expired"),
                     (dict(drop=("email",)), "no email"), (dict(drop=("exp",)), "no exp"),
                     (dict(kid="unknown"), "unknown key"), (dict(alg="HS256"), "HS256")):
        await problem(await http.get("/chat/api/me", headers=auth(**bad)), 401, "unauthenticated")
    ok(certs.fetches == 1, f"keys fetched once, an unknown key id does not refetch within 5 min: {certs.fetches}")
    await problem(await http.get("/chat/api/me", headers=auth(STRANGER)), 403, "not_allowed")
    await problem(await http.get("/chat/api/me", headers=auth(DH_EMAIL)), 403, "not_allowed")  # not a call friend
    await problem(await http.get("/chat/api/me", headers=auth()), 403, "no_dm")  # no Discord DM yet
    access.expires, certs.fail = 0, True
    await problem(await http.get("/chat/api/me", headers=auth()), 503, "db_unavailable")
    certs.fail = False
    access.expires = 0
    # 현경's first Discord DM opens the in-app chat too.
    await client.on_message(event(client, HK, DM_HK, 1001, "HK_DISCORD_FIRST"))
    r = await http.get("/chat/api/me", headers=auth())
    me = await r.json()
    ok(r.status == 200 and me == {"name": "현경", "delivery": {"to": "discord", "reason": "no_device"},
                                  "ring": {"to": "discord", "reason": "ring_disabled", "fullScreen": None},
                                  "textMax": 2000}, me)
    db.admin("UPDATE call.callers SET enabled = false WHERE friend_id = 2")
    await problem(await http.get("/chat/api/me", headers=auth()), 403, "not_allowed")
    db.admin("UPDATE call.callers SET enabled = true WHERE friend_id = 2")

    ok(AccessConfig.from_env({}) is None, "no Access values")
    ok(AccessConfig.from_env({"CF_ACCESS_TEAM_DOMAIN": "evil.example.com", "CF_ACCESS_AUD": "a",
                              "CF_ACCESS_EMAILS": "a@b"}) is None, "not an Access team domain")
    config = AccessConfig.from_env({"CF_ACCESS_TEAM_DOMAIN": f"https://{TEAM}/", "CF_ACCESS_AUD": AUD,
                                    "CF_ACCESS_EMAILS": " HK@example.test , dh@example.test"})
    ok(config == AccessConfig(TEAM, AUD, frozenset({HK_EMAIL, DH_EMAIL})), config)
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"MARONG_APP_CHAT": "1"}, clear=False):
        for name in ("CF_ACCESS_TEAM_DOMAIN", "CF_ACCESS_AUD", "CF_ACCESS_EMAILS", "MARONG_APP_RING"):
            os.environ.pop(name, None)
        ok(run_discord.app_settings(Path(tmp)) is None, "without Access values the chat server never starts")
        os.environ.update({"CF_ACCESS_TEAM_DOMAIN": TEAM, "CF_ACCESS_AUD": AUD, "CF_ACCESS_EMAILS": HK_EMAIL})
        got = run_discord.app_settings(Path(tmp))
        ok(got["fcm"] is None and got["ring"] is False and got["port"] == 8796, "no key file: FCM off")
        os.environ["MARONG_APP_ORIGIN"] = "http://marong.example.test"
        try:
            run_discord.app_settings(Path(tmp))
            ok(False, "a plain-http origin is refused")
        except SystemExit:
            ok(True, "origin must be https")
        os.environ.pop("MARONG_APP_ORIGIN")
    with patch.dict(os.environ, {"MARONG_APP_CHAT": "0"}):
        ok(run_discord.app_settings(Path(".")) is None, "MARONG_APP_CHAT=0 keeps the bot as before")
    print("PASS TC-119 Access proof: signature, aud, iss, exp, claims, alg, allowlist, call friend, Discord DM first, "
          "key list outage, settings")


async def send_checks(db, http, chat, client, llm, store):
    url = "/chat/api/messages"
    sent_before = len(client.channels[DM_HK].sent)
    cid = str(uuid.uuid4())
    await problem(await http.post(url, json={"clientId": cid, "text": "x"}, headers=auth()), 403, "cross_site")
    await problem(await http.post(url, json={"clientId": cid, "text": "x"},
                                  headers=auth(write=True, origin="https://evil.example")), 403, "cross_site")
    await problem(await http.put(f"/chat/api/devices/{INSTALL_A}", headers=auth(),
                                 json={"fid": FID_A, "notifications": "granted", "appVersion": "0.2.0"}),
                  403, "cross_site")
    ok(not rows(db, "SELECT 1 FROM marong.messages WHERE kakao_id LIKE 'app:%%'"), "nothing saved from another site")
    print("PASS TC-120 writes from another site are refused")

    for body, field, reason in (({"text": "a"}, "clientId", "required"),
                                ({"clientId": cid.upper(), "text": "a"}, "clientId", "bad_format"),
                                ({"clientId": cid}, "text", "required"),
                                ({"clientId": cid, "text": "  \n "}, "text", "too_short"),
                                ({"clientId": cid, "text": "가" * 2001}, "text", "too_long"),
                                ({"clientId": cid, "text": 3}, "text", "bad_format"),
                                ({"clientId": cid, "text": "a", "extra": 1}, "body", "bad_format")):
        await problem(await http.post(url, json=body, headers=auth(write=True)), 400, "invalid_request", field, reason)
    await problem(await http.post(url, data="not json", headers=auth(write=True)), 400, "invalid_request",
                  "body", "bad_format")
    await problem(await http.post(url, json=[1], headers=auth(write=True)), 400, "invalid_request", "body", "bad_format")

    calls = len(llm.bodies)
    r = await http.post(url, json={"clientId": cid, "text": "  APP_HELLO_MARKER  "}, headers=auth(write=True))
    first = (await r.json())["message"]
    ok(r.status == 202 and first["from"] == "me" and first["text"] == "APP_HELLO_MARKER" and first["via"] == "app"
       and first["kind"] == "chat" and first["at"].endswith("+09:00"), first)
    await settle(chat)
    again = await http.post(url, json={"clientId": cid, "text": "APP_HELLO_MARKER"}, headers=auth(write=True))
    ok(again.status == 200 and (await again.json())["message"]["id"] == first["id"], "the same clientId is one message")
    await settle(chat)
    ok(len(llm.bodies) == calls + 1, "answered once")
    saved = rows(db, "SELECT room_key, kakao_id, meta FROM marong.messages WHERE id = %s", (first["id"],))[0]
    ok(saved == (HK_ROOM, f"app:{cid}", {"transport": "app"}), saved)
    reply = rows(db, "SELECT role, content, reply_to, meta FROM marong.messages WHERE reply_to = %s", (first["id"],))
    ok(len(reply) == 1 and reply[0][0] == "assistant" and reply[0][3]["transport"] == "app"
       and reply[0][3]["delivered"] is True, reply)
    body = json.dumps(llm.bodies[-1], ensure_ascii=False)
    ok("마롱이 앱의 글 대화 화면" in body and "HK_DISCORD_FIRST" in body and "APP_HELLO_MARKER" in body,
       "Marong knows it is the app and keeps the Discord conversation")
    ok(len(client.channels[DM_HK].sent) == sent_before, "the app's answer does not go to Discord")
    link = rows(db, "SELECT last_incoming_at > now() - interval '1 minute' FROM marong.discord_dm_links "
                    "WHERE discord_user_id = %s", (HK,))[0][0]
    ok(link, "an app message counts as the friend talking")

    cid2 = str(uuid.uuid4())
    calls = len(llm.bodies)
    both = await asyncio.gather(*(http.post(url, json={"clientId": cid2, "text": "TWICE_AT_ONCE"},
                                            headers=auth(write=True)) for _ in range(2)))
    await settle(chat)
    ok(sorted(r.status for r in both) == [200, 202] and len(llm.bodies) == calls + 1, "two at once: one message")
    print("PASS TC-121 same clientId saved and answered once, also when sent twice at once")

    lock = client.room_lock(HK_ROOM)
    await lock.acquire()
    calls = len(llm.bodies)
    r = await http.post(url, json={"clientId": str(uuid.uuid4()), "text": "LOCKED_MARKER"}, headers=auth(write=True))
    locked = (await r.json())["message"]
    await asyncio.sleep(0.3)
    ok(r.status == 202 and len(llm.bodies) == calls, "the answer waits for the room's Discord answer")
    began = time.monotonic()
    w = await (await http.get(f"/chat/api/messages/wait?after={locked['id']}&typing=0", headers=auth())).json()
    ok(w["typing"] is True and time.monotonic() - began < 1, f"Marong is writing: {w}")
    lock.release()
    await settle(chat)
    ok(len(llm.bodies) == calls + 1, "then it answers")

    async def say(words):
        r = await http.post(url, json={"clientId": str(uuid.uuid4()), "text": words}, headers=auth(write=True))
        await settle(chat)
        mid = (await r.json())["message"]["id"]
        return rows(db, "SELECT content FROM marong.messages WHERE reply_to = %s", (mid,))[0][0]

    ok(await say("선톡 끄기") == "응, 먼저 연락하는 건 멈출게.", "opt-out from the app")
    ok(rows(db, "SELECT opted_in_at FROM marong.discord_dm_links WHERE discord_user_id = %s", (HK,))[0][0] is None,
       "opted out")
    ok(await say("먼저 톡해 줘") == "응, 나도 먼저 톡할게 🌰", "opt-in from the app")
    ok(await say("구글 캘린더 연결") == APP_GOOGLE_TEXT, "Google linking stays in the Discord DM")

    chat.sent[2] = deque([clock_now(chat) - 10] * 20)
    r = await http.post(url, json={"clientId": str(uuid.uuid4()), "text": "too many"}, headers=auth(write=True))
    await problem(r, 429, "too_many_messages")
    ok(r.headers["Retry-After"] == "50", r.headers.get("Retry-After"))
    chat.sent[2].clear()
    print("PASS TC-122 the DM room and its lock, opt-in/out and Google from the app, 21st message in a minute is 429")


def clock_now(chat):
    return chat.clock()


async def wait_checks(db, http, chat, client):
    def wait(after, typing=0):
        return http.get(f"/chat/api/messages/wait?after={after}&typing={typing}", headers=auth())

    top = rows(db, "SELECT max(id) FROM marong.messages WHERE room_key = %s", (HK_ROOM,))[0][0]
    began = time.monotonic()
    r = await (await wait(0)).json()
    ok(r["messages"] and time.monotonic() - began < 0.5, "messages after 'after' come at once")
    began = time.monotonic()
    r = await (await wait(top)).json()
    ok(not [m for m in r["messages"] if m["id"] > top] and r["typing"] is False
       and 1.4 <= time.monotonic() - began < 3, "nothing new: an empty answer after the wait")

    pending = asyncio.ensure_future(wait(top))
    await asyncio.sleep(0.2)
    began = time.monotonic()
    sent = await http.post("/chat/api/messages", json={"clientId": str(uuid.uuid4()), "text": "WAIT_PULSE"},
                           headers=auth(write=True))
    mine = (await sent.json())["message"]
    r = await (await pending).json()
    ok(mine["id"] in [m["id"] for m in r["messages"]] and time.monotonic() - began < 1, "a saved message wakes it")
    await settle(chat)

    top = rows(db, "SELECT max(id) FROM marong.messages WHERE room_key = %s", (HK_ROOM,))[0][0]
    pending = asyncio.ensure_future(wait(top))
    await asyncio.sleep(0.1)
    new = db.admin("INSERT INTO marong.messages(room_key, user_key, role, content, kakao_id) "
                   "VALUES (%s, %s, 'user', 'FROM_ANOTHER_PROCESS', 'other:1') RETURNING id",
                   (HK_ROOM, f"discord-user:{HK}"))[0][0]
    began = time.monotonic()
    r = await (await pending).json()
    ok(new in [m["id"] for m in r["messages"]] and time.monotonic() - began < 0.8, "the DB check finds it")

    late = db.admin("INSERT INTO marong.messages(room_key, role, content, meta) VALUES "
                    "(%s, 'assistant', 'LATE_COMMIT', '{\"delivered\": true}') RETURNING id", (HK_ROOM,))[0][0]
    after = db.admin("INSERT INTO marong.messages(room_key, role, content, meta) VALUES "
                     "(%s, 'assistant', 'COMMITTED_FIRST', '{\"delivered\": true}') RETURNING id", (HK_ROOM,))[0][0]
    r = await (await wait(after)).json()
    ok(late in [m["id"] for m in r["messages"]], "a message committed late (smaller id) still comes")

    waits = []
    for _ in range(4):  # one after another, so the first is the oldest
        waits.append(asyncio.ensure_future(wait(after)))
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.1)
    began = time.monotonic()
    fifth = asyncio.ensure_future(wait(after))
    first = await waits[0]
    ok((await first.json())["messages"] == [] and time.monotonic() - began < 0.6, "a 5th wait ends the oldest empty")
    await asyncio.gather(fifth, *waits[1:])
    ok(not chat.waiters, "no waits left")
    for query, field in (("", "after"), ("?after=-1", "after"), ("?after=x", "after"),
                         ("?after=1&typing=2", "typing")):
        reason = "required" if not query else "bad_format"
        await problem(await http.get(f"/chat/api/messages/wait{query}", headers=auth()), 400, "invalid_request",
                      field, reason)
    print("PASS TC-123 waits: at once, empty after the wait, woken by a save, DB check, late commits, four per friend, "
          "typing")


async def read_checks(db, http, chat, client, llm):
    """'읽음' and '대답 중' (docs/app-chat.md SPEC-148, SPEC-149): an answer that takes up the friend's message reads
    it and everything before it, an answered message is no longer only read, and '대답 중' lasts while any message of
    the friend's is not answered yet, also when Marong's answer to an earlier one came after it (BUG-106)."""
    url = "/chat/api/messages"

    def wait(after, typing=0, read=None):
        query = f"?after={after}&typing={typing}" + ("" if read is None else f"&read={read}")
        return http.get(f"/chat/api/messages/wait{query}", headers=auth())

    async def send(words):
        r = await http.post(url, json={"clientId": str(uuid.uuid4()), "text": words}, headers=auth(write=True))
        return (await r.json())["message"]

    async def marks():
        return await (await http.get(f"{url}?limit=1", headers=auth())).json()

    async def taken_up(message_id):
        for _ in range(100):
            if chat.read.get(HK_ROOM) == message_id:
                return
            await asyncio.sleep(0.02)
        ok(False, f"an answer took up {message_id}: {chat.read.get(HK_ROOM)}")

    def newest_answer():
        return rows(db, "SELECT max(reply_to) FROM marong.messages WHERE room_key = %s AND role = 'assistant'",
                    (HK_ROOM,))[0][0]

    gates = deque()
    real = llm.create

    async def gated(body, timeout):
        if gates:
            await gates.popleft().wait()
        return await real(body, timeout)

    llm.create = gated
    try:
        page = await marks()
        answered = newest_answer()
        other = rows(db, "SELECT id FROM marong.messages WHERE kakao_id = 'other:1'")[0][0]
        ok(page["answeredUpTo"] == answered and page["readUpTo"] == answered and other > answered,
           f"history: read up to the last answered message, a message no answer took up is not read: {page}")

        lock = client.room_lock(HK_ROOM)
        await lock.acquire()
        began = time.monotonic()
        r = await (await wait(page["messages"][-1]["id"], typing=0, read=page["readUpTo"])).json()
        ok(r["typing"] is True and r["readUpTo"] == answered and time.monotonic() - began < 1,
           f"a held room with a message no answer took up: writing, still not read: {r}")
        lock.release()

        first, second = asyncio.Event(), asyncio.Event()
        gates.extend([first, second])
        began = time.monotonic()
        a = await send("READ_FIRST")
        r = await (await wait(a["id"], typing=0, read=page["readUpTo"])).json()
        ok(r["readUpTo"] == a["id"] and r["answeredUpTo"] == answered and r["typing"] is True
           and time.monotonic() - began < 1, f"taken up at once: read with what came before, writing: {r}")
        b = await send("READ_SECOND")
        page = await marks()
        ok(page["readUpTo"] == a["id"] and page["answeredUpTo"] == answered,
           f"a message waiting behind the answer in progress is not read yet: {page}")

        first.set()
        await taken_up(b["id"])
        reply_a = rows(db, "SELECT id FROM marong.messages WHERE reply_to = %s", (a["id"],))[0][0]
        last = rows(db, "SELECT role FROM marong.messages WHERE room_key = %s ORDER BY id DESC LIMIT 1",
                    (HK_ROOM,))[0][0]
        began = time.monotonic()
        r = await (await wait(reply_a, typing=0, read=a["id"])).json()
        ok(reply_a > b["id"] and last == "assistant" and r["typing"] is True and r["readUpTo"] == b["id"]
           and r["answeredUpTo"] == a["id"] and time.monotonic() - began < 1,
           f"the second message: read and '대답 중' though the answer to the first came after it: {r}")

        began = time.monotonic()
        pending = asyncio.ensure_future(wait(reply_a, typing=1, read=b["id"]))
        await asyncio.sleep(0.2)
        second.set()
        r = await (await pending).json()
        ok([m["from"] for m in r["messages"] if m["id"] > reply_a] == ["marong"] and r["typing"] is False
           and r["readUpTo"] == r["answeredUpTo"] == b["id"] and time.monotonic() - began < 1,
           f"answered: no longer only read, not writing: {r}")
        await settle(chat)

        third = asyncio.Event()
        gates.append(third)
        await lock.acquire()
        c = await send("READ_OLD_SCREEN")
        pending = asyncio.ensure_future(wait(c["id"], typing=1))
        await asyncio.sleep(0.2)
        lock.release()
        await taken_up(c["id"])
        r = await (await pending).json()
        ok(not [m for m in r["messages"] if m["id"] > c["id"]] and r["typing"] is True and r["readUpTo"] == c["id"],
           f"a screen from before '읽음' (no read) gets no early end for it, the answer still says so: {r}")
        third.set()
        await settle(chat)
        ok(newest_answer() == c["id"], "then it is answered")
        await lock.acquire()
        top = rows(db, "SELECT max(id) FROM marong.messages WHERE room_key = %s", (HK_ROOM,))[0][0]
        began = time.monotonic()
        r = await (await wait(top, typing=1, read=c["id"])).json()
        ok(r["typing"] is False and time.monotonic() - began < 1,
           f"a held room with everything answered is not writing (a 선톡 being written): {r}")
        lock.release()

        for query in ("?after=1&read=x", "?after=1&read=-1"):
            await problem(await http.get(f"/chat/api/messages/wait{query}", headers=auth()), 400, "invalid_request",
                          "read", "bad_format")
        kept = dict(chat.read)
        for n in range(chat_module.READ_ROOMS_MAX + 5):
            chat._took_up(f"discord-dm:test-{n}", 1)
        ok(len(chat.read) == chat_module.READ_ROOMS_MAX and HK_ROOM not in chat.read, "only the newest rooms are kept")
        page = await marks()
        ok(page["readUpTo"] == page["answeredUpTo"] == c["id"], f"a room no longer kept reads what was answered: {page}")
        chat.read.clear()
        chat.read.update(kept)
    finally:
        llm.create = real
        gates.clear()
    print("PASS TC-155 읽음: up to the message an answer took up, gone once answered, old screens; "
          "TC-156 대답 중 also for the second of two messages (BUG-106)")


async def device_checks(db, http, chat, client, push, store):
    def put(install, body, email=HK_EMAIL):
        return http.put(f"/chat/api/devices/{install}", json=body, headers=auth(email, write=True))

    good = {"fid": FID_A, "notifications": "granted", "appVersion": "0.2.0"}
    r = await put(INSTALL_A, good)
    ok(r.status == 201 and await r.json() == {"delivery": {"to": "app", "reason": "app_on"},
                                              "ring": {"to": "discord", "reason": "ring_disabled",
                                                       "fullScreen": None}}, "new phone: 201")
    r = await put(INSTALL_A, good)
    ok(r.status == 200, "known phone: 200")
    me = await (await http.get("/chat/api/me", headers=auth())).json()
    ok(me["delivery"] == {"to": "app", "reason": "app_on"}, me)
    push.ring_enabled = True
    r = await (await put(INSTALL_A, {**good, "ring": {"channel": "enabled", "fullScreen": "denied"}})).json()
    ok(r["ring"] == {"to": "app", "reason": "app_on", "fullScreen": False}, r)
    r = await (await put(INSTALL_A, {**good, "ring": {"channel": "disabled", "fullScreen": "granted"}})).json()
    ok(r["ring"] == {"to": "discord", "reason": "ring_off", "fullScreen": True}, r)
    r = await (await put(INSTALL_A, good)).json()
    ok(r["ring"] == {"to": "discord", "reason": "old_app", "fullScreen": None}, r)
    push.ring_enabled = False
    r = await (await put(INSTALL_A, {**good, "notifications": "denied"})).json()
    ok(r["delivery"] == {"to": "discord", "reason": "notifications_off"}, r)
    r = await (await put(INSTALL_A, {**good, "fid": None})).json()
    ok(r["delivery"] == {"to": "discord", "reason": "no_fid"}, r)
    await put(INSTALL_A, good)
    db.admin("UPDATE marong.app_devices SET seen_at = now() - interval '31 days' WHERE install_id = %s", (INSTALL_A,))
    me = await (await http.get("/chat/api/me", headers=auth())).json()
    ok(me["delivery"] == {"to": "discord", "reason": "not_seen"}, me)
    ok(AppPush(store, None).delivery(await store.app_devices(2)) == {"to": "discord", "reason": "fcm_off"}, "no key")
    await put(INSTALL_A, good)

    r = await put(INSTALL_B, {**good, "fid": FID_A})
    ok(r.status == 201 and rows(db, "SELECT fid FROM marong.app_devices WHERE install_id = %s", (INSTALL_A,))[0][0]
       is None, "the same FID on another install id clears the old row")
    await put(INSTALL_A, good)
    ok(rows(db, "SELECT fid FROM marong.app_devices WHERE install_id = %s", (INSTALL_B,))[0][0] is None, "and back")
    # 동희 signs in on 현경's phone: the install id moves to 동희.
    db.admin("INSERT INTO call.callers(friend_id) VALUES (1)")
    db.admin("INSERT INTO call.caller_logins(email_sha256, caller_id, email_hint) SELECT %s, id, 'd***@example.test' "
             "FROM call.callers WHERE friend_id = 1", (email_hash(DH_EMAIL),))
    await client.on_message(event(client, DH, DM_DH, 2001, "DH_FIRST"))
    r = await put(INSTALL_B, {**good, "fid": FID_B}, DH_EMAIL)
    ok(r.status == 200 and rows(db, "SELECT friend_id FROM marong.app_devices WHERE install_id = %s",
                                (INSTALL_B,))[0][0] == 1, "an install id seen with another friend moves")
    for install, body, field, reason in (
            (INSTALL_A.upper(), good, "installId", "bad_format"),
            (INSTALL_A, {**good, "fid": "short"}, "fid", "bad_format"),
            (INSTALL_A, {k: v for k, v in good.items() if k != "fid"}, "fid", "required"),
            (INSTALL_A, {**good, "notifications": "maybe"}, "notifications", "bad_format"),
            (INSTALL_A, {**good, "appVersion": "1.2"}, "appVersion", "bad_format"),
            (INSTALL_A, {**good, "ring": {"channel": "enabled"}}, "body", "bad_format"),
            (INSTALL_A, {**good, "extra": True}, "body", "bad_format")):
        await problem(await put(install, body), 400, "invalid_request", field, reason)
    with psycopg.connect(db.app_url, autocommit=True) as conn:
        try:
            conn.execute("DELETE FROM marong.app_devices")
            ok(False, "the bot account cannot delete phones")
        except psycopg.errors.InsufficientPrivilege:
            ok(True, "no DELETE")
    print("PASS TC-125/130 phones: 201/200, FID moves, install id moves, reasons app_on, notifications_off, no_fid, "
          "not_seen, fcm_off, ring states, input checks, no DELETE")


async def reply_notice_checks(db, http, chat, client, sender):
    before = len(sender.sent)
    r = await http.post("/chat/api/messages", json={"clientId": str(uuid.uuid4()), "text": "CLOSED_SCREEN"},
                        headers=auth(write=True))
    await settle(chat)
    note = sender.sent[before:]
    ok(r.status == 202 and len(note) == 1 and note[0]["fid"] == FID_A and note[0]["data"] == {"kind": "reply",
       "open": "/chat/"} and note[0]["android"]["ttl"] == "3600s"
       and note[0]["android"]["notification"]["channel_id"] == TALK
       and note[0]["notification"]["body"].startswith("APP_REPLY_TEXT"), note)

    lock = client.room_lock(HK_ROOM)
    await lock.acquire()
    r = await http.post("/chat/api/messages", json={"clientId": str(uuid.uuid4()), "text": "OPEN_SCREEN"},
                        headers=auth(write=True))
    mid = (await r.json())["message"]["id"]
    open_wait = asyncio.ensure_future(http.get(f"/chat/api/messages/wait?after={mid}&typing=1", headers=auth()))
    await asyncio.sleep(0.3)
    before = len(sender.sent)
    lock.release()
    got = await (await open_wait).json()
    await settle(chat)
    ok(any(m["from"] == "marong" for m in got["messages"]) and len(sender.sent) == before,
       "a screen waiting for the reply gets it there, without a notification")
    print("PASS TC-129 reply notifications only when no chat screen is waiting")


async def own_runner_checks(store, agent, client, access, push, logs):
    """The bot's own server: 127.0.0.1 only and no access log (SPEC-110)."""
    import aiohttp
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    own = AppChat(store, agent, client, access, push, origin=ORIGIN, port=port)
    await own.serve()
    mark = len(logs.getvalue())
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/chat/api/devices/{INSTALL_A}") as r:
                ok(r.status == 405, "PUT only")
            async with session.get(f"http://127.0.0.1:{port}/chat/healthz") as r:
                ok(r.status == 200, "the bot's server answers on 127.0.0.1")
        bad = [line[:200] for line in logs.getvalue()[mark:].splitlines()
               if line.startswith("aiohttp.access") or INSTALL_A in line]
        ok(not bad, f"no access log: {bad}")
        sockets = [s.getsockname()[0] for site in own.runner.sites for s in site._server.sockets]
        ok(sockets == ["127.0.0.1"], sockets)
    finally:
        await own.close()


def reset_proactive(db):
    db.admin("UPDATE marong.discord_dm_links SET last_slot = NULL, last_attempt_at = NULL, failures = 0, "
             "last_incoming_at = now() - interval '2 hours', opted_in_at = now() - interval '2 hours' "
             "WHERE discord_user_id = %s", (HK,))


async def delivery_checks(db, settings, store, agent, client, push, sender):
    channel = client.channels[DM_HK]

    async def proactive():
        reset_proactive(db)
        room = (await store.proactive_rooms(HK_ROOM))[0]
        plan = DiscordProactive(settings, store, agent, client, clock=lambda: NOW, rng=lambda: 0, app=push,
                                sleep=lambda s: asyncio.sleep(0))
        result = await plan.deliver(room)
        last = rows(db, "SELECT meta FROM marong.messages WHERE room_key = %s AND meta->>'proactive' = 'true' "
                        "ORDER BY id DESC LIMIT 1", (HK_ROOM,))[0][0]
        return result, last

    sent, before = len(channel.sent), len(sender.sent)
    result, meta = await proactive()
    note = sender.sent[before:]
    ok(result["ok"] and len(channel.sent) == sent and len(note) == 1 and note[0]["data"]["kind"] == "proactive"
       and note[0]["android"]["ttl"] == "7200s" and note[0]["android"]["notification"]["channel_id"] == TALK
       and meta["transport"] == "app" and meta["devices"] == 1, (result, meta, note))
    sender.answers.append("failed")
    sent = len(channel.sent)
    result, meta = await proactive()
    ok(result["ok"] and len(channel.sent) > sent and meta["transport"] == "discord", "every phone failed: Discord")
    sender.answers.append("gone")
    result, meta = await proactive()
    ok(meta["transport"] == "discord" and rows(db, "SELECT fid, dropped_at IS NOT NULL FROM marong.app_devices "
                                                   "WHERE install_id = %s", (INSTALL_A,))[0] == (None, True),
       "FCM no longer knows the phone: its FID is dropped and Discord gets it")
    await put_device(db, INSTALL_A, FID_A)
    client.available = False
    before = len(sender.sent)
    result, meta = await proactive()
    ok(result["ok"] and meta["transport"] == "app" and len(sender.sent) == before + 1, "Discord down: the app still")
    db.admin("UPDATE marong.app_devices SET notifications = 'denied' WHERE install_id = %s", (INSTALL_A,))
    calls = len(agent.llm.bodies)
    result, _ = await proactive()
    ok(not result["ok"] and len(agent.llm.bodies) == calls and rows(
        db, "SELECT last_slot FROM marong.discord_dm_links WHERE discord_user_id = %s", (HK,))[0][0] is None,
       "Discord down and no phone: the slot is kept for later and nothing is written")
    client.available = True
    sent = len(channel.sent)
    result, meta = await proactive()
    ok(result["ok"] and len(channel.sent) > sent and meta["transport"] == "discord", "no phone: Discord as before")
    db.admin("UPDATE marong.app_devices SET notifications = 'granted' WHERE install_id = %s", (INSTALL_A,))
    print("PASS TC-127 proactive messages: app only with a phone, Discord when every phone fails or none, "
          "app while Discord is down, gone FIDs dropped")

    reminders = DiscordReminders(settings, store, agent, client, app=push)

    def due(title, late="1 minute"):
        return db.admin("INSERT INTO marong.schedules(friend_id, room_key, title, remind_at) "
                        "VALUES (2, %s, %s, now() - %s::interval) RETURNING id", (HK_ROOM, title, late))[0][0]

    def state(sid):
        return rows(db, "SELECT status, failures, claimed_until > now() + interval '50 seconds' "
                        "FROM marong.schedules WHERE id = %s", (sid,))[0]

    def record(sid):
        return rows(db, "SELECT content, meta FROM marong.messages WHERE meta->>'reminder' = %s", (str(sid),))

    sid = due("물 마시기")
    sent, before = len(channel.sent), len(sender.sent)
    ok(await reminders.step() == 1, "one reminder")
    note = sender.sent[before:]
    ttl = int(note[0]["android"]["ttl"][:-1])
    ok(len(note) == 1 and note[0]["data"]["kind"] == "reminder" and REMINDER ==
       note[0]["android"]["notification"]["channel_id"] and 10_700 < ttl <= 10_740 and len(channel.sent) == sent
       and state(sid)[0] == "done" and record(sid)[0][1]["transport"] == "app", (note, record(sid)))
    sid = due("약 먹기")
    sender.answers.append("failed")
    ok(await reminders.step() == 1 and len(channel.sent) == sent + 1 and record(sid)[0][1]["transport"] == "discord",
       "the app failed: Discord")
    db.admin("UPDATE marong.app_devices SET notifications = 'denied' WHERE install_id = %s", (INSTALL_A,))
    client.available = False
    sid = due("우산 챙기기")
    ok(await reminders.step() == 0 and state(sid) == ("active", 0, True) and not record(sid),
       "no phone and Discord away: tried again later without counting a failure")
    client.available = True
    db.admin("UPDATE marong.schedules SET claimed_until = NULL WHERE id = %s", (sid,))
    ok(await reminders.step() == 1 and state(sid)[0] == "done" and record(sid)[0][1]["transport"] == "discord",
       "Discord back: sent there")
    sid = due("너무 늦은 알림", "4 hours")
    ok(await reminders.step() == 0 and state(sid)[0] == "missed", "over three hours late: missed")
    db.admin("UPDATE marong.app_devices SET notifications = 'granted' WHERE install_id = %s", (INSTALL_A,))
    print("PASS TC-128 reminders: app with ttl, Discord on failure or without a phone, later when nothing can go, "
          "missed when too late")


async def put_device(db, install, fid):
    db.admin("UPDATE marong.app_devices SET fid = %s, dropped_at = NULL, notifications = 'granted', seen_at = now() "
             "WHERE install_id = %s", (fid, install))


async def page_checks(http):
    r = await http.get("/chat", allow_redirects=False)
    ok(r.status == 302 and r.headers["Location"] == "/chat/", "/chat → /chat/")
    for path, kind in (("/chat/", "text/html"), ("/chat/chat.js", "text/javascript"), ("/chat/chat.css", "text/css")):
        r = await http.get(path)
        ok(r.status == 200 and r.headers["Content-Type"].startswith(kind) and r.headers["Cache-Control"] == "no-store"
           and "frame-ancestors 'none'" in r.headers["Content-Security-Policy"], f"{path} {r.headers}")
    ok((await http.get("/chat/other.js")).status == 404, "only the three files")
    html = await (await http.get("/chat/")).text()
    ok("<script" in html and "script src=\"/chat/chat.js" in html and "style=" not in html
       and "onclick" not in html, "no inline script or style (the CSP allows only files)")
    js = await (await http.get("/chat/chat.js")).text()
    ok("innerHTML" not in js and "textContent" in js and "redirect: 'manual'" in js, "text goes in as text")
    print("PASS SPEC-124 page files with no inline code, served without sign-in checks behind Access")


async def list_checks(db, http):
    marker = lambda content, meta: db.admin(  # noqa: E731
        "INSERT INTO marong.messages(room_key, role, content, meta) VALUES (%s, 'assistant', %s, %s::jsonb) RETURNING id",
        (HK_ROOM, content, json.dumps(meta)))[0][0]
    marker("UNDELIVERED_MARKER", {"delivered": False})
    marker("FORGOTTEN_MARKER", {"delivered": True, "memory": {"call_revision": 0}})
    db.admin("UPDATE call.callers SET context_revision = 1 WHERE friend_id = 2")
    marker(f"LINK_MARKER {LINK_MARK}", {"delivered": True})
    marker("PROACTIVE_MARKER", {"delivered": True, "proactive": True, "transport": "app"})
    marker("REMINDER_MARKER", {"delivered": True, "reminder": 1, "transport": "discord"})
    marker("RING_MARKER", {"delivered": True, "ring": "late", "reminder": 2, "transport": "app"})
    db.admin("INSERT INTO marong.messages(room_key, user_key, role, content, kakao_id) VALUES "
             "(%s, %s, 'user', 'DH_DM_MARKER', 'discord:9')", (f"discord-dm:{DH}", f"discord-user:{DH}"))
    every, before = [], ""
    while True:  # all pages, newest first
        got = await (await http.get(f"/chat/api/messages?limit=50{before}", headers=auth())).json()
        every = got["messages"] + every
        if not got["hasMore"]:
            break
        before = f"&before={got['messages'][0]['id']}"
    texts = {m["text"]: m for m in every}
    joined = "\n".join(texts)
    ok(all(x not in joined for x in ("UNDELIVERED_MARKER", "FORGOTTEN_MARKER", "HK_OWN_KAKAO", "DH_DM_MARKER",
                                     "DH_FIRST")), "undelivered, call-deleted, Kakao and other rooms stay out")
    ok("LINK_MARKER (일회용 링크)" in texts and texts["PROACTIVE_MARKER"]["kind"] == "proactive"
       and texts["PROACTIVE_MARKER"]["via"] == "app" and texts["REMINDER_MARKER"]["kind"] == "reminder"
       and texts["REMINDER_MARKER"]["via"] == "discord" and texts["RING_MARKER"]["kind"] == "ring"
       and texts["HK_DISCORD_FIRST"]["via"] == "discord" and texts["HK_DISCORD_FIRST"]["from"] == "me",
       "kinds, ways and the one-time link mark")
    ids = [m["id"] for m in every]
    ok(ids == sorted(ids) and len(set(ids)) == len(ids), "oldest first, once each")
    page = await (await http.get("/chat/api/messages?limit=2", headers=auth())).json()
    older = await (await http.get(f"/chat/api/messages?limit=2&before={page['messages'][0]['id']}",
                                  headers=auth())).json()
    ok(page["hasMore"] and len(page["messages"]) == 2 and older["messages"][-1]["id"] < page["messages"][0]["id"],
       "pages before an id")
    for query, field in (("?limit=51", "limit"), ("?limit=0", "limit"), ("?before=0", "before"),
                         ("?before=1e3", "before")):
        await problem(await http.get(f"/chat/api/messages{query}", headers=auth()), 400, "invalid_request", field,
                      "bad_format")
    print("PASS TC-124 reading: DM room only, no undelivered or call-deleted words, kinds, link mark, pages")


if __name__ == "__main__":
    asyncio.run(fcm_checks())
    db = TestDB()
    try:
        prepare(db)
        asyncio.run(main(db))
    finally:
        db.close()
    print(f"OK {CHECKS} checks")
