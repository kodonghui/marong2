"""TC-276 code and fallback checks, with synthetic inputs."""

from marong.style import check, fallback


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
    print("TC-276 partial: rule correction, laughter, question cap, owner claim, scope and topic fallbacks")


if __name__ == "__main__":
    main()
