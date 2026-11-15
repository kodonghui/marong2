"""Claude API 호출(공식 anthropic SDK). 주 키가 실패(한도·크레딧·장애·시간 초과)하면 백업 키로 한 번 더 보낸다."""
import asyncio
import logging

import anthropic

from .config import Settings

log = logging.getLogger("llm")


def brief(e: Exception | None) -> str:
    """로그용 짧은 오류 설명(키 값은 들어가지 않음)."""
    if e is None:
        return "-"
    status = getattr(e, "status_code", None)
    return f"{type(e).__name__}{f' {status}' if status else ''}: {str(e)[:200]}"


# 서버 도구(웹 검색·웹 가져오기)는 Anthropic 서버가 돌리고, 그 호출과 결과가 응답 블록으로 같이 온다
SERVER_BLOCKS = {"server_tool_use", "web_search_tool_result", "web_fetch_tool_result"}


def text_of(resp) -> str:
    """응답의 글(text) 블록만 이어 붙인다. 생각(thinking) 블록이 앞에 올 수 있어 종류로 고른다.
    인용이 붙은 글은 블록 여러 개로 쪼개져 오므로 그대로 잇고, 서버 도구(웹 검색) 블록을 사이에 둔 글만 빈 줄로 나눈다."""
    parts, run = [], []
    for b in resp.content:
        if b.type == "text":
            run.append(b.text)
        elif b.type in SERVER_BLOCKS and run:
            parts.append("".join(run))
            run = []
    parts.append("".join(run))
    return "\n\n".join(p.strip() for p in parts if p.strip())


def server_tool_counts(usage) -> tuple[int, int]:
    """이 응답에서 서버가 한 (웹 검색, 웹 가져오기) 횟수. usage.server_tool_use 가 없으면 (0, 0)."""
    used = getattr(usage, "server_tool_use", None)
    if used is None:
        return 0, 0
    get = used.get if isinstance(used, dict) else (lambda key, default=None: getattr(used, key, default))
    return int(get("web_search_requests", 0) or 0), int(get("web_fetch_requests", 0) or 0)


class LLM:
    def __init__(self, s: Settings):
        self.s = s
        # 재시도는 SDK 가 아니라 여기서 키를 바꿔 가며 한다(정해진 시간 안에서)
        self.clients = [(name, anthropic.AsyncAnthropic(api_key=key, base_url=s.anthropic_base_url, max_retries=0))
                        for name, key in s.anthropic_keys()]

    async def close(self) -> None:
        for _, client in self.clients:
            await client.close()

    async def create(self, body: dict, timeout: float):
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        last: Exception | None = None
        for i, (name, client) in enumerate(self.clients):
            per_try = (end - loop.time()) / (len(self.clients) - i)  # 남은 시간을 남은 키끼리 나눔: 첫 키가 멈춰도 백업 키 시간을 남김
            if per_try < 1:
                break
            try:
                return await self._once(client, body, per_try)
            except anthropic.BadRequestError as e:
                if "credit" not in str(e).lower():  # 요청 자체가 잘못됨: 다른 키로 보내도 같음(크레딧 부족만 다음 키로)
                    raise
                last = e
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:  # 시간 초과도 여기(APITimeoutError)
                last = e
            log.warning("anthropic %s 실패(%s) → 다음 키", name, brief(last))
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
