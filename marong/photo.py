"""친구가 보낸 사진. 카카오는 사진을 서명된(시간이 지나면 만료되는) 카카오 CDN 주소 하나로 보낸다(content 가 그 주소뿐).
주소 안에 인증값이 들어 있어서 저장·로그에 남기지 않고, 받자마자 내려받아 Claude 에게 보여 준다.
기록에는 사진 대신 '[사진] 설명'을 남긴다(설명은 agent.py 가 Claude 에게 사진을 보여 주고 짧게 받은 것)."""
import base64
import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

log = logging.getLogger("photo")

MAX_BYTES = 3_750_000  # Claude 는 사진 한 장을 base64 로 5MB 까지 받음 → 원본은 3.75MB 까지
TIMEOUT_S = 15
REDIRECTS = 2          # 카카오 CDN 안에서만 따라감
MAGIC = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"GIF87a", "image/gif"),
         (b"GIF89a", "image/gif"))


@dataclass
class Photo:
    media: str | None = None   # image/jpeg·png·gif·webp. 못 열었으면 None
    data: bytes | None = None
    problem: str = ""          # 못 연 이유: big(너무 큼)·type(사진이 아님)·error(내려받기 실패)

    def block(self) -> dict | None:
        """Claude messages 에 넣는 사진 블록(못 열었으면 None)."""
        if not (self.media and self.data):
            return None
        return {"type": "image",
                "source": {"type": "base64", "media_type": self.media, "data": base64.b64encode(self.data).decode()}}


def photo_url(text: str | None) -> str | None:
    """카카오 CDN(https://….kakaocdn.net) 주소 하나만 온 메시지면 그 주소. 다른 말이 섞였거나 다른 곳 주소면 None."""
    t = (text or "").strip()
    if not t or any(c.isspace() for c in t):
        return None
    try:
        u = urlsplit(t)
        host = (u.hostname or "").lower()
    except ValueError:
        return None
    if u.scheme == "https" and (host == "kakaocdn.net" or host.endswith(".kakaocdn.net")) and len(u.path) > 1:
        return t
    return None


def sniff(data: bytes) -> str | None:
    """파일 앞부분으로 사진 종류를 알아낸다(서버가 알려 주는 종류는 믿지 않음)."""
    for magic, media in MAGIC:
        if data.startswith(magic):
            return media
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def download(http: httpx.AsyncClient, url: str) -> Photo:
    """사진을 내려받는다. 주소와 응답 본문은 로그에 남기지 않는다(주소에 인증값이 있음)."""
    try:
        for _ in range(REDIRECTS + 1):
            async with http.stream("GET", url, timeout=TIMEOUT_S, follow_redirects=False) as r:
                if r.is_redirect:
                    url = photo_url(urljoin(url, r.headers.get("location", "")))
                    if url is None:  # 카카오 CDN 밖으로 가는 이동은 따라가지 않음
                        break
                    continue
                if r.status_code != 200:
                    log.warning("photo_download status=%d", r.status_code)
                    return Photo(problem="error")
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        log.warning("photo_download too_big")
                        return Photo(problem="big")
                media = sniff(bytes(buf))
                if media is None:
                    log.warning("photo_download not_image bytes=%d", len(buf))
                    return Photo(problem="type")
                return Photo(media=media, data=bytes(buf))
    except httpx.HTTPError as e:
        log.warning("photo_download_error %s", type(e).__name__)
        return Photo(problem="error")
    log.warning("photo_download bad_redirect")
    return Photo(problem="error")
