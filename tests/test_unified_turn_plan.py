"""Synthetic cases for the deterministic planner and bounded tool graph."""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from fakes import ScriptedLLM, message, text, tool_use
from marong.chat_tool_graph import answer_with_tools
from marong.turn_plan import plan_turn


class PlanTests(unittest.TestCase):
    def test_labeled_fixture_prompts(self):
        now = datetime(2026, 11, 19, 12, tzinfo=ZoneInfo("Asia/Seoul"))
        tools = {"schedule_list", "schedule_add", "web_search", "web_fetch"}
        windows = [
            ("다음 달 일정 알려 줘", (date(2026, 12, 1), date(2026, 12, 31))),
            ("이번 달의 약속 보여 줘", (date(2026, 11, 1), date(2026, 11, 30))),
            ("지난달 일정 확인해 줘", (date(2026, 10, 1), date(2026, 10, 31))),
            ("다음 주 일정 있나", (date(2026, 11, 23), date(2026, 11, 29))),
            ("이번 주 일정 조회", (date(2026, 11, 16), date(2026, 11, 22))),
            ("11월 26일부터 29일까지 일정 조회", (date(2026, 11, 26), date(2026, 11, 29))),
            ("12월 일정 뭐 있어", (date(2026, 12, 1), date(2026, 12, 31))),
            ("내일 일정 알려 줘", (date(2026, 11, 20), date(2026, 11, 20))),
            ("모레 약속 확인", (date(2026, 11, 21), date(2026, 11, 21))),
            ("2027년 2월 일정", (date(2027, 2, 1), date(2027, 2, 28))),
        ]
        groups = {
            "schedule_write": [
                "내일 약속 추가해 줘", "일정 취소해", "모레 알림 저장", "약속 날짜 변경해 줘",
                "10분 뒤에 알려 줘", "아침 8시에 깨워 줘", "일정 등록해 줘", "알림 지워 줘",
                "다음 달 약속 기억해 줘", "내일 3시에 연락해 줘",
            ],
            "shop": [
                "이 상품 찾아 줘", "재킷 가격 알아봐", "최저가 검색해 줘", "쇼핑 도와 줘",
                "이 상품 비교해줘", "이 안경 구매하려고", "장바구니에 있던 상품 봐 줘",
                "옷 가격 목록이 있나", "이 책 가격을 같이 봐 줘", "구매할 만한 신발 골라 줘",
            ],
            "search": [
                "오늘 날씨 알려 줘", "인터넷으로 찾아 봐", "뉴스 좀 보여 줘", "고양이 검색해 줘",
                "내일 부산 날씨", "요즘 뉴스 뭐 있나", "인터넷 이용자 통계 찾아 봐",
                "전시회 운영 시간 검색", "기상 뉴스 봐 줘", "올해 수상자 찾아봐",
            ],
            "memory": [
                "지난번에 무슨 이야기 했더라", "전에 말한 거 기억해?", "그 사람 기억나?",
                "전에 말했지 않나", "지난번에 먹었던 거", "우리 기억나?", "전에 말하던 그 책",
                "지난번에 만든 그림 기억해", "전에 말한 여행지", "네가 기억나는 얘기 해줘",
            ],
            "chat": [
                "안녕", "뭐 하고 있었어?", "오늘 힘들었어", "잠깐 얘기하자", "너무 졸려",
                "그렇구나", "고마워", "어제 늦게 잤어", "같이 생각하자", "이게 내 취향이야",
            ],
        }
        for prompt, expected in windows:
            with self.subTest(prompt=prompt):
                result = plan_turn(prompt, (), tools, now)
                self.assertEqual((result.intents, result.window), (("schedule_read",), expected))
        for intent, prompts in groups.items():
            for prompt in prompts:
                with self.subTest(prompt=prompt):
                    self.assertEqual(plan_turn(prompt, (), tools, now).intents, (intent,))
                    self.assertIsNone(plan_turn(prompt, (), tools, now).window)
        long = plan_turn("1월 1일부터 12월 31일까지 일정 확인", (), tools, now)
        self.assertEqual((long.window[1] - long.window[0]).days + 1, 62)
        follow = plan_turn("그럼 다음 주는 뭐 있어?", ("이번 주 일정 확인",), tools, now)
        self.assertEqual(follow.window, windows[3][1])
        self.assertEqual(plan_turn(windows[0][0], (), set(), now).intents, ("chat",))


class GraphTests(unittest.IsolatedAsyncioTestCase):
    async def run_graph(self, responses):
        invoked = []
        model = ScriptedLLM(lambda body: next(responses))
        agent = SimpleNamespace(
            llm=model, s=SimpleNamespace(anthropic_model="fixture", anthropic_effort=None),
            _body=lambda system, messages, tools: {"messages": messages, **({"tools":tools} if tools else {})},
        )
        msg = SimpleNamespace(via="app", schedule_rows=[{"id": 7}], shown_schedule_ids=set())
        async def run_tool(block, subject):
            invoked.append((block.name, block.input))
            if block.name == "schedule_list":
                subject.shown_schedule_ids.add(17)
            return {"type": "tool_result", "tool_use_id": block.id, "content": "fixture tool result"}
        agent._run_tool = run_tool
        reply, meta = await answer_with_tools(
            agent, msg, [], [{"role": "user", "content": "fixture"}],
            [{"name": name} for name in ("schedule_cancel", "schedule_list", "schedule_add")],
            asyncio.get_running_loop().time() + 5, texts=("nudge", "fallback", "refusal"),
        )
        return reply, meta, model.bodies, invoked

    async def test_permissions_and_quota_preserve_tool_results(self):
        first = [
            tool_use("not_available", {}, "unknown"),
            tool_use("schedule_cancel", {"id": 17}, "not_shown"),
            tool_use("schedule_list", {}, "list"),
            tool_use("schedule_cancel", {"id": 17}, "shown"),
            *[tool_use("schedule_add", {}, f"addition-{i}") for i in range(10)],
        ]
        reply, meta, bodies, invoked = await self.run_graph(iter([
            message(first, "tool_use"), message([text("fixture done")]),
        ]))
        self.assertEqual(reply, "fixture done")
        self.assertEqual(meta["calls"], 2)
        self.assertEqual(len(invoked), 8)
        self.assertEqual(invoked[0][0], "schedule_list")
        self.assertEqual(invoked[1], ("schedule_cancel", {"id": 17}))
        self.assertNotIn("tools", bodies[-1])
        outcomes = {r["tool_use_id"]: r["content"] for r in bodies[-1]["messages"][-1]["content"]}
        self.assertEqual(len(outcomes), len(first))
        self.assertEqual(outcomes["unknown"], "unknown_tool")
        self.assertEqual(outcomes["not_shown"], "not_shown")
        self.assertEqual(outcomes["addition-9"], "turn_limit")

    async def test_sixth_model_call_receives_final_result_without_tools(self):
        reply, meta, bodies, invoked = await self.run_graph(iter(
            [message([tool_use("schedule_add", {}, f"call-{i}")], "tool_use") for i in range(5)] +
            [message([text("fixture final")])]
        ))
        self.assertEqual((reply, meta["calls"], len(invoked)), ("fixture final", 6, 5))
        self.assertNotIn("tools", bodies[-1])
        self.assertEqual(bodies[-1]["messages"][-1]["content"][0]["tool_use_id"], "call-4")


if __name__ == "__main__":
    unittest.main()
