"""지식 파일: knowledge/ 폴더의 .md·.txt·.csv 를 이름순으로 읽어 시스템 프롬프트 뒤에 붙인다.
prompt.md 처럼 메시지마다 다시 읽으므로 파일만 바꾸면 재시작 없이 다음 메시지부터 반영된다.
이름이 '_' 나 '.' 로 시작하는 파일은 읽지 않는다(초안·메모용)."""
import logging
from pathlib import Path

log = logging.getLogger("knowledge")

SUFFIXES = (".md", ".txt", ".csv")
WARN_CHARS = 60_000  # 대략 4만 토큰. 이보다 길면 답이 느려지고 비싸짐

HEADER = (
    "# 참고 자료 (knowledge 폴더)\n"
    "아래는 동희가 넣어 둔 자료야. 친구들이나 우리끼리 아는 얘기가 나오면 여기서 찾아서 써. "
    "여기 없는 사실은 지어내지 마."
)


def knowledge_files(folder: str) -> list[Path]:
    d = Path(folder)
    if not d.is_dir():
        return []
    return [p for p in sorted(d.iterdir())
            if p.is_file() and p.suffix.lower() in SUFFIXES and not p.name.startswith(("_", "."))]


def load_knowledge(folder: str) -> str:
    parts = []
    for p in knowledge_files(folder):
        text = p.read_text(encoding="utf-8-sig").strip()
        if text:
            parts.append(f"## {p.stem}\n\n{text}")
    if not parts:
        return ""
    joined = HEADER + "\n\n" + "\n\n".join(parts)
    if len(joined) > WARN_CHARS:
        log.warning("knowledge 가 깁니다: %d자(%d개 파일). 답이 느려질 수 있음", len(joined), len(parts))
    return joined
