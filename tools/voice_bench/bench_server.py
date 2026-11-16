#!/usr/bin/env python3
"""마롱이 통화 엔진 비교 측정. 마롱이 서버(싱가포르)에서 표준 라이브러리만으로 돌려요.

    python3 -I bench_server.py check     # 키 파일이 있는지(이름만)와 요금 없는 모델 조회
    python3 -I bench_server.py all       # 아래를 차례로 돌리고 results.tar.gz와 results/DONE을 만들어요
    python3 -I bench_server.py gemini    # 지금 통화와 같은 Vertex 설정(gemini-3.8-live, Sulafat, 침묵 700ms)
    python3 -I bench_server.py openai    # gpt-realtime-2.1-mini, marin
    python3 -I bench_server.py live      # gpt-live-1, noeul
    python3 -I bench_server.py cascade   # gpt-live-transcribe -> gpt-6-luna -> Gemini 3.8 Flash-Lite TTS·gpt-4o-mini-tts

같은 가짜 친구(지우)의 10턴 통화 음성을 실제 말하는 속도로 보내고, 말이 끝난 때부터 첫 대답 소리가 올 때까지를
재요. 턴 사이에는 마이크가 계속 무음을 보내고, 대답이 다 '재생'된 뒤 0.6초 있다가 다음 말을 해요.

키는 ~/.config/marong-call/ 의 openai.key, gemini2.key(운영 통화와 같은 Vertex 키), gemini.key(AI Studio)에서
읽기만 하고 출력·저장하지 않아요. sudo를 쓰지 않고, 이 폴더 밖에는 쓰지 않으며, 운영 서비스는 건드리지 않아요.
말 내용은 지어낸 이름(지우, 도윤)의 시험 대본뿐이에요.
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

VERTEX_PROJECT = 'project-bc2d15a4-11c0-476b-ae8'  # tools/vertex_live/server.py
VERTEX_LOCATION = 'us-central1'

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


S2S = {'gemini': (GeminiVertex, 'gemini-3.8-live', 'Sulafat', 'gemini2.key'),
       'openai': (OpenAIRealtime, 'gpt-realtime-2.1-mini', 'marin', 'openai.key'),
       'live': (GPTLive, 'gpt-live-1', 'noeul', 'openai.key')}


async def run_s2s(kind, prompt, turns, timeout=25.0):
    cls, model, voice, keyname = S2S[kind]
    outdir = os.path.join(RESULTS, 's2s-' + kind)
    log = Log(outdir)
    if not key(keyname):
        log.summary({'engine': kind, 'skipped': 'no key file ' + keyname})
        return
    eng = cls(model, voice, prompt)
    t0 = mono()
    await eng.connect()
    recv = asyncio.ensure_future(eng.recv_loop())
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
        if kind == 'live':
            # GPT-Live has no per-turn done event over WebSocket: the reply ends after 1.5 s without audio
            while mono() < deadline and not recv.done():
                await asyncio.sleep(0.05)
                if t.t_first_audio is not None and mono() - t.t_last_audio > 1.5:
                    t.status, t.t_done = 'completed', t.t_last_audio
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


def tts_openai(text, voice='marin'):
    res = {'t_req': mono(), 't_first': None, 'pcm': bytearray(), 'sr': 24000, 'error': None}

    def on_chunk(chunk, t):
        if res['t_first'] is None:
            res['t_first'] = t
        res['pcm'] += chunk
    try:
        http_post_stream(OPENAI_HTTP + '/v1/audio/speech', {'Authorization': 'Bearer ' + key('openai.key')},
                         {'model': 'gpt-4o-mini-tts', 'voice': voice, 'input': text, 'response_format': 'pcm',
                          'instructions': ('한국어 원어민 성인 여성 목소리로, 친한 친구와 전화하듯 다정하고 차분하게 말해. '
                                           '아이 같거나 과장된 톤은 쓰지 마.')}, on_chunk)
    except Exception as e:
        res['error'] = repr(e)[:400]
    if len(res['pcm']) % 2:
        res['pcm'] = res['pcm'][:-1]
    return res


def tts_gemini(text, voice='Sulafat', model='gemini-3.8-flash-lite-tts'):
    res = {'t_req': mono(), 't_first': None, 'pcm': bytearray(), 'sr': 24000, 'error': None, 'usage': None,
           'chunks': 0}
    sse = SSE()

    def on_chunk(chunk, t):
        for data in sse.feed(chunk):
            d = json.loads(data)
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
    hdr = {'x-goog-api-key': key('gemini.key')}
    res['mode'] = 'stream'
    try:
        http_post_stream('%s/v1beta/models/%s:streamGenerateContent?alt=sse' % (GEMINI_HTTP, model), hdr, body,
                         on_chunk)
    except HTTPError as e:
        res['stream_error'] = str(e)[:300]
        res['mode'], res['t_req'] = 'unary', mono()
        raw = bytearray()
        try:
            http_post_stream('%s/v1beta/models/%s:generateContent' % (GEMINI_HTTP, model), hdr, body,
                             lambda c, t: raw.extend(c))
            t = mono()
            on_chunk(b'data: ' + bytes(raw).replace(b'\n', b' ') + b'\n', t)
        except Exception as e2:
            res['error'] = repr(e2)[:400]
    except Exception as e:
        res['error'] = repr(e)[:400]
    return res


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


def cascade_turn(history, user_text, use_gemini):
    """LLM stream; at its first sentence both TTS start at once; the rest is synthesized after for the samples."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    first = {}

    def on_first_sentence(sentence, t):
        first['sentence'], first['t'] = sentence, t
        first['openai'] = pool.submit(tts_openai, sentence)
        if use_gemini:
            first['gemini'] = pool.submit(tts_gemini, sentence)
    llm = llm_turn(history + [{'role': 'user', 'content': user_text}], on_first_sentence)
    rest = llm['text'][len(first.get('sentence', '')):].strip() if first else ''
    out = {'llm': llm, 'sentence': first.get('sentence', ''), 'rest': rest}
    for vendor in ('openai', 'gemini'):
        if vendor in first:
            r1 = first[vendor].result()
            r2 = None
            if rest and not r1['error']:
                r2 = tts_openai(rest) if vendor == 'openai' else tts_gemini(rest)
            out[vendor] = {'first': r1, 'rest': r2}
    pool.shutdown(wait=False)
    return out


