#!/usr/bin/env python3
"""마롱이 통화 엔진 비교 측정. 마롱이 서버(싱가포르)에서 표준 라이브러리만으로 돌려요.

    python3 -I bench_server.py check     # 키 파일이 있는지(이름만)와 요금 없는 모델 조회
    python3 -I bench_server.py all       # 아래를 차례로 돌리고 results.tar.gz와 results/DONE을 만들어요
    python3 -I bench_server.py gemini    # 지금 통화와 같은 Vertex 설정(gemini-3.8-live, Sulafat, 침묵 700ms)
    python3 -I bench_server.py openai    # gpt-realtime-2.1-mini, marin
    python3 -I bench_server.py live      # gpt-live-1, noeul
    python3 -I bench_server.py cascade   # gpt-live-transcribe -> gpt-6-luna -> 목소리 셋(아래)을 동시에
    python3 -I bench_server.py cascade-aai  # AssemblyAI 실시간 받아쓰기(자체 말 끝 판정) -> gpt-6-luna -> 목소리 셋
    python3 -I bench_server.py gemini,cascade,cascade-aai  # 쉼표로 여러 개를 차례로

연쇄형의 목소리는 gpt-4o-mini-tts marin, Gemini 3.8 Flash-Lite TTS Sulafat(Vertex global),
ElevenLabs Flash v2.5 Han Aim이에요. VB_CASCADE_TTS=openai,gemini,elevenlabs 로 고르고, 없으면 키 파일이 있는 것만 켜요.

같은 가짜 친구(지우)의 10턴 통화 음성을 실제 말하는 속도로 보내고, 말이 끝난 때부터 첫 대답 소리가 올 때까지를
재요. 턴 사이에는 마이크가 계속 무음을 보내고, 대답이 다 '재생'된 뒤 0.6초 있다가 다음 말을 해요.

키는 ~/.config/marong-call/ 의 openai.key, gemini2.key(운영 통화와 같은 Vertex 키), gemini.key(AI Studio),
elevenlabs.key, assemblyai.key에서 읽기만 하고 출력·저장하지 않아요. sudo를 쓰지 않고, 이 폴더 밖에는 쓰지 않으며,
운영 서비스는 건드리지 않아요. 말 내용은 지어낸 이름(지우, 도윤)의 시험 대본뿐이에요.
"""
import argparse
import array
import asyncio
import base64
import concurrent.futures
import hashlib
import http.client
import json
import math
import os
import platform
import re
import secrets
import shutil
import ssl
import struct
import subprocess
import sys
import tarfile
import threading
import time
import traceback
import urllib.parse
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
INPUTS = os.path.join(HERE, 'inputs')
RESULTS = os.path.join(HERE, 'results')
KEY_DIR = os.path.expanduser(os.environ.get('VB_KEY_DIR', '~/.config/marong-call'))
# Cloud self-test only: an egress proxy adds the keys, so requests carry this placeholder.
PROXY_KEYS = os.environ.get('VB_PROXY_KEYS') == '1'
PLACEHOLDER = 'placeholder-the-proxy-injects-the-key'

OPENAI_HTTP = os.environ.get('VB_OPENAI_HTTP', 'https://api.openai.com')
OPENAI_WS = os.environ.get('VB_OPENAI_WS', 'wss://api.openai.com')
VERTEX_WS = os.environ.get('VB_VERTEX_WS', 'wss://us-central1-aiplatform.googleapis.com')
GEMINI_HTTP = os.environ.get('VB_GEMINI_HTTP', 'https://generativelanguage.googleapis.com')
VERTEX_HTTP = os.environ.get('VB_VERTEX_HTTP', 'https://aiplatform.googleapis.com')
ELEVEN_HTTP = os.environ.get('VB_ELEVEN_HTTP', 'https://api.elevenlabs.io')
AAI_WS = os.environ.get('VB_AAI_WS', 'wss://streaming.assemblyai.com')
AAI_HTTP = os.environ.get('VB_AAI_HTTP', 'https://api.assemblyai.com')

VERTEX_PROJECT = 'project-bc2d15a4-11c0-476b-ae8'  # tools/vertex_live/server.py
VERTEX_LOCATION = 'us-central1'

# Gemini TTS goes through Vertex (global, the production key) unless VB_GEMINI_TTS_VIA=aistudio.
GEMINI_TTS_VIA = os.environ.get('VB_GEMINI_TTS_VIA', 'vertex')
HAN_AIM = '8jHHF8rMqMlg8if2mOUe'   # ElevenLabs voice the maintainer picked by ear (2026-11-17)
TTS_TIMEOUT = float(os.environ.get('VB_TTS_TIMEOUT', '10'))  # seconds without bytes before a TTS request fails
# AssemblyAI streaming, docs read 2026-11-17: assemblyai.com/docs/streaming/select-the-speech-model.md,
# .../turn-detection.md, .../message-sequence.md, .../api-spec/streaming-websocket.md
AAI_MODEL = os.environ.get('VB_AAI_MODEL', 'assemblyai-stt-3-7-realtime-agent')
AAI_MODE = os.environ.get('VB_AAI_MODE', 'min_latency')
ELEVEN_WS = os.environ.get('VB_ELEVEN_WS', 'wss://api.elevenlabs.io')
# Eleven Realtime (speech to speech over the OpenAI Realtime wire protocol), docs read 2026-11-17:
# elevenlabs.io/docs/eleven-agents/customization/realtime-models.md, .../guides/openai-realtime-compatibility.md,
# .../api-reference/conversations/create-client-secret.md
ELEVEN_RT_MODEL = os.environ.get('VB_ELEVEN_RT_MODEL', 'eleven_realtime_v1_mini')
ELEVEN_RT_EAGERNESS = os.environ.get('VB_ELEVEN_RT_EAGERNESS', 'medium')
# ElevenAgents in Custom mode (their ASR, turn-taking model, an LLM they host, their TTS), docs read 2026-11-17:
# .../libraries/web-sockets.md, .../api-reference/eleven-agents/websocket.md, .../api-reference/agents/create.md
ELEVEN_AGENT_LLM = os.environ.get('VB_ELEVEN_AGENT_LLM', 'gpt-6-luna')
ELEVEN_AGENT_EAGERNESS = os.environ.get('VB_ELEVEN_AGENT_EAGERNESS', 'normal')

VAD_MS = 700           # production silenceDurationMs
GAP_AFTER_REPLY = 0.6  # the friend answers 0.6 s after the reply finished playing
VOICED_RMS = 250.0      # 16-bit RMS (about -42 dBFS) above which an output chunk counts as speech
MAX_USD = float(os.environ.get('VB_MAX_USD', '1.5'))

# USD, official price pages read 2026-11-16 (per 1M tokens unless noted)
PRICES = {
    'gpt-realtime-2.1-mini': {'audio_in': 10.0, 'audio_in_cached': 0.30, 'audio_out': 20.0,
                              'text_in': 0.60, 'text_in_cached': 0.06, 'text_out': 2.40},
    'gpt-live-1': {'per_min': 0.05},
    'gemini-3.8-live': {'text_in': 0.75, 'audio_in': 3.0, 'text_out': 4.50, 'audio_out': 12.0},
    'gpt-live-transcribe': {'per_min': 0.017},
    'gpt-6-luna': {'in': 0.10, 'in_cached': 0.01, 'out': 0.50},
    'gpt-4o-mini-tts': {'per_min_est': 0.015},
    'gemini-3.8-flash-lite-tts': {'text_in': 0.50, 'audio_out': 6.0},
    # elevenlabs.io/pricing/api read 2026-11-16, billed on characters sent
    'eleven_flash_v2_5': {'usd_per_1k_chars': 0.04},
    # assemblyai.com/docs/getting-started/models.md read 2026-11-17, billed on WebSocket session duration
    'assemblyai-stt-3-7-realtime-agent': {'per_hour': 0.45},
    'universal-3-6-pro': {'per_hour': 0.45},
    'assemblyai-stt-3-7-realtime': {'per_hour': 0.30},
    # elevenlabs.io/pricing/api and /pricing/agents read 2026-11-17: per call minute, LLM usage billed on top
    'eleven_realtime_v1_mini': {'per_min': 0.08},
    'elevenagents': {'per_min': 0.08},
}

mono = time.monotonic
spent = {'usd': 0.0}


def now_iso():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def key(name):
    if PROXY_KEYS:
        return PLACEHOLDER
    try:
        with open(os.path.join(KEY_DIR, name), encoding='utf-8') as f:
            v = f.read().strip()
    except OSError:
        return None
    return v or None


# ------------------------------------------------------------------ audio and text helpers

def read_wav(path):
    with wave.open(path, 'rb') as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError('need mono 16-bit: ' + path)
        return w.readframes(w.getnframes()), w.getframerate()


def write_wav(path, pcm, sr):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(pcm))


def norm_ko(s):
    return re.sub(r'[^0-9a-z가-힣]', '', (s or '').lower())


def edit_distance(a, b):
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(refs, hyp):
    h = norm_ko(hyp)
    best = None
    for r in refs:
        r = norm_ko(r)
        c = edit_distance(r, h) / max(1, len(r))
        best = c if best is None else min(best, c)
    return round(best, 3)


SENT_END = re.compile(r'[.!?~…]+["\')\]]*(\s|$)|\n')


def first_sentence_end(text, min_chars=4):
    for m in SENT_END.finditer(text):
        if len(norm_ko(text[:m.end()])) >= min_chars:
            return m.end()
    return -1


def load_inputs():
    with open(os.path.join(INPUTS, 'system_prompt.txt'), encoding='utf-8') as f:
        prompt = f.read()
    with open(os.path.join(INPUTS, 'turns.json'), encoding='utf-8') as f:
        turns = json.load(f)
    for t in turns:
        t['pcm24'], _ = read_wav(os.path.join(INPUTS, t['id'] + '_24k.wav'))
        t['pcm16'], _ = read_wav(os.path.join(INPUTS, t['id'] + '_16k.wav'))
    return prompt, turns


class Log:
    def __init__(self, outdir):
        self.outdir = outdir
        os.makedirs(outdir, exist_ok=True)
        self.path = os.path.join(outdir, 'turns.jsonl')

    def write(self, rec):
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    def summary(self, rec):
        with open(os.path.join(self.outdir, 'summary.json'), 'w', encoding='utf-8') as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ minimal WebSocket client (RFC 6455)

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


