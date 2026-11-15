"""친구가 보낸 사진. 카카오는 사진을 서명된(시간이 지나면 만료되는) 카카오 CDN 주소 하나로 보낸다(content 가 그 주소뿐).
주소 안에 인증값이 들어 있어서 저장·로그에 남기지 않고, 받자마자 내려받아 Claude 에게 보여 준다.
폰 원본 사진은 Claude 가 한 장에 받는 크기보다 커서, 서버에서 줄여 보낸다.
기록에는 사진 대신 '[사진] 설명'을 남긴다(설명은 agent.py 가 Claude 에게 사진을 보여 주고 짧게 받은 것).
디스코드 DM 사진은 discord_dm.py 가 첨부를 받아 prepare() 로 같은 처리를 한다."""
import asyncio
import base64
import io
import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image, ImageOps

log = logging.getLogger("photo")

MAX_BYTES = 3_750_000      # Claude 는 사진 한 장을 base64 로 5MB 까지 받음 → 보내는 사진은 3.75MB 까지
MAX_DOWNLOAD = 30_000_000  # 폰 원본 사진도 받음. MAX_BYTES 가 넘으면 줄여서 보냄
MAX_SIDE = 1568            # 줄일 때 긴 변(Claude 는 이보다 큰 사진도 이만큼 줄여서 봄)
MAX_PIXELS = 25_000_000    # JPEG 가 아닌 사진은 통째로 풀어야 해서 화소 수를 막음(메모리)
Image.MAX_IMAGE_PIXELS = 250_000_000  # 2억 화소 폰 사진(JPEG)도 열게. JPEG 는 draft 로 작게 풂
TIMEOUT_S = 15
REDIRECTS = 2          # 카카오 CDN 안에서만 따라감
MAGIC = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"GIF87a", "image/gif"),
         (b"GIF89a", "image/gif"))


@dataclass
class Photo:
    media: str | None = None   # image/jpeg·png·gif·webp. 못 열었으면 None
    data: bytes | None = None
    problem: str = ""          # 못 연 이유: big(너무 큼)·type(사진이 아님)·error(내려받기 실패·깨진 사진)

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


def shrink(data: bytes) -> bytes | None:
    """사진을 긴 변 MAX_SIDE 의 JPEG 로 줄인다. 폰 사진의 회전 정보는 실제 방향으로 바꾸고, 투명한 곳은 흰색으로.
    움직이는 사진은 첫 장만. 화소가 너무 많으면 None, 깨진 파일이면 예외."""
    with Image.open(io.BytesIO(data)) as src:
        if src.format != "JPEG" and src.width * src.height > MAX_PIXELS:
            return None
        src.draft("RGB", (MAX_SIDE, MAX_SIDE))  # JPEG 는 처음부터 작게 풀어서 메모리·시간을 아낌
        im = ImageOps.exif_transpose(src)
        if im.mode in ("RGBA", "LA", "P", "PA"):
            im = im.convert("RGBA")
            flat = Image.new("RGB", im.size, "white")
            flat.paste(im, mask=im.getchannel("A"))
            im = flat
        elif im.mode != "RGB":
            im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=85)
    return out.getvalue() if out.tell() <= MAX_BYTES else None


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
                    if len(buf) > MAX_DOWNLOAD:
                        log.warning("photo_download too_big")
                        return Photo(problem="big")
                return await prepare(bytes(buf))
    except httpx.HTTPError as e:
        log.warning("photo_download_error %s", type(e).__name__)
        return Photo(problem="error")
    log.warning("photo_download bad_redirect")
    return Photo(problem="error")


async def prepare(data: bytes) -> Photo:
    """받은 사진 파일 → Photo. 종류는 파일 앞부분으로 알아내고, Claude 가 받는 크기보다 크면 줄인다."""
    media = sniff(data)
    if media is None:
        log.warning("photo_download not_image bytes=%d", len(data))
        return Photo(problem="type")
    if len(data) <= MAX_BYTES:
        return Photo(media=media, data=data)
    try:  # 줄이는 데 CPU 를 써서 다른 방 답이 밀리지 않게 따로 돌림
        small = await asyncio.to_thread(shrink, data)
    except Exception as e:  # 깨진 사진 등. 오류 글에는 내용이 없지만 종류만 남김
        log.warning("photo_shrink_error %s bytes=%d", type(e).__name__, len(data))
        return Photo(problem="error")
    if small is None:
        log.warning("photo_shrink too_many_pixels bytes=%d", len(data))
        return Photo(problem="big")
    log.info("photo_shrunk %s %d→%d bytes", media, len(data), len(small))
    return Photo(media="image/jpeg", data=small)
