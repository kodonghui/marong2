"""Exercise account-scoped call admission and voice snapshots without a Live provider."""

import asyncio
from pathlib import Path
import tempfile
from unittest.mock import patch
import uuid

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer


class FixtureLive:
    def __init__(self, ws, owner, store, person, setup, headers, resume, diagnostics, location, model, voice,
                 client_id, **options):
        self.ws = ws
        self.owner = owner
        self.p = person
        self.client_id = client_id
        self.voice = voice
        self.d = diagnostics
        self.setup = setup
        self.rtc = None
        self.explicit = False
        self.stop = asyncio.Event()
        self.resume = resume

    async def run(self):
        self.d["fixtureOwner"] = self.owner
        setup = self.setup()["setup"]
        assert any("네 이름은 합성밤이야" in part["text"] for part in setup["systemInstruction"]["parts"])
        voice = setup["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]
        await self.ws.send_json({"type": "ready", "voice": voice["voiceName"]})
        async for frame in self.ws:
            if frame.type == WSMsgType.TEXT and frame.json().get("type") == "stop":
                self.explicit = True
                break


async def main():
    with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", return_value=Path(directory)):
        import server

    voices = {1: "Aoede", 2: "Sulafat", 3: "Removed"}

    async def identify(req):
        friend = req.headers.get("X-Fixture-Account")
        if friend is None:
            return None
        index = int(friend)
        return {"owner": f"fixture:{friend}", "principal": server.Principal(index, index, "Fixture"),
                "voice": voices.get(index), "bot_name": "합성밤이"}

    with patch.object(server, "identity", identify), patch.object(server, "LiveSession", FixtureLive), (
        patch.dict("os.environ", {"MARONG_CALL_VOICES": "Sulafat,Aoede,Charon"})
    ), patch.object(server, "CALL_MAX", 3):
        async with TestClient(TestServer(server.app)) as browser:
            origin = str(browser.make_url("/")).rstrip("/")

            def headers(friend):
                return {"Origin": origin, "X-Fixture-Account": str(friend)}

            async def start(friend, expected, client_id=None):
                ws = await browser.ws_connect("/live", params={"client": client_id or str(uuid.uuid4())},
                                              headers=headers(friend))
                first = await ws.receive_json(timeout=2)
                assert first["type"] == expected
                return ws, first

            a, first = await start(1, "ready")
            assert first["voice"] == "Aoede"
            b, first = await start(2, "ready")
            assert first["voice"] == "Sulafat"
            status = await (await browser.get("/status", headers=headers(1))).json()
            assert status["diagnostics"] == {"fixtureOwner": "fixture:1"}
            status = await (await browser.get("/status", headers=headers(2))).json()
            assert status["diagnostics"] == {"fixtureOwner": "fixture:2"}
            status = await (await browser.get("/status", headers=headers(4))).json()
            assert not status["active"] and not status["diagnostics"]
            duplicate, _ = await start(1, "call_busy")
            await duplicate.close()
            c, first = await start(3, "ready")
            assert first["voice"] == "Sulafat"
            excess, _ = await start(4, "calls_full")
            await excess.close()
            voices[1] = "Charon"
            assert (await (await browser.get("/status", headers=headers(1))).json())["voice"] == "Aoede"
            await a.send_json({"type": "stop"})
            await a.close()
            async with asyncio.timeout(2):
                while 1 in server.active_calls:
                    await asyncio.sleep(.01)
            d, _ = await start(4, "ready")
            await d.close()
            async with asyncio.timeout(2):
                while 4 in server.active_calls:
                    await asyncio.sleep(.01)
            a, first = await start(1, "ready")
            assert first["voice"] == "Charon"
            for socket in (a, b, c):
                await socket.close()
            async with asyncio.timeout(2):
                while server.active_calls:
                    await asyncio.sleep(.01)
    print("PASS TC-465 TC-466 TC-468: three slots, account isolation, admission messages, voice snapshots")


if __name__ == "__main__":
    asyncio.run(main())