class WSClosed(Exception):
    def __init__(self, code, reason):
        super().__init__('closed %s %s' % (code, reason))
        self.code, self.reason = code, reason


def _mask(data, mk):
    n = len(data)
    if not n:
        return b''
    m = (mk * (n // 4 + 1))[:n]
    return (int.from_bytes(data, 'big') ^ int.from_bytes(m, 'big')).to_bytes(n, 'big')


class WS:
    def __init__(self, reader, writer):
        self.r, self.w = reader, writer
        self.lock = asyncio.Lock()
        self.closed = False

    @classmethod
    async def connect(cls, url, headers, timeout=20):
        u = urllib.parse.urlsplit(url)
        tls = u.scheme == 'wss'
        host, port = u.hostname, u.port or (443 if tls else 80)
        path = (u.path or '/') + ('?' + u.query if u.query else '')
        ctx = ssl.create_default_context() if tls else None
        r, w = await asyncio.wait_for(asyncio.open_connection(
            host, port, ssl=ctx, server_hostname=host if tls else None, limit=1 << 24), timeout)
        k = base64.b64encode(secrets.token_bytes(16)).decode()
        lines = ['GET %s HTTP/1.1' % path, 'Host: %s' % (host if port in (80, 443) else '%s:%d' % (host, port)),
                 'Upgrade: websocket', 'Connection: Upgrade', 'Sec-WebSocket-Key: ' + k, 'Sec-WebSocket-Version: 13',
                 'User-Agent: voice-bench']
        lines += ['%s: %s' % (a, b) for a, b in headers.items()]
        w.write(('\r\n'.join(lines) + '\r\n\r\n').encode())
        await w.drain()
        head = await asyncio.wait_for(r.readuntil(b'\r\n\r\n'), timeout)
        status = head.split(b'\r\n', 1)[0].decode('latin-1')
        if status.split(' ')[1:2] != ['101']:
            body = b''
            try:
                body = await asyncio.wait_for(r.read(1500), 3)
            except Exception:
                pass
            w.close()
            raise ConnectionError('%s %s' % (status, body[:600].decode('utf-8', 'replace')))
        accept = base64.b64encode(hashlib.sha1((k + GUID).encode()).digest())
        if accept not in head:
            w.close()
            raise ConnectionError('bad Sec-WebSocket-Accept')
        return cls(r, w)

    async def send(self, data, op=0x1):
        if isinstance(data, str):
            data = data.encode('utf-8')
        n = len(data)
        hdr = bytearray([0x80 | op])
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack('!H', n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack('!Q', n)
        mk = secrets.token_bytes(4)
        frame = bytes(hdr) + mk + _mask(data, mk)
        async with self.lock:
            self.w.write(frame)
            await self.w.drain()

    async def send_json(self, obj):
        await self.send(json.dumps(obj, ensure_ascii=False))

    async def recv(self):
        buf, op0 = bytearray(), None
        while True:
            b = await self.r.readexactly(2)
            fin, op = b[0] & 0x80, b[0] & 0x0F
            masked, n = b[1] & 0x80, b[1] & 0x7F
            if n == 126:
                n = struct.unpack('!H', await self.r.readexactly(2))[0]
            elif n == 127:
                n = struct.unpack('!Q', await self.r.readexactly(8))[0]
            mk = await self.r.readexactly(4) if masked else None
            data = await self.r.readexactly(n) if n else b''
            if mk:
                data = _mask(data, mk)
            if op == 0x9:
                await self.send(data, 0xA)
                continue
            if op == 0xA:
                continue
            if op == 0x8:
                code = struct.unpack('!H', data[:2])[0] if len(data) >= 2 else None
                reason = data[2:].decode('utf-8', 'replace')
                if not self.closed:
                    self.closed = True
                    try:
                        await self.send(data[:2], 0x8)
                    except Exception:
                        pass
                raise WSClosed(code, reason)
            if op != 0x0:
                op0, buf = op, bytearray()
            buf += data
            if fin:
                return op0, bytes(buf)

    async def recv_json(self):
        _, data = await self.recv()
        return json.loads(data.decode('utf-8'))

    async def close(self, code=1000):
        if not self.closed:
            self.closed = True
            try:
                await asyncio.wait_for(self.send(struct.pack('!H', code), 0x8), 2)
            except Exception:
                pass
        try:
            self.w.close()
        except Exception:
            pass


# ------------------------------------------------------------------ blocking HTTP streaming (run in threads)

class HTTPError(Exception):
    pass


def http_post_stream(url, headers, body, on_chunk, timeout=60):
    """POST JSON and call on_chunk(bytes, t) as the response arrives. Returns the status code."""
    u = urllib.parse.urlsplit(url)
    host = u.hostname
    path = (u.path or '/') + ('?' + u.query if u.query else '')
    if u.scheme == 'https':
        ctx = ssl.create_default_context()
        proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
        if proxy:
            pu = urllib.parse.urlsplit(proxy)
            conn = http.client.HTTPSConnection(pu.hostname, pu.port, timeout=timeout, context=ctx)
            conn.set_tunnel(host, u.port or 443)
        else:
            conn = http.client.HTTPSConnection(host, u.port or 443, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, u.port or 80, timeout=timeout)
    try:
        h = {'Content-Type': 'application/json', 'User-Agent': 'voice-bench'}
        h.update(headers)
        conn.request('POST', path, body=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=h)
        r = conn.getresponse()
        if r.status != 200:
            raise HTTPError('%s %s' % (r.status, r.read(1500).decode('utf-8', 'replace')))
        while True:
            chunk = r.read1(65536) if hasattr(r, 'read1') else r.read(64)
            if not chunk:
                break
            on_chunk(chunk, mono())
        return r.status
    finally:
        conn.close()


def http_get_status(url, headers, timeout=20):
    u = urllib.parse.urlsplit(url)
    ctx = ssl.create_default_context()
    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if u.scheme != 'https':
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    elif proxy:
        pu = urllib.parse.urlsplit(proxy)
        conn = http.client.HTTPSConnection(pu.hostname, pu.port, timeout=timeout, context=ctx)
        conn.set_tunnel(u.hostname, u.port or 443)
    else:
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout, context=ctx)
    try:
        conn.request('GET', (u.path or '/') + ('?' + u.query if u.query else ''), headers=headers)
        r = conn.getresponse()
        r.read(2000)
        return r.status
    except Exception as e:
        return type(e).__name__
    finally:
        conn.close()


def http_json(method, url, headers, body=None, timeout=30):
    """Blocking JSON request. Returns (status, parsed body or text). Never raises for HTTP errors."""
    u = urllib.parse.urlsplit(url)
    ctx = ssl.create_default_context()
    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if u.scheme != 'https':
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    elif proxy:
        pu = urllib.parse.urlsplit(proxy)
        conn = http.client.HTTPSConnection(pu.hostname, pu.port, timeout=timeout, context=ctx)
        conn.set_tunnel(u.hostname, u.port or 443)
    else:
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout, context=ctx)
    try:
        h = {'User-Agent': 'voice-bench'}
        if body is not None:
            h['Content-Type'] = 'application/json'
        h.update(headers)
        data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
        conn.request(method, (u.path or '/') + ('?' + u.query if u.query else ''), body=data, headers=h)
        r = conn.getresponse()
        raw = r.read()
        try:
            return r.status, json.loads(raw.decode('utf-8'))
        except ValueError:
            return r.status, raw[:1500].decode('utf-8', 'replace')
    except Exception as e:
        return type(e).__name__, repr(e)[:300]
    finally:
        conn.close()


async def ahttp_json(*a, **kw):
    return await asyncio.get_event_loop().run_in_executor(None, lambda: http_json(*a, **kw))


class SSE:
    """Split a text/event-stream body into data payloads."""

    def __init__(self):
        self.buf = b''

    def feed(self, chunk):
        self.buf += chunk
        out = []
        while b'\n' in self.buf:
            line, self.buf = self.buf.split(b'\n', 1)
            line = line.rstrip(b'\r')
            if line.startswith(b'data:'):
                out.append(line[5:].strip().decode('utf-8'))
        return out


# ------------------------------------------------------------------ microphone at real-time pace

class Mic:
    """Sends 20 ms chunks at capture time: queued speech, otherwise silence. say() resolves at end of speech."""

    def __init__(self, send, sr, chunk_ms=20):
        self.send, self.sr, self.chunk_ms = send, sr, chunk_ms
        self.bpc = int(sr * chunk_ms / 1000) * 2
        self.queue = []
        self.stopped = False
        self.sent_bytes = 0
        self.errors = []
        self.task = None

    def start(self):
        self.task = asyncio.ensure_future(self._run())
        return self

    async def _run(self):
        t0, k, cur, fut, pos = mono(), 0, None, None, 0
        try:
            while not self.stopped:
                k += 1
                delay = t0 + k * self.chunk_ms / 1000 - mono()
                if delay > 0:
                    await asyncio.sleep(delay)
                if cur is None and self.queue:
                    cur, fut = self.queue.pop(0)
                    pos = 0
                if cur is not None:
                    chunk = cur[pos:pos + self.bpc]
                    pos += self.bpc
                    if len(chunk) < self.bpc:
                        chunk += b'\0' * (self.bpc - len(chunk))
                    await self.send(chunk)
                    self.sent_bytes += len(chunk)
                    if pos >= len(cur):
                        if not fut.done():
                            fut.set_result(mono())
                        cur = fut = None
                else:
                    await self.send(b'\0' * self.bpc)
                    self.sent_bytes += self.bpc
        except Exception as e:
            self.errors.append(repr(e))
            if fut is not None and not fut.done():
                fut.set_exception(e)

    def say(self, pcm):
        fut = asyncio.get_event_loop().create_future()
        self.queue.append((pcm, fut))
        return fut

    async def stop(self):
        self.stopped = True
        if self.task:
            try:
                await asyncio.wait_for(self.task, 2)
            except Exception:
                self.task.cancel()


# ------------------------------------------------------------------ speech-to-speech engines

def rms16(b):
    """RMS of 16-bit little-endian PCM, every 4th sample (enough to tell speech from silence)."""
    a = array.array('h')
    a.frombytes(bytes(b[:len(b) // 2 * 2]))
    if sys.byteorder == 'big':
        a.byteswap()
    vals = a[::4]
    if not vals:
        return 0.0
    return math.sqrt(sum(v * v for v in vals) / len(vals))


class Turn:
    def __init__(self):
        self.t_end = None
        self.t_first_audio = None
        self.t_last_audio = None
        self.t_done = None
        self.audio = bytearray()
        self.pre_audio = 0
        self.user_text = ''
        self.reply_text = ''
        self.usage = None
        self.events = []
        self.done = asyncio.Event()
        self.status = None


class Engine:
    in_sr = 24000
    out_sr = 24000
    voiced_only = False  # True when the engine streams output audio continuously, silence included


    def __init__(self, model, voice, prompt):
        self.model, self.voice, self.prompt = model, voice, prompt
        self.ws = None
        self.turn = None
        self.ready = asyncio.Event()
        self.ok = False
        self.errors = []
        self.session_log = []
        self.t_any_audio = None

    def on_audio(self, b):
        voiced = (not self.voiced_only) or rms16(b) >= VOICED_RMS
        if voiced:
            self.t_any_audio = mono()
        t = self.turn
        if t is None:
            return
        if t.t_end is None:
            if voiced:
                t.pre_audio += len(b)
            return
        now = mono()
        if t.t_first_audio is None:
            if not voiced:
                return
            t.t_first_audio = now
        if voiced:
            t.t_last_audio = now
        t.audio += b

    async def recv_loop(self):
        try:
            while True:
                ev = await self.ws.recv_json()
                self.handle(ev)
        except WSClosed as e:
            self.session_log.append({'type': 'closed', 'code': e.code, 'reason': e.reason[:300]})
        except (asyncio.IncompleteReadError, ConnectionError) as e:
            self.session_log.append({'type': 'connection_lost', 'error': repr(e)[:300]})
        finally:
            self.ready.set()
            if self.turn is not None:
                self.turn.done.set()

    async def close(self):
        if self.ws:
            await self.ws.close()


class OpenAIRealtime(Engine):
    name = 'openai'

    async def connect(self):
        self.ws = await WS.connect('%s/v1/realtime?model=%s' % (OPENAI_WS, self.model),
                                   {'Authorization': 'Bearer ' + key('openai.key')})
        self.session = {
            'type': 'realtime', 'model': self.model, 'instructions': self.prompt, 'output_modalities': ['audio'],
            'audio': {
                'input': {'format': {'type': 'audio/pcm', 'rate': 24000},
                          'turn_detection': {'type': 'server_vad', 'silence_duration_ms': VAD_MS,
                                             'prefix_padding_ms': 300, 'threshold': 0.5,
                                             'create_response': True, 'interrupt_response': True},
                          'transcription': {'model': 'gpt-4o-mini-transcribe', 'language': 'ko'}},
                'output': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'voice': self.voice},
            },
        }
        self.updated = False
        await self.ws.send_json({'type': 'session.update', 'session': self.session})

    def handle(self, ev):
        ty = ev.get('type', '')
        t = self.turn
        now = mono()
        if ty == 'response.output_audio.delta':
            self.on_audio(base64.b64decode(ev['delta']))
        elif ty == 'response.output_audio_transcript.delta':
            if t is not None and t.t_end is not None:
                t.reply_text += ev.get('delta', '')
        elif ty in ('input_audio_buffer.speech_started', 'input_audio_buffer.speech_stopped'):
            if t is not None:
                t.events.append([ty.split('.')[-1], round(now, 3)])
        elif ty == 'conversation.item.input_audio_transcription.completed':
            if t is not None:
                t.user_text = (t.user_text + ' ' + ev.get('transcript', '')).strip()
        elif ty == 'response.done':
            resp = ev.get('response') or {}
            if t is not None:
                t.events.append(['response.done', round(now, 3), resp.get('status')])
                if t.t_end is not None and resp.get('status') == 'completed':
                    t.usage = resp.get('usage')
                    t.status = 'completed' if t.t_first_audio is not None else 'completed-no-audio'
                    t.t_done = now
                    t.done.set()
        elif ty == 'session.updated':
            self.updated = self.ok = True
            s = ev.get('session') or {}
            self.session_log.append({'type': ty, 'voice': ((s.get('audio') or {}).get('output') or {}).get('voice'),
                                     'instructions_chars': len(s.get('instructions') or '')})
            self.ready.set()
        elif ty == 'error':
            err = ev.get('error') or {}
            self.errors.append({k: err.get(k) for k in ('type', 'code', 'message', 'param')})
            if not self.updated:
                self.ready.set()

    async def send_audio(self, chunk):
        await self.ws.send_json({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(chunk).decode()})

    def turn_cost(self, t):
        u = t.usage or {}
        p = PRICES[self.model]
        it, ot = u.get('input_token_details') or {}, u.get('output_token_details') or {}
        cd = it.get('cached_tokens_details') or {}
        text_in, audio_in = it.get('text_tokens', 0), it.get('audio_tokens', 0)
        c_text, c_audio = cd.get('text_tokens', 0), cd.get('audio_tokens', 0)
        cost = ((text_in - c_text) * p['text_in'] + c_text * p['text_in_cached'] +
                (audio_in - c_audio) * p['audio_in'] + c_audio * p['audio_in_cached'] +
                ot.get('text_tokens', 0) * p['text_out'] + ot.get('audio_tokens', 0) * p['audio_out']) / 1e6
        return cost, {'text_in': text_in, 'text_in_cached': c_text, 'audio_in': audio_in, 'audio_in_cached': c_audio,
                      'text_out': ot.get('text_tokens', 0), 'audio_out': ot.get('audio_tokens', 0)}


class GPTLive(Engine):
    """GPT-Live is full duplex: its WebSocket can keep sending output audio, silence included, so a reply is the
    voiced audio (RMS >= VOICED_RMS) after the friend stops, ending after 1.5 s without voiced audio."""
    name = 'live'
    voiced_only = True

    async def connect(self):
        self.ws = await WS.connect('%s/v1/live/sessions' % OPENAI_WS, {'Authorization': 'Bearer ' + key('openai.key')})
        self.usage_seconds = 0.0
        self.closed_usage = None
        await self.ws.send_json({'type': 'session.start', 'event_id': 'start', 'session': {
            'model': self.model, 'instructions': self.prompt,
            'audio': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'output': {'voice': self.voice}}}})

    def handle(self, ev):
        ty = ev.get('type', '')
        t = self.turn
        now = mono()
        if ty == 'session.output_audio.delta':
            self.on_audio(base64.b64decode(ev['delta']))
        elif ty == 'session.output_transcript.delta':
            if t is not None and t.t_end is not None:
                t.reply_text += ev.get('delta', '')
        elif ty == 'session.input_transcript.delta':
            if t is not None:
                t.user_text += ev.get('delta', '')
        elif ty == 'session.usage.updated':
            self.usage_seconds = (ev.get('usage') or {}).get('seconds', self.usage_seconds)
        elif ty == 'session.started':
            self.session_log.append({'type': ty})
            self.ok = True
            self.ready.set()
        elif ty == 'session.closed':
            self.closed_usage = ev.get('usage')
            self.session_log.append({'type': ty, 'usage': ev.get('usage')})
        elif ty == 'error':
            err = ev.get('error') or {}
            self.errors.append({k: err.get(k) for k in ('type', 'code', 'message', 'param')})
            self.ready.set()
        elif t is not None and len(t.events) < 40:
            t.events.append([ty, round(now, 3)])

    async def send_audio(self, chunk):
        await self.ws.send_json({'type': 'session.input_audio.append', 'audio': base64.b64encode(chunk).decode()})

    async def close(self):
        try:
            await self.ws.send_json({'type': 'session.close', 'event_id': 'close'})
            for _ in range(100):
                if self.closed_usage is not None:
                    break
                await asyncio.sleep(0.1)
        except Exception:
            pass
        await super().close()


class GeminiVertex(Engine):
    """The production call path: Vertex AI Live, us-central1, API key header, same setup minus tools and memory seed."""
    name = 'gemini'
    in_sr = 16000

    async def connect(self):
        url = '%s/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent' % VERTEX_WS
        self.ws = await WS.connect(url, {'x-goog-api-key': key('gemini2.key')})
        await self.ws.send_json({'setup': {
            'model': 'projects/%s/locations/%s/publishers/google/models/%s' % (VERTEX_PROJECT, VERTEX_LOCATION, self.model),
            'generationConfig': {'responseModalities': ['AUDIO'], 'maxOutputTokens': 1024,
                                 'speechConfig': {'languageCode': 'ko-KR',
                                                  'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': self.voice}}}},
            'systemInstruction': {'parts': [{'text': self.prompt}]},
            'realtimeInputConfig': {'automaticActivityDetection': {'silenceDurationMs': VAD_MS, 'prefixPaddingMs': 100}},
            'contextWindowCompression': {'triggerTokens': 8192, 'slidingWindow': {'targetTokens': 4096}},
            'sessionResumption': {'transparent': True}, 'inputAudioTranscription': {}, 'outputAudioTranscription': {},
            'explicitVadSignal': True}})

    def handle(self, ev):
        t = self.turn
        now = mono()
        if 'setupComplete' in ev:
            self.session_log.append({'type': 'setupComplete'})
            self.ok = True
            self.ready.set()
        sc = ev.get('serverContent') or {}
        for part in (sc.get('modelTurn') or {}).get('parts', []):
            d = part.get('inlineData') or {}
            if d.get('data'):
                self.on_audio(base64.b64decode(d['data']))
        if t is not None:
            if sc.get('inputTranscription'):
                t.user_text += sc['inputTranscription'].get('text', '')
            if sc.get('outputTranscription') and t.t_end is not None:
                t.reply_text += sc['outputTranscription'].get('text', '')
            if sc.get('interrupted'):
                t.events.append(['interrupted', round(now, 3)])
            if ev.get('voiceActivityDetectionSignal') or ev.get('voiceActivity'):
                t.events.append(['vad', round(now, 3), ev.get('voiceActivityDetectionSignal') or ev.get('voiceActivity')])
            if ev.get('usageMetadata'):
                t.usage = ev['usageMetadata']
            if sc.get('turnComplete'):
                t.events.append(['turnComplete', round(now, 3)])
                if t.t_end is not None and t.t_first_audio is not None:
                    t.status = 'completed'
                    t.t_done = now
                    t.done.set()
        if ev.get('goAway'):
            self.session_log.append({'type': 'goAway'})
        if ev.get('error'):
            self.errors.append(ev['error'])
            self.ready.set()

    async def send_audio(self, chunk):
        await self.ws.send_json({'realtimeInput': {'audio': {'mimeType': 'audio/pcm;rate=16000',
                                                             'data': base64.b64encode(chunk).decode()}}})

    def turn_cost(self, t):
        u = t.usage or {}
        p = PRICES[self.model]

        def by_mod(details):
            out = {}
            for d in details or []:
                m = d.get('modality', '?')
                out[m] = out.get(m, 0) + d.get('tokenCount', 0)
            return out
        pin = by_mod(u.get('promptTokensDetails'))
        pout = by_mod(u.get('responseTokensDetails') or u.get('candidatesTokensDetails'))
        thoughts = u.get('thoughtsTokenCount', 0)
        cost = (pin.get('AUDIO', 0) * p['audio_in'] + pin.get('TEXT', 0) * p['text_in'] +
                pout.get('AUDIO', 0) * p['audio_out'] + (pout.get('TEXT', 0) + thoughts) * p['text_out']) / 1e6
        return cost, {'prompt_total': u.get('promptTokenCount'), 'in': pin, 'out': pout, 'thoughts': thoughts,
                      'total': u.get('totalTokenCount')}


