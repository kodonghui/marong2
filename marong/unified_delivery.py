"""Deliver app messages and scheduled calls to an account's writing room."""

import asyncio
from dataclasses import replace
from datetime import timedelta
import logging

from .app_delivery import (ANSWER_APP, ANSWER_DISCORD, LATE_RING, MISSED_LINES, NOTE_TTL_S, RING_DISCORD_TEXT,
                           RING_LATE_TEXT, RING_LINK, reminder_ttl)
from .app_push import REMINDER, TALK
from .discord_dm import PROACTIVE_APP_TTL_S, PrivateProactive, PrivateReminders
from .proactive import schedule
from .schedules import reminder_text
from .style import tidy
from .topics import HELLO_MISSED_LINES, MISSED_NOTE, picture_set


log = logging.getLogger(__name__)


class UnifiedDelivery:
    def __init__(self, store, push, authentication, on_saved, *, origin=None):
        self.store = store
        self.push = push
        self.authentication = authentication
        self.on_saved = on_saved
        self.origin = origin

    async def notifications_allowed(self, friend_id):
        if self.authentication != "session":
            return True
        target = await self.store.writing_target(friend_id)
        return bool(target and target["has_session"])

    async def say(self, friend_id, text, *, kind, app_channel=TALK, ttl_s=NOTE_TTL_S, open_path="/chat/",
                  app_text=None, meta=None, key=None, notify=True):
        target = await self.store.writing_target(friend_id)
        if target is None or target["room_key"] is None:
            log.info("app_delivery kind=%s result=no_room", kind)
            return None
        saved = await self.store.add_message(target["room_key"], "assistant", text, kakao_id=key, meta={
            **(meta or {}), "delivered": True, "transport": "app",
        })
        if saved is None:
            return "later"
        self.on_saved()
        if notify and self.push.enabled and (self.authentication != "session" or target["has_session"]):
            return await self._notify(friend_id, kind, app_text or text, app_channel, ttl_s, open_path)
        return "later"

    async def _notify(self, friend_id, kind, text, channel, ttl_s, open_path):
        try:
            accepted, _ = await self.push.notify(friend_id, kind, text, channel=channel, ttl_s=ttl_s,
                                                 open_path=open_path)
        except Exception as e:
            log.warning("app_delivery_push_failed kind=%s error=%s", kind, type(e).__name__)
            return "later"
        return "app" if accepted else "later"

    async def tell(self, friend_id, text, meta):
        return await self.say(friend_id, text, kind="system", meta=meta) is not None

    async def call_texts(self, spawn):
        """Persist the call tool's queued text and acknowledge it before attempting a push."""
        while True:
            try:
                await self.send_call_texts(spawn)
            except Exception as e:
                log.warning("app_call_text_step_error error=%s", type(e).__name__)
            await asyncio.sleep(.5)

    async def send_call_texts(self, spawn):
        for row in await self.store._all("""
            SELECT id,friend_id,call_id,text,now()-created_at>=interval '5 seconds' AS expired
            FROM marong.call_texts WHERE status='queued' ORDER BY created_at,id LIMIT 20
        """):
            friend = row["friend_id"]
            target = await self.store.writing_target(friend)
            key = f"app-call-text:{row['id']}"
            previous = (await self.store.app_message(target["room_key"], key)
                        if target and target["room_key"] else None)
            result = "later" if previous else None
            if not previous and not row["expired"]:
                result = await self.say(friend, row["text"], kind="call_text", key=key,
                                        meta={"from_call": str(row["call_id"])}, notify=False)
            if result:
                if not previous:
                    previous = await self.store.app_message(target["room_key"], key)
                await self.store._one("""
                    UPDATE marong.call_texts SET text=NULL,status='sent',via='app',message_id=%s,done_at=now()
                    WHERE id=%s AND status='queued' RETURNING id
                """, (previous["id"], row["id"]))
                if self.push.enabled and await self.notifications_allowed(friend):
                    spawn(self._notify(friend, "call_text", row["text"], TALK, NOTE_TTL_S, "/chat/"))
            else:
                await self.store._one("""
                    UPDATE marong.call_texts SET text=NULL,status='failed',error_code=%s,done_at=now()
                    WHERE id=%s AND status='queued' RETURNING id
                """, ("too_late" if row["expired"] else "no_route", row["id"]))


