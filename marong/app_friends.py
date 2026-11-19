"""Account-scoped friend requests, mutual closeness and a shared read for model context."""

from datetime import datetime, time, timedelta
import re
from weakref import WeakValueDictionary

import asyncio

from aiohttp import web

from .app_chat import Problem
from .app_profile import usage_day
from .app_session import SessionError, one


BASE = "/chat/api/friends"
CODE = re.compile(r"[A-HJ-NP-Za-hj-np-z2-9]{6}")
FRIEND_ID = re.compile(r"[0-9]{1,19}")



class AppFriends:
    def __init__(self, chat):
        self.chat = chat
        self.pool = chat.store.pool
        self.day = None
        self.sent = {}
        self.send_locks = WeakValueDictionary()

    async def identity(self, req, write=False):
        who = await self.chat.profile.who(req, write=write)
        if not self.chat.profile.features["friends"]:
            raise Problem("feature_off" if write else "not_found")
        return who["friend_id"]

    def other(self, req):
        raw = req.match_info["friendId"]
        if not FRIEND_ID.fullmatch(raw) or not 0 < int(raw) < 2**63:
            raise Problem("invalid_input")
        return int(raw)

    @staticmethod
    def request_view(record, other):
        return {"friendId": other, "name": record["name"], "requestedAt": record["requested_at"].isoformat()}

    async def list(self, req):
        friend = await self.identity(req)
        rows = await self.chat.store._all("""
            SELECT f.id AS friend_id,f.name,fs.state,fs.close,fs.requested_by,fs.requested_at,
                   CASE WHEN fs.friend_a=%(friend)s THEN close_a ELSE close_b END AS close_mine
            FROM marong.friendships fs JOIN marong.friends f
                ON f.id=CASE WHEN fs.friend_a=%(friend)s THEN fs.friend_b ELSE fs.friend_a END
            WHERE %(friend)s IN (fs.friend_a,fs.friend_b) AND fs.state IN ('pending','accepted')
            ORDER BY fs.close DESC,coalesce(fs.responded_at,fs.requested_at,fs.created_at),f.id
        """, {"friend": friend})
        result = {"friends": [], "incoming": [], "outgoing": []}
        for row in rows:
            other = row["friend_id"]
            if row["state"] == "accepted":
                result["friends"].append({"friendId": other, "name": row["name"], "close": row["close"],
                                          "closeMine": row["close_mine"]})
            else:
                path = "outgoing" if row["requested_by"] == friend else "incoming"
                result[path].append(self.request_view(row, other))
        return self.chat._json(200, {key: rows[:200] for key, rows in result.items()})

    async def send(self, req):
        friend = await self.identity(req, write=True)
        code = (await self.chat._session_body(req, "friendCode"))["friendCode"]
        if not isinstance(code, str) or not CODE.fullmatch(code):
            raise Problem("invalid_input")
        lock = self.send_locks.setdefault(friend, asyncio.Lock())
        async with lock:
            return await self.create_request(friend, code)

    async def create_request(self, friend, code):
        now = self.chat.sessions.now()
        day = usage_day(now, self.chat.tz)
        since = datetime.combine(day, time(4), self.chat.tz)
        async with self.pool.connection() as conn, conn.transaction():
            target = await one(conn, """
                SELECT p.friend_id,f.name FROM marong.friend_profiles p JOIN marong.friends f ON f.id=p.friend_id
                WHERE p.friend_code=%s
            """, (code.upper(),))
            if not target:
                raise Problem("code_not_found")
            other = target["friend_id"]
            if other == friend:
                raise Problem("self_request")
            a, b = sorted((friend, other))
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"marong.friend-send:{friend}",))
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"marong.friend-pair:{a}:{b}",))
            current = await one(conn, "SELECT state FROM marong.friendships WHERE friend_a=%s AND friend_b=%s FOR UPDATE",
                                (a, b))
            if current and current["state"] in {"accepted", "pending"}:
                raise Problem("already_friends" if current["state"] == "accepted" else "request_exists")
            recorded = await one(conn, """
                SELECT count(*) AS count FROM marong.friendships WHERE requested_by=%s AND requested_at>=%s
            """, (friend, since))
            if self.day != day:
                self.day = day
                self.sent = {}
            count = max(recorded["count"], self.sent.get(friend, 0))
            if count >= 10:
                after = (since + timedelta(days=1) - now).total_seconds()
                raise Problem("request_limit", headers={"Retry-After": str(max(1, int(after)))})
            await conn.execute("""
                INSERT INTO marong.friendships(friend_a,friend_b,requested_by,requested_at,state)
                VALUES (%s,%s,%s,%s,'pending') ON CONFLICT (friend_a,friend_b) DO UPDATE
                SET requested_by=EXCLUDED.requested_by,requested_at=EXCLUDED.requested_at,state='pending',
                    responded_at=NULL,close=false,close_a=false,close_b=false
            """, (a, b, friend, now))
        self.sent[friend] = count + 1
        return self.chat._json(201, {"request": self.request_view({**target, "requested_at": now}, other)})

    async def respond(self, req):
        friend = await self.identity(req, write=True)
        other = self.other(req)
        answer = (await self.chat._session_body(req, "action"))["action"]
        if answer not in ("accept", "decline"):
            raise Problem("invalid_input")
        state = "accepted" if answer == "accept" else "declined"
        a, b = sorted((friend, other))
        row = await self.chat.store._one("""
            UPDATE marong.friendships SET state=%s,responded_at=now()
            WHERE friend_a=%s AND friend_b=%s AND state='pending' AND requested_by=%s RETURNING state
        """, (state, a, b, other))
        if not row:
            raise Problem("not_found")
        return self.chat._json(200, row)

    async def close(self, req):
        friend = await self.identity(req, write=True)
        other = self.other(req)
        close = (await self.chat._session_body(req, "close"))["close"]
        if type(close) is not bool:
            raise Problem("invalid_input")
        a, b = sorted((friend, other))
        side, peer = ("close_a", "close_b") if friend == a else ("close_b", "close_a")
        row = await self.chat.store._one(f"""
            UPDATE marong.friendships SET {side}=%s,close=%s AND {peer}
            WHERE friend_a=%s AND friend_b=%s AND state='accepted' RETURNING close,{side} AS close_mine
        """, (close, close, a, b))
        if not row:
            raise Problem("not_found")
        return self.chat._json(200, {"close": row["close"], "closeMine": row["close_mine"]})

    async def end(self, req):
        friend = await self.identity(req, write=True)
        a, b = sorted((friend, self.other(req)))
        row = await self.chat.store._one("""
            UPDATE marong.friendships SET state='ended',close=false,close_a=false,close_b=false
            WHERE friend_a=%s AND friend_b=%s AND state='accepted' RETURNING state
        """, (a, b))
        if not row:
            raise Problem("not_found")
        return web.Response(status=204)

    async def page(self, req):
        try:
            await self.identity(req)
        except (Problem, SessionError) as error:
            if error.code not in {"login_required", "unauthenticated"}:
                raise
            raise web.HTTPFound("/chat/login") from None
        return self.chat.unified_page("friends")

    def register(self, router):
        router.add_get("/chat/friends", self.page)
        router.add_get(BASE, self.list)
        router.add_post(BASE + "/requests", self.send)
        router.add_post(BASE + "/requests/{friendId}", self.respond)
        router.add_patch(BASE + "/{friendId}", self.close)
        router.add_delete(BASE + "/{friendId}", self.end)