def _dig(d, *path):
    for p in path:
        d = d.get(p) if isinstance(d, dict) else None
    return d


def _trim_conversation(c):
    """Billing fields of an ElevenAgents conversation. The (synthetic) transcript is already in turns.jsonl."""
    if not isinstance(c, dict):
        return str(c)[:300]
    m = c.get('metadata') or {}
    ch = m.get('charging') or {}
    keep = ('dev_discount', 'is_burst', 'tier', 'llm_price', 'llm_charge', 'call_charge', 'free_minutes_consumed',
            'free_llm_dollars_consumed', 'voice_surcharge_charge', 'platform_usage', 'llm_usage')
    return {'conversation_id': c.get('conversation_id'), 'agent_id': c.get('agent_id'), 'status': c.get('status'),
            'start_time_unix_secs': m.get('start_time_unix_secs'), 'call_duration_secs': m.get('call_duration_secs'),
            'cost_credits': m.get('cost'), 'cost_fiat_usd': m.get('cost_fiat', c.get('cost_fiat')),
            'charging': {k: ch.get(k) for k in keep if k in ch}}


async def eleven_billing(conv_id, t_start_unix, wait_s=120):
    """The billed conversation: by id when the API knows it, otherwise the workspace's conversations started during
    this run. Polls until ElevenLabs has processed it (status done), at most wait_s."""
    h = {'xi-api-key': key('elevenlabs.key')}
    out = {'looked_up_by': None, 'conversations': []}
    ids = []
    if conv_id:
        st, c = await ahttp_json('GET', '%s/v1/convai/conversations/%s' % (ELEVEN_HTTP, conv_id), h)
        if st == 200:
            ids, out['looked_up_by'] = [conv_id], 'id'
        else:
            out['by_id_status'] = st
    if not ids:
        st, lst = await ahttp_json('GET', '%s/v1/convai/conversations?page_size=10' % ELEVEN_HTTP, h)
        rows = lst.get('conversations', []) if st == 200 and isinstance(lst, dict) else []
        ids = [r.get('conversation_id') for r in rows
               if isinstance(r, dict) and (r.get('start_time_unix_secs') or 0) >= t_start_unix - 60]
        out['looked_up_by'] = 'list since run start (status %s)' % st
    for cid in ids[:3]:
        t0, last = mono(), None
        while mono() - t0 < wait_s:
            st, c = await ahttp_json('GET', '%s/v1/convai/conversations/%s' % (ELEVEN_HTTP, cid), h)
            last = c if st == 200 else '%s %s' % (st, str(c)[:200])
            if st == 200 and isinstance(c, dict) and c.get('status') in ('done', 'failed'):
                break
            await asyncio.sleep(5)
        out['conversations'].append(_trim_conversation(last))
    return out


