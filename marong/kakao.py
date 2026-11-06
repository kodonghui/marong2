"""카카오톡 봇 메시지 API.
답장(콜백): POST {KAKAO_API_URL}/v1/bot/callback
  Authorization: KakaoAK {봇 인증 토큰}
  X-Bot-Callback-Token: {이벤트 d.callbackToken}  ← 1회용, 5분 안에 써야 함
  본문: {"skillResponse": {"version": "2.0", "template": {"outputs": [...] }}}
먼저 보내기(전송, 선톡): POST {KAKAO_API_URL}/v1/bot/send_message
  Authorization: KakaoAK {봇 인증 토큰}
  본문: {"botGroupKey": …(방 키) 또는 "botUserKey": …(사람 키), "skillResponse": {…}} 둘 중 하나만.
  채널채팅은 그 친구가 채널 친구여야 하고(-877), 알림을 끈 친구에게는 안 감(-879).
  일반·오픈채팅은 봇이 그 방에 초대돼 있어야 함(-880). 하루 1,000건까지.
  2026-11-05 14:30 KST부터 1:1 채널채팅은 사람 키로 보내면 400 {"code": -876, "msg": "botGroupKey만 입력되어야
  합니다."}, 방 키로 보내면 400 {"code": -880, "msg": "봇이 초대되지 않은 방입니다."}로 막힘(그 전에는 사람 키로 갔음).
  봇을 초대한 단체방에는 방 키로 감. 1:1 은 send_first 가 방 키, 안 되면 사람 키로 보내서 카카오가 어느 쪽을 다시 열어도 감.
주의: 이 API들은 앱의 '호출 허용 IP'에 등록된 서버에서만 호출됨."""
import logging
import re

import httpx

from .config import Settings

log = logging.getLogger("kakao")

MAX_BUBBLES = 3      # 콜백 한 번에 말풍선 최대 3개
BUBBLE_CHARS = 1000  # SimpleText 한 개 최대 글자 수(500자가 넘으면 '전체 보기'로 접힘)
# 키 때문에 보내지 않은 것이 분명한 오류: -876 이 방에는 다른 종류의 키를 넣어야 함, -880 봇이 초대되지 않은 방.
# 1:1 은 이때 다른 키로 한 번 더 보내도 두 번 가지 않는다
KEY_REJECTED = (-876, -880)


def bubbles(text: str) -> list[str]:
    """빈 줄로 나눈 덩어리를 말풍선으로. 3개가 넘으면 남은 덩어리를 셋째 말풍선에 모음."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()] or [text.strip() or "…"]
    if len(parts) > MAX_BUBBLES:
        parts = parts[:MAX_BUBBLES - 1] + ["\n\n".join(parts[MAX_BUBBLES - 1:])]
    return [p if len(p) <= BUBBLE_CHARS else p[:BUBBLE_CHARS - 1] + "…" for p in parts]


def skill_text(text: str, quick_replies: list[str] | None = None) -> dict:
    """SimpleText 말풍선 1~3개(+ 퀵리플라이)."""
    template: dict = {"outputs": [{"simpleText": {"text": b}} for b in bubbles(text)]}
    if quick_replies:
        template["quickReplies"] = [
            {"label": q[:14], "action": "message", "messageText": q} for q in quick_replies[:10]
        ]
    return {"version": "2.0", "template": template}


async def send_callback(http: httpx.AsyncClient, s: Settings, callback_token: str, skill_response: dict) -> bool:
    headers = {"Authorization": f"KakaoAK {s.bot_token}", "X-Bot-Callback-Token": callback_token}
    for attempt in (1, 2):  # 네트워크 오류·5xx 만 한 번 더(토큰이 1회용이라 중복 발송은 -881로 막힘)
        try:
            r = await http.post(
                f"{s.kakao_api_url}/v1/bot/callback",
                headers=headers,
                json={"skillResponse": skill_response},
                timeout=10,
            )
        except httpx.HTTPError as e:
            log.warning("callback_error attempt=%d %s", attempt, type(e).__name__)
            continue
        if r.status_code == 200:
            return True
        log.error("callback_failed status=%d body=%s", r.status_code, r.text[:300])
        if r.status_code < 500:
            return False  # -401(IP·토큰), -878(말풍선 형식), -881(만료·재사용) 등은 재시도해도 같음
    return False


async def send_message(http: httpx.AsyncClient, s: Settings, skill_response: dict, *, user_key: str | None = None,
                       group_key: str | None = None) -> tuple[bool, int | None]:
    """봇이 먼저 보낸다. user_key(사람 키 botUserKey)나 group_key(방 키 botGroupKey) 하나만 넣는다.
    콜백과 달리 중복을 막는 토큰이 없어서 다시 보내지 않는다(두 번 갈 수 있음). 200 이어도 sendCount 가 0 이거나
    errorCount 가 있으면 받는 사람에게 못 간 것으로 본다.
    돌려주는 것: (전달 성공, 카카오 오류 코드. 성공이거나 응답이 없으면 None)."""
    target = {"botUserKey": user_key} if user_key else {"botGroupKey": group_key}
    try:
        r = await http.post(
            f"{s.kakao_api_url}/v1/bot/send_message",
            headers={"Authorization": f"KakaoAK {s.bot_token}"},
            json={**target, "skillResponse": skill_response},
            timeout=10,
        )
    except httpx.HTTPError as e:
        log.warning("send_message_error %s", type(e).__name__)
        return False, None
    try:
        data = r.json()
    except ValueError:
        data = None
    if r.status_code == 200:
        sent, errors = (data.get("sendCount"), data.get("errorCount")) if isinstance(data, dict) else (None, None)
        if (isinstance(sent, int) and sent < 1) or (isinstance(errors, int) and errors > 0):
            log.error("send_message_not_delivered sendCount=%s errorCount=%s", sent, errors)
            return False, None
        return True, None
    code = data.get("code") if isinstance(data, dict) else None
    log.error("send_message_failed status=%d body=%s", r.status_code, r.text[:300])
    return False, code if isinstance(code, int) else None


async def send_first(http: httpx.AsyncClient, s: Settings, skill_response: dict, *, room_key: str | None,
                     user_key: str | None, prefer: str = "room") -> tuple[bool, int | None, str]:
    """1:1 채널 방에 먼저 보낸다. prefer 키('room' 방 키 botGroupKey, 'user' 사람 키 botUserKey)로 보내고, 카카오가 키
    때문에 보내지 않았다고(KEY_REJECTED) 하면 다른 키로 한 번만 더 보낸다. 다른 오류는 다시 보내지 않는다(두 번 갈 수 있음).
    돌려주는 것: (전달 성공, 카카오 오류 코드, 마지막으로 쓴 키 'room'|'user'). 연달아 보낼 때는 그 키를 prefer 로."""
    keys = {"room": room_key, "user": user_key}
    order = [k for k in [prefer] + [k for k in keys if k != prefer] if keys.get(k)]
    if not order:
        return False, None, prefer
    ok, code = False, None
    for i, kind in enumerate(order):
        if i:
            log.info("send_message_retry key=%s after=%s", kind, code)
        target = {"group_key": room_key} if kind == "room" else {"user_key": user_key}
        ok, code = await send_message(http, s, skill_response, **target)
        if ok or code not in KEY_REJECTED:
            return ok, code, kind
    return ok, code, order[-1]
