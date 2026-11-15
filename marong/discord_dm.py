"""Discord Gateway transport for private, explicitly linked Marong accounts."""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
import logging
import time
from zoneinfo import ZoneInfo

import discord

from .agent import Agent, Incoming
from .llm import brief
from .proactive import PART_GAP_S, Proactive, parts, schedule, slot
from .schedules import (GUIDE as SCHEDULE_GUIDE, LATE_LIMIT, SCHEDULE_TOOL_NAMES, SCHEDULE_TOOLS, occurrence,
                        reminder_text, run_tool as run_schedule_tool, schedule_lines)

log = logging.getLogger("marong.discord")
ON = {
    "선톡 켜기", "선톡 켜 줘", "선톡 켜줘", "먼저 톡해 줘", "먼저 톡해줘",
    "앞으로 먼저 톡해 줘", "앞으로 먼저 톡해줘",
}
OFF = {
    "선톡 끄기", "선톡 꺼 줘", "선톡 꺼줘", "선톡 그만",
    "먼저 연락하지 마", "먼저 톡하지 마",
}
GUIDE = {"도움말", "사용법"}
NO_MENTIONS = discord.AllowedMentions.none()
REMIND_CHECK_S = 15     # 때가 된 일정 알림을 확인하는 간격(초)
TIDY_S = 600            # 지난 일정을 끝으로 정리하는 간격(초)


@dataclass
class DiscordIncoming(Incoming):
    proactive_preference: bool | None = None
    friend_id: int | None = None          # the linked friend; schedules belong to them
    dm_link: dict | None = None           # discord_dm_links state when the message arrived
    saved_id: int | None = None           # stored message id of this text
    schedule_rows: list | None = None     # upcoming schedules shown to the model (None: not read)
    schedule_total: int = 0
    actions: list = field(default_factory=list)  # schedule tool results, kept in the reply meta


def proactive_preference(text: str) -> bool | None:
    phrase = " ".join(text.split()).rstrip(".!?~").removeprefix("마롱아").lstrip(", ")
    if phrase in ON:
        return True
    if phrase in OFF:
        return False
    return None