class ElevenRealtime(OpenAIRealtime):
    """Eleven Realtime v1: ElevenLabs' speech-to-speech agent model (a tuned cascade inside, per their FAQ) on the
    OpenAI Realtime wire protocol. The key mints a short-lived client secret here, and the WebSocket uses it."""
    name = 'eleven-rt'
    ALIASES = {'response.audio.delta': 'response.output_audio.delta',
               'response.audio_transcript.delta': 'response.output_audio_transcript.delta'}
    QUIET = ('response.output_audio.delta', 'response.output_audio_transcript.delta', 'response.output_text.delta')

    async def connect(self):
        h = {'xi-api-key': key('elevenlabs.key')}
        self.session = {
            'type': 'realtime', 'model': self.model, 'instructions': self.prompt, 'output_modalities': ['audio'],
            'max_duration_seconds': 600,
            'audio': {'input': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'transcription': {'language': 'ko'},
                                'turn_detection': {'type': 'semantic_vad', 'eagerness': ELEVEN_RT_EAGERNESS}},
                      'output': {'format': {'type': 'audio/pcm'}, 'voice': self.voice}}}
        self.mint_log, self.connect_log, self.event_types = [], [], {}
        self.session_id = None
        self.updated = False
        secret = None
        for attempt in ('voice', 'default voice'):
            if attempt == 'default voice':
                self.session['audio']['output'].pop('voice', None)
            st, data = await ahttp_json('POST', ELEVEN_HTTP + '/v1/convai/realtime/client_secrets', h,
                                        {'session': self.session,
                                         'expires_after': {'anchor': 'created_at', 'seconds': 600}})
            ok = st == 200 and isinstance(data, dict) and bool(data.get('value'))
            self.mint_log.append({'attempt': attempt, 'status': st, 'detail': None if ok else str(data)[:400],
                                  'session_voice': _dig(data, 'session', 'audio', 'output', 'voice') if ok else None})
            if ok:
                secret = data['value']
                break
            if st not in (400, 422):
                break
        if not secret:
            raise RuntimeError('client secret refused: %s' % self.mint_log)
        self.voice_used = self.mint_log[-1]['session_voice']
        url = '%s/v1/convai/realtime?model=%s' % (ELEVEN_WS, self.model)
        for auth, hh in (('bearer client secret', {'Authorization': 'Bearer ' + secret}),
                         ('subprotocol client secret',
                          {'Sec-WebSocket-Protocol': 'realtime, openai-insecure-api-key.' + secret}),
                         ('api key header', h)):
            try:
                self.ws = await WS.connect(url, hh)
                self.connect_log.append({'auth': auth, 'ok': True})
                break
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                self.connect_log.append({'auth': auth, 'error': str(e)[:300]})
        if self.ws is None:
            raise RuntimeError('WebSocket refused: %s' % self.connect_log)

    def handle(self, ev):
        ty = ev.get('type', '')
        self.event_types[ty] = self.event_types.get(ty, 0) + 1
        if ty in self.ALIASES:
            ty = self.ALIASES[ty]
            ev = dict(ev, type=ty)
        if ty == 'session.created':
            s = ev.get('session') or {}
            self.session_id = s.get('id')
            self.session_log.append({'type': ty, 'model': s.get('model'), 'voice': _dig(s, 'audio', 'output', 'voice'),
                                     'turn_detection': _dig(s, 'audio', 'input', 'turn_detection')})
            self.ok = self.updated = True
            self.ready.set()
            return
        super().handle(ev)
        t = self.turn
        if t is not None and ty not in self.QUIET and len(t.events) < 60:
            if not t.events or t.events[-1][0] != ty:
                t.events.append([ty, round(mono(), 3)])

    def turn_cost(self, t):
        return None, t.usage


class ElevenAgent(Engine):
    """ElevenAgents in Custom mode with Han Aim: their streaming ASR and turn-taking model, an LLM they host and Flash
    v2.5, all on their side. The run creates one private agent tagged voice-bench (it stays in the workspace) and
    talks to it through a signed URL made here with the key."""
    name = 'eleven-agent'
    in_sr = 16000
    out_sr = 16000

    async def connect(self):
        h = {'xi-api-key': key('elevenlabs.key')}
        prompt_cfg = {'prompt': self.prompt, 'llm': self.model, 'reasoning_effort': 'none'}
        cfg = {'agent': {'first_message': '', 'language': 'ko', 'prompt': prompt_cfg},
               'asr': {'provider': 'scribe_realtime', 'user_input_audio_format': 'pcm_16000'},
               'turn': {'turn_eagerness': ELEVEN_AGENT_EAGERNESS},
               'tts': {'model_id': 'eleven_flash_v2_5', 'voice_id': self.voice, 'agent_output_audio_format': 'pcm_16000'},
               'conversation': {'max_duration_seconds': 480}}
        body = {'name': 'voice-bench %s Han Aim (synthetic test)' % self.model, 'tags': ['voice-bench'],
                'conversation_config': cfg}
        self.create_log, self.other_types = [], {}
        self.agent_id = self.conversation_id = self.formats = None
        for attempt in ('reasoning none', 'model default reasoning'):
            if attempt == 'model default reasoning':
                prompt_cfg.pop('reasoning_effort', None)
            st, data = await ahttp_json('POST', ELEVEN_HTTP + '/v1/convai/agents/create', h, body)
            ok = st == 200 and isinstance(data, dict) and bool(data.get('agent_id'))
            self.create_log.append({'attempt': attempt, 'status': st, 'detail': None if ok else str(data)[:400]})
            if ok:
                self.agent_id = data['agent_id']
                break
            if st not in (400, 422):
                break
        if not self.agent_id:
            raise RuntimeError('agent create refused: %s' % self.create_log)
        st, data = await ahttp_json('GET', '%s/v1/convai/conversation/get-signed-url?agent_id=%s'
                                    % (ELEVEN_HTTP, self.agent_id), h)
        if st != 200 or not isinstance(data, dict) or not data.get('signed_url'):
            raise RuntimeError('signed URL refused: %s %s' % (st, str(data)[:300]))
        self.ws = await WS.connect(data['signed_url'], {})
        await self.ws.send_json({'type': 'conversation_initiation_client_data'})

    def handle(self, ev):
        ty = ev.get('type', '')
        t = self.turn
        now = mono()
        if ty == 'audio':
            a = ev.get('audio_event') or {}
            if a.get('audio_base_64'):
                self.on_audio(base64.b64decode(a['audio_base_64']))
            if a.get('is_final') and t is not None:
                t.events.append(['audio_is_final', round(now, 3)])
        elif ty == 'ping':
            eid = (ev.get('ping_event') or {}).get('event_id')
            asyncio.ensure_future(self.ws.send_json({'type': 'pong', 'event_id': eid}))
        elif ty == 'conversation_initiation_metadata':
            m = ev.get('conversation_initiation_metadata_event') or {}
            self.conversation_id = m.get('conversation_id')
            self.formats = {'in': m.get('user_input_audio_format'), 'out': m.get('agent_output_audio_format')}
            self.session_log.append({'type': ty, 'formats': self.formats})
            self.ok = True
            self.ready.set()
        elif ty == 'user_transcript':
            if t is not None:
                txt = _dig(ev, 'user_transcription_event', 'user_transcript') or ''
                t.user_text = (t.user_text + ' ' + txt).strip()
                t.events.append(['user_transcript', round(now, 3)])
        elif ty == 'agent_response':
            if t is not None:
                txt = _dig(ev, 'agent_response_event', 'agent_response') or ''
                if t.t_end is not None:
                    t.reply_text = (t.reply_text + ' ' + txt).strip()
                t.events.append(['agent_response', round(now, 3)])
        elif ty == 'interruption':
            if t is not None:
                t.events.append(['interruption', round(now, 3), _dig(ev, 'interruption_event', 'reason')])
        elif ty == 'agent_response_complete':
            if t is not None:
                t.events.append([ty, round(now, 3)])
                if t.t_end is not None and t.t_first_audio is not None:
                    t.status, t.t_done = 'completed', now
                    t.done.set()
        elif ty in ('vad_score', 'context_usage'):
            pass
        else:
            self.other_types[ty] = self.other_types.get(ty, 0) + 1
            if ty == 'error' or 'error' in ev:
                self.errors.append(str(ev)[:300])
                self.ready.set()
            elif t is not None and len(t.events) < 60:
                t.events.append([ty, round(now, 3)])

    async def send_audio(self, chunk):
        await self.ws.send_json({'user_audio_chunk': base64.b64encode(chunk).decode()})


