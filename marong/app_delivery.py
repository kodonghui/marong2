"""Reminders and Marong's own calls by the D18 path: the app when the friend has a phone for it, else the Discord DM
(docs/app-chat.md SPEC-119, docs/app-ring.md SPEC-130, SPEC-138). Mixed into DiscordReminders, which provides
self.store, client, agent, app (AppPush or None), tz, origin and rng."""
from datetime import timedelta
import logging

import discord

from .app_push import REMINDER, TALK
from .llm import brief
from .schedules import LATE_LIMIT, LATE_PREFIX, reminder_text
from .style import tidy

log = logging.getLogger("marong.discord")

LATE_RING = timedelta(minutes=5)         # a call promise handled later than this gets a sorry note instead (REQ-131)
ANSWER_APP = timedelta(minutes=5)        # a call started within this after the ring is Marong's call (REQ-127)
ANSWER_DISCORD = timedelta(minutes=10)   # the same for the Discord path (REQ-128)
RING_LATE_TEXT = LATE_PREFIX + "약속한 전화를 제때 못 걸었어. 지금 통화할 수 있으면 전화 줘 📞"
RING_DISCORD_TEXT = "약속한 통화 시간이야! 📞"
RING_LINK = "여기서 받아 줘: {origin}/?ring={ring}"
MISSED_LINES = (
    "전화했는데 바빴나 봐! 편할 때 전화 줘 📞",
    "방금 전화했었어~ 시간 될 때 걸어 줘 😊",
    "약속한 전화 걸었는데 못 받았네! 편할 때 전화해 📞",
)
NOTE_TTL_S = 3600


def reminder_ttl(late: timedelta) -> int:
    """A reminder notification is useless after the three-hour limit: what is left of it, at least a minute."""
    return max(60, int((LATE_LIMIT - late).total_seconds()))


class AppRoutes:
    async def say(self, friend_id: int, channel_id: str | None, text: str, *, kind: str, app_channel: str,
                  ttl_s: int, open_path: str = "/chat/") -> tuple[str, dict]:
        """(sent | failed | later, meta). later: nothing could be tried, because the friend has no phone for the app
        and Discord is away; the caller tries again later without counting a failure."""
        tried = 0
        if self.app is not None and self.app.enabled:
            ok, tried = await self.app.notify(friend_id, kind, text, channel=app_channel, ttl_s=ttl_s,
                                              open_path=open_path)
            if ok:
                return "sent", {"transport": "app", "devices": ok}
        if self.client.available and channel_id:
            from .discord_dm import send_text  # discord_dm mixes this class in
            channel = self.client.get_partial_messageable(int(channel_id), type=discord.ChannelType.private)
            return ("sent" if await send_text(channel, text) else "failed"), {"transport": "discord"}
        return ("failed" if tried else "later"), {}

    async def remind(self, row: dict, text: str, following, meta: dict, *, kind: str = "reminder",
                     app_channel: str = REMINDER, ttl_s: int | None = None, open_path: str = "/chat/") -> int:
        """Send a due schedule row's text by the D18 path, finish the row and keep one record of it."""
        outcome, extra = await self.say(row["friend_id"], row["channel_id"], text, kind=kind, app_channel=app_channel,
                                        ttl_s=ttl_s or reminder_ttl(row["late"]), open_path=open_path)
        if outcome == "later":
            await self.store.release_reminder(row)
            log.info("discord_reminder_later id=%s", row["id"])
            return 0
        ok = outcome == "sent"
        state = await self.store.finish_reminder(row, "sent" if ok else "failed", following)
        if ok or state == "done":  # Keep one record per reminder, not one per retry.
            try:
                await self.store.add_message(row["dm_room"], "assistant", text, meta={
                    **meta, "delivered": ok, "transport": extra.get("transport", "discord"),
                    **({"devices": extra["devices"]} if "devices" in extra else {})})
                self.agent.on_saved()
            except Exception as e:
                log.error("db_error %s", brief(e))
        log.info("discord_reminder_sent id=%s ok=%s state=%s via=%s", row["id"], ok, state, extra.get("transport"))
        return int(ok)


