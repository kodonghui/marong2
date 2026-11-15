"""디스코드 DM에서 친구 메시지에 이모지 반응 달기(2026-11-15 동희님 "야 대화에서 하트 이런거도 눌러주고 그래라").
마롱이(Claude)가 답 맨 앞에 '[반응 ❤️]'를 쓰면, 그 표시는 글에서 빼고 친구가 보낸 메시지에 그 이모지 반응을 단다.
- 아래 REACTIONS 만 단다. 한숨 이모티콘(😮‍💨)처럼 친구가 싫어하는 건 목록에 없어서 써도 안 달린다.
- 너무 잦지 않게: 한 방에서 반응을 단 뒤에는 GAP_REPLIES 번 더 답할 때까지(또는 GAP_S 가 지날 때까지) 안내를 빼서
  반응을 안 단다. 그 사이에 표시가 나와도 빼기만 한다.
- 표시는 친구에게 가는 글과 대화 기록에 남지 않는다. 단 반응은 마롱이 답의 meta.reaction 에 남는다.
- 카카오와 선톡·알림에는 안내가 없다(카카오는 반응을 달 수 없음)."""
import re

# Discord 가 받는 모양 그대로(❤️ 은 U+2764 U+FE0F). 순서는 GUIDE 의 쓰임과 같다.
REACTIONS = ("❤️", "🥰", "😂", "🎉", "👏", "🔥", "🥹", "🫂", "😋", "👍", "👀", "🌰")
GAP_REPLIES = 3     # 반응을 단 뒤 이만큼 더 답할 때까지는 다시 안 닮(많아야 네 번에 한 번)
GAP_S = 1800        # 또는 반응을 단 지 이만큼(초) 지나면 다시 달 수 있음
ALONE_TEXT = "ㅎㅎ"  # 답이 표시뿐이고 이모지도 못 쓰는 것일 때 대신 보낼 말(드묾)
# '[반응 ❤️]', '[반응: ❤]', '[반응]', '(반응 😂)'. '[반응형 웹]'처럼 낱말에 붙은 건 아님. 안의 글은 짧게만 본다.
# 둥근 괄호는 안이 REACTIONS 의 이모지일 때만 표시로 본다('(반응 좋았어)' 같은 보통 말은 그대로).
MARK = re.compile(r"[\[(]\s*반응(?:(?:\s*[:：]|\s)\s*(?P<emoji>[^\[\]()\n]{0,24}?))?\s*[\])]")
GUIDE = """# 반응 달기 (이 DM에서만)
- 디스코드라서 친구 메시지에 이모지 반응을 하나 달 수 있어. 달고 싶으면 답 맨 앞에 [반응 ❤️]처럼 쓰고 이어서 답을 써. 이 표시는 글로 안 가고 친구 메시지에 반응으로 붙어.
- 친구 사이처럼 가끔만 달아. 대부분의 답에는 달지 말고, 친구 말에 마음이 움직였을 때만 달아: 다정한 말·고맙다는 말 ❤️ 🥰, 웃긴 말 😂, 좋은 소식·축하할 일 🎉, 해낸 일·열심히 한 일 👏 🔥, 뭉클한 말 🥹, 속상하거나 힘든 얘기 🫂, 맛있어 보이는 음식 😋, 약속을 정할 때 👍, 궁금해지는 얘기 👀, 밤·군밤 얘기 🌰.
- 반응은 하나만, 이 목록에서만 골라. 평범한 말·질문·짧은 대답에는 달지 마.
- 반응을 달아도 답은 꼭 같이 써. 죽고 싶다는 말처럼 아주 무거운 얘기에는 반응 없이 말로만 해."""


def _bare(emoji: str) -> str:
    return emoji.replace("\ufe0f", "").replace("\ufe0e", "").strip()  # 이모지 모양 선택 글자는 빼고 비교


ALLOWED = {_bare(e): e for e in REACTIONS}


def pick(raw: str | None) -> str | None:
    """표시 안의 글이 REACTIONS 의 이모지 하나면 Discord 가 받는 모양으로, 아니면 None."""
    return ALLOWED.get(_bare(raw)) if raw else None


def _marks(line: str) -> list[re.Match]:
    return [m for m in MARK.finditer(line) if m.group(0)[0] == "[" or pick(m.group("emoji"))]


def split(text: str) -> tuple[str, str | None]:
    """(표시를 모두 뺀 글, 첫 표시 안의 글('[반응]'이면 '') 또는 표시가 없으면 None). 표시만 있던 줄은 지우고,
    글 가운데 있던 표시는 빈칸 하나로 바꾼다. 표시가 없으면 글을 그대로 돌려준다."""
    first, lines = None, []
    for line in (text or "").split("\n"):
        found = _marks(line)
        if found:
            first = first or found[0]
            for m in reversed(found):
                line = line[:m.start()] + " " + line[m.end():]
            line = re.sub(r"[ \t]{2,}", " ", line).strip()
            if not line:
                continue
        lines.append(line)
    if first is None:
        return text, None
    out = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "\n".join(lines)).strip()
    return out, first.group("emoji") or ""