class AppProactive(PrivateProactive):
    def __init__(self, settings, store, agent, locks, delivery, *, scenes=None, reactions=None, **kwargs):
        super().__init__(settings, store, agent, locks, app=delivery.push, **kwargs)
        self.delivery = delivery
        self.scenes = scenes
        self.reactions = reactions
        self.reaction_friends = set()

    def ready(self):
        return True

    async def can_reach(self, room):
        return True

    def next_slot(self, room, now):
        current = self._slot(room, now)
        (start, end), _ = schedule(room, self.s)
        morning = now.replace(hour=start, minute=0, second=0, microsecond=0)
        if current and current[1] < now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=end):
            return current[1]
        return morning if now < morning else morning + timedelta(days=1)

    def plan(self, room, now):
        if room.get("friend_id") in self.reaction_friends:
            return super(PrivateProactive, self).plan(room, now)
        return super().plan(room, now)

    async def step(self, now=None):
        if not self.reactions:
            return await super().step(now)
        now = now or self.clock()
        rows = await self.reactions.due()
        before = {row["id"]: row for row in rows}
        self.reaction_friends = {row["friend_id"] for row in rows if row["active"]}
        try:
            result = await super().step(now)
            active_rooms = {row["friend_id"]: row for row in await self.store.proactive_rooms()}
            for row in await self.reactions.due():
                if row["id"] not in before:
                    continue
                if not row["active"]:
                    await self.reactions.finish(row, "skipped")
                else:
                    room = active_rooms.get(row["friend_id"], {})
                    await self.reactions.defer(row, self.next_slot(room, now))
            return result
        finally:
            self.reaction_friends = set()

    async def priority(self, room, begin):
        if not self.reactions or room["friend_id"] not in self.reaction_friends:
            return None
        for row in await self.reactions.due(room["friend_id"]):
            if not row["active"]:
                await self.reactions.finish(row, "skipped")
                continue
            item = self.reactions.catalog.items.get(row["item_id"])
            if not item:
                await self.reactions.finish(row, "skipped")
                continue
            try:
                scene = await self.reactions.scene(row)
                if not scene or not await self.still_current(room, begin):
                    return None
                current = await self.reactions.due(room["friend_id"])
                if not any(job["id"] == row["id"] and job["active"] for job in current):
                    await self.reactions.finish(row, "skipped")
                    return None
                made = await self.agent.proactive_message(room, reaction=item.name)
                text = made[0].strip() if made and made[0] else ""
                if not text or len(text) > 60 or "\n" in text:
                    text = f"나 {item.name} 생겼어! 어때?"
                result = await self.delivery.say(row["friend_id"], text, kind="proactive", ttl_s=PROACTIVE_APP_TTL_S,
                    meta={"proactive": True, "reaction": row["item_id"], "scene": str(scene),
                          "sceneAlt": row["name"] + "의 새 차림", "reactionName": item.name},
                    key=f"app-reaction:{row['id']}")
                if result:
                    await self.reactions.finish(row, "sent", scene)
                    await self.store.record_delivery(room, begin, True)
                    return {"text": text, "ok": True, "code": None, "via": "app"}
            except Exception as error:
                log.warning("reaction_send_error friend=%s error=%s", row["friend_id"], type(error).__name__)
            return None
        return None

    async def still_current(self, room, begin, discord=False):
        current = self._slot(room, self.clock())
        if current is None or current[0] != begin:
            return False
        fresh = await self.store.proactive_rooms(room["room_key"])
        return bool(fresh) and all(fresh[0][k] == room[k] for k in (
            "friend_id", "opted_in_at", "last_incoming_at", "per_day", "start_hour", "end_hour",
        ))

    async def _topic(self, room, begin, choice):
        return await super()._topic({**room, "topic_choice": choice}, begin, choice)

    async def _topic_scene(self, room, choice, *, wait):
        if not (self.scenes and choice and choice.at and choice.prefs["pictures"]):
            return None
        try:
            job = await self.scenes.topic_job(room["friend_id"], choice.picture.key, choice.at,
                                              queue=wait and choice.kind != "call")
            if wait and choice.kind != "call":
                return await self.scenes.wait_for_topic(job)
            return job["id"] if job and job["state"] == "done" else None
        except Exception as error:
            log.warning("scene_topic_error friend=%s error=%s", room["friend_id"], type(error).__name__)
            return None

    async def _link_scene(self, choice, scene):
        await self.store._one("UPDATE marong.topic_sends SET scene_picture_id=%s WHERE id=%s RETURNING id",
                              (scene, choice.topic_id))

    async def _send(self, room, begin, text, meta, *, app_text=None, picture=None):
        result = None
        if await self.still_current(room, begin):
            scene = None
            choice = room.get("topic_choice")
            if room.get("wearing_character"):
                meta = {key: value for key, value in meta.items() if key != "topic"}
                app_text = None
                if picture:
                    scene = await self._topic_scene(room, choice, wait=True)
                    if scene:
                        meta["scene"] = str(scene)
                        name = await self.store.app_bot_name(room["friend_id"])
                        meta["sceneAlt"] = picture.alt.replace("마롱이", name or "반려동물 캐릭터")
                        if meta.get("topic_fallback") and name:
                            text = text.replace("마롱이", name)
                    if self.scenes and not await self.still_current(room, begin):
                        return {"text": None, "ok": False, "code": None, "via": None}
            result = await self.delivery.say(room["friend_id"], text, kind="proactive", ttl_s=PROACTIVE_APP_TTL_S,
                                             app_text=app_text, meta={**meta, "proactive": True},
                                             key=f"app-proactive:{begin.isoformat()}")
            await self.store.record_delivery(room, begin, result is not None)
            if result and scene:
                await self._link_scene(choice, scene)
        return {"text": text if result else None, "ok": bool(result), "code": None, "via": "app" if result else None}

    async def _hello(self, room, choice):
        if not await self.delivery.notifications_allowed(room["friend_id"]):
            return False
        if room.get("wearing_character"):
            scene = await self._topic_scene(room, choice, wait=False)
            with_scene = replace(choice, prefs={**choice.prefs, "pictures": False}, scene_id=scene)
            sent = await super()._hello(room, with_scene)
            if sent and scene:
                await self._link_scene(choice, scene)
            return sent
        return await super()._hello(room, choice)