S2S = {'gemini': (GeminiVertex, 'gemini-3.8-live', 'Sulafat', 'gemini2.key'),
       'openai': (OpenAIRealtime, 'gpt-realtime-2.1-mini', 'marin', 'openai.key'),
       'live': (GPTLive, 'gpt-live-1', 'noeul', 'openai.key'),
       'eleven-rt': (ElevenRealtime, ELEVEN_RT_MODEL, HAN_AIM, 'elevenlabs.key'),
       'eleven-agent': (ElevenAgent, ELEVEN_AGENT_LLM, HAN_AIM, 'elevenlabs.key')}
ELEVEN = ('eleven-rt', 'eleven-agent')


async def run_s2s(kind, prompt, turns, timeout=25.0):
    cls, model, voice, keyname = S2S[kind]
    outdir = os.path.join(RESULTS, 's2s-' + kind)
    log = Log(outdir)
    if not key(keyname):
        log.summary({'engine': kind, 'skipped': 'no key file ' + keyname})
        return
    eng = cls(model, voice, prompt)
    t0 = mono()
    t0_unix = time.time()
    await eng.connect()
    recv = asyncio.ensure_future(eng.recv_loop())
    if kind == 'eleven-rt':
        # the minted session is the starting session; send it as session.update only if nothing arrives
        try:
            await asyncio.wait_for(eng.ready.wait(), 5)
        except asyncio.TimeoutError:
            eng.session_log.append({'note': 'no session.created within 5 s, sent session.update'})
            await eng.ws.send_json({'type': 'session.update', 'session': eng.session})
            await asyncio.wait_for(eng.ready.wait(), 15)
    else:
        await asyncio.wait_for(eng.ready.wait(), 20)
    if kind == 'openai' and not eng.updated:
        # the session.update was refused: try once without input transcription, then give up
        eng.errors.append({'note': 'retry session.update without input transcription'})
        eng.session['audio']['input'].pop('transcription', None)
        eng.ready.clear()
        await eng.ws.send_json({'type': 'session.update', 'session': eng.session})
        await asyncio.wait_for(eng.ready.wait(), 15)
        if not eng.updated:
            raise RuntimeError('session.update refused: %s' % eng.errors[-1:])
    if not eng.ok:
        raise RuntimeError('setup refused: errors=%s log=%s' % (eng.errors[:2], eng.session_log[-2:]))
    connect_s = mono() - t0
    mic = Mic(eng.send_audio, eng.in_sr).start()
    await asyncio.sleep(1.5)
    # if the model greets on its own, let it finish before the friend speaks (at most 12 s)
    t_wait = mono()
    while mono() - t_wait < 12 and eng.t_any_audio is not None and mono() - eng.t_any_audio < 2.0:
        await asyncio.sleep(0.1)
    greeting = eng.t_any_audio is not None
    session_t0 = mono()
    last_secs, misses, total = 0.0, 0, 0.0
    for ut in turns:
        t = Turn()
        eng.turn = t
        t_speech = mono()
        t.t_end = await mic.say(ut['pcm24'] if eng.in_sr == 24000 else ut['pcm16'])
        deadline = t.t_end + timeout
        quiet = {'live': 1.5, 'eleven-agent': 2.5}.get(kind)
        if quiet:
            # GPT-Live has no per-turn done event over WebSocket, and the ElevenAgents one is not documented as
            # always sent: the reply also ends after `quiet` seconds without audio
            while mono() < deadline and not recv.done() and not t.done.is_set():
                await asyncio.sleep(0.05)
                if t.t_first_audio is not None and mono() - t.t_last_audio > quiet:
                    t.status, t.t_done = 'completed', t.t_last_audio
                    t.events.append(['quiet_end', round(mono(), 3)])
                    break
        else:
            try:
                await asyncio.wait_for(t.done.wait(), max(0.1, deadline - mono()))
            except asyncio.TimeoutError:
                pass
        t.status = t.status or ('timeout' if not recv.done() else 'connection-ended')
        reply_s = len(t.audio) / 2 / eng.out_sr
        if t.t_first_audio is not None:
            await asyncio.sleep(max(0.0, reply_s - (mono() - t.t_first_audio)) + GAP_AFTER_REPLY)
        else:
            await asyncio.sleep(GAP_AFTER_REPLY)
        rec = {'engine': kind, 'model': model, 'voice': voice, 'turn': ut['id'], 'status': t.status,
               'user_ref': ut['text'], 'user_heard': t.user_text.strip(),
               'user_cer': cer(ut['refs'], t.user_text) if t.user_text.strip() else None,
               'latency_s': round(t.t_first_audio - t.t_end, 3) if t.t_first_audio else None,
               'reply_text': t.reply_text.strip(), 'reply_audio_s': round(reply_s, 2),
               'pre_audio_s': round(t.pre_audio / 2 / eng.out_sr, 2), 'speech_s': round(t.t_end - t_speech, 2),
               'events': [[e[0], round(e[1] - t.t_end, 3)] + list(e[2:]) for e in t.events[-12:]]}
        if kind in ('openai', 'gemini'):
            c, tok = eng.turn_cost(t)
            rec['cost_usd'], rec['tokens'] = round(c, 6), tok
        elif kind in ELEVEN:
            # billed per call minute plus LLM tokens: read from the conversation after the run (summary billing)
            rec['cost_usd'], rec['usage'] = None, t.usage
        else:
            secs = float(eng.usage_seconds or 0)
            rec['usage_seconds_cum'] = secs
            rec['cost_usd'] = round((secs - last_secs) * PRICES[model]['per_min'] / 60, 6)
            last_secs = secs
        total += rec['cost_usd'] or 0
        log.write(rec)
        if t.audio:
            write_wav(os.path.join(outdir, ut['id'] + '.wav'), t.audio, eng.out_sr)
        print('%s %s lat=%s cost=%s status=%s' % (kind, ut['id'], rec['latency_s'], rec.get('cost_usd'), t.status),
              flush=True)
        misses = misses + 1 if t.t_first_audio is None else 0
        if misses >= 3 or recv.done():
            break
        if spent['usd'] + total > MAX_USD:
            log.write({'note': 'stopped at the cost cap', 'cap_usd': MAX_USD})
            break
    session_s = mono() - session_t0
    await mic.stop()
    await eng.close()
    await asyncio.sleep(0.3)
    recv.cancel()
    summary = {'engine': kind, 'model': model, 'voice': voice, 'connect_s': round(connect_s, 2),
               'session_s': round(session_s, 1), 'mic_seconds_sent': round(mic.sent_bytes / 2 / eng.in_sr, 1),
               'turn_cost_sum_usd': round(total, 6), 'errors': eng.errors[:5], 'mic_errors': mic.errors[:3],
               'audio_before_first_turn': greeting, 'session_log': eng.session_log[-5:]}
    if kind == 'live':
        summary['closed_usage'] = eng.closed_usage
        summary['usage_seconds_final'] = eng.usage_seconds
    if kind in ELEVEN:
        price = PRICES['eleven_realtime_v1_mini' if kind == 'eleven-rt' else 'elevenagents']['per_min']
        total = session_s / 60 * price
        summary['call_minutes_estimate_usd'] = round(total, 6)
        summary['price_note'] = '%.2f USD per call minute (list price 2026-11-17) plus LLM usage' % price
        if kind == 'eleven-rt':
            summary.update({'mint': eng.mint_log, 'connect': eng.connect_log, 'voice_used': eng.voice_used,
                            'turn_detection': {'type': 'semantic_vad', 'eagerness': ELEVEN_RT_EAGERNESS},
                            'event_types': eng.event_types, 'session_id': eng.session_id})
            conv = eng.session_id
        else:
            summary.update({'agent_id': eng.agent_id, 'agent_create': eng.create_log, 'formats': eng.formats,
                            'asr': 'scribe_realtime', 'turn_eagerness': ELEVEN_AGENT_EAGERNESS,
                            'tts': 'eleven_flash_v2_5', 'llm': model + ' (reasoning_effort none when accepted)',
                            'other_event_types': eng.other_types, 'conversation_id': eng.conversation_id})
            conv = eng.conversation_id
        try:
            summary['billing'] = await eleven_billing(conv, t0_unix)
        except Exception as e:
            summary['billing'] = {'error': repr(e)[:300]}
    spent['usd'] += total
    log.summary(summary)


# ------------------------------------------------------------------ cascade: realtime STT -> text LLM -> TTS

