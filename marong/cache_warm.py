"""프롬프트 캐시 유지: 친구 말이 뜸할 때도 Claude 캐시(도구·성격 앞부분)가 식지 않게 한다.

- Claude 는 요청 앞부분(tools → system 의 cache_control 블록까지)을 캐시한다. 수명은 5분이나 1시간(ANTHROPIC_CACHE_TTL)뿐이고
  하루짜리는 없다. 대신 캐시를 읽으면(입력값의 0.1배) 수명이 처음부터 다시 시작된다.
- 그래서 실제 답장·선톡 요청에 쓰인 앞부분을 기억해 두고, WARM_AFTER_S 동안 그 앞부분을 쓴 요청이 없으면 같은 앞부분에
  max_tokens 0 을 붙여 보낸다. API 는 앞부분을 읽어 1시간을 다시 채우고 글은 만들지 않는다(출력 0, 공식 문서 'Pre-warming the
  cache'). 앞부분은 요청 그대로 기억하므로 도구(웹 검색 max_uses 등)가 바뀌면 새 앞부분을 따라간다.
- 1시간 수명일 때만 켠다(5분이면 4분마다 보내야 해서 아끼는 것보다 비쌈). 실제 요청이 IDLE_S 동안 없으면 그 앞부분은 놓는다.
- 돈이 새지 않게: 유지 요청이 캐시를 새로 썼으면(이미 식음) 그 앞부분은 놓고 다음 실제 요청이 다시 등록하게 한다(유지 요청이
  쓰기 값을 연달아 내지 않음). 하루(한국 날짜) DAILY_MAX 번까지만 보내고, API 가 거절한(400) 앞부분은 다시 보내지 않는다.
- 로그(marong.cache)에는 앞부분 해시 앞 12자와 토큰 수만 남긴다(글 내용 없음).
"""
import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .llm import brief

log = logging.getLogger("marong.cache")

CHECK_S = 60             # 이 간격으로 식어 가는 앞부분이 있는지 확인
WARM_AFTER_S = 45 * 60   # 마지막 사용 뒤 이만큼 지나면 유지 요청(1시간 수명에서 늦은 답·재시도 여유를 둠)
RETRY_S = 5 * 60         # 유지 요청이 실패하면 이만큼 뒤에 다시
IDLE_S = 24 * 3600       # 실제 요청이 이만큼 없으면 그 앞부분은 놓음
KEEP = 3                 # 유지하는 앞부분 수(도구 있는 답장, 도구 없는 선톡, 도구가 바뀐 판 하나)
DAILY_MAX = 100          # 하루 유지 요청 상한(앞부분 3개를 24시간 유지해도 96번)
TIMEOUT_S = 30
PLACEHOLDER = "warmup"   # 유지 요청의 user 말. 읽기만 하고 답하지 않음
PREFIX_KEYS = ("model", "tools", "thinking", "speed")  # 캐시 앞부분을 바꾸는 요청 값(system·effort 는 따로 고름)


def hour_writes(usage) -> int:
    """이 응답에서 1시간 수명으로 쓴 캐시 토큰(1시간 쓰기는 입력의 2배, 5분 쓰기는 1.25배라 따로 셈)."""
    made = getattr(usage, "cache_creation", None)
    if made is None:
        return 0
    value = made.get("ephemeral_1h_input_tokens") if isinstance(made, dict) else \
        getattr(made, "ephemeral_1h_input_tokens", None)
    return int(value or 0)


def cached_prefix(body: dict) -> dict | None:
    """요청에서 마지막 system 캐시 표시까지의 앞부분(이것만 다시 보내면 같은 캐시를 읽음). 표시가 없으면 None."""
    system = body.get("system")
    if not isinstance(system, list):
        return None
    marks = [i for i, b in enumerate(system) if isinstance(b, dict) and b.get("cache_control")]
    if not marks:
        return None
    if (body.get("thinking") or {}).get("type") == "enabled":
        return None  # max_tokens 0 요청은 확장 생각(enabled)과 같이 못 보냄
    prefix = {k: body[k] for k in PREFIX_KEYS if body.get(k) is not None}
    prefix["system"] = system[:marks[-1] + 1]
    effort = (body.get("output_config") or {}).get("effort")
    if effort:  # effort 는 프롬프트에 들어가 캐시를 가름. format(구조화 출력)은 max_tokens 0 과 못 써서 뺌
        prefix["output_config"] = {"effort": effort}
    return json.loads(json.dumps(prefix, ensure_ascii=False))  # 원본 요청이 뒤에 바뀌어도 그대로인 사본


