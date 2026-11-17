"""선톡: 마롱이가 하루에 몇 번 먼저 말을 건다(.env 의 PROACTIVE=on 일 때만).
- 누구에게: 카카오 1:1(채널채팅) 방(기본 켬)과 관리자가 켠 단체방(기본 꺼짐, rooms.group_proactive). 답이 없으면
  다음 선톡까지 21·45·93시간 기다리고, 네 번 답이 없으면 친구가 다시 말할 때까지 쉰다. 방에서 누가 조금 전
  (QUIET_HOURS 시간, 칸이 짧으면 칸 반 길이)에 마롱이에게 말했으면 이야기 중이라 끼어들지
  않고 조용해지면 보낸다. 관리자가 끈 방에는 보내지 않는다. 2026-11-05 14:30 KST부터 카카오가 1:1 방에 먼저 보내기를
  막아서(사람 키 -876, 방 키 -880) 지금은 단체방으로만 간다(봇을 초대한 단체방은 방 키로 감). 관리자가 한 친구의 1:1
  방에 묶은 단체방(admin merge, 표 버전 9)은 1:1 처럼 그 친구에게 말을 걸고(기억도 1:1 과 같이 씀) 방 키로 보낸다.
- 언제: 방마다 일정(하루 횟수, 한국 시각 시작~끝 시). 방에 정한 일정이 없으면 .env 의 PROACTIVE_PER_DAY·PROACTIVE_HOURS.
  방마다 하루 최대 세 번, 한국 시각 8시부터 22시 전까지만 보낸다.
  일정 시간을 하루 횟수만큼 칸으로 똑같이 나눠 칸마다 한 번(12~21시를 2칸이면 12:00~16:30, 16:30~21:00). 매분 확인하고,
  칸에 남은 확인 횟수로 나눈 확률로 보내서 보내는 시각이 칸 안에 고루 퍼진다(칸 마지막 확인에선 꼭 보냄). 칸 경계에서
  연달아 가지 않게 지난 선톡에서 칸 반 길이가 지나야 보낸다. 일정과 켬·끔은 관리자만 tools/admin.py schedule 로 바꾼다
  (친구가 그만·덜·더 보내 달라고 하면 마롱이는 요청으로만 남김).
- 어떻게: 사람이 카톡을 연달아 보내듯 짧은 말 몇 개(빈 줄로 나눈 덩어리, 많아야 PARTS_MAX 개)를 몇 초 간격으로 따로 보낸다.
  단체방은 방 키(botGroupKey)로, 1:1 방은 방 키로 보내고 카카오가 키 때문에 안 보냈다고(-876·-880) 하면 사람 키로 한 번 더
  (kakao.send_first). 카카오가 1:1 을 어느 키로 다시 열어도 코드를 고치지 않고 다시 간다.
- 얼마나: 모든 친구를 합쳐 하루 PROACTIVE_DAILY_MAX 번까지(연달아 보낸 말 묶음이 한 번).
- 기록: 보낸 말은 messages 에 마롱이 말로 남기고 meta.proactive=true(쓴 키는 meta.send_key). 중간에 전달이 끊기면 받은
  말까지만 남긴다. 첫 말부터 전달에 실패해도 남긴다(같은 칸에 다시 시도하지 않게). 방에서 마지막으로 누가 말한 뒤로 전달
  실패가 두 번이면(차단·내보냄 등) 누가 다시 말할 때까지 쉰다.
- 끄기: .env 를 PROACTIVE=off 로 바꾸고 재시작. 시험으로 한 방에만 보내기: run.py --proactive <이름|#키|#방키>"""
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
from .config import PROACTIVE_AWAKE, PROACTIVE_CAP, Settings, proactive_schedule
from .fmt import short_key
from .kakao import send_first, send_message, skill_text
from .llm import brief
from .store import Store

log = logging.getLogger("proactive")

