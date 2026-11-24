"""Korean relative time for conversation records (SPEC-484)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from marong.fmt import WEEKDAYS


KST = ZoneInfo("Asia/Seoul")


def relative_time(when: datetime | None, now: datetime) -> str | None:
    if when is None:
        return None
    elapsed = now - when
    if elapsed < timedelta(minutes=2):
        return "방금"
    if elapsed < timedelta(hours=1):
        return f"{elapsed // timedelta(minutes=1)}분 전"

    local = when.astimezone(KST)
    days = (now.astimezone(KST).date() - local.date()).days
    weekday = WEEKDAYS[local.weekday()]
    date = f"{local.month}/{local.day} {weekday}"
    if days < 3:
        if local.hour < 12:
            hour = f"오전 {local.hour}시"
        elif local.hour == 12:
            hour = "낮 12시"
        else:
            hour = f"오후 {local.hour - 12}시"
        minutes = f" {local.minute}분" if local.minute else ""
        suffix = f"({date})" if days else ""
        return f"{('오늘', '어제', '그저께')[days]} {hour}{minutes}{suffix}"
    if days < 7:
        return f"{days}일 전({date})"
    return f"{local.month}월 {local.day}일({weekday})"