class RingCalls(AppRoutes):
    async def place_call(self, row: dict, late: timedelta, following) -> int:
        """A call promise came due (SPEC-130 ②~⑦). 1 when the phone rang or the Discord invitation went out."""
        base = {"reminder": row["id"], "late_s": int(late.total_seconds())}
        if late > LATE_RING:
            log.info("ring_late")
            return await self.remind(row, RING_LATE_TEXT, following, {**base, "ring": "late"}, kind="missed_call",
                                     app_channel=TALK, ttl_s=NOTE_TTL_S, open_path="/")
        caller = await self.store.call_friend(row["friend_id"])
        if caller is None:  # calls were turned off for this friend: an ordinary reminder
            log.info("ring_not_caller")
            return await self.remind(row, tidy(reminder_text(row, self.tz, late))[0], following, base)
        if await self.store.call_live(caller):
            return await self._ring_skip(row, caller, "busy", following)
        if await self.store.recent_ring(row["friend_id"]):
            return await self._ring_skip(row, caller, "skipped", following)
        devices = await self.app.ring_devices(row["friend_id"])
        if not devices and not (self.client.available and row["channel_id"]):
            await self.store.release_reminder(row)  # Discord is away and nothing can ring: try again shortly
            log.info("ring_later")
            return 0
        ring = await self.store.ring_add(row, caller, "app" if devices else "discord", "ringing",
                                         ANSWER_APP if devices else ANSWER_DISCORD)
        if ring is None:  # another promise of this friend is ringing right now
            return await self._ring_skip(row, caller, "skipped", following)
        if devices:
            accepted = await self.app.ring(devices, ring["id"])
            if accepted:
                await self.store.ring_update(ring["id"], devices=accepted)
                await self.store.finish_reminder(row, "sent", following)
                log.info("ring_sent devices=%d", accepted)
                return 1
            await self.store.ring_update(ring["id"], via="discord", answer_for=ANSWER_DISCORD)
        return await self._ring_discord(row, ring["id"], following)

    async def _ring_skip(self, row, caller, status, following) -> int:
        await self.store.ring_add(row, caller, "app", status, timedelta(0))
        await self.store.finish_reminder(row, "sent", following)
        log.info("ring_%s", status)
        return 0

    async def _ring_discord(self, row, ring_id: str, following) -> int:
        """No phone could ring: invite the friend to call from the Discord DM (FL-112)."""
        text = (row["say"] or RING_DISCORD_TEXT) + "\n" + RING_LINK.format(origin=self.origin, ring=ring_id)
        ok = False
        if self.client.available and row["channel_id"]:
            from .discord_dm import send_text
            channel = self.client.get_partial_messageable(int(row["channel_id"]), type=discord.ChannelType.private)
            ok = await send_text(channel, text)
        if not ok:
            await self.store.ring_update(ring_id, failed=True)
        state = await self.store.finish_reminder(row, "sent" if ok else "failed", following)
        if ok or state == "done":
            try:
                await self.store.add_message(row["dm_room"], "assistant", text, meta={
                    "reminder": row["id"], "ring": ring_id, "delivered": ok, "transport": "discord"})
                self.agent.on_saved()
            except Exception as e:
                log.error("db_error %s", brief(e))
        log.info("ring_discord ok=%s state=%s", ok, state)
        return int(ok)

    async def sweep_rings(self) -> int:
        """Rings nobody answered in time become missed; an app ring gets one short note by the D18 path (SPEC-138).
        A Discord invitation already said everything. A note that cannot be sent is not tried again."""
        noted = 0
        for ring in await self.store.rings_missed():
            log.info("ring_missed via=%s", ring["via"])
            if ring["via"] != "app":
                continue
            target = await self.store.dm_target(ring["friend_id"])
            text = MISSED_LINES[int(self.rng() * len(MISSED_LINES)) % len(MISSED_LINES)]
            outcome, extra = await self.say(ring["friend_id"], target and target["channel_id"], text,
                                            kind="missed_call", app_channel=TALK, ttl_s=NOTE_TTL_S, open_path="/")
            if outcome != "sent" or not target:
                log.info("ring_missed_note_failed")
                continue
            try:
                await self.store.add_message(target["room_key"], "assistant", text, meta={
                    "ring": ring["id"], "missed": True, "delivered": True, **extra})
                self.agent.on_saved()
            except Exception as e:
                log.error("db_error %s", brief(e))
            noted += 1
        return noted
