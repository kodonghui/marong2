"""카카오톡 봇 메시지 콜백 API(답장).
POST {KAKAO_API_URL}/v1/bot/callback
  Authorization: KakaoAK {봇 인증 토큰}
  X-Bot-Callback-Token: {이벤트 d.callbackToken}  ← 1회용, 5분 안에 써야 함
  본문: {"skillResponse": {"version": "2.0", "template": {"outputs": [...] }}}
주의: 이 API는 앱의 '호출 허용 IP'에 등록된 서버에서만 호출됨."""
import logging
import re

import httpx

from .config import Settings

log = logging.getLogger("kakao")

MAX_BUBBLES = 3      # 콜백 한 번에 말풍선 최대 3개
BUBBLE_CHARS = 1000  # SimpleText 한 개 최대 글자 수(500자가 넘으면 '전체 보기'로 접힘)


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