class LiveTranscribe:
    """gpt-live-transcribe over WebSocket; the client commits each turn (the model has no server VAD)."""

    def __init__(self):
        self.ws = None
        self.ready = asyncio.Event()
        self.errors = []
        self.committed = []      # (item_id, t)
        self.final = {}          # item_id -> (text, t)
        self.deltas = {}         # item_id -> first delta time
        self.event = asyncio.Event()

    VARIANTS = ({'model': 'gpt-live-transcribe', 'languages': ['ko'], 'delay': 'low'},
                {'model': 'gpt-live-transcribe', 'languages': ['ko']},
                {'model': 'gpt-live-transcribe'})

    async def connect(self):
        self.ws = await WS.connect('%s/v1/realtime?intent=transcription' % OPENAI_WS,
                                   {'Authorization': 'Bearer ' + key('openai.key')})
        self.ok = False
        self.variant = None

    async def configure(self):
        for v in self.VARIANTS:
            self.ready.clear()
            n_err = len(self.errors)
            await self.ws.send_json({'type': 'session.update', 'session': {
                'type': 'transcription',
                'audio': {'input': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'transcription': v,
                                    'turn_detection': None}}}})
            try:
                await asyncio.wait_for(self.ready.wait(), 15)
            except asyncio.TimeoutError:
                pass
            if self.ok and len(self.errors) == n_err:
                self.variant = v
                return v
            self.ok = False
        raise RuntimeError('transcription session refused: %s' % self.errors[-3:])

    async def recv_loop(self):
        try:
            while True:
                ev = await self.ws.recv_json()
                ty = ev.get('type', '')
                now = mono()
                if ty in ('session.updated', 'transcription_session.updated'):
                    self.ok = True
                    self.ready.set()
                elif ty == 'input_audio_buffer.committed':
                    self.committed.append((ev.get('item_id'), now))
                elif ty == 'conversation.item.input_audio_transcription.delta':
                    self.deltas.setdefault(ev.get('item_id'), now)
                elif ty == 'conversation.item.input_audio_transcription.completed':
                    self.final[ev.get('item_id')] = (ev.get('transcript', ''), now)
                elif ty == 'error':
                    err = ev.get('error') or {}
                    self.errors.append({k: err.get(k) for k in ('type', 'code', 'message', 'param')})
                    self.ready.set()
                self.event.set()
        except (WSClosed, asyncio.IncompleteReadError, ConnectionError) as e:
            self.errors.append({'closed': repr(e)[:200]})
            self.ready.set()
            self.event.set()

    async def send_audio(self, chunk):
        await self.ws.send_json({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(chunk).decode()})

    async def commit_and_wait(self, timeout=10.0):
        n0 = len(self.committed)
        await self.ws.send_json({'type': 'input_audio_buffer.commit'})
        deadline = mono() + timeout
        item = None
        while mono() < deadline:
            if item is None and len(self.committed) > n0:
                item = self.committed[n0][0]
            if item is not None and item in self.final:
                text, t = self.final[item]
                return text, t, self.deltas.get(item)
            self.event.clear()
            try:
                await asyncio.wait_for(self.event.wait(), max(0.05, deadline - mono()))
            except asyncio.TimeoutError:
                break
        return None, None, None


def llm_turn(messages, on_first_sentence, model='gpt-6-luna'):
    """Stream one reply. Calls on_first_sentence(text, t) once. Returns timings, text and usage."""
    out = {'t_req': mono(), 't_first_token': None, 't_first_sentence': None, 't_done': None, 'text': '', 'usage': None}
    sse = SSE()
    fired = [False]

    def on_chunk(chunk, t):
        for data in sse.feed(chunk):
            if data == '[DONE]':
                continue
            d = json.loads(data)
            if d.get('usage'):
                out['usage'] = d['usage']
            for ch in d.get('choices') or []:
                piece = (ch.get('delta') or {}).get('content') or ''
                if piece:
                    if out['t_first_token'] is None:
                        out['t_first_token'] = t
                    out['text'] += piece
                    if not fired[0]:
                        e = first_sentence_end(out['text'])
                        if e > 0:
                            fired[0] = True
                            out['t_first_sentence'] = t
                            on_first_sentence(out['text'][:e].strip(), t)
    http_post_stream(OPENAI_HTTP + '/v1/chat/completions', {'Authorization': 'Bearer ' + key('openai.key')},
                     {'model': model, 'messages': messages, 'stream': True, 'stream_options': {'include_usage': True},
                      'reasoning_effort': 'none', 'max_completion_tokens': 300}, on_chunk)
    out['t_done'] = mono()
    if not fired[0] and out['text'].strip():
        out['t_first_sentence'] = out['t_done']
        on_first_sentence(out['text'].strip(), out['t_done'])
    return out


def _tts_call(res, send):
    """Run send() and, when it fails before any audio with a timeout, a dropped connection, 429 or 5xx, once more.

    t_req stays at the first attempt, so a retry counts in the waiting time the way a caller would feel it.
    """
    for attempt in (1, 2):
        res['t_req_last'] = mono()
        try:
            send()
            return
        except HTTPError as e:
            msg = str(e)[:300]
            retry = msg[:1] == '5' or msg[:3] == '429'
        except Exception as e:  # socket timeout, reset, DNS
            msg = repr(e)[:300]
            retry = True
        if attempt == 1 and retry and res['t_first'] is None:
            res.setdefault('retries', []).append(msg)
            continue
        res['error'] = msg
        return


def _pcm_res(text):
    return {'t_req': mono(), 't_first': None, 'pcm': bytearray(), 'sr': 24000, 'error': None, 'chunks': 0,
            'chars': len(text)}


def _pcm_sink(res):
    def on_chunk(chunk, t):
        if res['t_first'] is None:
            res['t_first'] = t
        res['pcm'] += chunk
        res['chunks'] += 1
    return on_chunk


def _even(res):
    if len(res['pcm']) % 2:
        res['pcm'] = res['pcm'][:-1]
    return res


def tts_openai(text, voice='marin'):
    res = _pcm_res(text)
    _tts_call(res, lambda: http_post_stream(
        OPENAI_HTTP + '/v1/audio/speech', {'Authorization': 'Bearer ' + key('openai.key')},
        {'model': 'gpt-4o-mini-tts', 'voice': voice, 'input': text, 'response_format': 'pcm',
         'instructions': ('한국어 원어민 성인 여성 목소리로, 친한 친구와 전화하듯 다정하고 차분하게 말해. '
                          '아이 같거나 과장된 톤은 쓰지 마.')}, _pcm_sink(res), timeout=TTS_TIMEOUT))
    return _even(res)


def tts_elevenlabs(text, voice_id=HAN_AIM, model='eleven_flash_v2_5'):
    """ElevenLabs streaming TTS as raw 24 kHz PCM. No style prompt and no unverified latency options."""
    res = _pcm_res(text)
    _tts_call(res, lambda: http_post_stream(
        '%s/v1/text-to-speech/%s/stream?output_format=pcm_24000' % (ELEVEN_HTTP, voice_id),
        {'xi-api-key': key('elevenlabs.key')}, {'text': text, 'model_id': model, 'language_code': 'ko'},
        _pcm_sink(res), timeout=TTS_TIMEOUT))
    return _even(res)


def tts_gemini(text, voice='Sulafat', model='gemini-3.8-flash-lite-tts'):
    res = _pcm_res(text)
    res.update({'usage': None, 'via': GEMINI_TTS_VIA, 'mode': 'stream'})

    def on_data(data, t):
        try:
            d = json.loads(data)
        except ValueError:
            return
        if d.get('usageMetadata'):
            res['usage'] = d['usageMetadata']
        for cand in d.get('candidates') or []:
            for part in (cand.get('content') or {}).get('parts') or []:
                inline = part.get('inlineData') or {}
                if inline.get('data'):
                    if res['t_first'] is None:
                        res['t_first'] = t
                    m = re.search(r'rate=(\d+)', inline.get('mimeType', ''))
                    if m:
                        res['sr'] = int(m.group(1))
                    res['pcm'] += base64.b64decode(inline['data'])
                    res['chunks'] += 1
    body = {'contents': [{'role': 'user', 'parts': [{'text': text}]}],
            'generationConfig': {'responseModalities': ['AUDIO'], 'speechConfig': {
                'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': voice}}}}}
    if GEMINI_TTS_VIA == 'aistudio':
        base, hdr = '%s/v1beta/models/%s' % (GEMINI_HTTP, model), {'x-goog-api-key': key('gemini.key')}
    else:
        base = '%s/v1beta1/projects/%s/locations/global/publishers/google/models/%s' % (VERTEX_HTTP, VERTEX_PROJECT,
                                                                                        model)
        hdr = {'x-goog-api-key': key('gemini2.key')}

    def stream():
        sse = SSE()
        http_post_stream(base + ':streamGenerateContent?alt=sse', hdr, body,
                         lambda c, t: [on_data(d, t) for d in sse.feed(c)], timeout=TTS_TIMEOUT)
    _tts_call(res, stream)
    if res['error'] and res['error'][:3] in ('400', '404') and res['t_first'] is None:
        # the streaming method was refused: one plain request, marked as unary
        res['stream_error'], res['error'], res['mode'] = res['error'], None, 'unary'
        raw = bytearray()

        def unary():
            del raw[:]
            http_post_stream(base + ':generateContent', hdr, body, lambda c, t: raw.extend(c), timeout=60)
        _tts_call(res, unary)
        if not res['error']:
            on_data(bytes(raw).decode('utf-8', 'replace'), mono())
    return _even(res)


def gemini_tts_cost(res):
    u = res.get('usage') or {}
    p = PRICES['gemini-3.8-flash-lite-tts']
    out = 0
    for d in u.get('candidatesTokensDetails') or u.get('responseTokensDetails') or []:
        if d.get('modality') == 'AUDIO':
            out += d.get('tokenCount', 0)
    if not out:
        out = u.get('candidatesTokenCount', 0)
    return (u.get('promptTokenCount', 0) * p['text_in'] + out * p['audio_out']) / 1e6


TTS = {
    'openai': (tts_openai, 'gpt-4o-mini-tts marin'),
    'gemini': (tts_gemini, 'gemini-3.8-flash-lite-tts Sulafat'),
    'elevenlabs': (tts_elevenlabs, 'eleven_flash_v2_5 Han Aim'),
}


def tts_keys(vendor):
    if vendor == 'gemini':
        return ['gemini.key'] if GEMINI_TTS_VIA == 'aistudio' else ['gemini2.key']
    return {'openai': ['openai.key'], 'elevenlabs': ['elevenlabs.key']}[vendor]


