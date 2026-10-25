"""채팅방 이벤트를 받아 마롱이 답을 콜백 API 로 보낸다. 로그에는 대화 내용·카카오 키 원문을 남기지 않는다."""
import asyncio
import logging
from collections import OrderedDict
from pathlib import Path

import httpx

from .agent import Agent, Incoming
from .config import Settings
from .fmt import short_key
from .kakao import send_callback, skill_text

log = logging.getLogger("app")

CALLBACK_TTL_S = 300   # 콜백 토큰은 받은 뒤 5분 동안만 쓸 수 있음
SAFETY_S = 20          # 보내는 데 걸리는 시간·시계 차이 여유


class BotApp:
    def __init__(self, settings: Settings, agent: Agent, http: httpx.AsyncClient):
        self.s = settings
        self.agent = agent
        self.http = http
        self._seen: OrderedDict[str, None] = OrderedDict()  # RESUME 뒤 같은 메시지가 다시 와도 한 번만 답함
        self._locks: dict[str, asyncio.Lock] = {}  # 같은 방의 메시지는 받은 순서대로 처리(room_lock)
        self._arrived = 0
        # (방, 친구) → 그 친구가 가장 최근에 보낸 '답할 말'의 순번(한 친구가 연달아 보낸 말을 묶어 답하기).
        # 다른 친구 말과는 묶지 않음: 이름·공유 설정 같은 도구는 답하는 말을 한 친구에게 걸리기 때문
        self._latest: dict[tuple[str, str], int] = {}

    async def on_dispatch(self, t: str, d: dict) -> None:
        token = d.get("callbackToken")
        if t == "MESSAGE_CREATE":
            await self._message(d, token)
        elif t in ("CHAT_JOIN", "ENTRANCE") and token:
            welcome, quick = self._welcome()
            if welcome:
                await send_callback(self.http, self.s, token, skill_text(welcome, quick))
                log.info("%s 인사 보냄 room=%s", t, short_key(d.get("botGroupKey")))
        # LEAVE 는 callbackToken 이 없어 답장할 수 없음. AD_REWARD 는 쓰지 않음.

    async def _message(self, d: dict, token: str | None) -> None:
        received = asyncio.get_running_loop().time()
        mid = str(d.get("id") or "")
        if mid:
            if mid in self._seen:
                return
            self._seen[mid] = None
            while len(self._seen) > 1000:
                self._seen.popitem(last=False)
        room_key, user_key = d.get("botGroupKey"), d.get("botUserKey")
        if not (room_key and user_key):
            log.warning("botGroupKey·botUserKey 없음 → 건너뜀 id=%s", mid)
            return
        content = str(d.get("content") or "")
        log.info("MESSAGE_CREATE id=%s room=%s user=%s channel=%s len=%d", mid, short_key(room_key),
                 short_key(user_key), d.get("isChannelChatroom"), len(content))
        if not token:
            log.warning("callbackToken 없음 → 답장 불가 id=%s", mid)
            return
        msg = Incoming(room_key=room_key, user_key=user_key, text=content,
                       is_channel=bool(d.get("isChannelChatroom")), kakao_id=mid or None)
        self._arrived += 1
        seq = self._arrived
        if self.agent.answers(msg):
            self._latest[(room_key, user_key)] = seq

        async def send(text: str) -> bool:
            return await send_callback(self.http, self.s, token, skill_text(text))

        async with self.room_lock(room_key):  # 답장까지 묶음: 앞 답이 늦어도 뒤 답이 앞지르지 않음
            reply = await self.agent.handle(msg, send, deadline=received + CALLBACK_TTL_S - SAFETY_S,
                                            superseded=lambda: self._latest.get((room_key, user_key), 0) > seq)
        if reply is not None:
            log.info("reply id=%s len=%d", mid, len(reply))

    def room_lock(self, room_key: str) -> asyncio.Lock:
        """같은 방의 답장·선톡은 한 번에 하나씩(선톡을 만드는 동안 친구가 말하면 선톡을 보낸 뒤에 답함)."""
        return self._locks.setdefault(room_key, asyncio.Lock())

    def _welcome(self) -> tuple[str, list[str]]:
        """welcome.txt: 첫 줄부터 인사말, '---' 아래 줄들은 퀵리플라이 버튼(채널채팅)."""
        p = Path(self.s.welcome_path)
        if not p.exists():
            return "", []
        body, _, buttons = p.read_text(encoding="utf-8").partition("\n---\n")
        quick = [b.strip() for b in buttons.splitlines() if b.strip()]
        return body.strip(), quick
