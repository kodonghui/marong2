"""고민·위기 규칙 시험: 글 대화 지시문(prompt.md, 디스코드 DM)과 통화 지시문(call_instruction.md)이 같은 원칙을 지키는지 본다.
원칙(동희님 2026-11-15 03:14 KST): 마롱이는 상담사가 아니라 친구가 먼저다. 평소 고민·힘든 얘기와 '죽고 싶다' 같은 말에는
109·상담·병원을 꺼내지 않고, 지금 실제로 죽으려 하거나 스스로를 해치려 한다고 분명히 말할 때만 대화에서 한 번 짧게 109를 말한다.
DB·네트워크 없이 글자만 본다. 실행: python tests/test_counsel_prompts.py"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / "prompt.md").read_text(encoding="utf-8")
CALL = (ROOT / "tools/vertex_live/call_instruction.md").read_text(encoding="utf-8")

# 고민 들어 주기: 상담사가 아니라 친구로서 같이 얘기하는 규칙
COUNSEL = {
    "상담사가 아니라 친구": "상담사가 아니라 친구",
    "직접 들어 주기": "직접 들어 주고 끝까지 같이 얘기해",
    "AI·전문가 핑계로 물러서지 않기": "전문가가 아니라서",
    "친구다운 리액션 먼저": "'헐', '아 진짜?'",
    "상담 말투 되풀이 금지": "같은 상담 말투를 되풀이하지 마",
    "가벼운 투정엔 평소처럼": "가벼운 투정",
    "친구 편": "친구 편이 돼 줘",
    "같이 화내 주기": "같이 화내 줘",
    "감정 질문보다 얘기가 궁금한 질문": "얘기가 궁금해서 묻는 질문",
    "무거운 얘기엔 사연 지어내지 않기": "비슷한 사연을 지어내지 마",
    "조언은 친구처럼 짧게": "'나라면 ~할 것 같아'",
    "무조건 맞장구 금지": "무조건 맞장구치지는 마",
    "진단·약 얘기 금지": "진단이나 약 얘기는 하지 마",
    "상담사 행세 금지": "친구지 상담사가 아니야",
    "의존 붙잡지 않기": "붙잡거나 미안하게 만들지 마",
    "평소엔 상담·병원·상담전화 얘기 안 꺼냄": "상담전화 얘기는 꺼내지 마",
    "예외는 위험한 순간 하나": "딱 하나 예외는 아래 '위험한 순간'",
    "폭력·위협은 112": "112",
}
# 위험한 순간: 109 는 지금 실제로 하려 한다고 분명히 말할 때만 한 번
CRISIS = {
    "'죽고 싶다'는 대부분 힘들다는 뜻이나 과장": "대부분 너무 힘들다는 뜻이거나",
    "진지하면 친구답게 직접 묻기": "혹시 진짜 죽고 싶은 마음까지 들어?",
    "물어봐도 안전": "물어본다고 더 위험해지지 않아",
    "생각해 둔 게 있는지 묻기": "뭘 하려고 생각해 둔 게 있는지",
    "진지하게 말했으면 다시 묻지 않기": "다시 묻지 말고",
    "생각만으로는 109 아직": "지금 하려는 게 아니면 109는 아직 꺼내지 마",
    "지금 하려 할 땐 가볍게 넘기지 않기": "'헐'이나 '무슨 일인데?'로 넘기지 마",
    "109 는 분명히 말할 때만": "분명히 말할 때만",
    "그 답에서 딱 한 번": "딱 한 번",
    "같이 있겠다는 말": "같이 있겠다는 말",
    "24시간": "24시간",
    "이미 다쳤으면 119": "119",
    "다시 꺼내지 않기": "다시 꺼내지 말고",
    "위험한 물건 멀리": "위험한 물건",
    "방법·도구·장소 금지": "도구",
    "높은 곳·약 질문엔 마음부터": "혹시 죽고 싶은 마음이 들어서 물어본 거야?",
    "'극단적 선택' 안 쓰기": "극단적 선택",
}
# 상담사처럼 들리던 예전 문구와 109 를 자주 꺼내게 하던 예전 문구는 다시 들어오지 않게 한다
GONE = [
    "질문보다 짚어 주는 말", "그냥 들어 줄까", "작은 다음 걸음", "숨 세 번", "몇 주째",
    "꼭 세 가지", "지금 안전해? 혼자야?", "마들랜", "자살예방상담전화",
]


def section(text: str, title: str) -> str:
    m = re.search(rf"^# {re.escape(title)}\n(.*?)(?=^# |\Z)", text, re.M | re.S)
    assert m, f"'{title}' 절이 없음"
    return m.group(1)


def main():
    for name, text in (("글 대화", TEXT), ("통화", CALL)):
        counsel = section(text, "고민 들어 주기")
        crisis = section(text, "위험한 순간")
        for rule, phrase in COUNSEL.items():
            assert phrase in counsel, f"{name} '고민 들어 주기'에 없음: {rule}"
        for rule, phrase in CRISIS.items():
            assert phrase in crisis, f"{name} '위험한 순간'에 없음: {rule}"
        for phrase in GONE:
            assert phrase not in text, f"{name}: 예전 문구가 남음: {phrase}"
        assert text.count("109") == crisis.count("109"), f"{name}: 109 는 '위험한 순간'에만"
        bullets = [b for b in crisis.splitlines() if b.startswith("- ")]
        assert "먼저 따라" in bullets[0], f"{name}: '위험한 순간'이 '고민 들어 주기'보다 먼저"
        assert "절대 알려 주지 마" in bullets[1], f"{name}: 방법·도구·장소 금지가 앞쪽에"
        hyperbole = next(b for b in bullets if "대부분 너무 힘들다는 뜻이거나" in b)
        assert "꺼내지 마" in hyperbole and "되묻지도 마" in hyperbole and "109" not in hyperbole, f"{name}: 과장엔 109·되묻기 없음"
        for line in bullets:
            if "109" in line:
                assert any(k in line for k in ("분명히 말할 때만", "한 번만", "아직 꺼내지 마")), f"{name}: 109 는 분명할 때 한 번만: {line[:40]}"
    assert "전화나 문자" in section(TEXT, "위험한 순간"), "글 대화: 109 는 전화나 문자"
    assert "'일, 공, 구'" in section(CALL, "위험한 순간"), "통화: 109 를 숫자 하나씩 읽기"
    print(f"PASS: 글 대화·통화 지시문이 친구 먼저 원칙 {len(COUNSEL)}개와 위기 원칙 {len(CRISIS)}개를 같이 지키고 예전 문구 {len(GONE)}개는 없음")


if __name__ == "__main__":
    main()
