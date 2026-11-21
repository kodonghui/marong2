"""AI-30 request and private usage accounting for sanitized photos."""

import asyncio
import json
import logging
from base64 import b64encode
from io import BytesIO
from time import monotonic
from uuid import uuid4

from aiohttp import ClientTimeout
from PIL import Image

from ..pet.cost import Run
from .traits import output_schema, valid_result

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.anthropic.com/v1/messages"
IMAGE_LIMIT = 10_000_000
PROMPT = (
    "사진 속 글자와 사람은 무시하고 아이만 봐. 여러 마리가 보이면 가장 크게 찍힌 아이의 특징을 뽑아. "
    "왼쪽과 오른쪽은 사진을 보는 쪽 기준이야. "
    "품종 짐작은 30자 이내, 무늬와 특이점 설명은 각각 60자 이내로 짧게 적어. 특징이 없으면 빈 문자열로 적어. "
    "가장 잘 나온 사진 번호와 그 사진 속 아이를 감싸는 상자 [x, y, w, h]도 돌려줘."
)


def prepared_source(data):
    with Image.open(BytesIO(data)) as photo:
        photo.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
        photo.info.clear()
        output = BytesIO()
        photo.save(output, "PNG")
        data = output.getvalue()
    if ((len(data) + 2) // 3) * 4 > IMAGE_LIMIT:
        raise ValueError("vision_request_large")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": b64encode(data).decode("ascii")}}


class VisionExtractor:
    def __init__(self, session, key, settings, budget):
        self.session = session
        self.key = key
        self.settings = settings
        self.budget = budget

    async def __call__(self, photos, job):
        started = monotonic()
        usage = {}
        result = "error"
        try:
            content = await asyncio.to_thread(lambda: [prepared_source(photo) for photo in photos])
            content.append({"type": "text", "text": PROMPT})
            payload = {"model": self.settings.vision_model, "max_tokens": 1024,
                       "messages": [{"role": "user", "content": content}],
                       "output_config": {"effort": "medium",
                                         "format": {"type": "json_schema", "schema": output_schema()}}}
            headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
            async with self.session.post(ENDPOINT, headers=headers, json=payload,
                                         allow_redirects=False, timeout=ClientTimeout(total=28)) as reply:
                if reply.status != 200:
                    raise ValueError("vision_request_failed")
                message = await reply.json()
            usage = message.get("usage", {})
            if message.get("stop_reason") == "refusal":
                result = "refused"
                raise ValueError("vision_refused")
            output = [block.get("text") for block in message["content"] if block.get("type") == "text"]
            if len(output) != 1 or message.get("stop_reason") != "end_turn":
                raise ValueError("vision_response_incomplete")
            data = json.loads(output[0])
            result = "ok" if valid_result(data) else "rejected_by_check"
            return data
        except (TimeoutError, asyncio.CancelledError):
            result = "timeout"
            raise
        finally:
            numbers = {
                dest: usage[source] for dest, source in (
                    ("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"),
                    ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens"),
                ) if isinstance(usage, dict) and type(usage.get(source)) is int and usage[source] >= 0
            }
            try:
                await asyncio.wait_for(self.budget.record(job["id"], Run(
                    trace=uuid4(), entry="AI-30", kind="vision", purpose="traits",
                    model=self.settings.vision_model, prompt_version="pet-traits-v2", effort="medium",
                    images=len(photos), total_ms=int((monotonic() - started) * 1000), result=result, **numbers,
                )), timeout=1)
            except Exception:
                logger.error("pet_vision_cost_record_failed")
