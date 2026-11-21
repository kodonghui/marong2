"""Serve finished scene bytes to the owning account (API-262)."""

from uuid import UUID

from aiohttp import web

from .app_chat import Problem, UUID as ID_PATTERN


class AppScenes:
    def __init__(self, chat):
        self.chat = chat

    async def get(self, req):
        friend = (await self.chat.profile.who(req))["friend_id"]
        raw = req.match_info["id"]
        if not ID_PATTERN.fullmatch(raw.lower()):
            raise Problem("invalid_input")
        row = await self.chat.store._one("""
            SELECT image, format FROM marong.scene_pictures WHERE id=%s AND friend_id=%s AND state='done'
        """, (UUID(raw), friend))
        if not row:
            raise Problem("not_found")
        req["cache"] = "private, max-age=31536000"
        return web.Response(body=row["image"], content_type=f"image/{row['format']}")

    def register(self, router):
        router.add_get("/chat/api/scenes/{id}", self.get)