class AppReminders(PrivateReminders):
    def __init__(self, settings, store, agent, delivery, *, scenes=False, **kwargs):
        super().__init__(settings, store, agent, None, app=delivery.push, **kwargs)
        self.delivery = delivery
        self.scenes = scenes

    def ready(self):
        return True

    def has_destination(self, row):
        return bool(row["dm_room"])

    async def remind(self, row, text, following, meta, *, kind="reminder",
                     app_channel=REMINDER, ttl_s=None, open_path="/chat/"):
        result = await self.delivery.say(row["friend_id"], text, kind=kind, app_channel=app_channel,
                                         ttl_s=ttl_s or reminder_ttl(row["late"]), open_path=open_path, meta=meta,
                                         key=f"app-reminder:{row['id']}:{row['remind_at'].isoformat()}")
        await self.store.finish_reminder(row, "sent" if result else "missed", following)
        return int(result is not None)

    async def place_call(self, row, late, following):
        base = {"reminder": row["id"], "late_s": int(late.total_seconds())}
        if late > LATE_RING:
            return await self.remind(row, RING_LATE_TEXT, following, {**base, "ring": "late"}, kind="missed_call",
                                     app_channel=TALK, ttl_s=NOTE_TTL_S, open_path="/")
        caller = await self.store.call_friend(row["friend_id"])
        if caller is None:
            return await self.remind(row, tidy(reminder_text(row, self.tz, late))[0], following, base)
        if await self.store.call_live(caller):
            return await self._ring_skip(row, caller, "busy", following)
        if await self.store.recent_ring(row["friend_id"]):
            return await self._ring_skip(row, caller, "skipped", following)
        devices = (await self.app.ring_devices(row["friend_id"])
                   if await self.delivery.notifications_allowed(row["friend_id"]) else [])
        ring = await self.store.ring_add(row, caller, "app", "ringing", ANSWER_APP if devices else ANSWER_DISCORD)
        if ring is None:
            return await self._ring_skip(row, caller, "skipped", following)
        accepted = 0
        if devices:
            try:
                accepted = await self.app.ring(devices, ring["id"], friend_id=row["friend_id"])
            except Exception as e:
                log.warning("app_ring_push_failed error=%s", type(e).__name__)
            if not accepted:
                await self.store.ring_update(ring["id"], answer_for=ANSWER_DISCORD)
        if accepted:
            await self.store.ring_update(ring["id"], devices=accepted)
        else:
            text = (row["say"] or RING_DISCORD_TEXT) + "\n" + RING_LINK.format(origin=self.origin, ring=ring["id"])
            await self.delivery.say(row["friend_id"], text, kind="call", meta={**base, "ring": ring["id"]},
                                    key=f"app-ring:{ring['id']}", notify=False)
        await self.store.finish_reminder(row, "sent", following)
        return 1

    async def sweep_rings(self):
        noted = 0
        options = {"with_scenes": True} if self.scenes else {}
        for ring in await self.store.rings_missed(**options):
            if ring["via"] != "app":
                continue
            hello = ring["reason"] == "hello"
            found = picture_set() if hello else None
            picture = found.get(ring["topic"]) if found and ring["topic"] else None
            choices = HELLO_MISSED_LINES if hello else MISSED_LINES
            text = picture.missed() if picture else choices[int(self.rng() * len(choices)) % len(choices)]
            meta = {"ring": ring["id"], "missed": True, **({"hello": True} if hello else {})}
            if ring.get("scene_picture_id"):
                meta["scene"] = str(ring["scene_picture_id"])
                name = await self.store.app_bot_name(ring["friend_id"])
                if picture:
                    meta["sceneAlt"] = picture.alt.replace("마롱이", name or "반려동물 캐릭터")
                if name:
                    text = text.replace("마롱이", name)
            elif picture:
                meta["topic"] = picture.key
            result = await self.delivery.say(ring["friend_id"], text, kind="missed_call", meta=meta,
                                             app_text=MISSED_NOTE if picture else None,
                                             key=f"app-missed:{ring['id']}", open_path="/chat/" if hello else "/")
            if result is not None:
                noted += 1
                if hello:
                    await self.store.topic_noted(ring["id"], "app")
        return noted
