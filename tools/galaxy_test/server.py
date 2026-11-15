#!/usr/bin/env python3
"""마롱이 통화 갤럭시 시험(기능 명세 7.1)용 작은 서버.

- 표준 라이브러리만 써요. 127.0.0.1에만 붙고, 바깥 HTTPS는 Cloudflare 임시 터널(run.sh)이 맡아요.
- 휴대폰이 보낸 WebRTC offer를 OpenAI `POST /v1/live/sessions`로 넘기고 answer를 돌려줘요.
  OpenAI 키는 이 서버에만 있고 휴대폰에는 가지 않아요.
- 비용 상한: 세션 수(TEST_MAX_SESSIONS), 세션 길이(TEST_MAX_SESSION_MIN), 모든 세션을 더한 통화 시간
  (TEST_MAX_TOTAL_MIN, 기본 120분 ≈ 6달러), 서버 수명(TEST_RUN_HOURS).
  길이를 넘긴 세션과, 더한 시간이 상한에 닿았을 때 열려 있는 세션은 sideband(`/attach`)로 `session.close`를 보내 닫아요.
- 기록에는 말 내용이 없어요. 시각, 상태, 소리 크기, 이벤트 종류와 수, 시험하는 사람이 누른 결과만 적어요.
  sideband로 오는 원음 사본과 자막은 읽자마자 버려요.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
STATIC = HERE / "static"
FACE = REPO / "marong" / "call" / "static" / "face" / "v1" / "01-neutral.webp"
PROMPT_PATH = REPO / "call_prompt.md"
KST = timezone(timedelta(hours=9))


def _env_num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


BIND = os.environ.get("TEST_BIND", "127.0.0.1:8791")
MAX_SESSIONS = int(_env_num("TEST_MAX_SESSIONS", 16))
MAX_SESSION_MIN = _env_num("TEST_MAX_SESSION_MIN", 20)
MAX_TOTAL_MIN = _env_num("TEST_MAX_TOTAL_MIN", 120)
MAX_OPEN = 3
RUN_HOURS = _env_num("TEST_RUN_HOURS", 8)
LOG_DIR = Path(os.environ.get("TEST_LOG_DIR", "~/marong-galaxy-test")).expanduser()
KEY_FILE = Path(os.environ.get("OPENAI_KEY_FILE", "~/.config/marong-call/openai.key")).expanduser()
OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
MODEL = os.environ.get("CALL_LIVE_MODEL", "gpt-live-1")
VOICE = os.environ.get("CALL_VOICE", "noeul")
CREATE_TIMEOUT = 15

# 휴대폰 데이터 채널에 허용하는 이벤트(기능 명세 F20: 화면이 보낼 것과 받을 것만). 시험에서는 화면이
# 인사와 위임 답(commentary)도 보내요. 실제 통화에서는 서버가 sideband로 보내요.
DC_CLIENT_EVENTS = ["session.close", "session.commentary.append"]
DC_SERVER_EVENTS = [
    "session.started", "session.closed", "session.usage.updated",
    "session.input_transcript.delta", "session.output_transcript.delta",
    "session.delegation.created", "session.commentary.appended", "error", "info",
]

OPENING = {
    "start": "전화가 연결됐어. 친구가 전화 받듯 짧게 먼저 말해.",
    "wake": "쉬던 전화가 다시 이어졌어. 친구가 방금 말을 걸었는데 첫마디를 못 들었을 수 있으니 "
            "자연스럽게 다시 물어봐도 돼. 인사는 하지 마.",
    "again": "연결이 끊겼다가 다시 이어졌어. 인사하지 말고 하던 얘기를 이어 가.",
}

PAGE_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
NAME_RE = re.compile(r"^[0-9A-Za-z가-힣 ]{1,10}$")
EVENT_KEYS = {"t", "k", "st", "vis", "s", "v", "n", "ms", "via", "sid", "exp_s", "memo", "ok", "dt", "fl"}
AGG_KEYS = {"micMax", "remMax", "remOn", "remN", "outTx", "inTx", "alive", "late", "tdN"}


def now_ms() -> int:
    return int(time.time() * 1000)


def kst(ms: int | float | None) -> str:
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000, KST).strftime("%H:%M:%S")


def load_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def build_instructions(name: str) -> str:
    base = PROMPT_PATH.read_text(encoding="utf-8").strip()
    when = datetime.now(KST)
    return (
        f"{base}\n\n# 지금 상황\n"
        f"- 지금 전화하는 친구: {name}\n"
        f"- 전화를 건 시각: {when.month}월 {when.day}일 {when.hour}시 {when.minute}분\n"
        "- 이 전화는 휴대폰에서 전화가 잘 되는지 보는 시험 통화야. 기억 자료는 없어.\n"
        "- 시험 통화라 기억 찾기, 기억해 두기, 잊어 주기는 아직 안 돼. 친구가 부탁하면 지금은 안 된다고 솔직하게 말해.\n"
    )


def session_body(sdp: str, kind: str, name: str) -> dict:
    return {
        "session": {
            "model": MODEL,
            "instructions": build_instructions(name),
            "input": [{"type": "message", "role": "developer",
                       "content": [{"type": "input_text", "text": OPENING[kind]}]}],
            "audio": {"output": {"voice": VOICE}},
            "delegation": {"type": "client", "acknowledgement_delay_ms": 800},
            "store": False,
            "client": {"data_channel": {
                "allowed_client_events": DC_CLIENT_EVENTS,
                "allowed_server_events": [{"type": t} for t in DC_SERVER_EVENTS],
            }},
        },
        "transport": {"type": "webrtc", "sdp": sdp},
    }


class OpenAIError(Exception):
    def __init__(self, status: int, code: str, param: str = ""):
        super().__init__(f"{status} {code} {param}".strip())
        self.status, self.code, self.param = status, code, param


def create_session(key: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{OPENAI_BASE}/live/sessions", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=CREATE_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        code, param = "http_error", ""
        try:
            err = json.loads(e.read().decode("utf-8")).get("error") or {}
            code = str(err.get("code") or err.get("type") or code)[:80]
            param = str(err.get("param") or "")[:120]
        except (ValueError, AttributeError, OSError):
            pass
        raise OpenAIError(e.code, code, param) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise OpenAIError(503, type(e).__name__) from None


# ---- sideband: 길이를 넘긴 세션을 닫는 최소 WebSocket 클라이언트(표준 라이브러리만) ----

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _recv_exact(s, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise EOFError("closed")
        buf += chunk
    return bytes(buf)


def _read_head(s) -> bytes:
    data = bytearray()
    while not data.endswith(b"\r\n\r\n"):
        data += _recv_exact(s, 1)
        if len(data) > 16384:
            raise OSError("header too long")
    return bytes(data)


def _ws_send(s, op: int, payload: bytes) -> None:
    head = bytearray([0x80 | op])
    n = len(payload)
    if n < 126:
        head.append(0x80 | n)
    elif n < 65536:
        head.append(0x80 | 126)
        head += n.to_bytes(2, "big")
    else:
        head.append(0x80 | 127)
        head += n.to_bytes(8, "big")
    mask = os.urandom(4)
    s.sendall(bytes(head) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))


def _ws_recv(s) -> tuple[int, bytes]:
    parts, first_op = [], None
    while True:
        b1, b2 = _recv_exact(s, 2)
        op, n = b1 & 0x0F, b2 & 0x7F
        if n == 126:
            n = int.from_bytes(_recv_exact(s, 2), "big")
        elif n == 127:
            n = int.from_bytes(_recv_exact(s, 8), "big")
        mask = _recv_exact(s, 4) if b2 & 0x80 else None
        data = _recv_exact(s, n)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if op >= 8:  # 제어 프레임은 조각나지 않아요
            return op, data
        if first_op is None:
            first_op = op
        parts.append(data)
        if b1 & 0x80:
            return first_op, b"".join(parts)


def _ws_open(session_id: str, key: str, timeout: float):
    host = urllib.parse.urlparse(OPENAI_BASE).hostname or "api.openai.com"
    path = urllib.parse.urlparse(OPENAI_BASE).path.rstrip("/") + f"/live/sessions/{session_id}/attach"
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        p = urllib.parse.urlparse(proxy)
        raw = socket.create_connection((p.hostname, p.port or 80), timeout=timeout)
        raw.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode())
        if b" 200" not in _read_head(raw).split(b"\r\n", 1)[0]:
            raw.close()
            raise OSError("proxy refused")
    else:
        raw = socket.create_connection((host, 443), timeout=timeout)
    s = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
    nonce = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n"
               f"Authorization: Bearer {key}\r\n\r\n").encode())
    head = _read_head(s)
    status = head.split(b"\r\n", 1)[0]
    accept = base64.b64encode(hashlib.sha1((nonce + _WS_GUID).encode()).digest())
    if b" 101" not in status or accept not in head:
        s.close()
        raise OSError(status.decode("latin-1")[:60])
    return s


def sideband_close(session_id: str, key: str, wait: float = 15.0) -> dict:
    """세션에 sideband로 붙어 session.close를 보내고 session.closed를 기다려요.
    오는 이벤트는 종류만 세고 내용(원음 사본, 자막)은 읽자마자 버려요."""
    if not SID_RE.match(session_id):
        return {"ok": False, "why": "bad_id"}
    result = {"ok": False, "types": {}}
    try:
        s = _ws_open(session_id, key, timeout=10)
    except (OSError, EOFError, ssl.SSLError) as e:
        return {"ok": False, "why": f"attach:{str(e)[:60]}"}
    try:
        _ws_send(s, 1, json.dumps({"type": "session.close", "event_id": "galaxy_test_cap"}).encode())
        deadline = time.time() + wait
        while time.time() < deadline:
            s.settimeout(max(0.5, deadline - time.time()))
            op, data = _ws_recv(s)
            if op == 8:
                result["why"] = "ws_closed"
                break
            if op == 9:
                _ws_send(s, 10, data)
                continue
            if op != 1:
                continue
            try:
                etype = json.loads(data.decode("utf-8")).get("type", "?")
            except ValueError:
                etype = "?"
            if etype == "session.closed":
                ev = json.loads(data.decode("utf-8"))
                result.update(ok=True, reason=ev.get("reason"), usage=(ev.get("usage") or {}).get("seconds"))
                break
            result["types"][etype] = result["types"].get(etype, 0) + 1
            del data  # 원음 사본·자막은 여기서 버려요
    except (OSError, EOFError, ssl.SSLError, ValueError) as e:
        result.setdefault("why", f"recv:{type(e).__name__}")
    finally:
        try:
            _ws_send(s, 8, b"")
            s.close()
        except OSError:
            pass
    return result


# ---- 상태와 기록 ----

class Run:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started = now_ms()
        self.deadline = self.started + int(RUN_HOURS * 3600 * 1000)
        self.sessions: list[dict] = []
        self.creating = 0
        self.beats: list[dict] = []
        self.events: list[dict] = []
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(LOG_DIR, 0o700)
        stamp = datetime.fromtimestamp(self.started / 1000, KST).strftime("%Y%m%d-%H%M%S")
        self.log_path = LOG_DIR / f"run-{stamp}.jsonl"
        fd = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self.log_file = os.fdopen(fd, "a", encoding="utf-8")

    def write(self, rec: dict) -> None:
        rec = {"ts": now_ms(), **rec}
        with self.lock:
            self.log_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.log_file.flush()

    def open_sessions(self) -> list[dict]:
        return [s for s in self.sessions if not s.get("closed_at")]

    def minutes_used(self) -> float:
        total = 0.0
        for s in self.sessions:
            if s.get("usage") is not None:
                total += s["usage"] / 60
            else:
                total += ((s.get("closed_at") or now_ms()) - s["created_at"]) / 60000
        return round(total, 1)


RUN: Run | None = None
KEY = ""
MODEL_CHECK = "-"
KEY_LOCK = threading.Lock()


def current_key() -> str:
    """키가 아직 없으면 키 파일을 다시 읽어요. 서버를 켠 뒤에 키를 넣어도 다시 켤 필요가 없어요."""
    global KEY, MODEL_CHECK
    if KEY:
        return KEY
    with KEY_LOCK:
        if not KEY:
            key = load_key()
            if key:
                KEY = key
                MODEL_CHECK = check_model(key)
                if RUN:
                    RUN.write({"src": "server", "k": "key_loaded", "model_check": MODEL_CHECK})
    return KEY


def check_model(key: str) -> str:
    """키가 맞고 이 모델을 쓸 수 있는지 요금 없는 모델 조회로 봐요(200이면 됨)."""
    if not key:
        return "no_key"
    req = urllib.request.Request(f"{OPENAI_BASE}/models/{MODEL}", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return str(r.status)
    except urllib.error.HTTPError as e:
        return str(e.code)
    except (urllib.error.URLError, OSError) as e:
        return type(e).__name__


def clean_event(e) -> dict | None:
    if not isinstance(e, dict):
        return None
    out = {}
    for k, v in e.items():
        if k not in EVENT_KEYS:
            continue
        if isinstance(v, bool) or v is None:
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = round(v, 4) if isinstance(v, float) else v
        elif isinstance(v, str):
            out[k] = v[:200] if k == "memo" else v[:100]
    return out if "k" in out else None


def clean_agg(a) -> dict:
    if not isinstance(a, dict):
        return {}
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in a.items()
            if k in AGG_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool)}


def short(text) -> str:
    return str(text)[:40]


class Handler(BaseHTTPRequestHandler):
    server_version = "marong-galaxy-test/1"
    sys_version = ""

    def log_message(self, fmt, *args):  # 요청 줄은 남기지 않아요
        return

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "microphone=(self), screen-wake-lock=(self)")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj: dict) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    # 정적 파일
    STATIC_FILES = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/index.html": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/worklet.js": ("worklet.js", "text/javascript; charset=utf-8"),
        "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
        "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
        "/icon-192.webp": ("icon-192.webp", "image/webp"),
    }
    CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; "
           "media-src 'self' blob: mediastream:; connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
           "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/healthz":
            return self._json(200, {"ok": True, "key": bool(current_key()), "model": MODEL_CHECK,
                                    "left_min": int((RUN.deadline - now_ms()) / 60000)})
        if path == "/report":
            return self._send(200, render_report().encode("utf-8"), "text/html; charset=utf-8",
                              {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
        if path == "/report.json":
            return self._json(200, report_data())
        if path in ("/icon-512.webp", "/face.webp"):
            return self._send(200, FACE.read_bytes(), "image/webp")
        if path in self.STATIC_FILES:
            name, ctype = self.STATIC_FILES[path]
            extra = {"Content-Security-Policy": self.CSP} if name == "index.html" else None
            if name == "sw.js":
                extra = {"Service-Worker-Allowed": "/"}
            return self._send(200, (STATIC / name).read_bytes(), ctype, extra)
        return self._json(404, {"error": "not_found"})

    def _origin_ok(self) -> bool:
        """다른 사이트에서 보낸 쓰기를 막아요. 터널이 Host를 그대로 넘기면 Origin으로, 아니면
        브라우저의 Sec-Fetch-Site로 같은 사이트인지 봐요."""
        origin = urllib.parse.urlparse(self.headers.get("Origin", ""))
        host = self.headers.get("Host", "")
        if origin.scheme in ("http", "https") and origin.netloc and origin.netloc == host:
            return True
        return bool(origin.netloc) and self.headers.get("Sec-Fetch-Site") == "same-origin"

    def _read_json(self, limit: int):
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return None, (415, "json_only")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, (400, "bad_length")
        if length <= 0 or length > limit:
            return None, (413, "too_large")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")), None
        except (ValueError, UnicodeDecodeError):
            return None, (400, "bad_json")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._origin_ok():
            return self._json(403, {"error": "origin"})
        limit = 64 * 1024 if path == "/api/session" else 256 * 1024
        body, err = self._read_json(limit)
        if err:
            return self._json(err[0], {"error": err[1]})
        if not isinstance(body, dict) or not PAGE_RE.match(str(body.get("page", ""))):
            return self._json(400, {"error": "page"})
        if path == "/api/session":
            return self.api_session(body)
        if path == "/api/beat":
            return self.api_beat(body)
        if path == "/api/end":
            return self.api_end(body)
        return self._json(404, {"error": "not_found"})

    def api_session(self, body: dict):
        page, kind = body["page"], body.get("kind")
        name = str(body.get("name") or "동희").strip()
        sdp = body.get("sdp")
        if kind not in OPENING or not isinstance(sdp, str) or not sdp.startswith("v=0") or len(sdp) > 32768:
            return self._json(400, {"error": "invalid_request"})
        if not NAME_RE.match(name):
            return self._json(400, {"error": "name"})
        if not current_key():
            return self._json(503, {"error": "no_key"})
        with RUN.lock:
            if now_ms() > RUN.deadline:
                return self._json(410, {"error": "run_over"})
            if len(RUN.sessions) + RUN.creating >= MAX_SESSIONS:
                return self._json(429, {"error": "session_cap"})
            if RUN.minutes_used() >= MAX_TOTAL_MIN:
                return self._json(429, {"error": "minute_cap"})
            if len(RUN.open_sessions()) + RUN.creating >= MAX_OPEN:
                return self._json(409, {"error": "too_many_open"})
            RUN.creating += 1
        t0 = time.monotonic()
        try:
            res = create_session(KEY, session_body(sdp, kind, name))
            sid = str((res.get("session") or {}).get("id") or "")
            answer = (res.get("transport") or {}).get("sdp")
            if not SID_RE.match(sid) or not isinstance(answer, str):
                raise OpenAIError(502, "bad_response")
        except OpenAIError as e:
            ms = int((time.monotonic() - t0) * 1000)
            RUN.write({"src": "server", "k": "create_fail", "page": page[:8], "kind": kind,
                       "status": e.status, "code": e.code, "param": e.param, "ms": ms})
            with RUN.lock:
                RUN.creating -= 1
            status = 429 if e.status == 429 else 502 if e.status >= 500 else 400 if e.status == 400 else 502
            return self._json(status, {"error": "openai", "status": e.status, "code": e.code, "param": e.param})
        ms = int((time.monotonic() - t0) * 1000)
        rec = {"sid": sid, "page": page, "kind": kind, "created_at": now_ms(), "ms": ms}
        with RUN.lock:
            RUN.creating -= 1
            RUN.sessions.append(rec)
            n = len(RUN.sessions)
        RUN.write({"src": "server", "k": "created", "page": page[:8], "kind": kind, "sid": sid, "ms": ms, "n": n})
        return self._json(201, {"session_id": sid, "sdp": answer, "max_min": MAX_SESSION_MIN,
                                "sessions_left": MAX_SESSIONS - n})

    def api_beat(self, body: dict):
        page = body["page"]
        raw = body.get("events")
        events = [e for e in (clean_event(x) for x in (raw if isinstance(raw, list) else [])[:800]) if e]
        beat = {
            "src": "beat", "page": page[:8], "seq": body.get("seq") if isinstance(body.get("seq"), int) else None,
            "gap": body.get("gap") if isinstance(body.get("gap"), int) else None,
            "st": short(body.get("st", "")), "vis": short(body.get("vis", "")), "mic": bool(body.get("mic")),
            "rtc": short(body.get("rtc", "")), "ctx": short(body.get("ctx", "")), "wl": short(body.get("wl", "")),
            "bat": short(body.get("bat", "")), "standalone": bool(body.get("standalone")),
            "fake": bool(body.get("fake")), "agg": clean_agg(body.get("agg")),
            "usage": body.get("usage") if isinstance(body.get("usage"), (int, float)) else None,
        }
        RUN.write(beat)
        for e in events:
            RUN.write({"src": "page", "page": page[:8], **e})
        with RUN.lock:
            RUN.beats.append({"at": now_ms(), **beat})
            RUN.events.extend({"page": page[:8], **e} for e in events)
            del RUN.beats[:-5000]
            del RUN.events[:-20000]
            left = MAX_SESSIONS - len(RUN.sessions)
        return self._json(200, {"ok": True, "now": now_ms(), "sessions_left": left,
                                "minutes_used": RUN.minutes_used(), "max_total_min": MAX_TOTAL_MIN,
                                "run_left_min": int((RUN.deadline - now_ms()) / 60000)})

    def api_end(self, body: dict):
        sid = str(body.get("session_id") or "")
        reason = short(body.get("reason") or "")
        usage = body.get("usage") if isinstance(body.get("usage"), (int, float)) else None
        with RUN.lock:
            rec = next((s for s in RUN.sessions if s["sid"] == sid and s["page"] == body["page"]), None)
            if rec and not rec.get("closed_at"):
                rec.update(closed_at=now_ms(), reason=reason, usage=usage, by="page")
        RUN.write({"src": "server", "k": "ended", "page": body["page"][:8], "sid": sid[:40], "reason": reason,
                   "usage": usage, "known": bool(rec)})
        if rec and reason not in CONFIRMED and KEY:
            threading.Thread(target=close_leftover, args=(rec,), daemon=True).start()
        return self._json(200, {"ok": True})


CONFIRMED = {"close_requested", "expired", "content", "remote_hangup", "connection_lost"}


def close_leftover(rec: dict) -> None:
    """화면이 끝을 확인하지 못한 세션(끊김, 확인 없는 끊기, 버린 세션)을 sideband로 닫아 요금이 남지 않게 해요."""
    res = sideband_close(rec["sid"], KEY)
    RUN.write({"src": "server", "k": "leftover_close", "sid": rec["sid"][:40], **res})
    if res.get("usage") is not None:
        with RUN.lock:
            rec["usage"] = res["usage"]


def watchdog(stop: threading.Event) -> None:
    """길이를 넘긴 세션을 sideband로 닫고, 더한 통화 시간이 상한에 닿으면 열린 세션을 모두 닫아요.
    서버 수명이 끝나면 열린 세션을 모두 닫고 끝내요."""
    limit_ms = int((MAX_SESSION_MIN * 60 + 60) * 1000)
    while not stop.wait(20):
        over = now_ms() > RUN.deadline
        with RUN.lock:
            spent = RUN.minutes_used() >= MAX_TOTAL_MIN
            todo = [s for s in RUN.open_sessions() if over or spent or now_ms() - s["created_at"] > limit_ms]
        for s in todo:
            res = sideband_close(s["sid"], KEY) if KEY else {"ok": False, "why": "no_key"}
            with RUN.lock:
                if not s.get("closed_at"):
                    s.update(closed_at=now_ms(), reason=res.get("reason") or res.get("why"), usage=res.get("usage"),
                             by="watchdog")
            RUN.write({"src": "server", "k": "watchdog_close", "sid": s["sid"][:40], **res})
        if over:
            RUN.write({"src": "server", "k": "run_over"})
            os._exit(0)


# ---- 결과 보기 ----

def report_data() -> dict:
    with RUN.lock:
        sessions = [dict(s, page=s["page"][:8]) for s in RUN.sessions]
        beats = list(RUN.beats)
        events = list(RUN.events)
    return {"started": RUN.started, "deadline": RUN.deadline, "max_sessions": MAX_SESSIONS,
            "max_session_min": MAX_SESSION_MIN, "max_total_min": MAX_TOTAL_MIN, "minutes_used": RUN.minutes_used(),
            "sessions": sessions, "beats": beats, "events": events, "log": RUN.log_path.name}


LABEL = {
    "idle": "대기", "connecting": "거는 중", "talking": "통화 중", "resting": "쉬는 중", "ended": "끝남",
    "h": "숨김", "v": "보임", "hidden": "숨김", "visible": "보임",
}



def render_report() -> str:
    d = report_data()
    esc = html.escape
    rows = []
    for s in d["sessions"]:
        rows.append(f"<tr><td>{kst(s['created_at'])}</td><td>{esc(s['kind'])}</td><td>{s['ms']}ms</td>"
                    f"<td>{kst(s.get('closed_at'))}</td><td>{esc(str(s.get('reason') or ''))}</td>"
                    f"<td>{'' if s.get('usage') is None else s['usage']}</td><td>{esc(str(s.get('by') or ''))}</td></tr>")
    # 신호 간격: 15초 기대, 숨김 상태별 가장 긴 간격
    gaps: dict = {}
    late = []
    for b in d["beats"]:
        g = b.get("gap") or 0
        key = (LABEL.get(b.get("st"), b.get("st")), LABEL.get(b.get("vis"), b.get("vis")))
        gaps[key] = max(gaps.get(key, 0), g)
        if g > 30000:
            late.append(b)
    gap_rows = "".join(f"<tr><td>{esc(str(k[0]))}</td><td>{esc(str(k[1]))}</td><td>{v / 1000:.0f}초</td></tr>"
                       for k, v in sorted(gaps.items(), key=lambda x: -x[1]))
    det: dict = {}
    for e in d["events"]:
        if e.get("k") == "det":
            key = (e.get("via"), LABEL.get(e.get("vis"), e.get("vis")))
            det[key] = det.get(key, 0) + 1
    det_rows = "".join(f"<tr><td>{esc(str(k[0]))}</td><td>{esc(str(k[1]))}</td><td>{v}</td></tr>"
                       for k, v in sorted(det.items(), key=lambda x: str(x[0])))
    alive = {}
    for b in d["beats"]:
        a = (b.get("agg") or {}).get("alive")
        if a is not None and b.get("st") == "resting":
            key = LABEL.get(b.get("vis"), b.get("vis"))
            n, tot = alive.get(key, (0, 0))
            alive[key] = (n + 1, tot + a)
    alive_rows = "".join(f"<tr><td>{esc(str(k))}</td><td>{n}</td><td>{tot / n:.1f}</td></tr>"
                         for k, (n, tot) in alive.items() if n)
    rem = {"on": 0, "n": 0, "tx": 0, "tx_on": 0}
    for b in d["beats"]:
        a = b.get("agg") or {}
        if a.get("remN"):
            rem["n"] += a.get("remN", 0)
            rem["on"] += a.get("remOn", 0)
            if a.get("outTx"):
                rem["tx"] += 1
                rem["tx_on"] += 1 if a.get("remOn") else 0
    timeline = []
    for e in d["events"]:
        extra = " ".join(f"{k}={esc(str(v))}" for k, v in e.items() if k not in ("t", "k", "page", "st", "vis"))
        timeline.append(f"<tr><td>{kst(e.get('t'))}</td><td>{esc(e.get('page', ''))}</td><td>{esc(e['k'])}</td>"
                        f"<td>{esc(str(LABEL.get(e.get('st'), e.get('st') or '')))}</td>"
                        f"<td>{esc(str(LABEL.get(e.get('vis'), e.get('vis') or '')))}</td><td>{extra}</td></tr>")
    late_rows = "".join(f"<tr><td>{kst(b['at'])}</td><td>{esc(str(b.get('page')))}</td><td>{(b.get('gap') or 0) / 1000:.0f}초</td>"
                        f"<td>{esc(str(LABEL.get(b.get('st'), b.get('st'))))}</td><td>{esc(str(LABEL.get(b.get('vis'), b.get('vis'))))}</td>"
                        f"<td>{esc(str(b.get('rtc')))}</td><td>{'켜짐' if b.get('mic') else '꺼짐'}</td></tr>" for b in late[-60:])
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>마롱이 갤럭시 시험 결과</title><style>
body{{font:15px/1.5 system-ui,sans-serif;margin:16px;color:#222;background:#fff}} table{{border-collapse:collapse;margin:6px 0 18px;font-size:13px}}
td,th{{border:1px solid #ccc;padding:3px 6px;text-align:left}} h2{{font-size:17px;margin:18px 0 4px}} .w{{overflow-x:auto}}
@media (prefers-color-scheme: dark){{body{{background:#111;color:#eee}} td,th{{border-color:#444}}}}
</style></head><body>
<h1 style="font-size:20px">마롱이 갤럭시 시험 결과</h1>
<p>서버 시작 {kst(d['started'])} · 끝 {kst(d['deadline'])} · 세션 {len(d['sessions'])}/{d['max_sessions']}개 · 쓴 시간 약 {d['minutes_used']}/{d['max_total_min']:g}분(약 {d['minutes_used'] * 0.05:.2f}달러) · 기록 파일 {esc(d['log'])}</p>
<p>말 내용은 기록하지 않아요. 시각·상태·소리 크기·이벤트 종류와 누른 결과만 있어요.</p>
<h2>세션</h2><div class="w"><table><tr><th>만든 때</th><th>종류</th><th>만들기</th><th>닫힌 때</th><th>이유</th><th>사용 초</th><th>닫은 쪽</th></tr>{''.join(rows)}</table></div>
<h2>신호 간격(15초 기대, 상태별 가장 긴 간격)</h2><div class="w"><table><tr><th>상태</th><th>화면</th><th>가장 긴 간격</th></tr>{gap_rows}</table></div>
<h2>30초 넘게 늦은 신호</h2><div class="w"><table><tr><th>받은 때</th><th>페이지</th><th>간격</th><th>상태</th><th>화면</th><th>WebRTC</th><th>마이크</th></tr>{late_rows}</table></div>
<h2>쉬는 중 말소리 감지</h2><div class="w"><table><tr><th>방식</th><th>화면</th><th>횟수</th></tr>{det_rows}</table></div>
<h2>쉬는 중 AudioWorklet이 살아 있었나(5초마다 1번, 신호 하나에 3번 기대)</h2><div class="w"><table><tr><th>화면</th><th>신호 수</th><th>신호당 평균</th></tr>{alive_rows}</table></div>
<h2>마롱이 소리 재기(7.1의 7번)</h2><p>원격 소리 표본 {rem['n']}개 중 0.01 넘음 {rem['on']}개. 마롱이 자막 조각이 온 신호 {rem['tx']}번 중 원격 소리도 잡힌 신호 {rem['tx_on']}번.</p>
<h2>시간순 기록</h2><div class="w"><table><tr><th>시각</th><th>페이지</th><th>종류</th><th>상태</th><th>화면</th><th>값</th></tr>{''.join(timeline[-400:])}</table></div>
</body></html>"""