CHECK_S = 60          # 이 간격(한국 시각 매분)으로 보낼 친구가 있는지 확인
QUIET_HOURS = 1       # 친구가 이만큼(시간) 조용해야 보냄(이야기 중이면 안 끼어듦). 칸이 짧으면 칸 반 길이까지 줄임
PARTS_MAX = 4         # 한 번 말 걸 때 연달아 보내는 말 수 상한
PART_GAP_S = (2, 6)   # 연달아 보낼 때 말 사이 간격(초. 이 사이 무작위)
BACKOFF = tuple(timedelta(days=days) - timedelta(hours=3) for days in (1, 2, 4))


def backoff(unanswered: int) -> timedelta | None:
    """답 없는 선톡 수에 따른 기다림. None 이면 친구가 다시 활동할 때까지 쉼."""
    if unanswered <= 0:
        return timedelta(0)
    return BACKOFF[unanswered - 1] if unanswered <= len(BACKOFF) else None


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
    """방별 일정이나 .env 기본값에 하루 횟수·시간 상한을 적용한다."""
    return proactive_schedule(room.get("start_hour"), room.get("end_hour"), room.get("per_day"),
                              s.proactive_hours, s.proactive_per_day)


def parts(text: str) -> list[str]:
    """빈 줄로 나눈 덩어리를 따로 보낼 말로. PARTS_MAX 개가 넘으면 남은 덩어리를 마지막 말에 모음."""
    out = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()] or [text.strip()]
    if len(out) > PARTS_MAX:
        out = out[:PARTS_MAX - 1] + ["\n".join(out[PARTS_MAX - 1:])]
    return out


