"""마롱이 기록 리포트: 대화 · 임베딩 · 들어간 기억(답마다 임베딩 검색으로 찾은 것과 실제로 넣은 것) · 요약·메모.
  python tools/report.py [--hours 24] [--until 2026-10-27T19:00+09:00] [--out 파일]   엑셀(--out 이 없으면 stdout)
  python tools/report.py --sheet [--until …]   구글 시트로 보냄(.env 의 SHEET_URL. 기간은 최근 SHEET_DAYS 일, 기본 30)
  python tools/report.py --sheet --if-asked    시트에서 '마롱이 > 지금 새로고침'을 눌렀을 때만 보냄(서버가 1분마다 물어봄)
노트북에서: bash deploy/ovh.sh report <저장할 파일.xlsx> [시간] [끝 시각] · bash deploy/ovh.sh sheet url|on|off|now|status
기간은 [끝 시각 - 기간, 끝 시각)이고 끝 시각 기본값은 지금. 서버에 파일을 남기지 않는다.
DB 는 읽기만 하고, 카카오 키 원문 대신 tools/admin.py 와 같은 #짧은키를 쓴다. SHEET_URL 은 비밀이라 출력하지 않는다."""
import argparse
import hashlib
import io
import json
import logging
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import psycopg
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from marong.config import load_dotenv  # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)  # INFO 로그에 요청 주소(비밀인 시트 주소)가 찍힘
logging.getLogger("httpcore").setLevel(logging.WARNING)

STAMP = "%Y-%m-%d %H:%M:%S"
REPLY_CHARS = 100  # '들어간 기억'에는 마롱이 답의 앞부분만
CELL_MAX = 32767   # 엑셀 칸 하나에 들어가는 최대 글자 수
SHEET_PREFIX = "https://script.google.com/"  # Apps Script 웹 앱이 아닌 곳으로는 대화를 보내지 않음
SHEET_TIMEOUT_S = 120
ASK_TIMEOUT_S = 30
HEADER_FILL = PatternFill("solid", fgColor="E8E3F3")
TOP, TOP_WRAP = Alignment(vertical="top"), Alignment(vertical="top", wrap_text=True)
RECALL = {"short": "안 함(말이 짧아서)", "off": "안 함(임베딩 준비 안 됨)", "error": "오류(검색 실패)"}


def key(k: str | None) -> str:
    return "#" + hashlib.sha1((k or "").encode()).hexdigest()[:8]


def stamp(dt, tz) -> str | None:
    """시간대가 붙은 시각 → 'YYYY-MM-DD HH:MM:SS' 한국 시각 글."""
    return dt.astimezone(tz).strftime(STAMP) if dt else None


def cut(text, n: int):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def yes(v) -> str:
    return "-" if v is None else ("예" if v else "아니오")


def plain(v):
    """칸 값은 글·정수·실수·빈칸만(엑셀과 시트가 같은 값을 받게). 글에서는 엑셀이 못 받는 제어 문자를 뺌."""
    if isinstance(v, bool):
        return yes(v)
    if v is None or isinstance(v, int):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    if not isinstance(v, str):
        v = json.dumps(v, ensure_ascii=False)  # meta 에 뜻밖의 모양이 들어 있어도 글로
    return ILLEGAL_CHARACTERS_RE.sub("", v)


def tab(name: str, headers: list[str], rows: list[list], widths: list[float], wrap=()) -> dict:
    """탭 하나. widths(칸 너비, 글자 수)·wrap(줄바꿈할 칸 번호, 1부터)은 보기용."""
    return {"name": name, "headers": headers, "rows": [[plain(v) for v in r] for r in rows],
            "widths": widths, "wrap": sorted(wrap)}


def hits(memory: dict, field: str) -> list[tuple[str, int, float | None]]:
    """meta.memory 의 candidates·recalled → (종류, 번호, 비슷함). 모양이 틀린 항목은 건너뜀."""
    out = []
    for h in memory.get(field) or []:
        try:
            sim = h.get("similarity")
            out.append(("summary" if h.get("type") == "summary" else "message", int(h["id"]),
                        None if sim is None else float(sim)))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return out


