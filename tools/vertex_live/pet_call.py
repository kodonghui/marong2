"""Isolated pet WebSocket ingress using the existing voice engine and the pet HTTP API."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import UUID
import wave

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType, web

from live_session import FRAME, LiveSession


FAREWELL = "졸려서 자러 간다고 한두 문장으로 인사하고 마쳐."
CALL_MODEL = "gemini-3.8-live"
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)
IDENTIFIER = re.compile(r"[A-Za-z0-9-]{1,90}", re.ASCII)


@dataclass(frozen=True)
class GatewayConfig:
    origin: str
    backend: str
    secret: str = field(repr=False)
    project: str
    region: str
    dog_voice: str
    cat_voice: str

    @classmethod
    def read(cls, env):
        names = ("PET_ORIGIN", "PET_CALL_BACKEND", "PET_CALL_INTERNAL_SECRET", "PET_CALL_VERTEX_PROJECT",
                 "PET_CALL_VERTEX_REGION", "PET_CALL_DOG_VOICE", "PET_CALL_CAT_VOICE")
        settings = cls(*(env.get(key, "") for key in names))
        try:
            local = urlsplit(settings.backend)
            public = urlsplit(settings.origin)
            if (local.scheme != "http" or local.hostname != "127.0.0.1" or local.port is None
                    or local.path or local.fragment or local.query or local.username is not None
                    or public.scheme != "https" or not public.hostname or public.path or public.query or public.fragment
                    or public.username is not None or not 32 <= len(settings.secret) <= 256
                    or not settings.secret.isascii() or not settings.secret.isprintable()
                    or not all(IDENTIFIER.fullmatch(value) for value in
                               (settings.project, settings.region, settings.dog_voice, settings.cat_voice))):
                raise ValueError
        except ValueError:
            raise ValueError("invalid pet call gateway configuration") from None
        return settings


class InternalCalls:
    def __init__(self, client, config):
        self.client, self.config = client, config

    async def post(self, path, body=None):
        async with self.client.post(self.config.backend + path, json=body, allow_redirects=False,
                                    headers={"X-Pet-Internal": self.config.secret}) as response:
            if response.status == 204:
                return None
            if response.status != 200:
                raise ConnectionError("pet_call_api_unavailable")
            return await response.json()

    async def verify(self, token):
        return await self.post("/internal/calls/verify", {"token": token})

    async def minute(self, call):
        answer = await self.post(f"/internal/calls/{call}/minute")
        if not isinstance(answer, dict) or answer.get("status") not in ("ok", "exhausted"):
            raise ConnectionError("pet_call_api_invalid")
        return answer["status"]

    async def end(self, call, reason, missed, transcript):
        return await self.post(f"/internal/calls/{call}/end", {
            "reason": reason, "unchargedMinutes": min(240, missed), "transcript": transcript,
        })


def notice_pcm(path):
    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 24000
                or not 0 < audio.getnframes() <= 24000 * 8):
            raise ValueError("invalid pet call notice")
        return audio.readframes(audio.getnframes())


async def disclose(ws, pcm, delay=asyncio.sleep):
    for offset in range(0, len(pcm), 8192):
        chunk = pcm[offset:offset + 8192]
        await ws.send_bytes(FRAME.pack(b"MRG2", 0, 0, offset // 8192, offset // 2, len(chunk) // 2) + chunk)
    await ws.send_json({"type": "audio_end", "epoch": 0, "turn": 0})
    await delay(len(pcm) / 48000 + .25)


def build_setup(config, voice, instructions):
    def setup(handle=None, _seed="", _memory=False, **_options):
        resume = {"transparent": True}
        if handle:
            resume["handle"] = handle
        return {"setup": {
            "model": f"projects/{config.project}/locations/{config.region}/publishers/google/models/{CALL_MODEL}",
            "generationConfig": {"responseModalities": ["AUDIO"], "maxOutputTokens": 1024,
                                 "speechConfig": {"languageCode": "ko-KR", "voiceConfig": {
                                     "prebuiltVoiceConfig": {"voiceName": voice},
                                 }}},
            "systemInstruction": {"parts": [{"text": instructions}]},
            "realtimeInputConfig": {"automaticActivityDetection": {"silenceDurationMs": 700, "prefixPaddingMs": 100}},
            "contextWindowCompression": {"triggerTokens": 8192, "slidingWindow": {"targetTokens": 4096}},
            "sessionResumption": resume, "inputAudioTranscription": {}, "outputAudioTranscription": {},
        }}
    return setup


class PetVoice(LiveSession):
    def __init__(self, ws, config, headers, ident, species, instructions):
        voice = config.dog_voice if species == "dog" else config.cat_voice
        super().__init__(ws, ident, None, None, build_setup(config, voice, instructions), headers,
                         {}, {}, config.region, CALL_MODEL, voice, ident, entry_transport="pet")
        self.call_id = ident
        self.final_turns = {}

    async def save(self, key, role, content, finalized, interrupted):
        if finalized and not interrupted and content.strip() and (key in self.final_turns or len(self.final_turns) < 400):
            self.final_turns[key] = {"role": "member" if role == "user" else "pet", "text": content[:1000],
                                     "at": datetime.now(timezone.utc).isoformat()}

    def transcript(self):
        return list(self.final_turns.values())

    async def say_goodbye(self):
        await self.controls.put({"clientContent": {"turns": [{"role": "user", "parts": [{"text": FAREWELL}]}],
                                                    "turnComplete": True}})
        self.available.set()


async def watch_quota(calls, ident, voice, state, *, started, interval=60, grace=30):
    loop = asyncio.get_running_loop()
    deadline = started + interval
    while True:
        await asyncio.sleep(max(0, deadline - loop.time()))
        deadline += interval
        try:
            quota = await calls.minute(ident)
        except (ClientError, TimeoutError, ConnectionError, ValueError):
            state["missed"] += 1
            continue
        if quota != "exhausted":
            continue
        state["reason"] = "quota"
        try:
            async with asyncio.timeout(grace):
                await voice.emit({"type": "ending", "reason": "quota"})
                await voice.say_goodbye()
                await asyncio.sleep(grace)
        except TimeoutError:
            pass
        return


async def report_end(calls, ident, state, transcript):
    for attempt in range(3):
        try:
            await calls.end(ident, state["reason"], state["missed"], transcript)
            return
        except (ClientError, TimeoutError, ConnectionError, ValueError):
            if attempt < 2:
                await asyncio.sleep(.2 * (attempt + 1))
    print("pet_call_end_unavailable", flush=True)


def make_app(config, pcm, headers, *, voice_factory=PetVoice, calls=None, delay=asyncio.sleep, interval=60, grace=30):
    if not pcm or len(pcm) % 2:
        raise ValueError("missing pet call disclosure")
    app = web.Application()

    async def client_state(_app):
        nonlocal calls
        if calls is not None:
            yield
        else:
            async with ClientSession(timeout=ClientTimeout(total=3)) as client:
                calls = InternalCalls(client, config)
                yield

    async def health(_req):
        return web.json_response({"ok": True})

    async def socket(req):
        if req.headers.get("Origin") != config.origin:
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=64000)
        await ws.prepare(req)
        state = {"reason": "error", "missed": 0}
        ident = None
        voice = None
        tasks = []
        try:
            first = await ws.receive(timeout=5)
            data = first.json() if first.type == WSMsgType.TEXT else {}
            token = data.get("token") if isinstance(data, dict) and data.get("type") == "auth" else None
            if not isinstance(token, str) or not TOKEN.fullmatch(token):
                await ws.close(code=1008)
                return ws
            verified = await calls.verify(token)
            ident = str(UUID(verified["callId"]))
            species, instructions = verified["voice"], verified["instructions"]
            if species not in ("dog", "cat") or not isinstance(instructions, str) or not 1 <= len(instructions) <= 20000:
                raise ValueError("invalid call authorization")
            started = asyncio.get_running_loop().time()
            await disclose(ws, pcm, delay)
            voice = voice_factory(ws, config, headers, ident, species, instructions)
            tasks = [asyncio.create_task(voice.run()), asyncio.create_task(
                watch_quota(calls, ident, voice, state, started=started, interval=interval, grace=grace)
            )]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if state["reason"] != "quota" and voice.explicit:
                state["reason"] = "member"
        except (ClientError, TimeoutError, ConnectionError, ValueError, KeyError):
            if ident is None:
                await ws.close(code=1008)
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if ident is not None:
                if not ws.closed:
                    with suppress(ConnectionError, RuntimeError):
                        await ws.send_json({"type": "ended", "reason": state["reason"]})
                await report_end(calls, ident, state, voice.transcript() if voice else [])
            await ws.close()
        return ws

    app.cleanup_ctx.append(client_state)
    app.router.add_get("/healthz", health, allow_head=False)
    app.router.add_get("/pet-call", socket, allow_head=False)
    return app


def main():
    from google.auth import default
    from google.auth.transport.requests import Request

    config = GatewayConfig.read(os.environ)
    bundled_notice = Path(__file__).with_name("assets") / "pet-call-notice.wav"
    audio = notice_pcm(Path(os.environ.get("PET_CALL_NOTICE_WAV", str(bundled_notice))))
    credentials, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credential_lock = asyncio.Lock()

    async def headers():
        async with credential_lock:
            if not credentials.valid:
                await asyncio.to_thread(credentials.refresh, Request())
            return {"Authorization": "Bearer " + credentials.token}

    web.run_app(make_app(config, audio, headers), host="127.0.0.1",
                port=int(os.environ.get("PET_CALL_PORT", "8798")), access_log=None, print=None)


if __name__ == "__main__":
    main()
