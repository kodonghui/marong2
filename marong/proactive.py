"""선톡: 1:1 친구에게 마롱이가 하루에 몇 번 먼저 말을 건다(.env 의 PROACTIVE=on 일 때만).
- 누구에게: 카카오 1:1(채널채팅) 방. 지난 선톡에 친구가 답하지 않았어도 보낸다. 친구가 조금 전(QUIET_HOURS 시간,
  칸이 짧으면 칸 반 길이)에 말했으면 이야기 중이라 끼어들지 않고 조용해지면 보낸다. 친구가 그만하라고 하면 그 방은 끈다.
- 언제: 방마다 일정(하루 횟수, 한국 시각 시작~끝 시). 방에 정한 일정이 없으면 .env 의 PROACTIVE_PER_DAY·PROACTIVE_HOURS.
  일정 시간을 하루 횟수만큼 칸으로 똑같이 나눠 칸마다 한 번(12~21시를 2칸이면 12:00~16:30, 16:30~21:00). 매분 확인하고,
  칸에 남은 확인 횟수로 나눈 확률로 보내서 보내는 시각이 칸 안에 고루 퍼진다(칸 마지막 확인에선 꼭 보냄). 칸 경계에서
  연달아 가지 않게 지난 선톡에서 칸 반 길이가 지나야 보낸다. 일정은 tools/admin.py schedule 로, 친구가 덜(더) 보내 달라고
  하면 마롱이가 set_proactive 의 per_day 로 바꾼다.
- 어떻게: 사람이 카톡을 연달아 보내듯 짧은 말 몇 개(빈 줄로 나눈 덩어리, 많아야 PARTS_MAX 개)를 몇 초 간격으로 따로 보낸다.
- 얼마나: 모든 친구를 합쳐 하루 PROACTIVE_DAILY_MAX 번까지(연달아 보낸 말 묶음이 한 번).
- 기록: 보낸 말은 messages 에 마롱이 말로 남기고 meta.proactive=true. 중간에 전달이 끊기면 친구가 받은 말까지만 남긴다.
  첫 말부터 전달에 실패해도 남긴다(같은 칸에 다시 시도하지 않게). 친구가 마지막으로 말한 뒤로 전달 실패가 두 번이면
  (차단 등) 친구가 다시 말할 때까지 쉰다.
- 끄기: .env 를 PROACTIVE=off 로 바꾸고 재시작. 시험으로 한 명에게만 보내기: run.py --proactive <이름|#키>"""
import asyncio
import logging
import math
import random
import re
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

CHECK_S = 60          # 이 간격(한국 시각 매분)으로 보낼 친구가 있는지 확인
QUIET_HOURS = 1       # 친구가 이만큼(시간) 조용해야 보냄(이야기 중이면 안 끼어듦). 칸이 짧으면 칸 반 길이까지 줄임
PARTS_MAX = 4         # 한 번 말 걸 때 연달아 보내는 말 수 상한
PART_GAP_S = (2, 6)   # 연달아 보낼 때 말 사이 간격(초. 이 사이 무작위)


