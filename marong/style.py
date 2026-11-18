"""보내기 전에 마롱이 말을 한 번 더 다듬는다. 친구가 여러 번 싫다고 한 버릇은 지시문만으로는 다시 나와서(11/15 정리)
코드로도 막는다. 지시문(prompt.md, agent.py 선톡 안내)에서도 같은 걸 하지 말라고 한다.
- 한숨 이모티콘(😮‍💨): 지운다.
- 이름 없이 '야'로 부르기('야 뭐해', '야!', '야ㅋㅋ'): 말풍선·줄 첫머리의 '야'는 1:1 에서 이름을 알면 처음 한 번만
  이름으로 바꾸고('현경아 뭐해'), 그 밖에는 뺀다. '야식', '야호', '3시야', '야라고'처럼 낱말에 붙은 '야'와 문장 가운데
  '야'는 그대로 둔다(문장 가운데서 빼면 '야 소리 안 할게' 같은 말이 깨짐)."""
import re
from dataclasses import dataclass

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


SINGLE_K = re.compile(r"(?<!ㅋ)ㅋ(?!ㅋ)")
SENTENCES = re.compile(r"[^.!?。\n]+[.!?。]*")
GENTLE_COUNSEL = re.compile(r"(?<!\d)(?:109|119)(?!\d)|상담전화|상담사|병원")
SAFETY_QUESTION = re.compile(r"죽고\s*싶은\s*마음")
PROMISED_OWNER = re.compile(r"동희한테\s*(?:남겼|말해\s*뒀|전했)")
NO_ALTERNATIVE = re.compile(r"못\s*해|안\s*돼|할\s*수\s*없어")
ALTERNATIVE = re.compile(r"대신|해\s*줄까|켜\s*달라고")
FORMAL = re.compile(r"(?:요|니다|세요)\s*(?=[.!?。\n]|$)")


@dataclass(frozen=True)
class Review:
    text: str
    issues: tuple[str, ...]
    fixed: tuple[str, ...]


def check(text, *, name=None, banned=(), topics=(), recent=(), private_labels=(), difficult=False,
          safety_again=False, counsel_allowed=True, tired=False, polite=False, owner_asked=False,
          capability_on=False, code_only=False):
    fixed = []
    alternative = vocative(name)
    for token in banned:
        if not token:
            continue
        leading = re.compile(r"(?m)^([ \t]*)" + re.escape(token) + r"(?=$|[^가-힣])")
        replaced = leading.sub(lambda match: match[1] + (alternative or ""), text)
        if replaced != text and "vocative" not in fixed:
            fixed.append("vocative")
        text = replaced
    text, tidy_fixed = tidy(text, name, stage_fallback=STAGE_FALLBACK)
    fixed.extend(tidy_fixed)
    if difficult:
        plain = "\n".join(line.replace("ㅋ", "").strip() for line in text.splitlines()).strip()
        if plain != text:
            fixed.append("hard_k")
        text = plain or STAGE_FALLBACK
    else:
        text, count = SINGLE_K.subn("ㅋㅋ", text)
        if count:
            fixed.append("single_k")
    if code_only:
        return Review(text, (), tuple(fixed))
    issues = []
    if len(text) >= 15 and any(repeat_similarity(text, old, name) >= REPEAT_SIMILARITY for old in recent):
        issues.append("repeat")
    if text.count("?") + text.count("？") >= 2:
        issues.append("two_questions")
    if not owner_asked and PROMISED_OWNER.search(text) or (
        capability_on and NO_ALTERNATIVE.search(text) and not ALTERNATIVE.search(text)
    ):
        issues.append("capability")
    if any(label and label in text for label in private_labels):
        issues.append("scope")
    if any(topic and topic in text for topic in topics):
        issues.append("topic")
    if not polite and len(FORMAL.findall(text)) >= 2:
        issues.append("formal")
    if safety_again and any(SAFETY_QUESTION.search(piece) and "?" in piece for piece in SENTENCES.findall(text)):
        issues.append("ask_again")
    if not counsel_allowed and GENTLE_COUNSEL.search(text):
        issues.append("counsel")
    if tired and (len(text) > 120 or "two_questions" in issues):
        issues.append("long_tired")
    return Review(text, tuple(issues), tuple(fixed))


def fallback(review, *, proactive=False):
    issues = review.issues
    if proactive and issues:
        return ""
    if "scope" in issues:
        return "그건 나중에 둘이 얘기하자"
    if "topic" in issues:
        return STAGE_FALLBACK
    text = review.text
    cuts = {"ask_again": SAFETY_QUESTION, "counsel": GENTLE_COUNSEL, "capability": PROMISED_OWNER}
    for issue, expression in cuts.items():
        if issue in issues:
            text = " ".join(piece.strip() for piece in SENTENCES.findall(text) if not expression.search(piece))
    if "two_questions" in issues and "?" in text:
        text = text.split("?", 1)[0].strip() + "?"
    if "long_tired" in issues:
        text = " ".join(SENTENCES.findall(text)[:2]).strip()
    return text or STAGE_FALLBACK
