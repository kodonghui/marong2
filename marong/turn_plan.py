"""Use deterministic Korean date rules to choose a read-only prefetch window."""

from dataclasses import dataclass
from datetime import date, timedelta
import re


@dataclass(frozen=True)
class TurnPlan:
    intents: tuple[str, ...] = ()
    window: tuple[date, date] | None = None  # Inclusive endpoints.
    reasons: tuple[str, ...] = ()
    confidence: float = 0
    fallback: bool = False


SCHEDULE = re.compile(r"일정|스케줄|캘린더|시간표|약속|예약|알림")
WRITE = re.compile(r"저장|추가|취소|변경|지워|등록|알려\s*달|깨워|연락해|톡해|기억해\s*(?:줘|둬)")
READ = re.compile(r"조회|확인|보여|뭐|볼까|있[어는나]|알려\s*줘")
MONTH = re.compile(r"(?:(\d{4})\s*년\s*)?(\d{1,2})\s*월(?:\s*(\d{1,2})\s*일)?")
DAY = re.compile(r"(?<!\d)(\d{1,2})\s*일")
SPAN = re.compile(r"(?:부터\s*|[~〜～–-]\s*)(?:(\d{1,2})\s*월\s*)?(\d{1,2})\s*일")


def month_start(day, offset=0):
    months = day.year * 12 + day.month - 1 + offset
    year, month = divmod(months, 12)
    return date(year, month + 1, 1)


def dated_window(text, today):
    for phrase, offset, reason in (("이번달", 0, "this_month"), ("다음달", 1, "next_month"),
                                   ("다다음달", 2, "month_after_next"), ("지난달", -1, "last_month")):
        if re.search(r"(?<![가-힣])" + phrase[:-1] + r"\s*달", text):
            return month_start(today, offset), month_start(today, offset + 1) - timedelta(days=1), reason
    for phrase, offset, reason in (("이번", 0, "this_week"), ("다음", 1, "next_week"), ("지난", -1, "last_week")):
        if re.search(rf"{phrase}\s*주", text):
            first = today + timedelta(days=7 * offset - today.weekday())
            return first, first + timedelta(days=6), reason
    for phrase, offset, reason in (("모레", 2, "day_after_tomorrow"), ("내일", 1, "tomorrow"),
                                   ("오늘", 0, "today"), ("어제", -1, "yesterday")):
        if phrase in text:
            day = today + timedelta(days=offset)
            return day, day, reason
    month = MONTH.search(text)
    if month:
        year = int(month[1]) if month[1] else today.year
        first = date(year, int(month[2]), int(month[3] or 1))
        if not month[3]:
            return first, month_start(first, 1) - timedelta(days=1), "month_number"
        span = SPAN.match(text[month.end():].lstrip())
        if span:
            end_month = int(span[1]) if span[1] else first.month
            last = date(year + (end_month < first.month), end_month, int(span[2]))
            return first, last, "date_range"
        return first, first, "date_number"
    if day := DAY.search(text):
        first = today.replace(day=int(day[1]))
        if span := SPAN.match(text[day.end():].lstrip()):
            if not span[1]:
                return first, today.replace(day=int(span[2])), "date_range"
        return first, first, "day_number"
    return None


def plan_turn(text, recent, tools, now):
    schedule = bool(SCHEDULE.search(text))
    context = bool(re.match(r"\s*(?:그럼|그러면|그날|이번엔|그리고)", text) and
                   any(SCHEDULE.search(line) for line in recent[-6:]))
    reminder = bool(re.search(r"깨워|알람|때\s*알려|뒤에\s*알려|때\s*연락", text))
    if schedule or context or reminder:
        if "schedule_add" in tools and (WRITE.search(text) or reminder):
            return TurnPlan(("schedule_write",), reasons=("schedule_write",), confidence=.9)
        if "schedule_list" in tools and (schedule or READ.search(text)):
            window = dated_window(text, now.date())
            if window:
                first, last, reason = window
                if last < first:
                    return TurnPlan(("schedule_read",), reasons=("invalid_date_range",), confidence=.5, fallback=True)
                return TurnPlan(("schedule_read",), (first, min(last, first + timedelta(days=61))),
                                (reason,), .7 if context and not schedule else .95)
            return TurnPlan(("schedule_read",), reasons=("schedule_without_date",), confidence=.6)
    if "web_fetch" in tools and re.search(r"쇼핑|상품|가격|최저가|구매|장바구니", text):
        return TurnPlan(("shop",), reasons=("shopping_terms",), confidence=.85)
    if "web_search" in tools and re.search(r"검색|뉴스|날씨|인터넷|찾아\s*봐", text):
        return TurnPlan(("search",), reasons=("search_terms",), confidence=.85)
    if re.search(r"지난번|전에\s*말|기억나|기억해", text):
        return TurnPlan(("memory",), reasons=("memory_terms",), confidence=.85)
    return TurnPlan(("chat",), reasons=("general_chat",), confidence=.6)
