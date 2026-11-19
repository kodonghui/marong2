"""Deliver app messages and scheduled calls to an account's writing room."""

import asyncio
from dataclasses import replace
from datetime import timedelta
import logging

from .app_delivery import (ANSWER_APP, ANSWER_DISCORD, LATE_RING, MISSED_LINES, NOTE_TTL_S, RING_DISCORD_TEXT,
                           RING_LATE_TEXT, RING_LINK, reminder_ttl)
from .app_push import REMINDER, TALK
from .discord_dm import PROACTIVE_APP_TTL_S, PrivateProactive, PrivateReminders
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
    def __init__(self, settings, store, agent, locks, delivery, **kwargs):
        super().__init__(settings, store, agent, locks, app=delivery.push, **kwargs)
        self.delivery = delivery

    def ready(self):
        return True

    async def can_reach(self, room):
        return True

    async def still_current(self, room, begin, discord=False):
        current = self._slot(room, self.clock())
        if current is None or current[0] != begin:
            return False
        fresh = await self.store.proactive_rooms(room["room_key"])
        return bool(fresh) and all(fresh[0][k] == room[k] for k in (
            "friend_id", "opted_in_at", "last_incoming_at", "per_day", "start_hour", "end_hour",
        ))

    async def _send(self, room, begin, text, meta, *, app_text=None, picture=None):
        result = None
        if await self.still_current(room, begin):
            if room.get("wearing_character"):
                meta = {key: value for key, value in meta.items() if key != "topic"}
                app_text = None
            result = await self.delivery.say(room["friend_id"], text, kind="proactive", ttl_s=PROACTIVE_APP_TTL_S,
                                             app_text=app_text, meta={**meta, "proactive": True},
                                             key=f"app-proactive:{begin.isoformat()}")
            await self.store.record_delivery(room, begin, result is not None)
        return {"text": text if result else None, "ok": bool(result), "code": None, "via": "app" if result else None}

    async def _hello(self, room, choice):
        if not await self.delivery.notifications_allowed(room["friend_id"]):
            return False
        if room.get("wearing_character"):
            choice = replace(choice, prefs={**choice.prefs, "pictures": False})
        return await super()._hello(room, choice)


class AppReminders(PrivateReminders):
    def __init__(self, settings, store, agent, delivery, **kwargs):
        super().__init__(settings, store, agent, None, app=delivery.push, **kwargs)
        self.delivery = delivery

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
        for ring in await self.store.rings_missed():
            if ring["via"] != "app":
                continue
            hello = ring["reason"] == "hello"
            found = picture_set() if hello else None
            picture = found.get(ring["topic"]) if found and ring["topic"] else None
            choices = HELLO_MISSED_LINES if hello else MISSED_LINES
            text = picture.missed() if picture else choices[int(self.rng() * len(choices)) % len(choices)]
            meta = {"ring": ring["id"], "missed": True, **({"hello": True} if hello else {})}
            if picture:
                meta["topic"] = picture.key
            result = await self.delivery.say(ring["friend_id"], text, kind="missed_call", meta=meta,
                                             app_text=MISSED_NOTE if picture else None,
                                             key=f"app-missed:{ring['id']}", open_path="/chat/" if hello else "/")
            if result is not None:
                noted += 1
                if hello:
                    await self.store.topic_noted(ring["id"], "app")
        return noted