def also(memory: dict) -> str:
    """임베딩 검색 말고 같이 넣은 기억(최근 대화 구간·요약·메모·친구 수)."""
    parts = []
    recent = memory.get("recent") or []
    if len(recent) == 2:
        parts.append(f"최근 대화 #{recent[0]}~#{recent[1]}")
    for field, label, unit in (("summaries", "요약", "개"), ("notes", "메모", "개"), ("friends", "친구", "명")):
        if memory.get(field):
            parts.append(f"{label} {len(memory[field])}{unit}")
    return " · ".join(parts) or "-"


def fetch(c, start: datetime, until: datetime, vectors: bool = True) -> dict:
    w = {"s": start, "u": until}
    # 벡터 전체가 필요 없으면(시트) 앞 8개 값만 읽음: 768개짜리를 30일치 통째로 읽지 않게
    vector = "e.embedding::text" if vectors else "((e.embedding::real[])[1:8])::text"
    data = {
        "messages": c.execute(
            "SELECT m.id, m.room_key, m.user_key, p.name, m.role, m.content, m.reply_to, m.meta, m.created_at "
            "FROM marong.messages m LEFT JOIN marong.people p ON p.user_key = m.user_key "
            "WHERE m.created_at >= %(s)s AND m.created_at < %(u)s ORDER BY m.id", w).fetchall(),
        "embeddings": c.execute(
            "SELECT e.model, e.source_type, e.source_id, e.room_key, e.created_at, vector_dims(e.embedding) AS dims, "
            f"  {vector} AS vector, coalesce(m.content, s.content) AS content FROM marong.embeddings e "
            "LEFT JOIN marong.messages m ON e.source_type = 'message' AND m.id = e.source_id "
            "LEFT JOIN marong.summaries s ON e.source_type = 'summary' AND s.id = e.source_id "
            "WHERE e.created_at >= %(s)s AND e.created_at < %(u)s "
            "ORDER BY e.created_at, e.source_type, e.source_id", w).fetchall(),
        "summaries": c.execute(
            "SELECT id, room_key, first_id, last_id, content, meta, created_at FROM marong.summaries "
            "WHERE created_at >= %(s)s AND created_at < %(u)s ORDER BY id", w).fetchall(),
        "notes": c.execute(
            "SELECT n.id, n.room_key, n.user_key, p.name, n.content, n.summary_id, n.created_at FROM marong.notes n "
            "LEFT JOIN marong.people p ON p.user_key = n.user_key "
            "WHERE n.created_at >= %(s)s AND n.created_at < %(u)s ORDER BY n.id", w).fetchall(),
        "shared": c.execute(
            "SELECT s.id, s.friend_id, f.name, s.content, s.meta, s.created_at FROM marong.shared_notes s "
            "JOIN marong.friends f ON f.id = s.friend_id "
            "WHERE s.created_at >= %(s)s AND s.created_at < %(u)s ORDER BY s.id", w).fetchall(),
    }
    # 답에 넣은(또는 찾고 안 넣은) 예전 기억과 친구가 한 말은 기간 밖일 수 있어서 따로 읽음
    msg_ids, sum_ids = set(), set()
    for m in data["messages"]:
        memory = (m["meta"] or {}).get("memory") or {}
        for t, i, _ in hits(memory, "candidates") + hits(memory, "recalled"):
            (sum_ids if t == "summary" else msg_ids).add(i)
        if m["reply_to"]:
            msg_ids.add(m["reply_to"])
    data["ref_messages"] = {r["id"]: r for r in c.execute(
        "SELECT m.id, m.role, m.user_key, p.name, m.content FROM marong.messages m "
        "LEFT JOIN marong.people p ON p.user_key = m.user_key WHERE m.id = ANY(%s)", (sorted(msg_ids),)).fetchall()}
    data["ref_summaries"] = {r["id"]: r for r in c.execute(
        "SELECT id, content FROM marong.summaries WHERE id = ANY(%s)", (sorted(sum_ids),)).fetchall()}
    room_keys = sorted({x["room_key"] for k in ("messages", "embeddings", "summaries", "notes") for x in data[k]})
    data["rooms"] = {r["room_key"]: r for r in c.execute(
        "SELECT room_key, is_channel FROM marong.rooms WHERE room_key = ANY(%s)", (room_keys,)).fetchall()}
    data["speakers"] = c.execute(
        "SELECT DISTINCT m.room_key, m.user_key, p.name FROM marong.messages m "
        "LEFT JOIN marong.people p ON p.user_key = m.user_key "
        "WHERE m.role = 'user' AND m.room_key = ANY(%s)", (room_keys,)).fetchall()
    return data


