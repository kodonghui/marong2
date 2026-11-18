"""TC-416 transport: fixed first audio, retries, goodbye and one shutdown report."""

import asyncio
from pathlib import Path
from uuid import uuid4

from aiohttp import WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from pet_call import FAREWELL, FRAME, GatewayConfig, PetVoice, build_setup, make_app, notice_pcm


PUBLIC = "https://pet.fixture.test"


class Calls:
    def __init__(self):
        self.id = str(uuid4())
        self.verified = self.ticks = 0
        self.closing = []

    async def verify(self, token):
        self.verified += 1
        if token != "a" * 43 or self.verified != 1:
            raise ConnectionError("signature")
        return {"callId": self.id, "voice": "cat", "instructions": "시험용 지시"}

    async def minute(self, ident):
        assert ident == self.id
        self.ticks += 1
        if self.ticks == 1:
            raise ConnectionError("temporarily unavailable")
        return "exhausted"

    async def end(self, ident, reason, missed, transcript):
        assert ident == self.id
        self.closing.append((reason, missed, transcript))


async def scenario():
    cfg = GatewayConfig(PUBLIC, "http://127.0.0.1:8095", "fixture" * 8,
                        "fixture", "us-central1", "DogVoice", "CatVoice")
    calls = Calls()
    recorded = notice_pcm(Path(__file__).with_name("assets") / "pet-call-notice.wav")
    assert 48_000 < len(recorded) < 240_000 and any(recorded)
    audio = b"\x01\x02" * 250
    sent = []

    def voice_factory(socket, config, headers, ident, species, instructions):
        class Fake(PetVoice):
            async def run(self):
                assert self.voice == "CatVoice"
                assert self.setup()["setup"]["systemInstruction"]["parts"] == [{"text": "시험용 지시"}]
                await self.ws.send_json({"type": "ready"})
                await self.save("t1", "user", "합성 글", True, False)
                await asyncio.Event().wait()

            async def emit(self, data):
                await self.ws.send_json(data)

            async def say_goodbye(self):
                await super().say_goodbye()
                sent.append((await self.controls.get())["clientContent"]["turns"][0]["parts"][0]["text"])

        return Fake(socket, config, headers, ident, species, instructions)

    async def instant(seconds):
        assert seconds >= len(audio) / 48000

    app = make_app(cfg, audio, None, voice_factory=voice_factory, calls=calls, delay=instant,
                   interval=.05, grace=.1)
    async with TestClient(TestServer(app)) as client:
        try:
            await client.ws_connect("/pet-call", headers={"Origin": "https://other.test"})
        except WSServerHandshakeError as e:
            assert e.status == 403
        else:
            raise AssertionError("unexpected origin connected")
        async with client.ws_connect("/pet-call", headers={"Origin": PUBLIC}) as socket:
            await socket.send_json({"type": "auth", "token": "a" * 43})
            first = await socket.receive(timeout=2)
            assert first.type == WSMsgType.BINARY
            assert FRAME.unpack(first.data[:24]) == (b"MRG2", 0, 0, 0, 0, 250)
            assert first.data[24:] == audio
            assert await socket.receive_json(timeout=2) == {"type": "audio_end", "epoch": 0, "turn": 0}
            assert await socket.receive_json(timeout=2) == {"type": "ready"}
            assert await socket.receive_json(timeout=2) == {"type": "ending", "reason": "quota"}
            assert await socket.receive_json(timeout=2) == {"type": "ended", "reason": "quota"}
            assert (await socket.receive(timeout=2)).type == WSMsgType.CLOSE
        assert sent == [FAREWELL]
        (reason, missed, captions), = calls.closing
        assert reason == "quota" and missed == 1
        assert len(captions) == 1 and captions[0]["role"] == "member"
        async with client.ws_connect("/pet-call", headers={"Origin": PUBLIC}) as socket:
            await socket.send_json({"type": "auth", "token": "a" * 43})
            assert (await socket.receive(timeout=2)).type == WSMsgType.CLOSE
            assert socket.close_code == 1008
    assert "tools" not in build_setup(cfg, "CatVoice", "시험")()["setup"]


if __name__ == "__main__":
    asyncio.run(scenario())
    print("TC-416 gateway: notice before provider, isolated setup, minute failure recovery and quota close")