def main() -> int:
    global RUN, KEY, MODEL_CHECK
    KEY = load_key()
    MODEL_CHECK = check_model(KEY)
    if not PROMPT_PATH.is_file() or not FACE.is_file():
        print("call_prompt.md나 얼굴 그림을 못 찾았어요. 저장소 구조 그대로 올려 주세요.", file=sys.stderr)
        return 1
    RUN = Run()
    host, port = BIND.rsplit(":", 1)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("TEST_BIND는 127.0.0.1이어야 해요(바깥은 터널이 맡아요).", file=sys.stderr)
        return 1
    srv = ThreadingHTTPServer((host, int(port)), Handler)
    srv.daemon_threads = True
    stop = threading.Event()
    threading.Thread(target=watchdog, args=(stop,), daemon=True).start()
    RUN.write({"src": "server", "k": "start", "key": bool(KEY), "model_check": MODEL_CHECK, "max_sessions": MAX_SESSIONS,
               "max_session_min": MAX_SESSION_MIN, "max_total_min": MAX_TOTAL_MIN, "run_hours": RUN_HOURS, "model": MODEL, "voice": VOICE})
    print(f"시험 서버: http://{host}:{port} (키 {'있음' if KEY else '없음'}, 모델 조회 {MODEL_CHECK}, 세션 {MAX_SESSIONS}개, "
          f"한 세션 {MAX_SESSION_MIN:g}분, 모두 더해 {MAX_TOTAL_MIN:g}분, {RUN_HOURS:g}시간 뒤 끝남, 기록 {RUN.log_path})",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for s in RUN.open_sessions():
            if KEY:
                RUN.write({"src": "server", "k": "shutdown_close", "sid": s["sid"][:40], **sideband_close(s["sid"], KEY)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