def build(c, start: datetime, until: datetime, tz, now: datetime | None = None, threshold: float = 0.4,
          recent_turns: int = 10, vectors: bool = True) -> tuple[list[dict], dict]:
    """기간 [start, until) 의 탭들(엑셀·시트 공용)과 개수. threshold·recent_turns 는 봇 설정(읽는 법 설명용).
    vectors 가 False 면 임베딩 벡터 전체 칸을 뺌(시트는 30일치를 30분마다 통째로 보내서 무거움)."""
    now = now or datetime.now(tz)
    data = fetch(c, start, until, vectors)
    msgs, embs = data["messages"], data["embeddings"]
    ref_msgs, ref_sums = data["ref_messages"], data["ref_summaries"]
    names: dict[str, set[str]] = {}
    for s in data["speakers"]:
        names.setdefault(s["room_key"], set()).add(s["name"] or key(s["user_key"]))

    def at(dt):
        return stamp(dt, tz)

    def room(k):
        if k == "terminal":
            return "터미널"
        who = ", ".join(sorted(names.get(k, ())))
        kind = "1:1" if (data["rooms"].get(k) or {}).get("is_channel") else "단체"
        return f"{kind} {key(k)}" + (f" {who}" if who else "")

    def speaker(m):
        return "마롱이" if m["role"] == "assistant" else (m["name"] or key(m["user_key"]))

    def kind(m):
        meta = m["meta"] or {}
        if m["role"] == "user":
            return "친구 말"
        if meta.get("proactive"):
            return "선톡"
        if meta.get("late"):
            return "늦은 답(안내)"
        if meta.get("error"):
            return f"대체 문구({meta['error']})"
        if meta.get("refusal"):
            return "거절 문구"
        return "답장"

    def no_memory(meta):
        return "기억 없이(늦음·오류)" if meta.get("late") or meta.get("error") else "기록 전"

    def used(m):
        """그 답에 실제로 들어간 예전 기억(임베딩 검색) 수."""
        if m["role"] != "assistant":
            return None
        meta = m["meta"] or {}
        memory = meta.get("memory")
        if memory is None:
            return no_memory(meta)
        if meta.get("proactive"):
            return "선톡(검색 안 함)"
        return len(hits(memory, "recalled"))

    tabs = []

    # ── 대화 ──
    rows = []
    for m in msgs:
        meta = m["meta"] or {}
        mine = m["role"] == "assistant"
        rows.append([m["id"], at(m["created_at"]), room(m["room_key"]), speaker(m), kind(m), m["content"],
                     m["reply_to"], yes(meta.get("delivered")) if mine else "-", meta.get("model"), meta.get("effort"),
                     meta.get("input_tokens"), meta.get("output_tokens"), meta.get("cache_read_tokens"),
                     meta.get("cache_write_tokens"), used(m)])
    tabs.append(tab("대화", ["번호", "시각(한국)", "방", "보낸 쪽", "종류", "내용", "답한 메시지 번호", "전달됨", "모델",
                           "effort", "입력 토큰", "출력 토큰(생각 포함)", "캐시에서 읽은 토큰", "캐시에 쓴 토큰",
                           "들어간 예전 기억 수"],
                    rows, [7, 19, 22, 9, 10, 70, 9, 7, 17, 7, 9, 10, 10, 9, 12], wrap={6}))

    # ── 임베딩 ──
    rows = []
    for e in embs:
        values = (e["vector"] or "").strip("[]{}").split(",")  # vector '[…]' 나 real[] '{…}'
        row = [e["model"], "메시지" if e["source_type"] == "message" else "요약", e["source_id"], room(e["room_key"]),
               at(e["created_at"]), e["dims"], e["content"], ", ".join(v.strip() for v in values[:8])]
        rows.append(row + [e["vector"]] if vectors else row)
    headers = ["모델", "원본 종류", "원본 번호", "방", "임베딩한 시각", "차원 수", "원본 글", "벡터 앞 8개 값"]
    widths = [26, 9, 9, 22, 19, 7, 60, 46]
    tabs.append(tab("임베딩", headers + ["벡터 전체"] if vectors else headers, rows,
                    widths + [40] if vectors else widths, wrap={7}))

    # ── 들어간 기억: 답마다 임베딩 검색 결과 한 줄씩 ──
    rows = []
    with_memory = 0
    blank = [None] * 7  # 순위 ~ 찾은 것 원문
    for m in msgs:
        if m["role"] != "assistant":
            continue
        meta = m["meta"] or {}
        memory = meta.get("memory")
        asked = ref_msgs.get(m["reply_to"]) if m["reply_to"] else None
        base = [m["id"], at(m["created_at"]), room(m["room_key"]),
                (asked or {}).get("content") if m["reply_to"] else ("(선톡)" if meta.get("proactive") else None),
                cut(m["content"], REPLY_CHARS)]
        if memory is None:
            rows.append(base + [no_memory(meta), None] + blank)
            continue
        with_memory += 1
        if meta.get("proactive"):
            rows.append(base + ["선톡(검색 안 함)", also(memory)] + blank)
            continue
        found, put = hits(memory, "candidates"), hits(memory, "recalled")
        shown = {(t, i) for t, i, _ in found}
        listed = found + [h for h in put if (h[0], h[1]) not in shown]  # 넣은 것은 찾은 것에 없어도 보여 줌
        status = memory.get("recall")
        if not listed:
            rows.append(base + [RECALL.get(status) or ("함(찾은 것 없음)" if status == "ok" else "-"), also(memory)]
                        + blank)
            continue
        put_keys = {(t, i) for t, i, _ in put}
        for rank, (t, i, sim) in enumerate(listed, 1):
            src = ref_sums.get(i) if t == "summary" else ref_msgs.get(i)
            if (t, i) in put_keys:
                verdict = "넣음"
            elif src is not None and not src["content"]:
                verdict = "안 넣음(빈 글)"
            elif sim is not None and sim < threshold:
                verdict = f"안 넣음({threshold:g} 미만)"
            else:
                verdict = "안 넣음(개수 초과)"
            who = "요약" if t == "summary" else (speaker(src) if src else "-")
            rows.append(base + ["함", also(memory), rank, "요약" if t == "summary" else "메시지", i, who,
                                None if sim is None else round(sim, 3), verdict, (src or {}).get("content")])
    tabs.append(tab("들어간 기억", ["답 번호", "답 시각", "방", "친구가 한 말", f"마롱이 답(앞 {REPLY_CHARS}자)",
                                "임베딩 검색", "같이 넣은 기억", "순위", "찾은 것 종류", "찾은 것 번호", "누구 말",
                                "비슷함(0~1)", "답에 넣었나", "찾은 것 원문"],
                    rows, [7, 19, 22, 40, 40, 16, 30, 6, 9, 9, 9, 10, 18, 60], wrap={4, 5, 14}))

    # ── 요약·메모(compact) ──
    rows = []
    for s in data["summaries"]:
        meta = s["meta"] or {}
        rows.append(["요약", s["id"], at(s["created_at"]), room(s["room_key"]), s["content"] or "(빈 요약)",
                     f"메시지 #{s['first_id']}~#{s['last_id']}" + (f" (건너뜀: {meta['skipped']})" if meta.get("skipped") else ""),
                     meta.get("model"), meta.get("effort"), meta.get("input_tokens"), meta.get("output_tokens")])
    for n in data["notes"]:
        rows.append(["친구 메모", n["id"], at(n["created_at"]), f"{room(n['room_key'])} · {n['name'] or key(n['user_key'])}",
                     n["content"], f"요약 #{n['summary_id']}" if n["summary_id"] else "요약 전에 먼저 고침",
                     None, None, None, None])
    for s in data["shared"]:
        meta = s["meta"] or {}
        rows.append(["공유 메모", s["id"], at(s["created_at"]), s["name"], s["content"] or "(다른 친구에게 할 얘기 없음)",
                     "거른 메모 " + (", ".join(f"#{x}" for x in meta.get("note_ids") or []) or "-"),
                     meta.get("model"), meta.get("effort"), meta.get("input_tokens"), meta.get("output_tokens")])
    tabs.append(tab("요약·메모", ["종류", "번호", "만든 시각", "방 또는 친구", "내용", "구간·재료", "모델", "effort",
                              "입력 토큰", "출력 토큰"],
                    rows, [9, 7, 19, 26, 80, 24, 17, 7, 9, 9], wrap={5}))

    # ── 읽는 법(맨 앞) ──
    replies = [m for m in msgs if m["role"] == "assistant" and not (m["meta"] or {}).get("proactive")]
    proactive = [m for m in msgs if m["role"] == "assistant" and (m["meta"] or {}).get("proactive")]
    counts = {"messages": len(msgs), "replies": len(replies), "proactive": len(proactive), "embeddings": len(embs),
              "with_memory": with_memory, "summaries": len(data["summaries"]), "notes": len(data["notes"]),
              "shared": len(data["shared"])}
    lines = [
        f"기간: {at(start)} ~ {at(until)} (한국 시각, 끝 시각은 빼고)",
        f"마지막 갱신: {at(now)}",
        "",
        "■ 탭",
        f"대화: 이 기간에 오간 메시지 {len(msgs)}개(친구 말 {len(msgs) - len(replies) - len(proactive)}, "
        f"마롱이 답 {len(replies)}, 선톡 {len(proactive)}). 마지막 칸은 그 답에 임베딩 검색으로 실제로 넣은 예전 기억 수예요.",
        f"임베딩: 이 기간에 만든 임베딩 {len(embs)}개. 메시지·요약을 숫자 벡터로 바꾼 것이고, 뜻이 비슷한 글끼리 숫자도 비슷해요."
        + ("" if vectors else " 벡터 전체는 엑셀(bash deploy/ovh.sh report)에만 있어요."),
        f"들어간 기억: 기억 기록이 있는 마롱이 말 {with_memory}개. 답마다 임베딩 검색으로 찾은 예전 대화를 한 줄씩 적고, "
        "실제로 답에 넣었는지(넣음·안 넣음)와 그 원문을 보여 줘요.",
        f"요약·메모: 이 기간에 만든 요약 {len(data['summaries'])}개, 친구 메모 {len(data['notes'])}줄, "
        f"공유 메모 {len(data['shared'])}줄(compact 된 기억).",
        "",
        "■ 마롱이가 답할 때 넣는 기억",
        f"- 최근 대화 원문(같은 방 최근 {recent_turns}턴)",
        "- 그 방의 최근 요약 3개와 친구별 기억 메모",
        f"- 지금 말과 비슷한 예전 대화: 지금 말을 임베딩해서 같은 방의 예전 메시지·요약과 비교해요. 비슷한 순으로 12개를 찾고, "
        f"비슷함 {threshold:g} 이상인 것 중 요약 3개·메시지 4개까지 넣어요. 최근 대화와 이미 넣은 요약 3개는 빼고 찾아요.",
        "- 지금 친구와 아는 친구들의 가벼운 얘기(공유 메모)",
        "- 선톡은 그 방의 최근 대화·요약·메모만 보고 임베딩 검색은 하지 않아요.",
        "",
        "■ 참고",
        "- '기록 전'은 기억 기록을 남기기 전에 보낸 답이에요. '안 함(말이 짧아서)'은 'ㅋㅋ'처럼 짧은 말이라 검색하지 않은 것.",
        "- 시각은 모두 한국 시각이에요. 카카오 키 원문 대신 관리 명령(admin)과 같은 #짧은키를 적었어요.",
    ]
    if not vectors:
        lines.append("- 시트 메뉴 '마롱이 > 지금 새로고침'을 누르면 1분쯤 뒤에 새로 채워요. 안 눌러도 30분마다 새로 채워요.")
    tabs.insert(0, tab("읽는 법", ["마롱이 기록 리포트"], [[line] for line in lines], [130], wrap={1}))
    return tabs, counts