def tts_label(vendor):
    if vendor == 'gemini':
        return TTS[vendor][1] + (' (AI Studio)' if GEMINI_TTS_VIA == 'aistudio' else ' (Vertex global)')
    return TTS[vendor][1]


def tts_cost(vendor, results, secs):
    rs = [r for r in results if r]
    if vendor == 'openai':
        return secs / 60 * PRICES['gpt-4o-mini-tts']['per_min_est']
    if vendor == 'gemini':
        return sum(gemini_tts_cost(r) for r in rs)
    return sum(r['chars'] for r in rs) / 1000 * PRICES['eleven_flash_v2_5']['usd_per_1k_chars']


def cascade_vendors():
    """Voices from VB_CASCADE_TTS, otherwise every voice whose key file exists. Returns (on, skipped reasons)."""
    want = os.environ.get('VB_CASCADE_TTS', '')
    names = [n.strip() for n in want.split(',') if n.strip()] or list(TTS)
    on, skipped = [], {}
    for n in names:
        if n not in TTS:
            skipped[n] = 'unknown voice'
            continue
        missing = [k for k in tts_keys(n) if not key(k)]
        if missing:
            skipped[n] = 'no key file ' + ', '.join(missing)
        else:
            on.append(n)
    return on, skipped


def cascade_turn(history, user_text, vendors):
    """LLM stream; at its first sentence every voice starts at once; the rest is synthesized after for the samples."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2 * len(vendors) + 1)
    first = {}

    def on_first_sentence(sentence, t):
        first['sentence'], first['t'] = sentence, t
        for v in vendors:
            first[v] = pool.submit(TTS[v][0], sentence)
    try:
        llm = llm_turn(history + [{'role': 'user', 'content': user_text}], on_first_sentence)
        rest = llm['text'][len(first.get('sentence', '')):].strip() if first else ''
        out = {'llm': llm, 'sentence': first.get('sentence', ''), 'rest': rest}
        pending = {}
        for v in vendors:
            if v in first:
                r1 = first[v].result()
                pending[v] = (r1, pool.submit(TTS[v][0], rest) if rest and not r1['error'] else None)
        for v, (r1, f2) in pending.items():
            out[v] = {'first': r1, 'rest': f2.result() if f2 else None}
    finally:
        pool.shutdown(wait=False)
    return out


class AAITranscribe:
    """AssemblyAI streaming (v3): binary PCM frames in, Turn messages out. The model decides where each turn ends.

    Docs read 2026-11-17: the final of a turn is the Turn message with end_of_turn true; ForceEndpoint ends the
    current turn at once; Terminate closes the session and Termination reports its duration (the billed time).
    """
    sr = 24000

    def __init__(self):
        self.ws = None
        self.ready = asyncio.Event()
        self.event = asyncio.Event()
        self.errors = []
        self.begin = None
        self.termination = None
        self.finals = []          # (turn_order, transcript, t)
        self.first_partial = {}   # turn_order -> t
        self.speech_started = 0
        self.in_turn = False
        self.t_open = None
        self.t_closed = None

    def params(self):
        p = {'speech_model': AAI_MODEL, 'sample_rate': self.sr, 'encoding': 'pcm_s16le',
             'language_codes': json.dumps(['ko'])}
        if AAI_MODE:
            p['mode'] = AAI_MODE
        return p

    async def connect(self):
        self.t_open = mono()
        self.ws = await WS.connect('%s/v3/ws?%s' % (AAI_WS, urllib.parse.urlencode(self.params())),
                                   {'Authorization': key('assemblyai.key')})

    async def configure(self):
        try:
            await asyncio.wait_for(self.ready.wait(), 15)
        except asyncio.TimeoutError:
            pass
        if not self.begin:
            raise RuntimeError('AssemblyAI session not started: %s' % self.errors[-3:])
        return {'requested': self.params(), 'applied': self.begin.get('configuration')}

    async def recv_loop(self):
        try:
            while True:
                op, data = await self.ws.recv()
                if op != 0x1:
                    continue
                ev = json.loads(data.decode('utf-8'))
                ty = ev.get('type')
                now = mono()
                if ty == 'Begin':
                    self.begin = ev
                    self.ready.set()
                elif ty == 'SpeechStarted':
                    self.in_turn = True
                    self.speech_started += 1
                elif ty == 'Turn':
                    order = ev.get('turn_order')
                    if ev.get('end_of_turn'):
                        if self.finals and self.finals[-1][0] == order:  # a later copy of the same final
                            self.finals[-1] = (order, ev.get('transcript', ''), self.finals[-1][2])
                        else:
                            self.finals.append((order, ev.get('transcript', ''), now))
                        self.in_turn = False
                    else:
                        self.in_turn = True
                        self.first_partial.setdefault(order, now)
                elif ty == 'Termination':
                    self.termination = ev
                elif ty == 'Error' or 'error' in ev:
                    self.errors.append(json.dumps(ev, ensure_ascii=False)[:300])
                self.event.set()
        except (WSClosed, asyncio.IncompleteReadError, ConnectionError) as e:
            if self.termination is None:  # a close after Termination is the normal end
                self.errors.append({'closed': repr(e)[:200]})
            self.t_closed = mono()
            self.ready.set()
            self.event.set()

    async def send_audio(self, chunk):
        await self.ws.send(chunk, 0x2)

    async def finish(self, n0, t_end, hold=3.0):
        """Wait for the final of the turn holding the end of speech; ForceEndpoint if none came within `hold` s."""
        forced = None
        deadline = t_end + hold
        while True:
            segs = self.finals[n0:]
            if segs and not self.in_turn and segs[-1][2] >= t_end:
                break
            if self.t_closed is not None:
                break
            now = mono()
            if now >= deadline:
                if forced is None:
                    forced = now
                    await self.ws.send_json({'type': 'ForceEndpoint'})
                    deadline = now + 2.0
                    continue
                break
            self.event.clear()
            try:
                await asyncio.wait_for(self.event.wait(), max(0.01, deadline - now))
            except asyncio.TimeoutError:
                pass
        segs = self.finals[n0:]
        text = ' '.join(s[1].strip() for s in segs if s[1].strip())
        last = segs[-1] if segs and segs[-1][2] >= t_end else None
        info = {'stt_final_after_end_s': round(last[2] - t_end, 3) if last else None,
                'stt_first_partial_after_end_s': (round(self.first_partial[last[0]] - t_end, 3)
                                                  if last and last[0] in self.first_partial else None),
                'stt_segments': sum(1 for s in segs if s[1].strip()),
                'stt_finals_before_end': sum(1 for s in segs if s[2] < t_end and s[1].strip()),
                'stt_forced_endpoint_after_end_s': round(forced - t_end, 3) if forced else None}
        return text, (last[2] if last else None), info

    async def close(self):
        try:
            await self.ws.send_json({'type': 'Terminate'})
            t = mono()
            while self.termination is None and self.t_closed is None and mono() - t < 5:
                await asyncio.sleep(0.05)
        except Exception as e:
            self.errors.append({'terminate': repr(e)[:200]})
        await self.ws.close()


async def run_cascade(prompt, turns, stt_kind='openai'):
    name = 'cascade' if stt_kind == 'openai' else 'cascade-aai'
    outdir = os.path.join(RESULTS, name)
    log = Log(outdir)
    need = ['openai.key'] + (['assemblyai.key'] if stt_kind == 'assemblyai' else [])
    missing = [k for k in need if not key(k)]
    vendors, skipped = cascade_vendors()
    if missing or not vendors:
        log.summary({'engine': name, 'skipped': ('no key file ' + ', '.join(missing)) if missing else 'no voice',
                     'tts_skipped': skipped})
        return
    stt = LiveTranscribe() if stt_kind == 'openai' else AAITranscribe()
    t0 = mono()
    await stt.connect()
    recv = asyncio.ensure_future(stt.recv_loop())
    variant = await stt.configure()
    connect_s = mono() - t0
    # AssemblyAI wants 20-1000 ms per frame and recommends 50-100 ms
    mic = Mic(stt.send_audio, 24000, chunk_ms=20 if stt_kind == 'openai' else 50).start()
    await asyncio.sleep(1.0)
    session_t0 = mono()
    loop = asyncio.get_event_loop()
    history = [{'role': 'system', 'content': prompt}]
    total = 0.0
    for ut in turns:
        t_speech = mono()
        n0 = len(getattr(stt, 'finals', []))
        t_end = await mic.say(ut['pcm24'])
        rec = {'engine': name, 'turn': ut['id'], 'user_ref': ut['text'], 'speech_s': round(t_end - t_speech, 2)}
        if stt_kind == 'openai':
            await asyncio.sleep(max(0.0, t_end + VAD_MS / 1000 - mono()))  # a 700 ms end-of-speech detector
            t_commit = mono()
            text, t_final, t_first_delta = await stt.commit_and_wait()
            rec.update({'commit_after_end_s': round(t_commit - t_end, 3),
                        'stt_final_after_commit_s': round(t_final - t_commit, 3) if t_final else None,
                        'stt_final_after_end_s': round(t_final - t_end, 3) if t_final else None,
                        'stt_first_delta_after_end_s': round(t_first_delta - t_end, 3) if t_first_delta else None})
        else:
            text, t_final, info = await stt.finish(n0, t_end)
            rec.update(info)
            if text and t_final is None:
                t_final = mono()
                rec['note'] = 'no final after the end of speech; the reply starts when the wait ended'
        rec.update({'user_heard': text, 'user_cer': cer(ut['refs'], text) if text else None})
        if not text:
            rec['status'] = 'no-transcript'
            log.write(rec)
            continue
        try:
            res = await loop.run_in_executor(None, cascade_turn, history, text, vendors)
        except Exception as e:
            rec.update({'status': 'llm-failed', 'error': repr(e)[:500]})
            log.write(rec)
            await asyncio.sleep(GAP_AFTER_REPLY)
            continue
        llm = res['llm']
        history += [{'role': 'user', 'content': text}, {'role': 'assistant', 'content': llm['text'].strip()}]
        u = llm['usage'] or {}
        cached = (u.get('prompt_tokens_details') or {}).get('cached_tokens', 0)
        p = PRICES['gpt-6-luna']
        llm_cost = ((u.get('prompt_tokens', 0) - cached) * p['in'] + cached * p['in_cached'] +
                    u.get('completion_tokens', 0) * p['out']) / 1e6
        rec.update({'status': 'completed', 'reply_text': llm['text'].strip(), 'first_sentence': res['sentence'],
                    'llm_first_token_after_final_s': round(llm['t_first_token'] - t_final, 3) if llm['t_first_token'] else None,
                    'llm_first_sentence_after_final_s': round(llm['t_first_sentence'] - t_final, 3) if llm['t_first_sentence'] else None,
                    'llm_done_after_final_s': round(llm['t_done'] - t_final, 3),
                    'llm_usage': {'prompt': u.get('prompt_tokens'), 'cached': cached, 'out': u.get('completion_tokens')},
                    'llm_cost_usd': round(llm_cost, 6)})
        play = {}
        turn_cost = llm_cost
        for vendor in vendors:
            v = res.get(vendor)
            if not v:
                continue
            r1, r2 = v['first'], v['rest']
            pcm = bytes(r1['pcm']) + (bytes(r2['pcm']) if r2 and r2['sr'] == r1['sr'] else b'')
            secs = len(pcm) / 2 / r1['sr']
            c = tts_cost(vendor, [r1, r2], secs)
            rec[vendor] = {'error': r1['error'] or (r2 or {}).get('error'),
                           'latency_s': round(r1['t_first'] - t_end, 3) if r1['t_first'] else None,
                           'tts_first_audio_after_request_s': round(r1['t_first'] - r1['t_req'], 3) if r1['t_first'] else None,
                           'tts_first_audio_after_sentence_s': round(r1['t_first'] - llm['t_first_sentence'], 3) if r1['t_first'] else None,
                           'audio_s': round(secs, 2), 'tts_cost_usd': round(c, 6), 'chunks': r1.get('chunks'),
                           'chars': r1['chars'] + (r2['chars'] if r2 else 0),
                           'retries': (r1.get('retries') or []) + ((r2 or {}).get('retries') or []) or None,
                           'mode': r1.get('mode'), 'stream_error': r1.get('stream_error')}
            rec['cost_usd_llm_plus_%s_tts' % vendor] = round(llm_cost + c, 6)
            turn_cost += c
            if pcm:
                write_wav(os.path.join(outdir, '%s-%s.wav' % (ut['id'], vendor)), pcm, r1['sr'])
            if r1['t_first']:
                play[vendor] = (r1['t_first'], secs)
        total += turn_cost
        log.write(rec)
        print('%s %s stt=%s llm1=%s %s' % (
            name, ut['id'], rec.get('stt_final_after_end_s'), rec.get('llm_first_sentence_after_final_s'),
            ' '.join('%s=%s' % (v, (rec.get(v) or {}).get('latency_s')) for v in vendors)), flush=True)
        # the friend waits until the reply has played; Han Aim when it answered, otherwise the first voice that did
        lead = next((v for v in ['elevenlabs'] + vendors if v in play), None)
        if lead:
            t_first_audio, play_s = play[lead]
            await asyncio.sleep(max(0.0, t_first_audio + play_s - mono()) + GAP_AFTER_REPLY)
        else:
            await asyncio.sleep(GAP_AFTER_REPLY)
        if spent['usd'] + total > MAX_USD:
            log.write({'note': 'stopped at the cost cap', 'cap_usd': MAX_USD})
            break
    session_s = mono() - session_t0
    await mic.stop()
    if stt_kind == 'openai':
        stt_minutes = mic.sent_bytes / 2 / 24000 / 60
        await stt.ws.close()
        stt_cost = stt_minutes * PRICES['gpt-live-transcribe']['per_min']
        stt_desc = 'gpt-live-transcribe, client commit 700 ms after speech'
        billed = {'stt_minutes_streamed': round(stt_minutes, 2)}
    else:
        await stt.close()
        secs = (stt.termination or {}).get('session_duration_seconds') or (mono() - stt.t_open)
        stt_cost = secs / 3600 * PRICES.get(AAI_MODEL, {'per_hour': 0.45})['per_hour']
        stt_desc = '%s, its own end-of-turn detection (mode %s), language_codes ["ko"]' % (AAI_MODEL, AAI_MODE)
        billed = {'stt_session_seconds': round(secs, 1), 'stt_termination': stt.termination,
                  'stt_speech_started': stt.speech_started}
    recv.cancel()
    spent['usd'] += total + stt_cost
    summary = {'engine': name, 'stt': stt_desc, 'stt_settings': variant,
               'llm': 'gpt-6-luna (reasoning_effort none)', 'tts': [tts_label(v) for v in vendors],
               'tts_skipped': skipped, 'tts_timeout_s': TTS_TIMEOUT,
               'connect_s': round(connect_s, 2), 'session_s': round(session_s, 1), 'stt_cost_usd': round(stt_cost, 6),
               'turn_cost_sum_usd': round(total, 6), 'stt_errors': stt.errors[:5], 'mic_errors': mic.errors[:3]}
    summary.update(billed)
    log.summary(summary)


# ------------------------------------------------------------------ check, all, pack

def check():
    names = ['openai.key', 'gemini2.key', 'gemini.key', 'elevenlabs.key', 'assemblyai.key']
    out = {'time': now_iso(), 'python': sys.version.split()[0], 'platform': platform.platform(),
           'ffmpeg': bool(shutil.which('ffmpeg')), 'keys_present': {n: bool(key(n)) for n in names}, 'models': {}}
    if key('openai.key'):
        h = {'Authorization': 'Bearer ' + key('openai.key')}
        for m in ('gpt-realtime-2.1-mini', 'gpt-live-1', 'gpt-live-transcribe', 'gpt-6-luna', 'gpt-4o-mini-tts'):
            out['models'][m] = http_get_status('%s/v1/models/%s' % (OPENAI_HTTP, m), h)
    if key('gemini.key'):
        out['models']['gemini-3.8-flash-lite-tts (AI Studio)'] = http_get_status(
            '%s/v1beta/models/gemini-3.8-flash-lite-tts' % GEMINI_HTTP, {'x-goog-api-key': key('gemini.key')})
    if key('elevenlabs.key'):
        out['models']['elevenlabs voice Han Aim'] = http_get_status(
            '%s/v1/voices/%s' % (ELEVEN_HTTP, HAN_AIM), {'xi-api-key': key('elevenlabs.key')})
    if key('elevenlabs.key'):
        out['models']['elevenlabs agents (list, needs the agents permission)'] = http_get_status(
            '%s/v1/convai/agents?page_size=1' % ELEVEN_HTTP, {'xi-api-key': key('elevenlabs.key')})
    if key('assemblyai.key'):
        out['models']['assemblyai key (transcript list)'] = http_get_status(
            '%s/v2/transcript?limit=1' % AAI_HTTP, {'Authorization': key('assemblyai.key')})
    if key('gemini2.key') and GEMINI_TTS_VIA != 'aistudio':
        r = tts_gemini('안녕, 나 마롱이야.')
        out['models']['gemini-3.8-flash-lite-tts (Vertex global, one sentence)'] = (
            'ok %.2f s audio' % (len(r['pcm']) / 2 / r['sr']) if r['pcm'] else (r['error'] or 'no audio')[:120])
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, 'check.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False))
    return out


def pack():
    """results.tar.gz next to this file. WAV becomes 64 kbps MP3 when ffmpeg exists, to keep the file small."""
    ff = shutil.which('ffmpeg')
    path = os.path.join(HERE, 'results.tar.gz')
    with tarfile.open(path, 'w:gz') as tar:
        for root, _, files in os.walk(RESULTS):
            for fn in sorted(files):
                full = os.path.join(root, fn)
                arc = os.path.relpath(full, HERE)
                if fn.endswith('.wav') and ff:
                    mp3 = full[:-4] + '.mp3'
                    p = subprocess.run([ff, '-y', '-loglevel', 'error', '-i', full, '-codec:a', 'libmp3lame',
                                        '-b:a', '64k', mp3])
                    if p.returncode == 0:
                        tar.add(mp3, arcname=arc[:-4] + '.mp3')
                        continue
                tar.add(full, arcname=arc)
    return path


async def run_named(name, prompt, turns, budget_s):
    t0 = mono()
    try:
        if name in S2S:
            await asyncio.wait_for(run_s2s(name, prompt, turns), budget_s)
        elif name == 'cascade':
            await asyncio.wait_for(run_cascade(prompt, turns), budget_s)
        elif name == 'cascade-aai':
            await asyncio.wait_for(run_cascade(prompt, turns, 'assemblyai'), budget_s)
        status = 'ok'
    except Exception as e:
        status = 'failed'
        os.makedirs(os.path.join(RESULTS, name), exist_ok=True)
        with open(os.path.join(RESULTS, name, 'error.txt'), 'w', encoding='utf-8') as f:
            f.write(traceback.format_exc()[-4000:])
        print('%s failed: %r' % (name, e), flush=True)
    return {'name': name, 'status': status, 'seconds': round(mono() - t0, 1)}


RUNS = ('gemini', 'openai', 'live', 'cascade', 'cascade-aai', 'eleven-rt', 'eleven-agent')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('what', help='check | pack | all | one or more of %s, comma-separated' % ','.join(RUNS))
    ap.add_argument('--turns', type=int, default=10)
    a = ap.parse_args()
    names = ['gemini', 'openai', 'live', 'cascade'] if a.what == 'all' else a.what.split(',')
    if a.what not in ('check', 'pack') and any(n not in RUNS for n in names):
        ap.error('unknown run in %r' % a.what)
    os.makedirs(RESULTS, exist_ok=True)
    if a.what == 'check':
        check()
        return
    if a.what == 'pack':
        print(pack())
        return
    prompt, turns = load_inputs()
    turns = turns[:a.turns]
    meta = {'started': now_iso(), 'host_python': sys.version.split()[0], 'runs': [], 'max_usd': MAX_USD}
    if a.what == 'all' or len(names) > 1:
        meta['check'] = check()
    for n in names:
        meta['runs'].append(asyncio.run(run_named(n, prompt, turns, 420)))
        meta['spent_usd_estimate'] = round(spent['usd'], 4)
        if spent['usd'] > MAX_USD:
            meta['stopped'] = 'cost cap'
            break
    meta['finished'] = now_iso()
    with open(os.path.join(RESULTS, 'run-meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(pack())
    with open(os.path.join(RESULTS, 'DONE'), 'w') as f:
        f.write(now_iso() + '\n')
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == '__main__':
    main()