def prefix_key(prefix: dict) -> str:
    return hashlib.sha256(json.dumps(prefix, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


@dataclass
class Entry:
    body: dict          # 유지 요청(앞부분 + max_tokens 0 + 자리 말)
    tokens: int         # 마지막으로 본 캐시 앞부분 크기(로그용)
    used: float         # 캐시를 마지막으로 읽거나 쓴 때(실제 요청이 끝난 때나 유지 요청을 보낸 때)
    real: float         # 마지막 실제 요청
    retry: float = 0.0  # 실패한 유지 요청을 다시 보낼 때


class CacheWarmer:
    def __init__(self, llm, timezone: str = "Asia/Seoul", *, after_s: float = WARM_AFTER_S, idle_s: float = IDLE_S,
                 keep: int = KEEP, daily_max: int = DAILY_MAX, clock=time.monotonic, today=None):
        self.llm = llm
        self.after_s, self.idle_s, self.keep, self.daily_max = after_s, idle_s, keep, daily_max
        self.clock = clock
        tz = ZoneInfo(timezone)
        self.today = today or (lambda: datetime.now(tz).date())
        self.entries: OrderedDict[str, Entry] = OrderedDict()  # 실제 요청이 오래된 것부터
        self.refused: set[str] = set()  # API 가 유지 요청을 거절한 앞부분(다시 등록하지 않음)
        self.day = None
        self.count = {"pings": 0, "hits": 0, "read": 0, "write": 0}
        self.capped = False  # 오늘 하루 상한에 닿음(경고는 하루 한 번)

    def seen(self, body: dict, usage) -> None:
        """실제 요청이 끝날 때마다 불린다. 캐시를 읽거나 쓴 앞부분을 (다시) 등록한다."""
        read = getattr(usage, "cache_read_input_tokens", None) or 0
        wrote = getattr(usage, "cache_creation_input_tokens", None) or 0
        if not (read or wrote):
            return  # 캐시 최소 길이보다 짧거나 캐시를 안 씀: 유지할 것이 없음
        prefix = cached_prefix(body)
        if prefix is None:
            return
        key = prefix_key(prefix)
        if key in self.refused:
            return
        now = self.clock()
        entry = self.entries.pop(key, None)
        if entry is None:
            entry = Entry({**prefix, "max_tokens": 0, "messages": [{"role": "user", "content": PLACEHOLDER}]},
                          0, now, now)
            log.info("cache_warm_track key=%s tokens=%d", key, read or wrote)
        entry.tokens, entry.used, entry.real, entry.retry = read or wrote, now, now, 0.0
        self.entries[key] = entry
        while len(self.entries) > self.keep:
            old, _ = self.entries.popitem(last=False)
            log.info("cache_warm_drop key=%s reason=replaced", old)

    async def run(self) -> None:
        log.info("cache_warm_on after_min=%d idle_h=%d keep=%d daily_max=%d", self.after_s // 60, self.idle_s // 3600,
                 self.keep, self.daily_max)
        while True:
            await asyncio.sleep(CHECK_S)
            try:
                await self.step()
            except Exception as e:  # 다음 확인 때 다시
                log.warning("cache_warm_step_error %s", brief(e))

    async def step(self) -> int:
        """식어 가는 앞부분마다 유지 요청을 보내고, 캐시를 읽어 수명을 다시 채운 수를 돌려준다."""
        hits = 0
        for key in list(self.entries):
            entry = self.entries.get(key)
            now = self.clock()
            if entry is None or now - entry.used < self.after_s or now < entry.retry:
                continue
            if now - entry.real > self.idle_s:
                self.entries.pop(key, None)
                log.info("cache_warm_drop key=%s reason=idle", key)
                continue
            if not self._spend():
                break
            hits += await self._ping(key, entry, now)
        return hits

    def _spend(self) -> bool:
        """하루 상한 안이면 유지 요청 하나를 센다. 날짜가 바뀌면 어제 합계를 로그에 남기고 0부터."""
        day = self.today()
        if day != self.day:
            if self.day is not None:
                log.info("cache_warm_day day=%s pings=%d hits=%d read=%d write=%d", self.day, *self.count.values())
            self.day, self.count, self.capped = day, {"pings": 0, "hits": 0, "read": 0, "write": 0}, False
        if self.count["pings"] >= self.daily_max:
            if not self.capped:
                self.capped = True
                log.warning("cache_warm_daily_max %d", self.daily_max)
            return False
        self.count["pings"] += 1
        return True

    async def _ping(self, key: str, entry: Entry, now: float) -> int:
        try:
            resp = await self.llm.create(entry.body, TIMEOUT_S)
        except Exception as e:
            if getattr(e, "status_code", None) == 400 and "credit" not in str(e).lower():
                self.entries.pop(key, None)  # 요청 자체가 거절됨: 다시 보내도 같음
                self.refused.add(key)
                log.warning("cache_warm_refused key=%s %s", key, brief(e))
            else:  # 과부하·네트워크·크레딧: 조금 뒤 다시(그사이 식으면 다음 유지 요청이 쓰기를 보고 놓음)
                entry.retry = self.clock() + RETRY_S
                log.warning("cache_warm_error key=%s %s", key, brief(e))
            return 0
        usage = resp.usage
        read = getattr(usage, "cache_read_input_tokens", None) or 0
        wrote = getattr(usage, "cache_creation_input_tokens", None) or 0
        self.count["read"] += read
        self.count["write"] += wrote
        if wrote or not read:
            # 이미 식어서 새로 썼거나 캐시가 안 됨: 유지 요청이 쓰기 값을 또 내지 않게 놓고, 다음 실제 요청이 다시 등록하게 함
            self.entries.pop(key, None)
            log.info("cache_warm_miss key=%s read=%d write=%d", key, read, wrote)
            return 0
        self.count["hits"] += 1
        entry.used, entry.tokens, entry.retry = max(entry.used, now), read, 0.0
        log.info("cache_warm_hit key=%s read=%d input=%d today=%d", key, read, getattr(usage, "input_tokens", 0) or 0,
                 self.count["pings"])
        return 1
