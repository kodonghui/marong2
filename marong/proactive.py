"""선톡: 1:1 친구가 며칠 조용하면 마롱이가 먼저 한 번 말을 건다(.env 의 PROACTIVE=on 일 때만).
- 누구에게: 카카오 1:1(채널채팅) 방에서 친구의 마지막 말이 PROACTIVE_QUIET_DAYS 일보다 오래됐고, 그 뒤로 선톡을
  아직 안 보낸 방. 친구가 답하기 전에는 다시 보내지 않는다. 친구가 그만하라고 하면 그 방은 끈다(set_proactive).
- 언제: PROACTIVE_HOURS(한국 시각) 안에서 30분마다 확인한다. 대상이 있어도 확인할 때마다 보내지는 않아서
  보내는 시각이 매번 같지 않다. 한 번에 한 명.
- 얼마나: 하루 PROACTIVE_DAILY_MAX 개까지.
- 기록: 보낸 말은 messages 에 마롱이 말로 남기고 meta.proactive=true. 전달에 실패해도 남긴다(같은 방에 다시 시도하지 않게).
- 끄기: .env 를 PROACTIVE=off 로 바꾸고 재시작. 시험으로 한 명에게만 보내기: run.py --proactive <이름|#키>"""
import asyncio
import logging
import random
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from .agent import Agent
from .config import Settings
from .fmt import short_key
from .kakao import send_message, skill_text
from .llm import brief
from .store import Store

log = logging.getLogger("proactive")

CHECK_S = 1800     # 이 간격으로 보낼 친구가 있는지 확인
CHANCE = 0.3       # 대상이 있어도 확인할 때마다 이 확률로만 보냄
CANDIDATES = 5     # 한 번 확인할 때 보는 방 수(오래 조용한 친구부터)


class Proactive:
    def __init__(self, settings: Settings, store: Store, agent: Agent, http: httpx.AsyncClient, room_lock=None,
                 chance: float = CHANCE, rng=random.random):
        self.s = settings
        self.store = store
        self.agent = agent
        self.http = http
        self.room_lock = room_lock or (lambda room_key: asyncio.Lock())  # 봇에서는 답장과 같은 방 잠금을 씀
        self.chance = chance
        self.rng = rng
        self._skip: dict[str, date] = {}  # 오늘 말을 못 만들었거나 저장에 실패한 방(오늘은 다시 안 함)

    async def run(self) -> None:
        start, end = self.s.proactive_hours
        log.info("선톡 켜짐: 1:1 친구가 %d일 조용하면 %d~%d시에 한 번, 하루 최대 %d개",
                 self.s.proactive_quiet_days, start, end, self.s.proactive_daily_max)
        while True:
            await asyncio.sleep(CHECK_S)
            try:
                await self.step()
            except Exception as e:  # DB·API 장애: 다음 확인 때 다시
                log.warning("proactive_step_error %s", brief(e))

    async def step(self, now: datetime | None = None) -> int:
        """한 번 확인하고, 보냈으면(전달 실패 포함) 1."""
        now = now or datetime.now(ZoneInfo(self.s.timezone))
        start, end = self.s.proactive_hours
        if not start <= now.hour < end:
            return 0
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if await self.store.proactive_count(today) >= self.s.proactive_daily_max:
            return 0
        for room in await self.store.proactive_due(self.s.proactive_quiet_days, CANDIDATES):
            if self._skip.get(room["room_key"]) == now.date() or self.rng() >= self.chance:
                continue
            async with self.room_lock(room["room_key"]):
                # 기다리는 동안 친구가 말을 걸었거나 선톡이 나갔으면 보내지 않음
                if not await self.store.proactive_due(self.s.proactive_quiet_days, 1, room_key=room["room_key"]):
                    return 0
                result = await self.deliver(room)
            if result["text"] is None or result.get("saved") is False:
                self._skip[room["room_key"]] = now.date()
            return 1 if result["text"] else 0
        return 0

    async def deliver(self, room: dict, dry: bool = False) -> dict:
        """그 방에 보낼 선톡을 만들어 보내고 저장한다. dry 면 만들기만 한다.
        돌려주는 것: {"text": 만든 말(못 만들면 None), "ok": 전달 성공, "code": 카카오 오류 코드, "saved": 저장 성공}."""
        made = await self.agent.proactive_message(room)
        if made is None:
            return {"text": None, "ok": False, "code": None}
        text, meta = made
        if dry:
            return {"text": text, "ok": None, "code": None}
        ok, code = await send_message(self.http, self.s, skill_text(text), user_key=room["user_key"])
        log.info("선톡 room=%s ok=%s code=%s len=%d", short_key(room["room_key"]), ok, code, len(text))
        saved = True
        try:
            await self.store.add_message(room["room_key"], "assistant", text,
                                         meta={**meta, "proactive": True, "delivered": ok, "send_code": code})
            self.agent.on_saved()
        except Exception as e:  # 저장을 못 하면 다음 확인 때 또 보낼 수 있어서 오늘은 이 방을 건너뜀
            saved = False
            log.error("db_error %s", brief(e))
        return {"text": text, "ok": ok, "code": code, "saved": saved}
