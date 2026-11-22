"""Read and update the signed-in friend's profile (API-216 and API-217)."""

import asyncio
import os
from pathlib import Path

from aiohttp import web

from .app_chat import Problem
from .app_session import SessionError
from .call_voice import chosen_voice, configured_voices


from .usage import usage_day


class AppProfile:
    def __init__(self, chat, *, character=None, friends=None, google=False, voices=None,
                 voice_samples=None):
        self.chat = chat
        self.features = {"character": bool(character), "friends": bool(friends), "decor": chat.pet_app_settings.decor}
        if chat.pet_app_settings.scene_pictures:
            self.features["scenePictures"] = True
        self.google = google
        self.voices = voices or configured_voices()
        self.voice_samples = Path(voice_samples) if voice_samples else None

    async def who(self, req, *, write=False):
        who = await self.chat._who(req, write=write)
        if who["profile_id"] is None:
            await self.chat.sessions.ensure_profile(who["friend_id"])
        return who

    async def read(self, friend):
        now = self.chat.sessions.now()
        day = usage_day(now)
        record = await self.chat.store._one("""
            SELECT f.name,f.share,p.bot_name,p.voice,p.friend_code,p.tickets,c.id AS character_id,
                   p.usage_unlimited,p.daily_units,p.call_monthly_usd,
                                      c.name AS character_name,c.kind,c.template,c.intro_at,coalesce(u.chat_turns,0) AS chat_turns,
                   coalesce(u.call_seconds,0) AS call_seconds,coalesce(u.images,0) AS images,
                   coalesce(u.units,0) AS units,r.id AS ring_id,r.answer_until
            FROM marong.friends f JOIN marong.friend_profiles p ON p.friend_id=f.id
            LEFT JOIN marong.characters c ON c.id=p.character_id AND c.friend_id=f.id AND c.status='ready'
            LEFT JOIN marong.usage_daily u ON u.friend_id=f.id AND u.day=%s
            LEFT JOIN LATERAL (
                SELECT id,answer_until FROM marong.app_rings
                WHERE friend_id=f.id AND reason='promise' AND status='ringing' AND answer_until>now()
                ORDER BY created_at DESC LIMIT 1
            ) r ON true
            WHERE f.id=%s
        """, (day, friend))
        google = "off"
        if self.google:
            link = await self.chat.store._one(
                "SELECT status FROM marong.google_links WHERE friend_id=%s", (friend,))
            google = "connected" if link and link["status"] == "connected" else "not_connected"
        character = None
        if record["character_id"] is not None:
            character = {"id": record["character_id"], "name": record["character_name"], "kind": record["kind"],
                         "faceUrl": f"/chat/api/characters/{record['character_id']}/images/front",
                         "template": record["template"], "outfit": {"head": None, "body": None, "neck": None},
                         "introMissing": record["intro_at"] is None}
        ringing = None
        if record["ring_id"] is not None:
            ringing = {"ringId": str(record["ring_id"]), "until": record["answer_until"].isoformat()}
        return {"friendName": record["name"], "botName": record["bot_name"], "character": character,
                "voice": record["voice"], "friendCode": record["friend_code"], "share": record["share"],
                "features": self.features, "google": google, "pendingRing": ringing,
                "usageToday": await self.chat.usage.summary(friend, now, day, record)}

    async def get(self, req):
        who = await self.who(req)
        return self.chat._json(200, await self.read(who["friend_id"]))

    async def usage(self, req):
        who = await self.who(req)
        return self.chat._json(200, await self.chat.usage.get(who["friend_id"]))

    async def patch(self, req):
        who = await self.who(req, write=True)
        try:
            data = await self.chat._body(req)
        except Problem as e:
            raise Problem("invalid_input", e.errors) from None
        if not data or data.keys() - {"botName", "voice", "share"}:
            raise Problem("invalid_input")
        if "botName" in data:
            name = data["botName"]
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 12:
                raise Problem("invalid_input", [{"field": "botName", "reason": "bad_length"}])
            data["botName"] = name.strip()
        if "voice" in data and data["voice"] is not None and data["voice"] not in self.voices:
            raise Problem("voice_unknown")
        if "share" in data and type(data["share"]) is not bool:
            raise Problem("invalid_input")
        friend = who["friend_id"]
        async with self.chat.store.pool.connection() as conn, conn.transaction():
            if "botName" in data:
                await conn.execute("""
                    UPDATE marong.friend_profiles SET bot_name=%s,updated_at=now()
                    WHERE friend_id=%s AND bot_name IS DISTINCT FROM %s
                """, (data["botName"], friend, data["botName"]))
            if "voice" in data:
                voice = data["voice"]
                source = "chosen" if voice is not None else None
                await conn.execute("""
                    UPDATE marong.friend_profiles SET voice=%s,voice_source=%s,updated_at=now()
                    WHERE friend_id=%s AND (voice,voice_source) IS DISTINCT FROM (%s,%s)
                """, (voice, source, friend, voice, source))
            if "share" in data:
                await conn.execute("UPDATE marong.friends SET share=%s WHERE id=%s AND share IS DISTINCT FROM %s",
                                   (data["share"], friend, data["share"]))
        return self.chat._json(200, await self.read(friend))

    async def page(self, req):
        try:
            await self.chat._who(req)
        except (Problem, SessionError) as error:
            if error.code not in {"login_required", "unauthenticated"}:
                raise
            raise web.HTTPFound("/chat/login")
        return self.chat.unified_page("voice" if req.path.endswith("/voice") else "profile")

    def voice_file(self, name):
        if not self.voice_samples:
            return None
        for suffix in ("mp3", "ogg", "wav"):
            path = self.voice_samples / f"{name}.{suffix}"
            if path.is_file():
                return path
        return None

    def voice_metadata(self):
        voices = []
        for name in self.voices:
            label = name
            if self.voice_samples:
                try:
                    found = (self.voice_samples / f"{name}.txt").read_text(encoding="utf-8").splitlines()
                    if found and found[0].strip():
                        label = found[0].strip()[:20]
                except (OSError, UnicodeError):
                    pass
            voices.append({"name": name, "label": label, "default": name == chosen_voice(choices=self.voices),
                           "sampleUrl": f"/chat/voices/{name}" if self.voice_file(name) else None})
        return voices

    async def voice_list(self, req):
        await self.who(req)
        return self.chat._json(200, {"voices": await asyncio.to_thread(self.voice_metadata)})

    async def voice_sample(self, req):
        await self.who(req)
        name = req.match_info["name"]
        if name not in self.voices:
            raise Problem("not_found")
        path = await asyncio.to_thread(self.voice_file, name)
        if not path:
            raise Problem("not_found")
        return web.FileResponse(path)

    def register(self, router):
        router.add_get("/chat/me", self.page)
        router.add_get("/chat/me/voice", self.page)
        router.add_get("/chat/api/profile", self.get)
        router.add_patch("/chat/api/profile", self.patch)
        router.add_get("/chat/api/voices", self.voice_list)
        router.add_get("/chat/voices/{name}", self.voice_sample)
