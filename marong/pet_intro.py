"""Read or store a ready character's intro and choose a first voice (API-250/251)."""

from .app_chat import Problem
from .app_session import one
from .call_voice import chosen_voice
from .character.http import positive_id
from .unified_prompt import clean


PERSONALITIES = frozenset(("활발함", "얌전함", "겁이 많음", "먹보", "애교 많음", "고집 셈", "호기심 많음", "느긋함"))
FIELDS = {"personality", "likes", "dislikes", "ownerCall"}


def validate_intro(body):
    if body.keys() != FIELDS:
        raise Problem("invalid_input")
    traits = body["personality"]
    if (not isinstance(traits, list) or len(traits) > 3 or
            any(not isinstance(value, str) or value not in PERSONALITIES for value in traits) or
            len(set(traits)) != len(traits)):
        raise Problem("invalid_input")
    result = {"personality": traits}
    for name, limit in (("likes", 60), ("dislikes", 60), ("ownerCall", 10)):
        value = body[name]
        if not isinstance(value, str) or len(value) > limit:
            raise Problem("invalid_input")
        result[name] = clean(value, limit)
    if not result["ownerCall"]:
        raise Problem("invalid_input")
    return result


def recommended_voice(kind, personality, rules, choices):
    rule = rules.get(kind, {})
    recommendation = next((rule[trait] for trait in personality if trait in rule), rule.get("default"))
    return chosen_voice(recommendation, choices)


def envelope(character, profile):
    intro_at = character["intro_at"]
    intro = None if intro_at is None else {
        "personality": character["personality"], "likes": character["likes"],
        "dislikes": character["dislikes"], "ownerCall": character["owner_call"],
    }
    return {"intro": intro, "introAt": intro_at.isoformat() if intro_at else None,
            "voice": profile["voice"], "voiceSource": profile["voice_source"] or "none"}


class PetIntro:
    def __init__(self, chat):
        self.chat = chat

    @staticmethod
    async def character(conn, friend, ident, *, lock=False):
        suffix = " FOR UPDATE" if lock else ""
        row = await one(conn, """
            SELECT status, kind, intro_at, personality, likes, dislikes, owner_call
            FROM marong.characters WHERE friend_id=%s AND id=%s
        """ + suffix, (friend, ident))
        if row is None:
            raise Problem("not_found")
        if row["status"] != "ready":
            raise Problem("not_ready")
        return row

    @staticmethod
    async def profile(conn, friend):
        return await one(conn, "SELECT voice, voice_source FROM marong.friend_profiles WHERE friend_id=%s", (friend,))

    async def get(self, req):
        friend = (await self.chat.profile.who(req))["friend_id"]
        ident = positive_id(req.match_info["id"])
        async with self.chat.store.pool.connection() as conn:
            character = await self.character(conn, friend, ident)
            return self.chat._json(200, envelope(character, await self.profile(conn, friend)))

    async def put(self, req):
        friend = (await self.chat.profile.who(req, write=True))["friend_id"]
        ident = positive_id(req.match_info["id"])
        try:
            data = await self.chat._body(req)
        except Problem:
            raise Problem("invalid_input") from None
        intro = validate_intro(data)
        values = (intro["personality"], intro["likes"], intro["dislikes"], intro["ownerCall"])
        async with self.chat.store.pool.connection() as conn, conn.transaction():
            previous = await self.character(conn, friend, ident, lock=True)
            character = await one(conn, """
                UPDATE marong.characters SET personality=%s, likes=%s, dislikes=%s, owner_call=%s,
                    intro_at=coalesce(intro_at, now())
                WHERE id=%s AND (intro_at IS NULL OR (personality,likes,dislikes,owner_call)
                    IS DISTINCT FROM (%s,%s,%s,%s))
                RETURNING personality,likes,dislikes,owner_call,intro_at
            """, (*values, ident, *values))
            if previous["intro_at"] is None:
                voice = recommended_voice(previous["kind"], intro["personality"],
                                         self.chat.pet_app_settings.voice_recommend, self.chat.profile.voices)
                await conn.execute("""
                    UPDATE marong.friend_profiles SET voice=%s, voice_source='recommended', updated_at=now()
                    WHERE friend_id=%s AND voice_source IS DISTINCT FROM 'chosen'
                """, (voice, friend))
            return self.chat._json(200, envelope(character or previous, await self.profile(conn, friend)))

    def register(self, router):
        path = "/chat/api/characters/{id}/intro"
        router.add_get(path, self.get)
        router.add_put(path, self.put)
