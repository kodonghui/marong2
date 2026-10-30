"""Grok(xAI) 호출. agent 가 만든 Claude 모양 요청을 xAI 의 OpenAI 호환 /chat/completions 모양으로 옮겨 보내고,
답을 Claude 응답과 같은 모양(content 블록·stop_reason·usage)으로 돌려준다. 그래서 agent 의 도구 처리는 그대로 쓴다.
effort·캐시 표시는 xAI 에 없어서 빼고, 생각(thinking) 블록은 보내지 않는다. 키 값은 로그·오류에 넣지 않는다."""
import asyncio
import json
import re
from types import SimpleNamespace

import httpx
from anthropic.types import TextBlock, ToolUseBlock

from .config import Settings

# xAI finish_reason → Claude stop_reason
STOP = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use", "content_filter": "refusal"}
KEY_LIKE = re.compile(r"xai-[A-Za-z0-9_-]+")


class GrokError(Exception):
    """xAI 호출 실패(키·크레딧·모델 이름·장애·시간 초과). 이걸 받으면 LLM 이 Claude 로 다시 보낸다."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(KEY_LIKE.sub("xai-…", message))
        self.status_code = status_code


def _get(block, name: str, default=None):
    """블록이 dict(agent 가 만든 것)든 객체(응답에서 온 것)든 같은 값을 읽는다."""
    return block.get(name, default) if isinstance(block, dict) else getattr(block, name, default)


def _text(content, sep: str = "\n") -> str:
    if isinstance(content, str):
        return content
    return sep.join(_get(b, "text") or "" for b in content or [] if _get(b, "type") == "text")


def _parts(blocks: list) -> str | list[dict]:
    """사용자 말: 글만 있으면 글 하나로, 사진이 있으면 글·사진 조각 목록으로."""
    parts = []
    for b in blocks:
        kind = _get(b, "type")
        if kind == "text":
            parts.append({"type": "text", "text": _get(b, "text") or ""})
        elif kind == "image":
            src = _get(b, "source") or {}
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:{_get(src, 'media_type')};base64,{_get(src, 'data')}"}})
    if all(p["type"] == "text" for p in parts):
        return "\n".join(p["text"] for p in parts)
    return parts


def to_chat(body: dict, model: str) -> dict:
    """Claude Messages 요청 → xAI chat/completions 요청."""
    messages = []
    if body.get("system"):
        messages.append({"role": "system", "content": _text(body["system"], "\n\n")})
    for m in body["messages"]:
        role, content = m["role"], m["content"]
        if role == "system":  # 빈 답일 때 다시 쓰게 하는 안내(EMPTY_NUDGE)
            messages.append({"role": "system", "content": _text(content)})
        elif role == "assistant":
            if isinstance(content, str):
                messages.append({"role": "assistant", "content": content})
                continue
            calls = [{"id": _get(b, "id"), "type": "function",
                      "function": {"name": _get(b, "name"),
                                   "arguments": json.dumps(_get(b, "input") or {}, ensure_ascii=False)}}
                     for b in content if _get(b, "type") == "tool_use"]
            text = "".join(_get(b, "text") or "" for b in content if _get(b, "type") == "text")
            out = {"role": "assistant", "content": text or (None if calls else "")}
            if calls:
                out["tool_calls"] = calls
            messages.append(out)
        elif isinstance(content, str):
            messages.append({"role": "user", "content": content})
        else:
            for r in (b for b in content if _get(b, "type") == "tool_result"):
                result = _text(_get(r, "content") or "")
                messages.append({"role": "tool", "tool_call_id": _get(r, "tool_use_id"),
                                 "content": f"(오류) {result}" if _get(r, "is_error") else result})
            rest = [b for b in content if _get(b, "type") != "tool_result"]
            if rest:
                messages.append({"role": "user", "content": _parts(rest)})
    out = {"model": model, "messages": messages}
    if body.get("max_tokens"):
        out["max_completion_tokens"] = body["max_tokens"]
    if body.get("tools"):
        out["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                                          "parameters": t["input_schema"]}} for t in body["tools"]]
    return out


def from_chat(data: dict, model: str) -> SimpleNamespace:
    """xAI 응답 JSON → Claude 응답처럼 읽는 객체(content·stop_reason·stop_details·usage·model)."""
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    blocks = []
    text = _text(msg.get("content") or "")
    if text.strip():
        blocks.append(TextBlock(type="text", text=text))
    for i, call in enumerate(msg.get("tool_calls") or []):
        fn = call.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = {}
        blocks.append(ToolUseBlock(type="tool_use", id=call.get("id") or f"call_{i}", name=fn.get("name") or "",
                                   input=args if isinstance(args, dict) else {}))
    if msg.get("refusal"):
        stop = "refusal"
    elif any(b.type == "tool_use" for b in blocks):
        stop = "tool_use"
    else:
        stop = STOP.get(choice.get("finish_reason"), "end_turn")
    usage = data.get("usage") or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return SimpleNamespace(
        provider="xai", model=data.get("model") or model, content=blocks, stop_reason=stop,
        stop_details=SimpleNamespace(category="grok") if stop == "refusal" else None,
        usage=SimpleNamespace(input_tokens=max((usage.get("prompt_tokens") or 0) - cached, 0),
                              output_tokens=usage.get("completion_tokens") or 0,
                              cache_read_input_tokens=cached, cache_creation_input_tokens=0))


class Grok:
    def __init__(self, s: Settings):
        self.model = s.xai_model
        self.http = httpx.AsyncClient(base_url=s.xai_base_url, headers={"Authorization": f"Bearer {s.xai_api_key}"})

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, path: str, timeout: float, **kw) -> dict:
        try:
            r = await asyncio.wait_for(self.http.request(method, path, timeout=timeout, **kw), timeout)
        except (httpx.HTTPError, asyncio.TimeoutError) as e:
            raise GrokError(f"{type(e).__name__}: 연결 실패 또는 시간 초과") from e
        if r.status_code != 200:
            try:
                err = r.json()
                detail = (err["error"] if isinstance(err, dict) and isinstance(err.get("error"), str)
                          else json.dumps(err, ensure_ascii=False))
            except ValueError:
                detail = r.text
            raise GrokError(f"HTTP {r.status_code}: {detail[:200]}", r.status_code)
        try:
            return r.json()
        except ValueError as e:
            raise GrokError("응답을 못 읽음") from e

    async def create(self, body: dict, timeout: float) -> SimpleNamespace:
        try:
            payload = to_chat(body, self.model)
        except Exception as e:  # 바꾸지 못하는 요청도 Claude 로 넘기게
            raise GrokError(f"요청을 xAI 모양으로 못 바꿈({type(e).__name__})") from e
        data = await self._call("POST", "/chat/completions", timeout, json=payload)
        try:
            return from_chat(data, self.model)
        except Exception as e:
            raise GrokError(f"응답 모양이 다름({type(e).__name__})") from e

    async def models(self, timeout: float) -> list[str]:
        data = await self._call("GET", "/models", timeout)
        return sorted(m.get("id", "") for m in data.get("data") or [])
