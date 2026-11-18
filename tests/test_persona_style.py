"""TC-276 code and fallback checks, with synthetic inputs."""

from marong.style import check, fallback
from marong.agent import Agent
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


async def model_checks():
    settings = SimpleNamespace(llm_timeout_s=20, llm_max_tokens=200, anthropic_model="fixture")
    llm = SimpleNamespace(create_once=AsyncMock())
    agent = Agent(settings, None, None, llm)
    agent.friend_cards = SimpleNamespace(read=AsyncMock(return_value={"rules": [], "instruction": None}),
                                       record_run=AsyncMock())
    msg = SimpleNamespace(card_actor=1, is_channel=True)
    original = "5월 20일에 갈까? 저녁은 어때?"
    loop = asyncio.get_running_loop()
    answer, _ = await agent._review_reply(msg, {}, original, "같이 가자", loop.time()+7)
    assert answer == "5월 20일에 갈까?" and llm.create_once.await_count == 0
    llm.create_once.return_value = SimpleNamespace(stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="같이 갈까?")])
    answer, meta = await agent._review_reply(msg, {}, original, "같이 가자", loop.time()+9)
    assert answer == "5월 20일에 갈까?" and not meta["persona_check"]["rewrote"]
    assert agent.friend_cards.record_run.call_args.args[0].outcome == "invalid"
    llm.create_once.return_value = SimpleNamespace(stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="5월 20일에 갈까? 저녁 먹을까?")])
    answer, meta = await agent._review_reply(msg, {}, original, "같이 가자", loop.time()+9)
    assert answer == "5월 20일에 갈까?" and meta["persona_check"]["rewrote"]
    assert llm.create_once.await_count == 2
    answer, _ = await agent._review_reply(msg, {}, original, "먼저 말 걸기", loop.time()+7, proactive=True)
    assert answer == "" and llm.create_once.await_count == 2


def main():
    result = check("야 그거 웃기다 ㅋ (웃음)", name="보리", banned=("야",))
    assert result.text == "보리야 그거 웃기다 ㅋㅋ"
    assert set(result.fixed) == {"vocative", "single_k", "stage"}
    assert check("잘 들어 줄게 ㅋㅋ", difficult=True).text == "잘 들어 줄게"
    question = check("오늘은 뭐 했어? 저녁 먹었어? 나중에 뭐 할까?")
    assert question.issues == ("two_questions",)
    assert fallback(question) == "오늘은 뭐 했어?"
    assert fallback(question, proactive=True) == ""
    promise = check("동희한테 남겼어. 같이 이야기하자.", owner_asked=False)
    assert "capability" in promise.issues and fallback(promise) == "같이 이야기하자."
    assert fallback(check("바닷가 얘기 할까?", topics=("바닷가",))) == "응응"
    assert fallback(check("그 사람의 비공개 이름", private_labels=("비공개 이름",))) == "그건 나중에 둘이 얘기하자"
    assert fallback(check("죽고 싶은 마음까지 들어? 그 이야기는 듣고 있어.", safety_again=True)) == "그 이야기는 듣고 있어."
    assert "formal" not in check("좋아요. 고마워요.", polite=True).issues
    assert "formal" in check("좋아요. 고마워요.").issues
    asyncio.run(model_checks())
    print("TC-276 partial: rule correction, laughter, question cap, owner claim, scope and topic fallbacks")


if __name__ == "__main__":
    main()
