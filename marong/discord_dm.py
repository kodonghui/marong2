"""Discord Gateway transport for private, explicitly linked Marong accounts."""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
import logging
from zoneinfo import ZoneInfo

import discord

from .agent import Agent, Incoming
from .proactive import PART_GAP_S, Proactive, parts, schedule, slot

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


@dataclass
class DiscordIncoming(Incoming):
    proactive_preference: bool | None = None


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
        return []  # Identity and opt-in never change on model output.

    def _system(self, situation):
        return super()._system(
            situation + "\n\n지금은 디스코드에서 마롱이와 하는 개인 DM이야. 이름을 바꾸거나 다른 친구의 기록을 "
            "찾아 주겠다고 말하지 마. 친구처럼 바로 대화하고, 사용법이나 선톡 설정을 먼저 설명하지 마. "
            "먼저 말 걸 때에는 잠금 화면에 보여도 괜찮은 가벼운 이야기만 하고, 개인적인 내용은 인용하지 마."
        )

    async def _reply(self, msg: DiscordIncoming, person, user_id, text, timeout, use_memory=True, held=None):
        if msg.proactive_preference is False:
            return "응, 먼저 연락하는 건 멈출게.", {}
        opening = self.first_replies.get(str((person or {}).get("friend_id")))
        if opening and use_memory and user_id is not None and not await self.store.has_delivered_reply(msg.room_key):
            return opening, {}
        if msg.proactive_preference is True:
            return "응, 나도 먼저 톡할게 🌰", {}
        if text in GUIDE:
            link = await self.store.link(msg.user_key.removeprefix("discord-user:"))
            schedule_text = (f"먼저 톡은 한국 시간 {link['start_hour']:02d}:00~{link['end_hour']:02d}:00에 "
                             f"하루 최대 {link['per_day']}번이야. " if link else "")
            return ("여기서 평소처럼 말 걸어 줘. 이 대화는 연구용 시트에 기록돼. " + schedule_text
                    + "원하면 ‘먼저 톡해 줘’, 그만 받으려면 ‘선톡 끄기’라고 말해 줘."), {}
        return await super()._reply(msg, person, user_id, text, timeout, use_memory, held)


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
                                proactive_preference=preference), reply,
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