async def run_cascade(prompt, turns):
    outdir = os.path.join(RESULTS, 'cascade')
    log = Log(outdir)
    if not key('openai.key'):
        log.summary({'engine': 'cascade', 'skipped': 'no key file openai.key'})
        return
    use_gemini = bool(key('gemini.key'))
    stt = LiveTranscribe()
    t0 = mono()
    await stt.connect()
    recv = asyncio.ensure_future(stt.recv_loop())
    variant = await stt.configure()
    connect_s = mono() - t0
    mic = Mic(stt.send_audio, 24000).start()
    await asyncio.sleep(1.0)
    session_t0 = mono()
    loop = asyncio.get_event_loop()
    history = [{'role': 'system', 'content': prompt}]
    total = 0.0
    for ut in turns:
        t_speech = mono()
        t_end = await mic.say(ut['pcm24'])
        await asyncio.sleep(max(0.0, t_end + VAD_MS / 1000 - mono()))  # a 700 ms end-of-speech detector
        t_commit = mono()
        text, t_final, t_first_delta = await stt.commit_and_wait()
        rec = {'engine': 'cascade', 'turn': ut['id'], 'user_ref': ut['text'], 'user_heard': text,
               'user_cer': cer(ut['refs'], text) if text else None, 'speech_s': round(t_end - t_speech, 2),
               'commit_after_end_s': round(t_commit - t_end, 3),
               'stt_final_after_commit_s': round(t_final - t_commit, 3) if t_final else None,
               'stt_first_delta_after_end_s': round(t_first_delta - t_end, 3) if t_first_delta else None}
        if not text:
            rec['status'] = 'no-transcript'
            log.write(rec)
            continue
        try:
            res = await loop.run_in_executor(None, cascade_turn, history, text, use_gemini)
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
        play_s = 0.0
        t_first_audio_any = None
        for vendor in ('openai', 'gemini'):
            v = res.get(vendor)
            if not v:
                continue
            r1, r2 = v['first'], v['rest']
            pcm = bytes(r1['pcm']) + (bytes(r2['pcm']) if r2 and r2['sr'] == r1['sr'] else b'')
            secs = len(pcm) / 2 / r1['sr']
            tts_cost = (secs / 60 * PRICES['gpt-4o-mini-tts']['per_min_est'] if vendor == 'openai'
                        else gemini_tts_cost(r1) + (gemini_tts_cost(r2) if r2 else 0))
            rec[vendor] = {'error': r1['error'] or (r2 or {}).get('error'),
                           'latency_s': round(r1['t_first'] - t_end, 3) if r1['t_first'] else None,
                           'tts_first_audio_after_request_s': round(r1['t_first'] - r1['t_req'], 3) if r1['t_first'] else None,
                           'tts_first_audio_after_sentence_s': round(r1['t_first'] - llm['t_first_sentence'], 3) if r1['t_first'] else None,
                           'audio_s': round(secs, 2), 'tts_cost_usd': round(tts_cost, 6), 'chunks': r1.get('chunks'),
                           'mode': r1.get('mode'), 'stream_error': r1.get('stream_error')}
            if pcm:
                write_wav(os.path.join(outdir, '%s-%s.wav' % (ut['id'], vendor)), pcm, r1['sr'])
            if vendor == 'openai' and r1['t_first']:
                t_first_audio_any, play_s = r1['t_first'], secs
        rec['cost_usd_llm_plus_openai_tts'] = round(llm_cost + (rec.get('openai') or {}).get('tts_cost_usd', 0), 6)
        rec['cost_usd_llm_plus_gemini_tts'] = round(llm_cost + (rec.get('gemini') or {}).get('tts_cost_usd', 0), 6)
        total += rec['cost_usd_llm_plus_openai_tts'] + (rec.get('gemini') or {}).get('tts_cost_usd', 0)
        log.write(rec)
        print('cascade %s stt=%s llm1=%s openai=%s gemini=%s' % (
            ut['id'], rec['stt_final_after_commit_s'], rec.get('llm_first_sentence_after_final_s'),
            (rec.get('openai') or {}).get('latency_s'), (rec.get('gemini') or {}).get('latency_s')), flush=True)
        if t_first_audio_any:
            await asyncio.sleep(max(0.0, t_first_audio_any + play_s - mono()) + GAP_AFTER_REPLY)
        else:
            await asyncio.sleep(GAP_AFTER_REPLY)
        if spent['usd'] + total > MAX_USD:
            log.write({'note': 'stopped at the cost cap', 'cap_usd': MAX_USD})
            break
    session_s = mono() - session_t0
    await mic.stop()
    stt_minutes = mic.sent_bytes / 2 / 24000 / 60
    await stt.ws.close()
    recv.cancel()
    stt_cost = stt_minutes * PRICES['gpt-live-transcribe']['per_min']
    spent['usd'] += total + stt_cost
    log.summary({'engine': 'cascade', 'stt': 'gpt-live-transcribe, client commit 700 ms after speech',
                 'stt_settings': variant,
                 'llm': 'gpt-6-luna (reasoning_effort none)', 'tts': ['gpt-4o-mini-tts marin',
                 'gemini-3.8-flash-lite-tts Sulafat' if use_gemini else 'gemini skipped: no gemini.key'],
                 'connect_s': round(connect_s, 2), 'session_s': round(session_s, 1),
                 'stt_minutes_streamed': round(stt_minutes, 2), 'stt_cost_usd': round(stt_cost, 6),
                 'turn_cost_sum_usd': round(total, 6), 'stt_errors': stt.errors[:5], 'mic_errors': mic.errors[:3]})


