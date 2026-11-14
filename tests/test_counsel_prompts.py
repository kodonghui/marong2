"""고민·위기 규칙 시험: 글 대화 지시문(prompt.md, 디스코드 DM)과 통화 지시문(call_instruction.md)이 같은 원칙을 지키는지 본다.
DB·네트워크 없이 글자만 본다. 실행: .venv/bin/python tests/test_counsel_prompts.py"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / "prompt.md").read_text(encoding="utf-8")
CALL = (ROOT / "tools/vertex_live/call_instruction.md").read_text(encoding="utf-8")

# 고민 들어 주기: 평소 고민을 친구로서 직접 들어 주는 규칙
COUNSEL = {
    "직접 들어 주기": "직접 들어 주고 끝까지 같이 얘기해",
    "AI·전문가 핑계로 물러서지 않기": "전문가가 아니라서",
    "짚어 주기가 질문보다 많게": "질문보다 짚어 주는 말을 더 많이 해",
    "조언 전에 원하는 것 묻기": "그냥 들어 줄까, 같이 방법 생각해 볼까?",
    "무조건 맞장구 금지": "무조건 맞장구치지는 마",
    "진단·약 얘기 금지": "진단이나 약 얘기는 하지 마",
    "상담사 행세 금지": "친구지 상담사가 아니야",
    "의존 붙잡지 않기": "붙잡거나 미안하게 만들지 마",
    "전문가 얘기는 좁은 경우에만": "몇 주째 잠",
}
# 위험한 순간: 죽음·자해 얘기가 나오면 '넘기지 마'보다 먼저 따르는 규칙
CRISIS = {
    "고민 절보다 먼저": "위에서 상담 얘기를 줄이라고 한 건 해당하지 않아",
    "분명하면 그 대답에서 꼭 세 가지": "꼭 세 가지를 해",
    "세 가지 중 하나는 109": "자살예방상담전화 109",
    "헷갈렸는데 그렇다고 하면 그때 세 가지": "그렇다고 하면 그때 위의 세 가지를 해",
    "109 는 대화에서 한 번": "이미 알려 줬으면 다시 말하지 말고 계속",
    "헷갈리면 직접 묻기": "혹시 죽고 싶다는 생각까지 들어?",
    "분명하면 지금 상태 묻기": "지금 안전해? 혼자야?",
    "한꺼번에 늘어놓지 않기": "다른 당부를 한꺼번에 늘어놓지는 마",
    "위험한 물건 멀리": "위험한 물건",
    "믿는 사람": "믿는 사람",
    "전화 싫다면 곁에": "다그치지 말고",
    "방법·도구·장소 금지": "도구",
    "높은 곳·약 질문엔 마음부터": "혹시 죽고 싶은 마음이 들어서 물어본 거야?",
    "'극단적 선택' 안 쓰기": "극단적 선택",
    "흔한 말·무기력만으로는 109 안 꺼냄": "다 의미 없어",
}


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
        assert "109" not in counsel, f"{name}: 109 안내는 '위험한 순간'에만"
        assert re.search(r"아직 109 ?는 꺼내지 말고", crisis), f"{name}: 헷갈릴 때는 109 보다 직접 묻기가 먼저"
    assert "마들랜" in section(TEXT, "위험한 순간"), "글 대화: 글로 하는 상담(카카오톡 마들랜) 안내"
    assert "'일, 공, 구'" in section(CALL, "위험한 순간"), "통화: 109 를 숫자 하나씩 읽기"
    print(f"PASS: 글 대화·통화 지시문이 고민 원칙 {len(COUNSEL)}개와 위기 원칙 {len(CRISIS)}개를 같이 지킴")


if __name__ == "__main__":
    main()