def clean(v):
    """엑셀 칸 한도를 넘는 글은 자름(시트는 sheet.gs 가 자름)."""
    return v[:CELL_MAX - 1] + "…" if isinstance(v, str) and len(v) > CELL_MAX else v


def workbook(tabs: list[dict]) -> Workbook:
    wb = Workbook()
    for n, t in enumerate(tabs):
        ws = wb.active if n == 0 else wb.create_sheet()
        ws.title = t["name"]
        ws.append(t["headers"])
        for c in ws[1]:
            c.font = Font(bold=True)
            c.fill = HEADER_FILL
            c.alignment = Alignment(vertical="center", wrap_text=True)
        wrap = set(t["wrap"])
        for row in t["rows"]:
            ws.append([clean(v) for v in row])
            for c in ws[ws.max_row]:
                if isinstance(c.value, str) and c.value.startswith("="):
                    c.data_type = "s"  # '=' 로 시작하는 말을 수식으로 읽지 않게
                c.alignment = TOP_WRAP if c.column in wrap else TOP
        for i, w in enumerate(t["widths"], 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        if t["rows"] and len(t["headers"]) > 1:
            ws.auto_filter.ref = ws.dimensions
    return wb


def post(url: str, payload: dict, timeout: float, transport=None) -> httpx.Response:
    # 웹 앱은 302 로 결과 주소를 알려 주고, httpx 는 그 주소를 GET 으로 따라감
    with httpx.Client(transport=transport, follow_redirects=True, timeout=timeout) as http:
        return http.post(url, content=json.dumps(payload, ensure_ascii=False).encode(),
                         headers={"Content-Type": "application/json"})


def asked(url: str, transport=None) -> bool:
    """시트에서 '마롱이 > 지금 새로고침'을 눌렀는지 웹 앱에 물어봄(웹 앱은 부탁을 넘기면서 지움).
    못 물었거나 물어보기를 모르는 예전 sheet.gs 면 False. 1분마다 도는 거라 까닭은 남기지 않음(30분 갱신이 남김)."""
    try:
        r = post(url, {"poll": True}, ASK_TIMEOUT_S, transport)
        answer = r.json() if r.status_code == 200 else None
    except Exception:  # 연결 실패·JSON 아닌 답(로그인 페이지 등)
        return False
    return (isinstance(answer, dict) and answer.get("ok") is True
            and isinstance(answer.get("asked"), (int, float)) and answer["asked"] > 0)


def send(url: str, payload: dict, transport=None) -> str | None:
    """시트 웹 앱(tools/sheet.gs)에 탭을 보냄. 잘 되면 None, 아니면 짧은 까닭(주소와 구글의 답 내용은 적지 않음)."""
    try:
        r = post(url, payload, SHEET_TIMEOUT_S, transport)
    except Exception as e:  # 오류 글에 주소가 들어 있을 수 있어서 종류만
        return type(e).__name__
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    try:
        answer = r.json()
    except ValueError:
        return "답이 JSON 이 아님(웹 앱을 '액세스: 모든 사용자'로 배포했는지 확인)"
    if not (isinstance(answer, dict) and answer.get("ok") is True):
        return "시트 스크립트가 실패함(Apps Script 의 실행 기록에서 확인)"
    return None


def main(argv: list[str] | None = None, transport=None) -> int:
    p = argparse.ArgumentParser(description="마롱이 기록 리포트(엑셀 또는 구글 시트)")
    p.add_argument("--hours", type=float, default=24, help="엑셀: 끝 시각에서 거꾸로 이만큼(기본 24시간)")
    p.add_argument("--until", help="끝 시각(예: 2026-10-27T19:00+09:00). 시간대가 없으면 TIMEZONE. 기본은 지금")
    out = p.add_mutually_exclusive_group()
    out.add_argument("--out", help="엑셀을 저장할 파일. 없으면 stdout 으로 보냄")
    out.add_argument("--sheet", action="store_true", help="엑셀 대신 구글 시트(.env 의 SHEET_URL)로. 기간은 최근 SHEET_DAYS 일(기본 30)")
    p.add_argument("--if-asked", action="store_true",
                   help="--sheet 와 같이: 시트에서 '마롱이 > 지금 새로고침'을 눌렀을 때만 보냄(누르지 않았으면 아무것도 안 함)")
    args = p.parse_args(argv)
    if args.if_asked and not args.sheet:
        p.error("--if-asked 는 --sheet 와 같이 씀")
    load_dotenv(str(ROOT / ".env"))
    tz = ZoneInfo(os.getenv("TIMEZONE") or "Asia/Seoul")
    now = datetime.now(tz)
    until = datetime.fromisoformat(args.until) if args.until else now
    if until.tzinfo is None:
        until = until.replace(tzinfo=tz)
    start = until - (timedelta(days=float(os.getenv("SHEET_DAYS") or 30)) if args.sheet else timedelta(hours=args.hours))
    url = (os.getenv("SHEET_URL") or "").strip()
    if args.sheet and not url.startswith(SHEET_PREFIX):
        if args.if_asked:  # 1분마다 같은 말을 남기지 않음(30분 갱신이 남김)
            return 0
        print("SHEET_URL 이 비었거나 Apps Script 웹 앱 주소가 아님(노트북에서 bash deploy/ovh.sh sheet url)", file=sys.stderr)
        return 1
    if args.if_asked and not asked(url, transport):
        return 0
    threshold = float(os.getenv("RECALL_MIN_SIMILARITY") or 0.4)
    recent_turns = int(os.getenv("RECENT_TURNS") or 10)
    with psycopg.connect(os.getenv("DATABASE_URL") or "postgresql:///marong", row_factory=dict_row) as c:
        c.read_only = True
        tabs, n = build(c, start, until, tz, now, threshold, recent_turns, vectors=not args.sheet)
    span = f"{stamp(start, tz)[5:16]}~{stamp(until, tz)[5:16]}(한국)"
    if args.sheet:
        what = "시트 갱신(시트에서 누름)" if args.if_asked else "시트 갱신"
        why = send(url, {"updated": stamp(now, tz), "tabs": tabs}, transport)
        if why:
            print(f"{what} 실패: {why}", file=sys.stderr)
            return 1
        print(f"{what} {span}: " + " · ".join(f"{t['name']} {len(t['rows'])}줄" for t in tabs[1:]))
        return 0
    buf = io.BytesIO()
    workbook(tabs).save(buf)
    if args.out:
        Path(args.out).write_bytes(buf.getvalue())
    else:
        sys.stdout.buffer.write(buf.getvalue())
        sys.stdout.buffer.flush()
    print(f"리포트 {span}: 메시지 {n['messages']}개(마롱이 답 {n['replies']}·선톡 {n['proactive']}) · "
          f"임베딩 {n['embeddings']}개 · 기억 기록 있는 마롱이 말 {n['with_memory']}개 · 요약 {n['summaries']} · "
          f"메모 {n['notes']} · 공유 메모 {n['shared']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
