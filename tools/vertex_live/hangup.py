"""When Marong may end a call: only after the friend asked for it in this call.

The model decides when to call end_call. This check runs on the server before
that decision takes effect, so a misjudged call can never hang up on a friend
who did not ask. Words that also appear in other talk (quitting smoking, a
dropped call earlier) can still pass; the model has to judge those.
"""
from __future__ import annotations

import re
import time
from collections import deque

# The friend asks to end this call: '끊어', '이제 끊자', '전화 꺼', '꺼 줘', '통화 종료'.
# Past or passive forms ('끊겼어', '끊길까 봐', '끊어졌어', '끊었어', '끊어서') talk
# about another call, and '꺼내' is not '꺼'.
ASK = re.compile(
    r'끊(?!겼|겨|긴|김|기|길|어\s*[졌지져짐]|었|어서)'
    r'|(?:전화|통화|마롱이?|이제|그만|얼른|빨리|좀|잠깐만?)\s*(?:을|를|아|야|이)?\s*꺼(?!내|낸|낼|냈|놓|놔)'
    r'|꺼\s*(?:줘|줄래|주라|주세요|봐|라|도\s*[돼되]|버려)'
    r'|끄자|끌게|끌래|끄고\s*싶|끄면\s*돼|꺼야\s*(?:돼|겠|지)'
    r'|종료'
    r'|그만\s*(?:통화\s*)?(?:하자|할래|할게|해도)'
    r'|바이\s*바이|빠이'
    r'|들어갈게|들어가\s*(?:볼게|볼래|야\s*겠|야\s*돼|야지)'
    r'|마치자|마칠게|마칠래|끝내자|끝낼게|끝낼래|끝내\s*줘')
# '끊지 마', '안 끊어', '끊기 싫어', '끄지 마' keep the call going.
REFUSE = re.compile(r'끊지\s*(?:는\s*)?(?:마|말)|안\s*끊|끊기\s*싫|끊으면\s*안|끄지\s*(?:는\s*)?(?:마|말)|안\s*꺼|끄면\s*안')
# Marong offered to end the call: '끊을까?', '이제 끊어 줄까?'
OFFER = re.compile(r'끊을까|끊어\s*줄까|끊을래|끊자고|끊는\s*거|끊으려고|끌까|꺼\s*줄까|마칠까|끝낼까')
# A short yes to that offer.
YES = re.compile(r'^\s*(?:응|어|엉|웅|으응|ㅇㅇ|ㅇㅋ|그래|그러자|좋아|네|예|넹|넵|오케이|ok|okay|알았어|알겠어|끊어|끊자|꺼\s*줘|그럼)'
                 r'(?=\s|[.!~,?ㅎㅋ]|$)', re.I)
# ...unless the same reply keeps the call going: '응 근데 아직', '어 아니 더 얘기하자'.
STAY = re.compile(r'아니|아직|더\s*(?:얘기|하자|할래|놀|있)|말고|싫|잠깐|있어\s*봐|안\s*끊|끊지')

WINDOW_S = 90       # only this call's recent words count
DIRECT_LINES = 2    # a direct ask must be among the friend's last two lines


class Consent:
    """Recent call lines, in the order they started, for the hang-up check."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lines = deque(maxlen=16)  # [role, key, text, at]

    def note(self, role, key, text):
        """Record a caption. Streaming captions update the line they started."""
        role = 'user' if role == 'user' else 'assistant'
        now = self.clock()
        for line in reversed(self.lines):
            if line[1] == key:
                line[2] = text
                line[3] = now
                return
        self.lines.append([role, key, text, now])

    def asked(self):
        """True when the friend asked to end this call, directly or by agreeing."""
        now = self.clock()
        recent = [line for line in self.lines if now - line[3] <= WINDOW_S and line[2].strip()]
        users = [line for line in recent if line[0] == 'user']
        if not users:
            return False
        for line in users[-DIRECT_LINES:]:
            if ASK.search(line[2]) and not REFUSE.search(line[2]):
                return True
        last = users[-1]
        offers = [line for line in recent[:recent.index(last)] if line[0] == 'assistant']
        reply = last[2].strip()
        # '어?' or '응?' answers with a question, not a yes.
        return bool(offers and OFFER.search(offers[-1][2]) and YES.search(reply)
                    and not STAY.search(reply) and not reply.endswith('?'))
