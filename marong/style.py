"""보내기 전에 마롱이 말을 한 번 더 다듬는다. 친구가 여러 번 싫다고 한 버릇은 지시문만으로는 다시 나와서(11/15 정리)
코드로도 막는다. 지시문(prompt.md, agent.py 선톡 안내)에서도 같은 걸 하지 말라고 한다.
- 한숨 이모티콘(😮‍💨): 지운다.
- 이름 없이 '야'로 부르기('야 뭐해', '야!', '야ㅋㅋ'): 말풍선·줄 첫머리의 '야'는 1:1 에서 이름을 알면 처음 한 번만
  이름으로 바꾸고('현경아 뭐해'), 그 밖에는 뺀다. '야식', '야호', '3시야', '야라고'처럼 낱말에 붙은 '야'와 문장 가운데
  '야'는 그대로 둔다(문장 가운데서 빼면 '야 소리 안 할게' 같은 말이 깨짐)."""
import re

SIGH = re.compile("\U0001F62E️?‍\U0001F4A8️?")
# 줄 첫머리에 홀로 선 '야'(뒤에 한글 음절이 붙지 않음)와 뒤따르는 문장 부호·빈칸
LEADING_YA = re.compile(r"^(?P<lead>[ \t]*)(?:야)+(?![가-힣])(?P<punct>[!~,.?…]*)[ \t]*")
EMPTY_FALLBACK = "ㅠㅠ"
STAGE_FALLBACK = "응응"
REPEAT_SIMILARITY = 0.35
STAGE_MARK = re.compile(r"\([^()\r\n]{1,40}\)|（[^（）\r\n]{1,40}）|\*[^*\r\n]{1,30}\*")
STAGE_GESTURE = re.compile(
    r"(?:(?:살짝|조용히|작게|크게|괜히|슬쩍|가만히)[ \t]+)?"
    r"(?:웃음|미소|한숨|끄덕|침묵|하품|눈물|훌쩍|머쓱|갸웃|두리번|토닥|쓰담|꼬옥|멈칫|뻘쭘|빙긋|싱긋|생긋)[가-힣]{0,3}"
)


def _stage(text: str) -> bool:
    text = text.strip().rstrip(".…!~").rstrip()
    before_nida = text[-3:-2]
    # '-ㅂ니다'의 받침은 '립', '듭'처럼 앞 음절에 들어 있다.
    if text.endswith("니다") and "가" <= before_nida <= "힣" and (ord(before_nida) - 0xAC00) % 28 == 17:
        return True
    return (len(text) <= 12 and text.endswith(("며", "면서"))) or bool(STAGE_GESTURE.fullmatch(text))


def _bigrams(text: str, name: str | None) -> set[tuple[str, str]]:
    text = text.casefold()
    name = " ".join((name or "").casefold().split())
    if len(name) > 2 and name.endswith("이"):
        name = name[:-1]
    if name:
        text = re.sub(rf"(?<!\w){re.escape(name)}(?:아|야|이)?(?!\w)", "", text)
    letters = "".join(ch for ch in text if ch.isalnum())
    return set(zip(letters, letters[1:]))


def repeat_similarity(left: str, right: str, name: str | None = None) -> float:
    """친구 이름을 뺀 글자 바이그램 집합의 자카드 유사도."""
    a, b = _bigrams(left, name), _bigrams(right, name)
    return len(a & b) / len(a | b) if a and b else 0.0


def vocative(name: str | None) -> str | None:
    """'현경' → '현경아', '동희' → '동희야'. 한글 이름이 아니면 None(그때는 '야'를 빼기만 함)."""
    name = " ".join(str(name or "").split())
    if len(name) > 2 and name.endswith("이"):  # '현경이' → '현경'
        name = name[:-1]
    last = name[-1:]
    if not ("가" <= last <= "힣"):
        return None
    return name + ("아" if (ord(last) - 0xAC00) % 28 else "야")


def tidy(text: str, name: str | None = None, *, stage_fallback: str = STAGE_FALLBACK) -> tuple[str, list[str]]:
    """(다듬은 말, 고친 것: 'sigh'·'stage'·'ya'). name 은 1:1 에서 부를 친구 이름."""
    if not text:
        return text, []
    fixes: list[str] = []
    out = SIGH.sub("", text)
    if out != text:
        fixes.append("sigh")
        out = "\n".join(re.sub(r"[ \t]{2,}", " ", line).rstrip() for line in out.split("\n"))
    plain = STAGE_MARK.sub(lambda match: "" if _stage(match[0][1:-1]) else match[0], out)
    if plain != out:
        fixes.append("stage")
        if not plain.strip():
            return stage_fallback, fixes
        out = "\n".join(re.sub(r"[ \t]{2,}", " ", line).strip() for line in plain.split("\n"))
    call = vocative(name)
    lines = []
    for line in out.split("\n"):
        m = LEADING_YA.match(line)
        if m:
            rest = line[m.end():]
            if call:  # 처음 한 번만 이름으로 부르고, 그다음 줄들은 빼기만 함
                line = m.group("lead") + call + m.group("punct") + (" " + rest if rest else "")
                call = None
            else:
                line = m.group("lead") + rest
            if "ya" not in fixes:
                fixes.append("ya")
        lines.append(line)
    if "ya" in fixes or "stage" in fixes:
        out = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "\n".join(lines))  # 지운 줄 때문에 빈 줄이 겹치지 않게
    out = out.strip()
    return (out or EMPTY_FALLBACK), fixes