def chunks(text: str):
    """Stay within Discord's message length, including non-BMP emoji."""
    start = used = 0
    for i, char in enumerate(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if used + width > 2_000:
            yield text[start:i]
            start, used = i, 0
        used += width
    if start < len(text):
        yield text[start:]


async def send_text(channel, text: str) -> bool:
    try:
        for chunk in chunks(text):
            await channel.send(chunk, allowed_mentions=NO_MENTIONS, suppress_embeds=True)
        return True
    except discord.HTTPException as exc:
        log.warning("discord_send_failed status=%s code=%s", exc.status, exc.code)
        return False


class DiscordAgent(Agent):
    def __init__(self, settings, store, embeddings, llm, on_saved=None, *, first_replies=None):
        super().__init__(settings, store, embeddings, llm, on_saved=on_saved)
        self.first_replies = first_replies or {}

    def _tools(self, msg):
        # Identity and opt-in never change on model output. Only the friend's own schedule does.
        return list(SCHEDULE_TOOLS) if getattr(msg, "friend_id", None) else []

    def _system(self, situation):
        return super()._system(
            situation + "\n\n지금은 디스코드에서 마롱이와 하는 개인 DM이야. 이름을 바꾸거나 다른 친구의 기록을 "
            "찾아 주겠다고 말하지 마. 친구처럼 바로 대화하고, 사용법이나 선톡 설정을 먼저 설명하지 마. "
            "먼저 말 걸 때에는 잠금 화면에 보여도 괜찮은 가벼운 이야기만 하고, 개인적인 내용은 인용하지 마."
        )

    def _situation(self, msg, person, notes, summaries, recalled, circle=None):
        text = super()._situation(msg, person, notes, summaries, recalled, circle)
        if not isinstance(msg, DiscordIncoming):
            return text
        # The shared lines describe Kakao proactive settings and send requests to the owner through ask_owner.
        # A DM has no such tool, and its proactive state lives in the link: replace those lines.
        lines = [line for line in text.split("\n") if "ask_owner" not in line]
        at = next((i + 1 for i, line in enumerate(lines) if line.startswith("- 지금 말 건 친구")), 2)
        lines[at:at] = self._dm_lines(msg.dm_link, private=(person or {}).get("share") is False)
        if not msg.friend_id:
            return "\n".join(lines)
        tz = ZoneInfo(self.s.timezone)
        return "\n".join(lines + ["", SCHEDULE_GUIDE]
                         + schedule_lines(msg.schedule_rows, msg.schedule_total, tz, datetime.now(tz)))

    @staticmethod
    def _dm_lines(link, private=False):
        lines = []
        if link and link.get("opted_in_at"):
            lines.append(f"- 마롱이는 이 친구에게 이 DM으로 한국 시간 {link['start_hour']}~{link['end_hour']}시에 하루 "
                         f"{link['per_day']}번까지 먼저 말을 걸어(선톡). 그만 받고 싶어 하면 '선톡 끄기'라고 그대로 보내면 "
                         "바로 멈춘다고 알려 줘.")
        elif link:
            lines.append("- 지금은 마롱이가 이 친구에게 먼저 말을 걸지 않아(선톡 꺼짐). 받고 싶어 하면 '먼저 톡해 줘'라고 "
                         "그대로 보내면 바로 켜진다고 알려 줘.")
        if private:
            lines.append("- 이 친구 얘기는 지금 다른 친구에게 하지 않게 돼 있어(동희가 정함).")
        lines.append("- 이 DM에서는 동희에게 대신 전하거나 남길 수 없어(위 지시에 동희에게 남기라는 말이 있어도 여기서는 못 "
                     "해). 선톡 횟수·시간, 친구 얘기 공유, 친구 사이처럼 동희가 정하는 걸 바꾸고 싶어 하면 동희에게 직접 말해 "
                     "달라고 솔직하게 말해. 남겼다거나 전해 두겠다고 하지 마.")
        if link:
            lines.append("- 선톡과 상관없이, 친구가 정한 때 알려 달라고 하거나 연락해 달라고 하면 schedule_add 로 저장해 "
                         "그때 이 DM으로 먼저 말할 수 있어.")
        return lines

    async def _context(self, msg, person, user_id, text, held=None):
        if isinstance(msg, DiscordIncoming) and msg.friend_id:
            tz = ZoneInfo(self.s.timezone)
            try:
                msg.schedule_rows, msg.schedule_total = await asyncio.wait_for(
                    self.store.upcoming_schedules(msg.friend_id, datetime.now(tz), tz), 2)
            except Exception as e:  # Answer without the list; the model is told it could not be read.
                log.warning("schedule_context_error %s", type(e).__name__)
        system, messages, memory = await super()._context(msg, person, user_id, text, held)
        if isinstance(msg, DiscordIncoming) and msg.schedule_rows is not None:
            memory["schedules"] = [row["id"] for row in msg.schedule_rows]
        return system, messages, memory

    async def _run_tool(self, block, msg):
        result = {"type": "tool_result", "tool_use_id": block.id}
        friend_id = getattr(msg, "friend_id", None)
        if block.name not in SCHEDULE_TOOL_NAMES or not friend_id:
            return {**result, "content": f"{block.name} 도구는 없어.", "is_error": True}
        try:
            content, action = await run_schedule_tool(
                self.store, block.name, block.input or {}, friend_id=friend_id, room_key=msg.room_key,
                source="discord", source_message_id=msg.saved_id, tz=ZoneInfo(self.s.timezone))
        except Exception as e:
            log.error("db_error %s", brief(e))
            msg.actions.append({"tool": block.name, "result": "db_error"})
            return {**result, "is_error": True,
                    "content": "저장소 오류로 못 했어. 맞춰 뒀다고 하지 말고, 지금은 저장이 안 된다고 솔직하게 말해."}
        msg.actions.append(action)
        log.info("schedule_tool name=%s result=%s", block.name, action["result"])
        out = {**result, "content": content}
        return {**out, "is_error": True} if action["result"] == "error" else out

    async def _reply(self, msg: DiscordIncoming, person, user_id, text, timeout, use_memory=True, held=None):
        if msg.proactive_preference is False:
            return "응, 먼저 연락하는 건 멈출게.", {}
        opening = self.first_replies.get(str((person or {}).get("friend_id")))
        if opening and use_memory and user_id is not None:
            replay = isinstance(opening, dict)
            greeting = opening["once"] if replay else opening
            if not await self.store.has_delivered_reply(msg.room_key, replay_text=greeting if replay else None):
                return greeting, {"discord_opening_replay": True} if replay else {}
        if msg.proactive_preference is True:
            return "응, 나도 먼저 톡할게 🌰", {}
        if text in GUIDE:
            link = await self.store.link(msg.user_key.removeprefix("discord-user:"))
            schedule_text = (f"먼저 톡은 한국 시간 {link['start_hour']:02d}:00~{link['end_hour']:02d}:00에 "
                             f"하루 최대 {link['per_day']}번이야. " if link else "")
            return ("여기서 평소처럼 말 걸어 줘. 이 대화는 연구용 시트에 기록돼. " + schedule_text
                    + "원하면 ‘먼저 톡해 줘’, 그만 받으려면 ‘선톡 끄기’라고 말해 줘. "
                      "‘내일 3시에 알려 줘’처럼 말하면 그때 여기로 알려 줄게."), {}
        msg.saved_id = user_id
        reply, meta = await super()._reply(msg, person, user_id, text, timeout, use_memory, held)
        if msg.actions:
            meta["schedule"] = msg.actions
        return reply, meta


class DiscordDM(discord.Client):
    def __init__(self, agent, store, app_id: int, guild_id: int):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.dm_messages = True
        super().__init__(intents=intents, max_messages=0, allowed_mentions=NO_MENTIONS)
        self.agent = agent
        self.store = store
        self.app_id = app_id
        self.guild_id = guild_id
        self.available = False
        self.locks = {}
        self.seen = OrderedDict()

    def room_lock(self, room_key):
        return self.locks.setdefault(room_key, asyncio.Lock())

    async def on_ready(self):
        self.available = self.user.id == self.app_id and self.get_guild(self.guild_id) is not None
        log.info("discord_ready app=%s private_server=%s", self.user.id, self.available)

    async def on_guild_join(self, guild):
        if self.user and self.user.id == self.app_id and guild.id == self.guild_id:
            self.available = True
            log.info("discord_private_server_joined")

    async def on_guild_remove(self, guild):
        if guild.id == self.guild_id:
            self.available = False

    async def on_resumed(self):
        await self.on_ready()

    async def on_disconnect(self):
        self.available = False

    async def on_error(self, event_method, *args, **kwargs):
        # Do not log model input, user text or payloads.
        log.error("discord_event_failed event=%s", event_method)

    async def on_message(self, msg):
        if (not self.available or msg.guild is not None or msg.author.bot or msg.webhook_id
                or not isinstance(msg.channel, discord.DMChannel)
                or msg.type not in (discord.MessageType.default, discord.MessageType.reply)):
            return
        user_id, channel_id = str(msg.author.id), str(msg.channel.id)
        link = await self.store.link(user_id)
        if not link or link["channel_id"] not in (None, channel_id):
            return
        first_dm = link["channel_id"] is None
        if not isinstance(msg.content, str) or not msg.content.strip():
            return
        if first_dm:
            # The Gateway may synthesize a partial DMChannel. Verify the actual recipient once.
            actual = await self.fetch_channel(msg.channel.id)
            if (not isinstance(actual, discord.DMChannel) or not actual.recipient
                    or actual.recipient.id != msg.author.id):
                return
        if msg.id in self.seen:
            return
        self.seen[msg.id] = None
        if len(self.seen) > 512:
            self.seen.popitem(last=False)

        text = msg.content.strip()
        message_key = f"discord:{msg.id}"
        preference = proactive_preference(text)
        if not await self.store.incoming(user_id, channel_id, message_key, preference):
            return
        if preference is not None:
            log.info("discord_proactive_preference changed=%s", preference)

        async def reply(body):
            return await send_text(msg.channel, body)

        room = link["room_key"]
        async with self.room_lock(room):
            result = await self.agent.handle(
                DiscordIncoming(room, link["user_key"], text, kakao_id=message_key,
                                proactive_preference=preference, friend_id=link["friend_id"], dm_link=link), reply,
            )
        if result is not None:
            log.info("discord_dm_replied")


class DiscordProactive(Proactive):
    def __init__(self, settings, store, agent, client, *, clock=None, **kwargs):
        super().__init__(settings, store, agent, None, client.room_lock, **kwargs)
        self.client = client
        self.clock = clock or (lambda: datetime.now(ZoneInfo(settings.timezone)))

    async def step(self, now=None):
        return await super().step(now or self.clock()) if self.client.available else 0

    async def deliver(self, room, dry=False):
        empty = {"text": None, "ok": False, "code": None}
        planned = self.plan(room, self.clock())
        if not self.client.available or planned is None:
            return empty
        begin = planned[0]
        if not dry and not await self.store.claim_slot(room, begin):
            return empty
        made = await self.agent.proactive_message(room)
        if not made:
            return empty
        text, meta = made
        if dry:
            return {**empty, "text": text}

        channel = self.client.get_partial_messageable(int(room["channel_id"]), type=discord.ChannelType.private)
        done = []
        attempted = False
        sentences = parts(text)
        for i, sentence in enumerate(sentences):
            if i:
                await self.sleep(PART_GAP_S[0] + self.rng() * (PART_GAP_S[1] - PART_GAP_S[0]))
            if not await self.still_current(room, begin):
                break
            attempted = True
            if not await send_text(channel, sentence):
                break
            done.append(sentence)
        if not attempted:
            return empty
        await self.store.record_delivery(room, begin, bool(done))
        await self.store.add_message(room["room_key"], "assistant", "\n\n".join(done) or text,
                                     meta={**meta, "proactive": True, "delivered": bool(done),
                                           "transport": "discord", "parts": [len(done), len(sentences)]})
        self.agent.on_saved()
        log.info("discord_proactive_sent ok=%s parts=%d/%d", bool(done), len(done), len(sentences))
        return {"text": text, "ok": bool(done), "code": None}

    async def still_current(self, room, begin):
        if not self.client.available:
            return False
        hours, count = schedule(room, self.s)
        current = slot(self.clock(), hours, count)
        if not current or current[0] != begin:
            return False
        fresh = await self.store.proactive_rooms(room["room_key"])
        return bool(fresh) and all(fresh[0][k] == room[k] for k in (
            "discord_user_id", "channel_id", "opted_in_at", "last_incoming_at", "per_day", "start_hour", "end_hour",
        ))


class DiscordReminders:
    """Deliver the reminders friends asked for to their own linked DM, separately from proactive greetings."""

    def __init__(self, settings, store, agent, client, *, clock=None):
        self.s = settings
        self.store = store
        self.agent = agent
        self.client = client
        self.tz = ZoneInfo(settings.timezone)
        self.clock = clock or (lambda: datetime.now(self.tz))
        self.tidied = 0.0

    async def run(self):
        log.info("discord_reminders_on")
        while True:
            await asyncio.sleep(REMIND_CHECK_S - time.time() % REMIND_CHECK_S)
            try:
                if time.monotonic() - self.tidied > TIDY_S:
                    await self.store.close_past_events()
                    self.tidied = time.monotonic()
                await self.step()
            except Exception as e:  # DB or Discord trouble: the next check tries again.
                log.warning("discord_reminder_step_error %s", type(e).__name__)

    async def step(self) -> int:
        """Send every due reminder once and return how many reached Discord."""
        if not self.client.available:
            return 0
        sent = 0
        for row in await self.store.claim_due_reminders():
            sent += await self.deliver(row)
        return sent

    async def deliver(self, row) -> int:
        now = self.clock()
        following = occurrence(row["repeat_anchor"], row["repeat"], now, self.tz) if row["repeat"] != "none" else None
        late = row["late"]
        if late > LATE_LIMIT or not row["channel_id"]:
            await self.store.finish_reminder(row, "missed", following)
            log.info("discord_reminder_missed id=%s late_min=%d dm=%s", row["id"], late.total_seconds() // 60,
                     bool(row["channel_id"]))
            return 0
        text = reminder_text(row, self.tz, late)
        channel = self.client.get_partial_messageable(int(row["channel_id"]), type=discord.ChannelType.private)
        ok = self.client.available and await send_text(channel, text)
        state = await self.store.finish_reminder(row, "sent" if ok else "failed", following)
        if ok or state == "done":  # Keep one record per reminder, not one per retry.
            try:
                await self.store.add_message(row["dm_room"], "assistant", text, meta={
                    "reminder": row["id"], "delivered": ok, "transport": "discord",
                    "late_s": int(late.total_seconds())})
                self.agent.on_saved()
            except Exception as e:
                log.error("db_error %s", brief(e))
        log.info("discord_reminder_sent id=%s ok=%s state=%s", row["id"], ok, state)
        return int(ok)