class Proactive:
    def __init__(self, settings: Settings, store: Store, agent: Agent, http: httpx.AsyncClient | None, room_lock=None,
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
        (start, end), per_day = schedule({}, self.s)
        log.info("선톡 켜짐: 기본 하루 %d번·%d~%d시, 방마다 최대 하루 %d번·%d~%d시 안, 모든 방 합계 하루 최대 %d번",
                 per_day, start, end, PROACTIVE_CAP, *PROACTIVE_AWAKE, self.s.proactive_daily_max)
        while True:
            await asyncio.sleep(CHECK_S - time.time() % CHECK_S)  # 매분 정각에 맞춰 확인
            try:
                await self.step()
            except Exception as e:  # DB·API 장애: 다음 확인 때 다시
                log.warning("proactive_step_error %s", brief(e))

    def plan(self, room: dict, now: datetime) -> tuple[datetime, float] | None:
        """지금 이 방에 보낼 수 있으면 (칸 시작, 이번 확인에서 보낼 확률). 일정 시간 밖이거나, 친구가 조금 전에 말했거나,
        이번 칸(또는 칸 반 길이) 안에 이미 보냈거나, 전달 실패·답 없는 선톡으로 쉬어야 하면 None."""
        hours, per_day = schedule(room, self.s)
        found = slot(now, hours, per_day)
        if found is None:
            return None
        begin, end = found
        half = (end - begin) / 2
        if room["quiet_for"] < min(timedelta(hours=QUIET_HOURS), half):
            return None
        sent_ago = room["sent_ago"]
        if sent_ago is not None and sent_ago < max(now - begin, half):
            return None
        if room["failures"] >= 2:
            return None
        wait = backoff(room.get("unanswered") or 0)
        if wait is None or (sent_ago is not None and sent_ago < wait):
            return None
        # 칸에 남은 확인 횟수로 나눈 확률: 보내는 시각이 칸 안에 고루 퍼지고, 칸 마지막 확인에선 꼭 보냄
        return begin, 1 / max(1, math.ceil((end - now) / timedelta(seconds=CHECK_S)))

    async def step(self, now: datetime | None = None) -> int:
        """한 번 확인하고 보낸 수(전달 실패 포함)."""
        checked_at = time.monotonic()
        now = now or datetime.now(ZoneInfo(self.s.timezone))
        today = now - now.replace(hour=0, minute=0, second=0, microsecond=0)
        sent = 0
        for room in await self.store.proactive_rooms():
            planned = self.plan(room, now)
            if planned is None or self._skip.get(room["room_key"]) == planned[0] or self.rng() >= planned[1]:
                continue
            if await self.daily_count(today) >= self.s.proactive_daily_max:
                break
            async with self.room_lock(room["room_key"]):
                # 기다리는 동안 친구가 말을 걸었거나 선톡이 나갔으면 보내지 않음
                fresh = await self.store.proactive_rooms(room["room_key"])
                if not fresh or self.plan(fresh[0], now) is None:
                    continue
                (_, end_hour), _ = schedule(fresh[0], self.s)
                end = now.replace(hour=end_hour, minute=0, second=0, microsecond=0)
                result = await self.deliver(fresh[0], send_until=checked_at + (end - now).total_seconds())
            if result["text"] is None or result.get("saved") is False:
                self._skip[room["room_key"]] = planned[0]
            if result["text"]:
                sent += 1
        return sent

    async def daily_count(self, today: timedelta) -> int:
        """오늘(한국 시각 0시부터 today 만큼) 나간 선톡 수. 하루 최대(PROACTIVE_DAILY_MAX)와 비교한다."""
        return await self.store.proactive_count(today)

    async def deliver(self, room: dict, dry: bool = False, *, send_until: float | None = None) -> dict:
        """그 방에 보낼 선톡을 만들어 보내고 저장한다. dry 면 만들기만 한다.
        send_until 은 자동 발송이 끝나는 시각(time.monotonic 기준).
        돌려주는 것: {"text": 만든 말(못 만들면 None), "ok": 한 말이라도 전달됨, "code": 카카오 오류 코드,
        "parts": [전달된 말 수, 만든 말 수], "saved": 저장 성공}."""
        if self.http is None and not dry:
            raise RuntimeError("Kakao delivery requires an HTTP client")
        made = await self.agent.proactive_message(room)
        if made is None:
            return {"text": None, "ok": False, "code": None}
        text, meta = made
        chunks = parts(text)
        if dry:
            return {"text": text, "ok": None, "code": None, "parts": [0, len(chunks)]}
        done: list[str] = []
        code = None
        key = "room"  # 방 키 먼저. 1:1 에서 앞 말이 사람 키로 갔으면 다음 말도 사람 키로
        for i, chunk in enumerate(chunks):
            if i:  # 사람이 연달아 치듯 몇 초 쉬고 다음 말
                await self.sleep(PART_GAP_S[0] + self.rng() * (PART_GAP_S[1] - PART_GAP_S[0]))
            moved = (getattr(self.store, "discord_context_enabled", False)
                     and not await self.store.proactive_rooms(room["room_key"]))
            # 말을 만드는 동안 선톡 시간을 넘겼거나 받는 곳을 옮겼을 수 있음.
            if moved or (send_until is not None and time.monotonic() >= send_until):
                if not done:
                    return {"text": None, "ok": False, "code": None}
                break
            if room["is_channel"]:
                ok, code, key = await send_first(self.http, self.s, skill_text(chunk), room_key=room["room_key"],
                                                 user_key=room["user_key"], prefer=key)
            else:  # 관리자가 켠 단체방: 방 키로만
                ok, code = await send_message(self.http, self.s, skill_text(chunk), group_key=room["room_key"])
            if not ok:
                break
            done.append(chunk)
        ok = bool(done)
        log.info("선톡 room=%s ok=%s code=%s key=%s parts=%d/%d len=%d", short_key(room["room_key"]), ok, code, key,
                 len(done), len(chunks), len(text))
        saved = True
        try:  # 친구가 받은 말까지만 남김(첫 말부터 실패하면 만든 말 전부를 '전달 실패'로)
            await self.store.add_message(room["room_key"], "assistant", "\n\n".join(done) if ok else text,
                                         meta={**meta, "proactive": True, "delivered": ok, "send_code": code,
                                               "send_key": key, "parts": [len(done), len(chunks)]})
            self.agent.on_saved()
        except Exception as e:  # 저장을 못 하면 다음 확인 때 또 보낼 수 있어서 이번 칸은 이 방을 건너뜀
            saved = False
            log.error("db_error %s", brief(e))
        return {"text": text, "ok": ok, "code": code, "parts": [len(done), len(chunks)], "saved": saved}
