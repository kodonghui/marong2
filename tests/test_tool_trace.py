"""Trace the real dispatch code with fake provider messages and storage."""

import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import WSMsgType
import anthropic
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools" / "vertex_live")]

from fakes import ScriptedLLM, message, text, thinking, tool_use
from live_session import LiveSession
from marong.agent import Agent, Incoming
from tools.vertex_live import tool_trace as text_trace
import tool_trace as voice_trace


PRIVATE_FIXTURE = "PRIVATE_FIXTURE_42"


class Captured:
    def __init__(self):
        self.traces = []

    def submit(self, runs):
        self.traces.append(runs)


class Upstream:
    def __init__(self, calls, disconnect=False):
        self.calls = calls
        self.disconnect = disconnect
        self.sent = asyncio.Queue()

    async def __aiter__(self):
        yield SimpleNamespace(type=WSMsgType.TEXT, data=json.dumps({"toolCall": {"functionCalls": self.calls}}))
        await asyncio.Future()

    async def send_json(self, payload):
        if self.disconnect:
            await self.sent.put(None)
            raise ConnectionError(PRIVATE_FIXTURE)
        await self.sent.put(payload)


class ToolTraceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.capture = Captured()
        for tracing in (text_trace, voice_trace):
            self.enterContext(patch.object(tracing, "_sink", return_value=self.capture))

    def tearDown(self):
        data = json.dumps(self.capture.traces)
        self.assertNotIn(PRIVATE_FIXTURE, data)
        for root, *children in self.capture.traces:
            self.assertTrue(root["end_time"])
            ids = {run["id"] for run in [root, *children]}
            for child in children:
                self.assertEqual(child["trace_id"], root["id"])
                self.assertIn(child["parent_run_id"], ids)

    def text_agent(self, respond):
        options = SimpleNamespace(anthropic_model="fixture", llm_max_tokens=100, anthropic_effort=None)
        store = SimpleNamespace(set_name=AsyncMock())
        with patch.dict(os.environ, {"MARONG_FRIEND_CARD": "off", "MARONG_SAFETY": "off"}):
            return Agent(options, store, None, ScriptedLLM(respond))

    async def ask(self, agent):
        deadline = asyncio.get_running_loop().time() + 2
        incoming = Incoming(PRIVATE_FIXTURE, PRIVATE_FIXTURE, PRIVATE_FIXTURE)
        return await agent.ask([], [{"role": "user", "content": PRIVATE_FIXTURE}], incoming, deadline)

    async def test_text_dispatch_then_confirm_result_return(self):
        def respond(body):
            if len(body["messages"]) == 1:
                return message([tool_use("set_name", {"name": PRIVATE_FIXTURE}, PRIVATE_FIXTURE)], "tool_use")
            self.assertEqual(body["messages"][-1]["content"][0]["tool_use_id"], PRIVATE_FIXTURE)
            return message([text(PRIVATE_FIXTURE)])

        agent = self.text_agent(respond)
        self.assertEqual((await self.ask(agent))[0], PRIVATE_FIXTURE)
        agent.store.set_name.assert_awaited_once()
        root, first, tool_node, dispatch, followup = self.capture.traces[0]
        self.assertEqual(root["outputs"]["surface"], "kakao_chat")
        self.assertEqual(first["outputs"]["requested"], 1)
        self.assertEqual(dispatch["outputs"], {"round": 1, "tool": "set_name", "offered": 1, "result": "ok"})
        self.assertEqual(dispatch["parent_run_id"], tool_node["id"])
        self.assertEqual(followup["outputs"]["results_sent"], 1)

    async def test_text_unknown_tool_and_provider_400_after_result(self):
        class Rejected(Exception):
            status_code = 400

        def respond(body):
            if len(body["messages"]) == 1:
                return message([tool_use(PRIVATE_FIXTURE, {})], "tool_use")
            return Rejected(PRIVATE_FIXTURE)

        with self.assertRaises(Rejected):
            await self.ask(self.text_agent(respond))
        _, _, _, dispatch, followup = self.capture.traces[0]
        self.assertEqual(dispatch["outputs"]["tool"], "other")
        self.assertEqual(dispatch["outputs"]["offered"], 0)
        self.assertEqual(dispatch["outputs"]["result"], "rejected")
        self.assertEqual(followup["outputs"]["results_attempted"], 1)
        self.assertNotIn("results_sent", followup["outputs"])
        self.assertEqual(followup["outputs"]["status_code"], 400)
        self.assertEqual(followup["error"], "provider_http_error")

    async def test_text_graph_returns_every_tool_result_after_six_rounds(self):
        def respond(body):
            turn = (len(body["messages"]) - 1) // 2
            if turn:
                result = body["messages"][-1]["content"][0]
                self.assertEqual(result["tool_use_id"], f"tool-{turn}")
                self.assertFalse(result.get("is_error"))
            if turn < 6:
                return message([tool_use("set_name", {"name": "가명"}, f"tool-{turn + 1}")], "tool_use")
            return message([text("확인했어")])

        agent = self.text_agent(respond)
        answer, meta = await self.ask(agent)
        self.assertEqual(answer, "확인했어")
        self.assertEqual(meta["calls"], 7)
        self.assertEqual(agent.store.set_name.await_count, 6)
        root, *children = self.capture.traces[0]
        self.assertNotIn("error", root)
        self.assertEqual(sum(row["name"] == "tool_node" for row in children), 6)
        self.assertEqual(children[-1]["name"], "model_request")
        self.assertEqual(children[-1]["outputs"]["results_sent"], 1)

    async def test_repeated_tools_stop_at_existing_deadline(self):
        agent = self.text_agent(lambda body: message([tool_use("set_name", {"name": "가명"})], "tool_use"))
        original = agent.llm.create

        async def slow_create(body, timeout):
            await asyncio.sleep(0.015)
            return await original(body, timeout)

        agent.llm.create = slow_create
        deadline = asyncio.get_running_loop().time() + 0.10
        with self.assertRaises(TimeoutError):
            await agent.ask([], [], Incoming(PRIVATE_FIXTURE, PRIVATE_FIXTURE, "시험"), deadline)
        root, *_ = self.capture.traces[0]
        self.assertEqual(root["error"], "timeout")

    async def test_tool_batch_preserves_signed_blocks_and_returns_every_result(self):
        original = [thinking("fixture"), tool_use("set_name", {"name": "하나"}, "first"),
                    tool_use("set_name", {"name": "둘"}, "second")]

        def respond(body):
            if len(body["messages"]) == 1:
                return message(original, "tool_use")
            assistant, tool_reply = body["messages"][-2:]
            self.assertEqual(assistant["role"], "assistant")
            self.assertEqual([vars(block) for block in assistant["content"]], original)
            self.assertEqual(tool_reply["role"], "user")
            self.assertEqual([block["tool_use_id"] for block in tool_reply["content"]], ["first", "second"])
            return message([text("둘 다 받았어")])

        answer, meta = await self.ask(self.text_agent(respond))
        self.assertEqual((answer, meta["calls"]), ("둘 다 받았어", 2))
        self.assertEqual(self.capture.traces[0][-1]["outputs"]["results_sent"], 2)

    async def test_malformed_tool_stop_does_not_send_an_empty_tool_response(self):
        agent = self.text_agent(lambda body: message([], "tool_use"))
        _, meta = await self.ask(agent)
        agent.store.set_name.assert_not_awaited()
        self.assertEqual(meta["calls"], 1)
        self.assertEqual(self.capture.traces[0][-1]["outputs"]["result"], "no_tool_blocks")

    async def test_provider_sdk_timeout_is_marked_at_model_request(self):
        url = "https://example.invalid/" + PRIVATE_FIXTURE
        agent = self.text_agent(lambda body: anthropic.APITimeoutError(request=httpx.Request("POST", url)))
        with self.assertRaises(anthropic.APITimeoutError):
            await self.ask(agent)
        _, request = self.capture.traces[0]
        self.assertEqual(request["error"], "timeout")

    async def run_voice(self, execute, disconnect=False):
        upstream = Upstream([{"name": "recall", "id": PRIVATE_FIXTURE,
                              "args": {"query": PRIVATE_FIXTURE}}], disconnect)
        session = LiveSession(None, None, None, None, None, None, {}, {}, None, None, None, None,
                              entry_transport="discord")
        session.recorder = SimpleNamespace(boundary=lambda *args: None)
        with patch("live_session.execute_tool", execute):
            provider = asyncio.create_task(session.provider(upstream))
            try:
                return await asyncio.wait_for(upstream.sent.get(), timeout=1)
            finally:
                session.stop.set()
                await asyncio.wait_for(provider, timeout=1)

    async def test_voice_dispatch_timeout_and_successful_fallback_delivery(self):
        response = await self.run_voice(AsyncMock(side_effect=TimeoutError(PRIVATE_FIXTURE)))
        self.assertEqual(response["toolResponse"]["functionResponses"][0]["response"],
                         {"result": "not_saved", "reason": "temporary_error"})
        root, dispatch, sent = self.capture.traces[0]
        self.assertEqual(root["outputs"]["result"], "temporary_error")
        self.assertEqual(dispatch["error"], "timeout")
        self.assertEqual(sent["outputs"]["results_sent"], 1)

    async def test_voice_execution_success_then_socket_error(self):
        response = await self.run_voice(
            AsyncMock(return_value={"result": "found", "items": [PRIVATE_FIXTURE]}), disconnect=True)
        self.assertIsNone(response)
        root, dispatch, sent = self.capture.traces[0]
        self.assertEqual(root["outputs"]["surface"], "discord_voice")
        self.assertEqual(dispatch["outputs"]["result"], "found")
        self.assertEqual(sent["error"], "connection_error")
        self.assertNotIn("results_sent", sent["outputs"])


if __name__ == "__main__":
    unittest.main()
