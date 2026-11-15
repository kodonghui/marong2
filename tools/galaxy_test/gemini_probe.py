#!/usr/bin/env python3
"""제미나이 키를 아주 짧게 불러 봐요(갤럭시 시험의 제미나이 길 확인용).

1. 요금 없는 모델 조회(GET models/<모델>)
2. 요금 없는 임시 토큰 만들기(POST auth_tokens, 시험 페이지와 같은 잠금 설정)
3. --live를 주면 그 토큰으로 실제 연결을 한 번 열고, 짧은 글 한 줄을 보내 첫 대답 소리를 받은 뒤 닫아요
   (한 차례라 요금은 1센트보다 훨씬 적을 것으로 추정해요).

키·토큰 값과 말 내용(소리, 자막 글자)은 출력하지 않아요. 상태 코드, 걸린 시간, 받은 소리 길이,
자막 글자 수, usageMetadata 숫자만 보여 줘요. 표준 라이브러리만 써요.

서버에서(파일을 올리지 않고 표준 입력으로 넘겨도 돼요):
    ssh ko-family 'python3 -I - ~/.config/marong-call/gemini.key --live' < tools/galaxy_test/gemini_probe.py
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")
WS_BASE = os.environ.get("GEMINI_WS_BASE", "wss://generativelanguage.googleapis.com").rstrip("/")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-live")
VOICE = os.environ.get("GEMINI_VOICE", "Gacrux")
VERSIONS = ("v1beta", "v1alpha")
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def probe_setup() -> dict:
    return {
        "model": f"models/{MODEL}",
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}},
        },
        "systemInstruction": {"parts": [{"text": "너는 친구처럼 반말로 아주 짧게 대답해. 한 문장만 말해."}]},
        "realtimeInputConfig": {"automaticActivityDetection": {"silenceDurationMs": 800, "prefixPaddingMs": 20}},
        "contextWindowCompression": {"slidingWindow": {"targetTokens": 16000}, "triggerTokens": 32000},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
    }


def field_mask(setup: dict) -> str:
    """SDK(lock_additional_fields=[])처럼 토큰에 넣은 칸만 잠가요. sessionResumption은 잠그지 않아
    화면이 이어 붙일 손잡이(handle)를 넣을 수 있게 해요."""
    out = []
    for k, v in setup.items():
        out.extend(f"{k}.{kk}" for kk in v) if isinstance(v, dict) and v else out.append(k)
    return ",".join(out)


def http(method: str, url: str, key: str, body: dict | None = None, timeout: float = 15) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": {"status": type(e).__name__}}


def err_text(obj: dict) -> str:
    err = obj.get("error") or {}
    reason = ""
    for d in err.get("details") or []:
        if isinstance(d, dict) and d.get("reason"):
            reason = d["reason"]
            break
    return " ".join(x for x in (str(err.get("status") or ""), reason, str(err.get("message") or "")[:160]) if x)


def mint(key: str, version: str, setup: dict, mode: str) -> tuple[int, str, str]:
    now = datetime.now(timezone.utc)
    body = {"uses": 1, "expireTime": iso(now + timedelta(minutes=5)),
            "newSessionExpireTime": iso(now + timedelta(minutes=1)), "bidiGenerateContentSetup": setup}
    if mode == "mask":
        body["fieldMask"] = field_mask(setup)
    status, res = http("POST", f"{BASE}/{version}/auth_tokens", key, body)
    token = str(res.get("name") or "") if status == 200 else ""
    return status, token, "" if token else err_text(res)


# ---- 아주 작은 WebSocket 클라이언트 ----

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


def ws_send(s, op: int, payload: bytes) -> None:
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


def ws_recv(s) -> tuple[int, bytes]:
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
        if op >= 8:
            return op, data
        if first_op is None:
            first_op = op
        parts.append(data)
        if b1 & 0x80:
            return first_op, b"".join(parts)


def ws_open(url: str, timeout: float = 15):
    u = urllib.parse.urlparse(url)
    host, port = u.hostname or "", u.port or (443 if u.scheme == "wss" else 80)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if u.scheme == "wss" and proxy:
        p = urllib.parse.urlparse(proxy)
        raw = socket.create_connection((p.hostname, p.port or 80), timeout=timeout)
        raw.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
        if b" 200" not in _read_head(raw).split(b"\r\n", 1)[0]:
            raw.close()
            raise OSError("proxy refused")
    else:
        raw = socket.create_connection((host, port), timeout=timeout)
    s = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if u.scheme == "wss" else raw
    nonce = base64.b64encode(os.urandom(16)).decode()
    path = u.path + ("?" + u.query if u.query else "")
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    head = _read_head(s)
    status = head.split(b"\r\n", 1)[0].decode("latin-1")
    accept = base64.b64encode(hashlib.sha1((nonce + _WS_GUID).encode()).digest())
    if " 101" not in status or accept not in head:
        s.close()
        raise OSError(f"handshake {status[:40]}")
    return s


def live_once(token: str, version: str, setup: dict) -> dict:
    """연결 → setup → setupComplete → 글 한 줄 → 첫 대답(turnComplete)까지 → 닫기. 숫자만 돌려줘요."""
    url = (f"{WS_BASE}/ws/google.ai.generativelanguage.{version}.GenerativeService."
           f"BidiGenerateContentConstrained?access_token={urllib.parse.quote(token, safe='/')}")
    out = {"ws": version, "setup_ok": False, "audio_s": 0.0, "audio_msgs": 0, "out_tx_chars": 0,
           "in_tx_msgs": 0, "usage": [], "resume_handle": False, "go_away": None, "kinds": {}}
    t0 = time.monotonic()
    try:
        s = ws_open(url)
    except (OSError, EOFError, ssl.SSLError) as e:
        out["error"] = f"open:{str(e)[:80]}"
        return out
    out["open_ms"] = int((time.monotonic() - t0) * 1000)
    rate = 24000
    try:
        ws_send(s, 1, json.dumps({"setup": dict(setup, sessionResumption={})}).encode())
        deadline = time.monotonic() + 25
        sent_at = None
        while time.monotonic() < deadline:
            s.settimeout(max(0.5, deadline - time.monotonic()))
            op, data = ws_recv(s)
            if op == 8:
                code = int.from_bytes(data[:2], "big") if len(data) >= 2 else None
                out["close"] = {"code": code, "reason": data[2:].decode("utf-8", "replace")[:160]}
                break
            if op == 9:
                ws_send(s, 10, data)
                continue
            if op not in (1, 2):
                continue
            try:
                msg = json.loads(data.decode("utf-8"))
            except ValueError:
                out["kinds"]["?"] = out["kinds"].get("?", 0) + 1
                continue
            for k in msg:
                out["kinds"][k] = out["kinds"].get(k, 0) + 1
            if "setupComplete" in msg and not out["setup_ok"]:
                out["setup_ok"] = True
                out["setup_ms"] = int((time.monotonic() - t0) * 1000)
                ws_send(s, 1, json.dumps({"realtimeInput": {"text": "안녕! 시험이야. 한 문장으로만 짧게 인사해 줘."}}).encode())
                sent_at = time.monotonic()
            if msg.get("usageMetadata"):
                um = msg["usageMetadata"]
                out["usage"].append({k: v for k, v in um.items() if isinstance(v, (int, float))})
            if msg.get("sessionResumptionUpdate"):
                u = msg["sessionResumptionUpdate"]
                out["resume_handle"] = out["resume_handle"] or bool(u.get("newHandle") and u.get("resumable"))
            if msg.get("goAway"):
                out["go_away"] = str(msg["goAway"].get("timeLeft"))[:20]
            sc = msg.get("serverContent") or {}
            for part in (sc.get("modelTurn") or {}).get("parts") or []:
                inline = part.get("inlineData") or {}
                if inline.get("data"):
                    mime = str(inline.get("mimeType") or "")
                    out["mime"] = mime[:40]
                    if "rate=" in mime:
                        try:
                            rate = int(mime.split("rate=")[1].split(";")[0])
                        except ValueError:
                            pass
                    n = len(base64.b64decode(inline["data"]))
                    if not out["audio_msgs"] and sent_at:
                        out["first_audio_ms"] = int((time.monotonic() - sent_at) * 1000)
                    out["audio_msgs"] += 1
                    out["audio_s"] = round(out["audio_s"] + n / 2 / rate, 2)
                    del inline
            if sc.get("outputTranscription"):
                out["out_tx_chars"] += len(str(sc["outputTranscription"].get("text") or ""))
            if sc.get("inputTranscription"):
                out["in_tx_msgs"] += 1
            if sc.get("turnComplete"):
                out["turn_ms"] = int((time.monotonic() - (sent_at or t0)) * 1000)
                # 늦게 오는 usageMetadata를 잠깐 더 기다려요
                deadline = min(deadline, time.monotonic() + 1.5)
    except (OSError, EOFError, ssl.SSLError) as e:
        out.setdefault("error", f"recv:{type(e).__name__}")
    finally:
        try:
            ws_send(s, 8, (1000).to_bytes(2, "big"))
            s.close()
        except OSError:
            pass
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    live = "--live" in argv
    key_file = os.path.expanduser(args[0] if args else "~/.config/marong-call/gemini.key")
    try:
        key = open(key_file, encoding="utf-8").read().strip()
    except OSError:
        print(json.dumps({"key_file": os.path.basename(key_file), "error": "no_key_file"}))
        return 1
    if not key:
        print(json.dumps({"key_file": os.path.basename(key_file), "error": "empty_key_file"}))
        return 1
    report: dict = {"key_file": os.path.basename(key_file), "model": MODEL}
    status, res = http("GET", f"{BASE}/v1beta/models/{MODEL}", key)
    report["model_lookup"] = status
    if status != 200:
        report["model_error"] = err_text(res)
    setup = probe_setup()
    token = ""
    for version in VERSIONS:
        for mode in ("mask", "lock"):
            status, token, why = mint(key, version, setup, mode)
            report.setdefault("token_tries", []).append({"v": version, "mode": mode, "status": status, "why": why})
            if token:
                report.update(token_version=version, token_mode=mode)
                break
            if status != 400:
                break
        if token:
            break
    if token and live:
        report["live"] = live_once(token, report["token_version"], setup)
        if not report["live"].get("setup_ok") and report["token_version"] == "v1beta":
            # 연결 주소의 버전이 다를 수 있어 새 토큰으로 v1alpha를 한 번 더 봐요
            status, token2, _ = mint(key, "v1alpha", setup, report["token_mode"])
            if token2:
                report["live_v1alpha"] = live_once(token2, "v1alpha", setup)
    del key, token
    print(json.dumps(report, ensure_ascii=False))
    live_res = report.get("live_v1alpha") if report.get("live_v1alpha", {}).get("setup_ok") else report.get("live")
    if report["model_lookup"] == 200 and report.get("token_version") and (not live or (live_res or {}).get("audio_s")):
        print("결과: 됨" + (f" (대답 소리 {live_res['audio_s']}초)" if live else ""))
    else:
        print("결과: 안 됨(위 숫자를 보세요)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
