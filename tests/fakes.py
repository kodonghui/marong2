"""시험용 가짜들: Claude API 서버(/v1/messages), Claude 응답 객체, 임베딩."""
import json
import math
import re
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace


def api_key(headers) -> str | None:
    """요청에 실린 API 키(SDK 2.x 는 Authorization: Bearer, 예전 방식은 x-api-key)."""
    auth = headers.get("Authorization") or ""
    return auth[len("Bearer "):] if auth.startswith("Bearer ") else headers.get("x-api-key")


def message(content: list[dict], stop_reason: str = "end_turn", **extra) -> dict:
    """Claude Messages API 응답 JSON."""
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0}, **extra}


def text(t: str) -> dict:
    return {"type": "text", "text": t}


def thinking(t: str = "생각 중") -> dict:
    return {"type": "thinking", "thinking": t, "signature": "sig-" + str(zlib.crc32(t.encode()))}


def tool_use(name: str, inp: dict, tid: str = "toolu_1") -> dict:
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


class FakeAnthropic:
    """respond(key, body) → (상태 코드, JSON) 또는 'stall'(답 없이 멈춤)."""

    def __init__(self, respond):
        self.calls: list[dict] = []
        self.respond = respond
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                key = api_key(self.headers)
                fake.calls.append({"key": key, "path": self.path, "body": body})
                out = fake.respond(key, body)
                if out == "stall":
                    time.sleep(3)
                    return
                code, resp = out
                data = json.dumps(resp, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()


def ns(resp: dict) -> SimpleNamespace:
    """응답 JSON → SDK 응답처럼 속성으로 읽는 객체(HTTP 없이 Agent 를 시험할 때)."""
    blocks = [SimpleNamespace(**b) for b in resp["content"]]
    usage = SimpleNamespace(**resp["usage"])
    details = resp.get("stop_details")
    return SimpleNamespace(content=blocks, stop_reason=resp["stop_reason"], usage=usage,
                           stop_details=SimpleNamespace(**details) if details else None)


class ScriptedLLM:
    """LLM 대신: fn(body) → 응답 JSON. 받은 요청 body 를 기록한다."""

    def __init__(self, fn):
        self.fn = fn
        self.bodies: list[dict] = []

    async def create(self, body: dict, timeout: float):
        self.bodies.append(body)
        out = self.fn(body)
        if isinstance(out, Exception):
            raise out
        return ns(out)


class FakeEmbeddings:
    """글자 두 개씩 묶어 세는 가벼운 임베딩: 겹치는 말이 많을수록 비슷하게 나옴."""
    model = "fake-bigram"
    enabled = True
    ready = True
    dim = 128
    error = None

    def start(self):
        pass

    async def wait_ready(self, timeout):
        return True

    def vec(self, s: str) -> list[float]:
        v = [0.0] * self.dim
        v[0] = 0.01  # 빈 글에도 0 벡터가 되지 않게
        t = re.sub(r"\s+", "", s)
        for a, b in zip(t, t[1:]):
            v[zlib.crc32((a + b).encode()) % self.dim] += 1
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v]

    async def query(self, s: str):
        return self.vec(s)

    async def documents(self, texts):
        return [self.vec(t) for t in texts]