# ------------------------------------------------------------------ check, all, pack

def check():
    names = ['openai.key', 'gemini2.key', 'gemini.key']
    out = {'time': now_iso(), 'python': sys.version.split()[0], 'platform': platform.platform(),
           'ffmpeg': bool(shutil.which('ffmpeg')), 'keys_present': {n: bool(key(n)) for n in names}, 'models': {}}
    if key('openai.key'):
        h = {'Authorization': 'Bearer ' + key('openai.key')}
        for m in ('gpt-realtime-2.1-mini', 'gpt-live-1', 'gpt-live-transcribe', 'gpt-6-luna', 'gpt-4o-mini-tts'):
            out['models'][m] = http_get_status('%s/v1/models/%s' % (OPENAI_HTTP, m), h)
    if key('gemini.key'):
        out['models']['gemini-3.8-flash-lite-tts (AI Studio)'] = http_get_status(
            '%s/v1beta/models/gemini-3.8-flash-lite-tts' % GEMINI_HTTP, {'x-goog-api-key': key('gemini.key')})
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
        status = 'ok'
    except Exception as e:
        status = 'failed'
        os.makedirs(os.path.join(RESULTS, name), exist_ok=True)
        with open(os.path.join(RESULTS, name, 'error.txt'), 'w', encoding='utf-8') as f:
            f.write(traceback.format_exc()[-4000:])
        print('%s failed: %r' % (name, e), flush=True)
    return {'name': name, 'status': status, 'seconds': round(mono() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('what', choices=['check', 'all', 'gemini', 'openai', 'live', 'cascade', 'pack'])
    ap.add_argument('--turns', type=int, default=10)
    a = ap.parse_args()
    os.makedirs(RESULTS, exist_ok=True)
    if a.what == 'check':
        check()
        return
    if a.what == 'pack':
        print(pack())
        return
    prompt, turns = load_inputs()
    turns = turns[:a.turns]
    names = ['gemini', 'openai', 'live', 'cascade'] if a.what == 'all' else [a.what]
    meta = {'started': now_iso(), 'host_python': sys.version.split()[0], 'runs': [], 'max_usd': MAX_USD}
    if a.what == 'all':
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
