"""선톡: 1:1 친구에게 마롱이가 하루에 두어 번 먼저 말을 건다(.env 의 PROACTIVE=on 일 때만).
- 누구에게: 카카오 1:1(채널채팅) 방. 지난 선톡에 친구가 답하지 않았어도 보낸다. 친구가 QUIET_HOURS 시간 안에
  말했으면 이야기 중이라 끼어들지 않고 조용해지면 보낸다. 친구가 그만하라고 하면 그 방은 끈다(set_proactive).
- 언제: PROACTIVE_HOURS(한국 시각)를 PROACTIVE_PER_DAY 칸으로 똑같이 나눠 칸마다 한 번(12~21시를 2칸이면
  12:00~16:30, 16:30~21:00). 정각·30분마다 확인하고, 칸에 남은 확인 횟수로 나눈 확률로 보내서 보내는 시각이 칸 안에
  고루 퍼진다(칸 마지막 확인에선 꼭 보냄). 칸 경계에서 연달아 가지 않게 지난 선톡에서 칸 반 길이가 지나야 보낸다.
- 얼마나: 모든 친구를 합쳐 하루 PROACTIVE_DAILY_MAX 개까지.
- 기록: 보낸 말은 messages 에 마롱이 말로 남기고 meta.proactive=true. 전달에 실패해도 남긴다(같은 칸에 다시 시도하지
  않게). 친구가 마지막으로 말한 뒤로 전달 실패가 두 번이면(차단 등) 친구가 다시 말할 때까지 쉰다.
- 끄기: .env 를 PROACTIVE=off 로 바꾸고 재시작. 시험으로 한 명에게만 보내기: run.py --proactive <이름|#키>"""
import asyncio
import logging
import math
import random
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .agent import Agent
from .config import Settings
from .fmt import short_key
from .kakao import send_message, skill_text
from .llm import brief
from .store import Store

log = logging.getLogger("proactive")

CHECK_S = 1800     # 이 간격(한국 시각 정각·30분)으로 보낼 친구가 있는지 확인
CANDIDATES = 5     # 한 번 확인할 때 보는 방 수(오래 조용한 친구부터)
QUIET_HOURS = 1    # 친구가 이만큼(시간) 조용해야 보냄(이야기 중이면 안 끼어듦)


def slot(now: datetime, hours: tuple[int, int], per_day: int) -> tuple[datetime, datetime] | None:
    """now 가 든 칸(시작, 끝): hours(한국 시각 시작·끝 시)를 per_day 칸으로 똑같이 나눈 것. 시간 밖이면 None."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    first, last = day + timedelta(hours=hours[0]), day + timedelta(hours=hours[1])
    if not first <= now < last:
        return None
    size = (last - first) / per_day
    k = min((now - first) // size, per_day - 1)
    return first + k * size, (last if k == per_day - 1 else first + (k + 1) * size)


class Proactive:
    def __init__(self, settings: Settings, store: Store, agent: Agent, http: httpx.AsyncClient, room_lock=None,
                 rng=random.random):
        self.s = settings
        self.store = store
        self.agent = agent
        self.http = http
        self.room_lock = room_lock or (lambda room_key: asyncio.Lock())  # 봇에서는 답장과 같은 방 잠금을 씀
        self.rng = rng
        self._skip: dict[str, datetime] = {}  # 방 → 칸 시작: 그 칸에 말을 못 만들었거나 저장에 실패함(그 칸엔 다시 안 함)

    async def run(self) -> None:
        start, end = self.s.proactive_hours
        log.info("선톡 켜짐: 1:1 친구에게 하루 %d번쯤 %d~%d시에(답이 없어도 보냄, %d시간 안에 말했으면 기다림), 하루 최대 %d개",
                 self.s.proactive_per_day, start, end, QUIET_HOURS, self.s.proactive_daily_max)
        while True:
            await asyncio.sleep(CHECK_S - time.time() % CHECK_S)  # 정각·30분에 맞춰 확인
            try:
                await self.step()
            except Exception as e:  # DB·API 장애: 다음 확인 때 다시
                log.warning("proactive_step_error %s", brief(e))

    async def step(self, now: datetime | None = None) -> int:
        """한 번 확인하고 보낸 수(전달 실패 포함)."""
        now = now or datetime.now(ZoneInfo(self.s.timezone))
        found = slot(now, self.s.proactive_hours, self.s.proactive_per_day)
        if found is None:
            return 0
        begin, end = found
        # 시각은 DB 시계에서 거꾸로 잰 길이로 넘긴다. 이번 칸이나 칸 반 길이 안에 보냈으면 안 보냄(칸 경계에서 연달아 안 가게)
        recent = max(now - begin, (end - begin) / 2)
        quiet = timedelta(hours=QUIET_HOURS)
        today = now - now.replace(hour=0, minute=0, second=0, microsecond=0)
        # 칸에 남은 확인 횟수로 나눈 확률: 보내는 시각이 칸 안에 고루 퍼지고, 칸 마지막 확인에선 꼭 보냄
        chance = 1 / max(1, math.ceil((end - now) / timedelta(seconds=CHECK_S)))
        sent = 0
        for room in await self.store.proactive_due(quiet, recent, CANDIDATES):
            if self._skip.get(room["room_key"]) == begin or self.rng() >= chance:
                continue
            if await self.store.proactive_count(today) >= self.s.proactive_daily_max:
                break
            async with self.room_lock(room["room_key"]):
                # 기다리는 동안 친구가 말을 걸었거나 선톡이 나갔으면 보내지 않음
                if not await self.store.proactive_due(quiet, recent, 1, room_key=room["room_key"]):
                    continue
                result = await self.deliver(room)
            if result["text"] is None or result.get("saved") is False:
                self._skip[room["room_key"]] = begin
            if result["text"]:
                sent += 1
        return sent

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
        except Exception as e:  # 저장을 못 하면 다음 확인 때 또 보낼 수 있어서 이번 칸은 이 방을 건너뜀
            saved = False
            log.error("db_error %s", brief(e))
        return {"text": text, "ok": ok, "code": code, "saved": saved}
