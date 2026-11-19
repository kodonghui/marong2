"""Use a fake Google provider to exercise the cookie-protected calendar pages."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer
from marong.app_session import COOKIE
from marong.google_calendar import web_app


ORIGIN = "https://fixture.invalid"


class GoogleSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_signed_in_start_idempotent_disconnect_and_origin(self):
        connected = set()
        notices = []
        sessions = SimpleNamespace(find_session=AsyncMock(return_value={"friend_id": 17, "room_key": "app:fixture"}))

        async def link(friend):
            return {"status": "connected"} if friend in connected else None

        async def finish(state, code, error):
            if error or not code:
                return "denied"
            self.assertEqual(state, "fixture-state")
            connected.add(17)
            return "connected"

        async def disconnect(friend):
            if friend in connected:
                connected.remove(friend)
                return True, True
            return False, True

        async def notify(friend, message, data):
            notices.append((friend, data))

        google = SimpleNamespace(
            store=SimpleNamespace(google_link=link), finish=finish, disconnect=disconnect,
            new_state=lambda _: "fixture-state", consent_url=lambda state: ORIGIN + "/oauth" if state else None,
            notify=notify,
        )
        async with TestClient(TestServer(web_app(google, sessions, authentication="session", origin=ORIGIN))) as http:
            cookie = {"Cookie": f"{COOKIE}=fixture-session"}
            for path in ("/google/", "/google/start?s=legacy"):
                response = await http.get(path, allow_redirects=False)
                self.assertEqual((response.status, response.headers["Location"]), (302, "/chat/login"))
            response = await http.get("/google/start", headers=cookie, allow_redirects=False)
            self.assertEqual(response.headers["Location"], ORIGIN + "/oauth")
            response = await http.get("/google/callback?error=access_denied&state=fixture-state")
            self.assertEqual(response.status, 400)
            self.assertEqual(connected, set())
            response = await http.get("/google/callback?code=fixture&state=fixture-state")
            self.assertEqual(response.status, 200)
            response = await http.get("/google/start", headers=cookie, allow_redirects=False)
            self.assertEqual((response.status, response.headers["Location"]), (303, "/google/"))
            response = await http.get("/google/", headers=cookie)
            self.assertIn("form-action 'self'", response.headers["Content-Security-Policy"])
            self.assertIn("연결 끊기", await response.text())
            response = await http.post("/google/disconnect", headers={**cookie, "Origin": "https://other.invalid"})
            self.assertEqual(response.status, 403)
            self.assertEqual(connected, {17})
            for _ in range(2):
                response = await http.post("/google/disconnect", headers={**cookie, "Origin": ORIGIN},
                                           allow_redirects=False)
                self.assertEqual(response.status, 303)
            self.assertEqual(notices, [(17, {"google": "disconnected"})])
            self.assertEqual(connected, set())


if __name__ == "__main__":
    unittest.main()
