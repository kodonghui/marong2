"""시각 표시와 로그용 짧은 키."""
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

WEEKDAYS = "월화수목금토일"


def now_line(tz: str) -> str:
    """'2026년 10월 25일 일요일 오후 7시 5분'."""
    n = datetime.now(ZoneInfo(tz))
    half = "오전" if n.hour < 12 else "오후"
    return f"{n.year}년 {n.month}월 {n.day}일 {WEEKDAYS[n.weekday()]}요일 {half} {n.hour % 12 or 12}시 {n.minute}분"


def day_line(dt: datetime, tz: str) -> str:
    """'2026년 10월 25일 일요일'."""
    d = dt.astimezone(ZoneInfo(tz))
    return f"{d.year}년 {d.month}월 {d.day}일 {WEEKDAYS[d.weekday()]}요일"


def short_time(dt: datetime, tz: str) -> str:
    """'10/25 19:05'."""
    d = dt.astimezone(ZoneInfo(tz))
    return f"{d.month}/{d.day} {d.hour:02d}:{d.minute:02d}"


def short_key(key: str | None) -> str:
    """로그에 카카오 키 원문 대신 남기는 8글자."""
    return hashlib.sha1((key or "").encode()).hexdigest()[:8]
