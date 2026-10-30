"""Claude API 호출(공식 anthropic SDK). 주 키가 실패(한도·크레딧·장애·시간 초과)하면 백업 키로 한 번 더 보낸다.
grok=True 면 Grok(xAI)에 먼저 보내고, Grok 이 실패하면(거절은 실패가 아님) 같은 요청을 Claude 키로 보낸다."""
import asyncio
import logging

import anthropic

from .config import Settings
from .grok import Grok, GrokError

log = logging.getLogger("llm")


def brief(e: Exception | None) -> str:
    """로그용 짧은 오류 설명(키 값은 들어가지 않음)."""
    if e is None:
        return "-"
    status = getattr(e, "status_code", None)
    return f"{type(e).__name__}{f' {status}' if status else ''}: {str(e)[:200]}"


def text_of(resp) -> str:
    """응답의 글(text) 블록만 이어 붙인다. 생각(thinking) 블록이 앞에 올 수 있어 종류로 고른다."""
    return "".join(b.text for b in resp.content if b.type == "text").strip()


class LLM:
    def __init__(self, s: Settings):
        self.s = s
        # 재시도는 SDK 가 아니라 여기서 키를 바꿔 가며 한다(정해진 시간 안에서)
        self.clients = [(name, anthropic.AsyncAnthropic(api_key=key, base_url=s.anthropic_base_url, max_retries=0))
                        for name, key in s.anthropic_keys()]
        self.grok = Grok(s) if s.xai_api_key else None  # 모델 이름이 비어도 --check 로 쓸 수 있는 모델을 볼 수 있게 만듦

    async def close(self) -> None:
        for _, client in self.clients:
            await client.close()
        if self.grok:
            await self.grok.close()

    async def create(self, body: dict, timeout: float, grok: bool = False):
        """body 는 Claude 모양. grok 이면 Grok 에 먼저 보낸다(Grok 이 실패하면 Claude 로)."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        last: Exception | None = None
        tries = ([("Grok", None)] if grok and self.grok and self.s.xai_model else []) + self.clients
        for i, (name, client) in enumerate(tries):
            # 남은 시간을 남은 키끼리 나눔: 첫 키가 멈춰도 백업 키 시간을 남김. Grok 은 생각이 길 수 있어 두 몫(남은 시간의 절반)
            shares = [2 if c is None else 1 for _, c in tries[i:]]
            per_try = (end - loop.time()) * shares[0] / sum(shares)
            if per_try < 1:
                break
            try:
                if client is None:
                    return await self.grok.create(body, per_try)
                return await self._once(client, body, per_try)
            except GrokError as e:  # 키·크레딧·모델 이름·장애: 같은 요청을 Claude 로
                last = e
            except anthropic.BadRequestError as e:
                if "credit" not in str(e).lower():  # 요청 자체가 잘못됨: 다른 키로 보내도 같음(크레딧 부족만 다음 키로)
                    raise
                last = e
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:  # 시간 초과도 여기(APITimeoutError)
                last = e
            log.warning("%s %s 실패(%s) → 다음 키", "xai" if client is None else "anthropic", name, brief(last))
        raise last or TimeoutError("Claude 호출 시간이 모자람")

    @staticmethod
    async def _once(client, body: dict, timeout: float):
        return await client.messages.create(**body, timeout=timeout)

    async def check_keys(self) -> list[tuple[str, str]]:
        """--check 용: 키를 하나씩 따로 시험한다(effort low, 짧은 답)."""
        body = {"model": self.s.anthropic_model, "max_tokens": 2000, "output_config": {"effort": "low"},
                "messages": [{"role": "user", "content": "연결 시험이야. '응'이라고만 답해."}]}
        out = []
        for name, client in self.clients:
            try:
                resp = await self._once(client, body, self.s.llm_timeout_s)
                out.append((name, f"정상: {text_of(resp)[:40]}"))
            except Exception as e:
                out.append((name, f"실패: {brief(e)}"))
        return out

    async def check_grok(self) -> tuple[str, list[str]]:
        """--check 용: Grok 키로 쓸 수 있는 모델 목록을 받고, 모델 이름이 있으면 짧은 답도 받아 본다. 키가 없으면 ('', [])."""
        if not self.grok:
            return "", []
        try:
            models = await self.grok.models(self.s.llm_timeout_s)
        except Exception as e:
            return f"실패: {brief(e)}", []
        if not self.s.xai_model:
            return "모델 이름(XAI_MODEL)이 비어 있음", models
        body = {"model": self.s.anthropic_model, "max_tokens": 2000,
                "messages": [{"role": "user", "content": "연결 시험이야. '응'이라고만 답해."}]}
        try:
            return f"정상: {text_of(await self.grok.create(body, self.s.llm_timeout_s))[:40]}", models
        except Exception as e:
            return f"실패: {brief(e)}", models