def slot(now: datetime, hours: tuple[int, int], per_day: int) -> tuple[datetime, datetime] | None:
    """now 가 든 칸(시작, 끝): hours(한국 시각 시작·끝 시)를 per_day 칸으로 똑같이 나눈 것. 시간 밖이면 None."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    first, last = day + timedelta(hours=hours[0]), day + timedelta(hours=hours[1])
    if not first <= now < last:
        return None
    size = (last - first) / per_day
    k = min((now - first) // size, per_day - 1)
    return first + k * size, (last if k == per_day - 1 else first + (k + 1) * size)


def schedule(room: dict, s: Settings) -> tuple[tuple[int, int], int]:
    """이 방의 선톡 일정 ((시작 시, 끝 시), 하루 횟수). 방에 정한 값이 없거나 시작이 끝보다 늦으면 .env 값."""
    start, end = room.get("start_hour"), room.get("end_hour")
    hours = (s.proactive_hours[0] if start is None else start, s.proactive_hours[1] if end is None else end)
    if not 0 <= hours[0] < hours[1] <= 24:
        hours = s.proactive_hours
    return hours, room.get("per_day") or s.proactive_per_day


def parts(text: str) -> list[str]:
    """빈 줄로 나눈 덩어리를 따로 보낼 말로. PARTS_MAX 개가 넘으면 남은 덩어리를 마지막 말에 모음."""
    out = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()] or [text.strip()]
    if len(out) > PARTS_MAX:
        out = out[:PARTS_MAX - 1] + ["\n".join(out[PARTS_MAX - 1:])]
    return out


class Proactive:
    def __init__(self, settings: Settings, store: Store, agent: Agent, http: httpx.AsyncClient, room_lock=None,
                 rng=random.random, sleep=asyncio.sleep):
        self.s = settings
        self.store = store
        self.agent = agent
        self.http = http
        self.room_lock = room_lock or (lambda room_key: asyncio.Lock())  # 봇에서는 답장과 같은 방 잠금을 씀
        self.rng = rng
        self.sleep = sleep
        self._skip: dict[str, datetime] = {}  # 방 → 칸 시작: 그 칸에 말을 못 만들었거나 저장에 실패함(그 칸엔 다시 안 함)

    async def run(self) -> None:
        start, end = self.s.proactive_hours
        log.info("선톡 켜짐: 1:1 친구에게 하루 %d번쯤 %d~%d시에(방마다 따로 정한 일정이 있으면 그것), 답이 없어도 보냄, "
                 "조금 전에 말했으면 기다림, 하루 최대 %d번", self.s.proactive_per_day, start, end,
                 self.s.proactive_daily_max)
        while True:
            await asyncio.sleep(CHECK_S - time.time() % CHECK_S)  # 매분 정각에 맞춰 확인
            try:
                await self.step()
            except Exception as e:  # DB·API 장애: 다음 확인 때 다시
                log.warning("proactive_step_error %s", brief(e))

    def plan(self, room: dict, now: datetime) -> tuple[datetime, float] | None:
        """지금 이 방에 보낼 수 있으면 (칸 시작, 이번 확인에서 보낼 확률). 일정 시간 밖이거나, 친구가 조금 전에 말했거나,
        이번 칸(또는 칸 반 길이) 안에 이미 보냈거나, 전달 실패가 두 번이면 None. 시각은 DB 시계에서 거꾸로 잰 길이로 비교."""
        hours, per_day = schedule(room, self.s)
        found = slot(now, hours, per_day)
        if found is None:
            return None
        begin, end = found
        half = (end - begin) / 2
        if room["quiet_for"] < min(timedelta(hours=QUIET_HOURS), half):
            return None
        if room["sent_ago"] is not None and room["sent_ago"] < max(now - begin, half):
            return None
        if room["failures"] >= 2:
            return None
        # 칸에 남은 확인 횟수로 나눈 확률: 보내는 시각이 칸 안에 고루 퍼지고, 칸 마지막 확인에선 꼭 보냄
        return begin, 1 / max(1, math.ceil((end - now) / timedelta(seconds=CHECK_S)))

    async def step(self, now: datetime | None = None) -> int:
        """한 번 확인하고 보낸 수(전달 실패 포함)."""
        now = now or datetime.now(ZoneInfo(self.s.timezone))
        today = now - now.replace(hour=0, minute=0, second=0, microsecond=0)
        sent = 0
        for room in await self.store.proactive_rooms():
            planned = self.plan(room, now)
            if planned is None or self._skip.get(room["room_key"]) == planned[0] or self.rng() >= planned[1]:
                continue
            if await self.store.proactive_count(today) >= self.s.proactive_daily_max:
                break
            async with self.room_lock(room["room_key"]):
                # 기다리는 동안 친구가 말을 걸었거나 선톡이 나갔으면 보내지 않음
                fresh = await self.store.proactive_rooms(room["room_key"])
                if not fresh or self.plan(fresh[0], now) is None:
                    continue
                result = await self.deliver(fresh[0])
            if result["text"] is None or result.get("saved") is False:
                self._skip[room["room_key"]] = planned[0]
            if result["text"]:
                sent += 1
        return sent

    async def deliver(self, room: dict, dry: bool = False) -> dict:
        """그 방에 보낼 선톡을 만들어 보내고 저장한다. dry 면 만들기만 한다.
        돌려주는 것: {"text": 만든 말(못 만들면 None), "ok": 한 말이라도 전달됨, "code": 카카오 오류 코드,
        "parts": [전달된 말 수, 만든 말 수], "saved": 저장 성공}."""
        made = await self.agent.proactive_message(room)
        if made is None:
            return {"text": None, "ok": False, "code": None}
        text, meta = made
        chunks = parts(text)
        if dry:
            return {"text": text, "ok": None, "code": None, "parts": [0, len(chunks)]}
        done: list[str] = []
        code = None
        for i, chunk in enumerate(chunks):
            if i:  # 사람이 연달아 치듯 몇 초 쉬고 다음 말
                await self.sleep(PART_GAP_S[0] + self.rng() * (PART_GAP_S[1] - PART_GAP_S[0]))
            ok, code = await send_message(self.http, self.s, skill_text(chunk), user_key=room["user_key"])
            if not ok:
                break
            done.append(chunk)
        ok = bool(done)
        log.info("선톡 room=%s ok=%s code=%s parts=%d/%d len=%d", short_key(room["room_key"]), ok, code,
                 len(done), len(chunks), len(text))
        saved = True
        try:  # 친구가 받은 말까지만 남김(첫 말부터 실패하면 만든 말 전부를 '전달 실패'로)
            await self.store.add_message(room["room_key"], "assistant", "\n\n".join(done) if ok else text,
                                         meta={**meta, "proactive": True, "delivered": ok, "send_code": code,
                                               "parts": [len(done), len(chunks)]})
            self.agent.on_saved()
        except Exception as e:  # 저장을 못 하면 다음 확인 때 또 보낼 수 있어서 이번 칸은 이 방을 건너뜀
            saved = False
            log.error("db_error %s", brief(e))
        return {"text": text, "ok": ok, "code": code, "parts": [len(done), len(chunks)], "saved": saved}
