"""Tool availability and the shared capability prompt (SPEC-203–205)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Feature:
    name: str
    areas: tuple[str, ...]
    tools: tuple[str, ...] = ()


TEXT = ("direct", "group")
FEATURES = (
    Feature("일정 기억, 정한 때 먼저 말 걸기", TEXT, ("schedule_add", "schedule_cancel", "schedule_list")),
    Feature("친구 자기 이름", TEXT, ("set_name",)),
    Feature("설정·켜기 요청을 동희님께", TEXT, ("ask_owner",)),
    Feature("웹 검색", TEXT, ("web_search",)),
    Feature("쇼핑 페이지 가격 읽기", TEXT, ("web_fetch",)),
    Feature("연결한 친구의 캘린더 일정", ("direct",)),
    Feature("앱으로 지금 전화·약속 전화 걸기", ("direct",)),
    Feature("지금 바람과 친구 규칙 적기", TEXT, ("card_update",)),
    Feature("나에 관해 기억하는 것 보기", TEXT, ("memory_list",)),
    Feature("통화 중 기억 찾기", ("call",), ("recall",)),
    Feature("지금 시각", ("call",), ("current_time",)),
    Feature("친구가 요청한 통화 끊기", ("call",), ("end_call",)),
    Feature("통화 중 웹 검색", ("call",), ("googleSearch",)),
)
TOOLS = frozenset(tool for feature in FEATURES for tool in feature.tools)
TEXT_FEATURE_NAMES = tuple(feature.name for feature in FEATURES if "direct" in feature.areas)
WATCH = "지켜보다 알려 주기(월세, 택배, 남의 답장)는 못 해. 대신 날짜 알림을 제안해."
CLOSED = "꺼진 일은 꺼져 있다고 말하고 동희한테 켜 달라고 할지 물어봐."
ALTERNATIVE = "못 하는 일은 '못 해'로 끝내지 말고 대신 할 수 있는 걸 같이 말해."


def text_matrix(tools):
    return [tool for tool in tools if tool.get("name") in TOOLS]


def availability(area, available, *, calendar=False, phone=False):
    extra = {"연결한 친구의 캘린더 일정": calendar, "앱으로 지금 전화·약속 전화 걸기": phone}
    enabled, disabled = [], []
    for feature in FEATURES:
        if area not in feature.areas:
            continue
        on = any(name in available for name in feature.tools) if feature.tools else extra[feature.name]
        (enabled if on else disabled).append(feature.name)
    return enabled, disabled


def description(area, available, *, calendar=False, phone=False):
    enabled, disabled = availability(area, available, calendar=calendar, phone=phone)
    lines = []
    if enabled:
        lines.append("마롱이가 할 수 있는 일: " + " · ".join(enabled))
    if disabled:
        lines.append("지금 꺼져 있는 일: " + " · ".join(disabled))
    if "schedule_add" in available:
        lines.append(WATCH)
    lines.extend((CLOSED, ALTERNATIVE))
    return "\n".join(lines)
