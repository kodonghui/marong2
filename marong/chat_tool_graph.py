"""Run each chat reply through separate model and tool execution nodes."""

import asyncio
from functools import lru_cache
import logging
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langsmith import tracing_context

from tools.vertex_live.tool_trace import app_parent, step as trace_step

from .llm import text_of

log = logging.getLogger("agent")


class Route(TypedDict):
    next: Literal["model", "tools", "finish"]


class Turn:
    def __init__(self, agent, msg, system, messages, tools, deadline, trace, texts, server_counts, server_blocks):
        self.agent, self.msg = agent, msg
        self.system, self.messages, self.tools = system, list(messages), tools
        self.loop, self.deadline, self.trace = asyncio.get_running_loop(), deadline, trace
        self.nudge, self.fallback, self.refusal = texts
        self.server_counts, self.server_blocks = server_counts, server_blocks
        self.llm, self.alternate = agent._llm_for(msg.room_key) if server_counts else (agent.llm, None)
        self.meta = {
            "model": self.alternate or agent.s.anthropic_model,
            "effort": (agent.route.effort if self.alternate else agent.s.anthropic_effort) or None,
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
        }
        self.said: list[tuple[str, bool]] = []
        self.nudged = False
        self.pending = []
        self.assistant_blocks = []
        self.results_waiting = 0
        self.answer = self.fallback

    async def model(self) -> Route:
        round_number = self.meta["calls"] + 1
        remaining = self.deadline - self.loop.time()
        if remaining <= 0:
            raise TimeoutError("chat deadline reached")
        body = self.agent._body(self.system, self.messages, self.tools)
        with trace_step("model_request", self.trace, round=round_number, offered=len(self.tools),
                        results_attempted=self.results_waiting) as request:
            if request:
                request.io(inputs={"request": body})
            response = await self.llm.create(body, remaining)
            usage = response.usage
            searches, fetches = self.server_counts(usage) if self.server_counts else (0, 0)
            self.pending = [block for block in response.content if block.type == "tool_use"]
            if request:
                request.io(outputs={"response": {"role": "assistant", "content": response.content}})
                request.record(stop_reason=response.stop_reason, requested=len(self.pending),
                               results_sent=self.results_waiting, web_searches=searches, web_fetches=fetches)
                if response.stop_reason == "tool_use" and not self.pending:
                    request.record(result="no_tool_blocks")
        self.results_waiting = 0
        served = getattr(response, "served_model", None)
        if self.alternate and served and served != self.alternate:
            self.llm, self.alternate = self.agent.llm, None
            self.meta.update(model=served, effort=self.agent.s.anthropic_effort or None, fallback="deepseek")
        if self.server_counts and not self.alternate:
            self.agent._cache_used(body, usage, self.meta)
        self.meta["calls"] = round_number
        self.meta["stop_reason"] = response.stop_reason
        self.meta["input_tokens"] += usage.input_tokens or 0
        self.meta["output_tokens"] += usage.output_tokens or 0
        self.meta["cache_read_tokens"] += getattr(usage, "cache_read_input_tokens", None) or 0
        self.meta["cache_write_tokens"] += getattr(usage, "cache_creation_input_tokens", None) or 0
        if searches:
            self.meta["web_searches"] = self.meta.get("web_searches", 0) + searches
        if fetches:
            self.meta["web_fetches"] = self.meta.get("web_fetches", 0) + fetches
        server = any(block.type in self.server_blocks for block in response.content)
        if server or searches or fetches:
            self.agent._server_tools_used(self.msg, response, searches, fetches)

        if response.stop_reason == "refusal":
            self.meta["refusal"] = getattr(getattr(response, "stop_details", None), "category", None)
            log.info("refusal category=%s", self.meta["refusal"])
            self.answer = self.refusal
            return {"next": "finish"}

        text = text_of(response)
        if response.stop_reason == "pause_turn" and self.server_counts:
            if text:
                self.said.append((text, True))
            self.messages = [*self.messages, {"role": "assistant", "content": response.content}]
            return {"next": "model"}
        if response.stop_reason == "tool_use":
            if text:
                self.said.append((text, server))
            if self.pending:
                self.assistant_blocks = response.content
                return {"next": "tools"}
            self.answer = "\n\n".join(t for t, _ in self.said) or self.fallback
            return {"next": "finish"}
        if text:
            self.answer = "\n\n".join([t for t, keep in self.said if keep] + [text])
        elif self.said:
            self.answer = "\n\n".join(t for t, _ in self.said)
        else:
            if response.stop_reason == "max_tokens":
                log.warning("stop_reason=max_tokens without response text")
            if not self.nudged:
                self.messages = [*self.messages, {"role": "system", "content": self.nudge}]
                self.nudged = True
                return {"next": "model"}
        return {"next": "finish"}

    async def tools_node(self):
        round_number = self.meta["calls"]
        with trace_step("tool_node", self.trace, round=round_number, requested=len(self.pending)) as node:
            results = []
            for block in self.pending:
                if self.loop.time() >= self.deadline:
                    raise TimeoutError("chat deadline reached")
                with trace_step("tool_dispatch", node, round=round_number, tool=block.name) as dispatch:
                    if dispatch:
                        dispatch.io(inputs={"arguments": block.input})
                    outcome = await self.agent._run_tool(block, self.msg)
                    if dispatch:
                        dispatch.io(outputs={"response": outcome})
                        dispatch.record(
                            result=("rejected" if outcome.get("is_error") else "ok") if isinstance(outcome, dict)
                            else "invalid_result",
                            offered=int(any(tool.get("name") == block.name for tool in self.tools)),
                        )
                    results.append(outcome)
            # Keep every original assistant block, including provider-signed thinking.
            self.messages = [*self.messages, {"role": "assistant", "content": self.assistant_blocks},
                             {"role": "user", "content": results}]
            self.results_waiting = len(results)


async def model_node(state: Route, runtime: Runtime[Turn]) -> Route:
    return await runtime.context.model()


async def tools_node(state: Route, runtime: Runtime[Turn]) -> Route:
    await runtime.context.tools_node()
    return {"next": "model"}


@lru_cache(maxsize=1)
def graph():
    return (StateGraph(Route, context_schema=Turn)
            .add_node("model", model_node)
            .add_node("tools", tools_node)
            .add_edge(START, "model")
            .add_conditional_edges("model", lambda state: state["next"],
                                   {"model": "model", "tools": "tools", "finish": END})
            .add_edge("tools", "model")
            .compile())


async def answer_with_tools(agent, msg, system, messages, tools, end, *, texts,
                            server_counts=None, server_blocks=()):
    surface = {"app": "app_chat", "discord": "discord_chat"}.get(getattr(msg, "via", None), "kakao_chat")
    with trace_step("text_turn", app_parent(), surface=surface) as trace:
        turn = Turn(agent, msg, system, messages, tools, end, trace, texts, server_counts, server_blocks)
        # Graph state carries only routing decisions. The provider request and tool values stay in memory.
        with tracing_context(enabled=False):
            async with asyncio.timeout_at(end):
                await graph().ainvoke({"next": "model"}, context=turn)
        return turn.answer, turn.meta
