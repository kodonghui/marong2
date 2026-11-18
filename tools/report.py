"""마롱이 기록 리포트: 대화 · 임베딩 · 들어간 기억(답마다 임베딩 검색으로 찾은 것과 실제로 넣은 것) · 요약·메모
· 친구·공유(지금 기준 공유 켬·끔, 아는 사이, 다른 친구에게 하는 얘기, 대화로 한 요청과 관리자가 정할 일).
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
import time
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
from marong.safety import owner_private


def report_private(row):
    if (row.get("meta") or {}).get("persona_care") is not None:
        return True
    return any(owner_private(value) for key, value in row.items()
               if key in ("content", "text", "close_content", "summary", "detail") and isinstance(value, str))

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
FRIEND_COLOR, MARONG_COLOR = "#fce8e6", "#e8f0fe"
DONGHUI_COLOR, HYUNGKYUNG_COLOR = "#d9ead3", "#fff2cc"
TOP, TOP_WRAP = Alignment(vertical="top"), Alignment(vertical="top", wrap_text=True)
RECALL = {"short": "안 함(말이 짧아서)", "off": "안 함(임베딩 준비 안 됨)", "slow": "안 함(임베딩이 1.5초 넘음)",
          "error": "오류(검색 실패)"}
UNRECORDED = "모름(기록 시작 전)"  # 답마다 넣은 기억을 적기 시작한 2026-10-26 밤 전의 답


def speaker_color(role: str, name: str | None) -> str:
    """카톡과 통화에 기록된 화자 기준. 음성이나 대화 내용으로 신원을 추측하지 않는다."""
    if role == "assistant":
        return MARONG_COLOR
    name = (name or "").strip().removesuffix("님").strip()
    if name in {"동희", "고동희"}:
        return DONGHUI_COLOR
    if name in {"현경", "현경이"}:
        return HYUNGKYUNG_COLOR
    return FRIEND_COLOR


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


def tab(name: str, headers: list[str], rows: list[list], widths: list[float], wrap=(), colors=None) -> dict:
    """탭 하나. widths(칸 너비, 글자 수)·wrap(줄바꿈할 칸 번호, 1부터)·colors(줄마다 바탕색 '#rrggbb')는 보기용."""
    t = {"name": name, "headers": headers, "rows": [[plain(v) for v in r] for r in rows],
         "widths": widths, "wrap": sorted(wrap)}
    if colors is not None:
        t["colors"] = colors
    return t


def call_sessions(c, start, until, tz):
    """The report role sees a metadata-only view, never voice content."""
    if not c.execute("SELECT to_regclass('call.session_report') AS report").fetchone()['report']:
        return None  # Older Kakao-only installations still produce their six tabs.
    records = c.execute("""SELECT * FROM call.session_report
        WHERE started_at < %s AND (ended_at IS NULL OR ended_at >= %s)
        ORDER BY started_at DESC,id""", (until, start)).fetchall()
    state = {'live': '통화 중', 'resting': '연결 대기', 'ended': '종료'}
    paths = {'webrtc': 'WebRTC', 'pcm': 'WebSocket PCM', 'discord': 'Discord 음성', None: '이전 기록 없음'}
    organized = {'none': '대기 전', 'pending': '대기', 'running': '정리 중', 'done': '완료', 'skipped': '생략', 'failed': '실패'}
    reasons = {'start': '시작/재연결', 'rtc_disconnected': 'WebRTC 끊김', 'rtc_reconnecting': 'WebRTC 재연결',
        'rtc_media_stalled': '음성 수신 정지', 'rtc_track_lost': '음성 트랙 끊김', 'rtc_no_media': '음성 수신 안 됨',
        'control_reconnect': '인터넷 재연결', 'network_change': '네트워크 변경', 'server_pcm': '서버 PCM 선택',
        'rtc_server_lost': '음성 중계 연결 끊김', None: '이전 기록 없음'}
    rows = [[str(r['id']), stamp(r['started_at'], tz), stamp(r['ended_at'], tz), state[r['status']],
        round(r['session_seconds'], 1), r['segment_count'], paths[r['initial_transport']], paths[r['last_transport']],
        r['fallback_count'], reasons[r['last_reason']], organized[r['organize_status']],
        r.get('input_tokens', ''), r.get('output_tokens', ''), float(r['usd']) if r.get('usd') is not None else '',
        '추정' if r.get('usd_estimated') else '', r.get('tunings') or ''] for r in records]
    return tab('통화 세션', ['통화 ID', '시작(한국 시각)', '종료(한국 시각)', '상태', '세션 시간(초)', '연결 구간 수',
        '첫 전송 방식', '마지막 전송 방식', '자동 전환 수', '마지막 연결 사유', '기억 정리',
        '입력 토큰', '출력 토큰', '비용(USD)', '추정 여부', '설정 실험'],
        rows, [42, 21, 21, 12, 16, 15, 20, 20, 15, 24, 12, 15, 15, 16, 14, 24])


def call_transcripts(c, start, until):
    """Saved ASR/output text, including drafts, through the filtered read-only view."""
    if not c.execute("SELECT to_regclass('call.transcript_report') AS report").fetchone()['report']:
        return []
    records = c.execute("""SELECT * FROM call.transcript_report
        WHERE started_at >= %s AND started_at < %s ORDER BY started_at,id""", (start, until)).fetchall()
    return [row for row in records if not report_private(row)]


def rung_calls(c, call_ids) -> set:
    """Calls that answered a call Marong placed at a time the friend set (marong.app_rings, docs/app-ring.md
    SPEC-142). Empty before 015_app_ring.sql."""
    if not call_ids or not c.execute("SELECT to_regclass('marong.app_rings') AS rings").fetchone()['rings']:
        return set()
    return {str(r['call_id']) for r in c.execute(
        "SELECT call_id FROM marong.app_rings WHERE status = 'answered' AND call_id = ANY(%s::uuid[])",
        (sorted({str(i) for i in call_ids}),)).fetchall()}


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
    for field, label, unit in (("summaries", "요약", "개"), ("notes", "메모", "개"), ("friends", "친구", "명"),
                               ("close", "근황", "명")):
        if memory.get(field):
            parts.append(f"{label} {len(memory[field])}{unit}")
    return " · ".join(parts) or "-"


def fetch(c, start: datetime, until: datetime, vectors: bool = True) -> dict:
    w = {"s": start, "u": until}
    # 벡터 전체가 필요 없으면(시트) 앞 8개 값만 읽음: 768개짜리를 30일치 통째로 읽지 않게
    vector = "e.embedding::text" if vectors else "((e.embedding::real[])[1:8])::text"
    data = {
        "messages": c.execute(
            "SELECT m.id, m.room_key, m.user_key, p.name, f.name AS friend_name, m.role, m.content, m.reply_to, m.meta, m.created_at "
            "FROM marong.messages m LEFT JOIN marong.people p ON p.user_key = m.user_key "
            "LEFT JOIN marong.friends f ON f.id = p.friend_id "
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
            "SELECT s.id, s.friend_id, f.name, s.content, s.close_content, s.meta, s.created_at FROM marong.shared_notes s "
            "JOIN marong.friends f ON f.id = s.friend_id "
            "WHERE s.created_at >= %(s)s AND s.created_at < %(u)s ORDER BY s.id", w).fetchall(),
        # 친구·공유 탭은 기간과 상관없이 지금 상태: 친구(카카오 키가 묶인 친구만), 말해 준 사이, 같은 단체방, 가장 최근 공유 메모
        "friends": c.execute(
            "SELECT f.id, f.name, f.share, max(p.last_seen) AS last FROM marong.friends f "
            "JOIN marong.people p ON p.friend_id = f.id GROUP BY f.id ORDER BY last DESC, f.name").fetchall(),
        "friendships": c.execute("SELECT friend_a, friend_b, label, close, told_by FROM marong.friendships").fetchall(),
        "mates": c.execute(
            "WITH rf AS (SELECT DISTINCT m.room_key, p.friend_id FROM marong.messages m "
            "  JOIN marong.people p ON p.user_key = m.user_key JOIN marong.rooms r ON r.room_key = m.room_key "
            "  WHERE NOT r.is_channel AND p.friend_id IS NOT NULL) "
            "SELECT DISTINCT a.friend_id AS a, b.friend_id AS b FROM rf a "
            "  JOIN rf b ON b.room_key = a.room_key AND b.friend_id <> a.friend_id").fetchall(),
        "latest_shared": {r["friend_id"]: r for r in c.execute(
            "SELECT DISTINCT ON (friend_id) friend_id, content, close_content, created_at FROM marong.shared_notes "
            "ORDER BY friend_id, id DESC").fetchall()},
        "requests": c.execute(
            "SELECT q.user_key, q.friend_id, q.kind, q.detail, q.created_at, r.is_channel, r.proactive, "
            "  r.proactive_per_day, p.name AS key_name, p.friend_id AS key_friend, p.last_seen AS key_seen "
            "FROM marong.requests q LEFT JOIN marong.rooms r ON r.room_key = q.room_key "
            "LEFT JOIN marong.people p ON p.user_key = q.user_key ORDER BY q.id DESC").fetchall(),
    }
    # Safety-state information and its content never enter the research export (SPEC-211).
    blocked = {row["id"] for row in data["messages"] if report_private(row)}
    replies = [row["reply_to"] for row in data["messages"] if row["reply_to"]]
    reply_sources = c.execute("SELECT id,content FROM marong.messages WHERE id=ANY(%s)", (replies,)).fetchall()
    blocked.update(row["id"] for row in reply_sources if report_private(row))
    blocked.update(row["id"] for row in data["messages"] if row["reply_to"] in blocked)
    data["messages"] = [row for row in data["messages"] if row["id"] not in blocked]
    for row in data["messages"]:
        row["meta"] = {key: value for key, value in (row["meta"] or {}).items() if key != "persona_check"}
    for key in ("embeddings", "summaries", "notes", "shared"):
        data[key] = [row for row in data[key] if not report_private(row)
                     and not (key == "embeddings" and row["source_type"] == "message" and row["source_id"] in blocked)]
    data["latest_shared"] = {id: row for id, row in data["latest_shared"].items() if not report_private(row)}
    data["requests"] = [row for row in data["requests"] if not owner_private(json.dumps(row["detail"], ensure_ascii=False))]
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
    data["ref_messages"] = {id: row for id, row in data["ref_messages"].items() if not report_private(row)}
    data["ref_summaries"] = {id: row for id, row in data["ref_summaries"].items() if not report_private(row)}
    room_keys = sorted({x["room_key"] for k in ("messages", "embeddings", "summaries", "notes") for x in data[k]})
    data["rooms"] = {r["room_key"]: r for r in c.execute(
        "SELECT room_key, is_channel FROM marong.rooms WHERE room_key = ANY(%s)", (room_keys,)).fetchall()}
    data["speakers"] = c.execute(
        "SELECT DISTINCT m.room_key, m.user_key, p.name FROM marong.messages m "
        "LEFT JOIN marong.people p ON p.user_key = m.user_key "
        "WHERE m.role = 'user' AND m.room_key = ANY(%s)", (room_keys,)).fetchall()
    return data


REQUESTS_SHOWN = 5


def request_text(q: dict, f: dict | None, friend_name: dict[int, str], pairs: dict[tuple[int, int], dict], tz) -> str:
    """대화로 한 요청 한 줄: 언제·어느 방에서 무엇을 말했는지와, 지금 그렇게 돼 있는지 아니면 관리자가 할 명령.
    f 는 요청을 붙인 친구 줄(말한 키가 지금 어느 친구에도 안 묶여 있으면 None). pairs 는 (작은 id, 큰 id) → 정해진 사이."""
    where = "1:1" if q["is_channel"] else "단체방" if q["is_channel"] is not None else "방 모름"
    head = f"{q['created_at'].astimezone(tz).strftime('%m/%d %H:%M')} {where}: "
    who = f["name"] if f else key(q["user_key"])
    if q["kind"] == "feature":
        return head + f"{q['detail']['feature']} 기능을 켜 달라고 함"
    if q["kind"].startswith("proactive_"):
        if q["kind"] == "proactive_off":
            return head + "선톡 그만 보내 달라고 함 → " + (
                "지금 안 보냄" if q["proactive"] is False else f"정할 일: admin schedule {who} off")
        if q["kind"] == "proactive_on":
            return head + "선톡 다시 보내 달라고 함 → " + (
                "지금 보냄" if q["proactive"] else f"정할 일: admin schedule {who} on")
        said = f"(하루 {q['detail']['per_day']}번)" if q["detail"].get("per_day") else ""
        now = f"하루 {q['proactive_per_day']}번" if q["proactive_per_day"] else "하루 횟수 기본값"
        return (head + f"선톡 {'더' if q['kind'] == 'proactive_more' else '덜'} 보내 달라고 함{said} → 지금 {now}, "
                f"정할 일: admin schedule {who} <하루 횟수>")
    if q["kind"] in ("share_off", "share_on", "friendship"):
        on = q["kind"] == "share_on"
        said = "공유 다시 켜 달라고 함" if on else "공유 꺼 달라고 함"
        if q["kind"] == "friendship":
            other = q["detail"].get("with")
            name = friend_name.get(other, q["detail"].get("name"))
            label = q["detail"].get("label") or "아는 사이"
            said = f"{name}(이)랑 '{label}' 사이라고 함"
        if f is None:  # 관리자가 그 키를 떼어 내서 지금은 어느 친구도 아님
            return head + said + f" → 이 키는 지금 어느 친구에도 안 묶여 있음, 정할 일: 먼저 admin link {who} <친구>"
        if q["kind"] != "friendship":
            return head + said + " → " + (f"지금 {'켜져' if on else '꺼져'} 있음" if f["share"] == on
                                          else f"정할 일: admin share {f['name']} {'on' if on else 'off'}")
        now = pairs.get(tuple(sorted((f["id"], other)))) if other else None
        arg = f'"{label}"' if " " in label else label
        todo = f"admin friendship {f['name']} {name} {arg} [close]"
        if now is None:
            return head + said + " → 정할 일: " + todo
        stored = (now["label"] or "아는 사이") + (" · 가까운 사이" if now["close"] else "")
        # 말한 관계가 정해진 것과 다르면(회사 동기 → 여자친구 같은) 바꿀 명령까지 보여 줌
        if q["detail"].get("label") and q["detail"]["label"] != now["label"]:
            return head + said + f" → 지금은 '{stored}'(으)로 정해져 있음, 바꾸려면: {todo}"
        return head + said + f" → 지금 '{stored}'(으)로 정해져 있음"
    k, name = key(q["user_key"]), q["detail"].get("name")
    return (head + f"{k} 키가 '{name}'(이)라고 함 → "
            + ("이 친구에 묶여 있음" if f and q["key_friend"] == f["id"]
               else "다른 친구에 묶여 있음" if q["key_friend"]
               else f"정할 일: 같은 사람이면 admin link {k} {name}, 다른 사람이면 admin unlink {k}"))


def build(c, start: datetime, until: datetime, tz, now: datetime | None = None, threshold: float = 0.4,
          recent_turns: int = 15, vectors: bool = True) -> tuple[list[dict], dict]:
    """기간 [start, until) 의 탭들(엑셀·시트 공용)과 개수. 탭마다 최신이 위. threshold·recent_turns 는 봇 설정(읽는 법 설명용).
    vectors 가 False 면 임베딩 벡터 전체 칸을 뺌(시트는 30일치를 5분마다 통째로 보내서 무거움)."""
    now = now or datetime.now(tz)
    data = fetch(c, start, until, vectors)
    msgs, embs = data["messages"], data["embeddings"]
    voice = call_transcripts(c, start, until)
    rung = rung_calls(c, {t["call_id"] for t in voice})
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
        kind = ("Discord DM" if k.startswith("discord-dm:") else "Discord 채널" if k.startswith("discord-ch:") else
                "1:1" if (data["rooms"].get(k) or {}).get("is_channel") else "단체")
        return f"{kind} {key(k)}" + (f" {who}" if who else "")

    def speaker(m):
        return "마롱이" if m["role"] == "assistant" else (m["name"] or key(m["user_key"]))

    def kind(m):
        # '(앱)': said in the in-app chat, or shown on the phone as an app notification (docs/app-chat.md SPEC-126)
        meta = m["meta"] or {}
        return what(m, meta) + ("(앱)" if meta.get("transport") == "app" else "")

    def what(m, meta):
        if m["role"] == "user":
            return "친구 말"
        if meta.get("missed"):
            return "알림(못 받은 전화)"
        if meta.get("reminder"):
            ring = meta.get("ring")
            return "알림(늦은 전화 약속)" if ring == "late" else "알림(전화 약속)" if ring else "알림(부탁한 일정)"
        if meta.get("google") == "connected":
            return "알림(구글 캘린더 연결)"
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
        if meta.get("reminder") or meta.get("missed"):
            return "알림(검색 안 함)"
        if meta.get("google"):
            return "구글 캘린더(검색 안 함)"
        return "기억 없이(늦음·오류)" if meta.get("late") or meta.get("error") else UNRECORDED

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

    # ── 대화: 동희(초록), 현경(노랑), 마롱이(파랑), 그 외 친구(분홍) ──
    rows, colors = [], []
    for m in reversed(msgs):
        meta = m["meta"] or {}
        mine = m["role"] == "assistant"
        rows.append([m["id"], at(m["created_at"]), room(m["room_key"]), speaker(m), kind(m), m["content"],
                     m["reply_to"], yes(meta.get("delivered")) if mine else "-", meta.get("model"), meta.get("effort"),
                     meta.get("input_tokens"), meta.get("output_tokens"), meta.get("cache_read_tokens"),
                     meta.get("cache_write_tokens"), used(m)])
        colors.append(speaker_color(m["role"], m["friend_name"] or m["name"]))
    if voice:
        # Merge only the exported conversation rows. Kakao storage, embeddings,
        # retrieval statistics and the running voice/bot processes stay intact.
        merged = [(m['created_at'], 0, m['id'], row, color)
                  for m, row, color in zip(reversed(msgs), rows, colors)]
        for t in voice:
            mine = t['role'] == 'assistant'
            label = ('통화(중단)' if t['interrupted'] else '통화(전사 중)' if not t['finalized']
                     else '통화(응답)' if mine else '통화(글)' if t['input_kind'] == 'text' else '통화(전사)')
            label += '(마롱이가 걺)' if str(t['call_id']) in rung else ''  # docs/app-ring.md SPEC-142
            room_label = 'Discord 통화' if t.get('entrypoint') == 'discord' else '통화'
            row = [f"V{t['id']}", at(t['started_at']), room_label + ' #' + str(t['call_id'])[:8],
                   '마롱이' if mine else (t['caller_name'] or '통화 사용자'), label, t['content'],
                   None, '미확인' if mine else '-', t['provider_model'], None, None, None, None, None,
                   '미집계' if mine else None]
            merged.append((t['started_at'], 1, t['id'], row, speaker_color(t['role'], t['caller_name'])))
        merged.sort(key=lambda item: item[:3], reverse=True)
        rows = [item[3] for item in merged]
        colors = [item[4] for item in merged]
    tabs.append(tab("대화", ["번호", "시각(한국)", "방", "보낸 쪽", "종류", "내용", "답한 메시지 번호", "전달됨", "모델",
                           "effort", "입력 토큰", "출력 토큰(생각 포함)", "캐시에서 읽은 토큰", "캐시에 쓴 토큰",
                           "들어간 예전 기억 수"],
                    rows, [7, 19, 22, 9, 10, 70, 9, 7, 17, 7, 9, 10, 10, 9, 12], wrap={5, 6}, colors=colors))

    # ── 임베딩 ──
    rows = []
    for e in reversed(embs):
        values = (e["vector"] or "").strip("[]{}").split(",")  # vector '[…]' 나 real[] '{…}'
        row = [e["model"], "메시지" if e["source_type"] == "message" else "요약", e["source_id"], room(e["room_key"]),
               at(e["created_at"]), e["dims"], e["content"], ", ".join(v.strip() for v in values[:8])]
        rows.append(row + [e["vector"]] if vectors else row)
    headers = ["모델", "원본 종류", "원본 번호", "방", "임베딩한 시각", "차원 수", "원본 글", "벡터 앞 8개 값"]
    widths = [26, 9, 9, 22, 19, 7, 60, 46]
    tabs.append(tab("임베딩", headers + ["벡터 전체"] if vectors else headers, rows,
                    widths + [40] if vectors else widths, wrap={7}))

    # ── 들어간 기억: 답마다 임베딩 검색 결과 한 줄씩(최신 답이 위, 한 답 안에서는 순위대로) ──
    rows = []
    with_memory = 0
    blank = [None] * 7  # 순위 ~ 찾은 것 원문
    for m in reversed(msgs):
        if m["role"] != "assistant":
            continue
        meta = m["meta"] or {}
        memory = meta.get("memory")
        asked = ref_msgs.get(m["reply_to"]) if m["reply_to"] else None
        base = [m["id"], at(m["created_at"]), room(m["room_key"]),
                (asked or {}).get("content") if m["reply_to"] else ("(선톡)" if meta.get("proactive") else
                                                                    "(못 받은 전화)" if meta.get("missed") else
                                                                    "(부탁한 알림)" if meta.get("reminder") else
                                                                    "(구글 캘린더 연결)" if meta.get("google") else None),
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
            elif sim is None:  # 낱말 검색으로만 찾은 것(2026-11-16부터)
                verdict = "안 넣음(흔한 낱말이거나 개수 초과)"
            else:
                verdict = "안 넣음(개수 초과)"
            who = "요약" if t == "summary" else (speaker(src) if src else "-")
            rows.append(base + ["함" if status == "ok" else RECALL.get(status, "함"), also(memory), rank,
                                "요약" if t == "summary" else "메시지", i, who,
                                None if sim is None else round(sim, 3), verdict, (src or {}).get("content")])
    tabs.append(tab("들어간 기억", ["답 번호", "답 시각", "방", "친구가 한 말", f"마롱이 답(앞 {REPLY_CHARS}자)",
                                "임베딩 검색", "같이 넣은 기억", "순위", "찾은 것 종류", "찾은 것 번호", "누구 말",
                                "비슷함(0~1)", "답에 넣었나", "찾은 것 원문"],
                    rows, [7, 19, 22, 40, 40, 16, 30, 6, 9, 9, 9, 10, 18, 60], wrap={4, 5, 14}))

    # ── 요약·메모(compact): 세 가지를 섞어 만든 시각이 최신인 것부터(같은 시각이면 요약·친구 메모·공유 메모 순) ──
    made = []
    for s in reversed(data["summaries"]):
        meta = s["meta"] or {}
        made.append((s["created_at"], [
            "요약", s["id"], at(s["created_at"]), room(s["room_key"]), s["content"] or "(빈 요약)",
            f"메시지 #{s['first_id']}~#{s['last_id']}" + (f" (건너뜀: {meta['skipped']})" if meta.get("skipped") else ""),
            meta.get("model"), meta.get("effort"), meta.get("input_tokens"), meta.get("output_tokens")]))
    for n in reversed(data["notes"]):
        made.append((n["created_at"], [
            "친구 메모", n["id"], at(n["created_at"]), f"{room(n['room_key'])} · {n['name'] or key(n['user_key'])}",
            n["content"], f"요약 #{n['summary_id']}" if n["summary_id"] else "요약 전에 먼저 고침",
            None, None, None, None]))
    for s in reversed(data["shared"]):
        meta = s["meta"] or {}
        told = s["content"] or "(다른 친구에게 할 얘기 없음)"
        if s["close_content"]:
            told += "\n[가까운 사이에게만: 요즘 근황]\n" + s["close_content"]
        made.append((s["created_at"], [
            "공유 메모", s["id"], at(s["created_at"]), s["name"], told,
            "거른 메모 " + (", ".join(f"#{x}" for x in meta.get("note_ids") or []) or "-"),
            meta.get("model"), meta.get("effort"), meta.get("input_tokens"), meta.get("output_tokens")]))
    made.sort(key=lambda x: x[0], reverse=True)  # 같은 시각은 넣은 순서 그대로(정렬이 안정적)
    tabs.append(tab("요약·메모", ["종류", "번호", "만든 시각", "방 또는 친구", "내용", "구간·재료", "모델", "effort",
                              "입력 토큰", "출력 토큰"],
                    [r for _, r in made], [9, 7, 19, 26, 80, 24, 17, 7, 9, 9], wrap={5}))

    # ── 친구·공유(지금 기준): 누구와 아는 사이인지와 다른 친구에게 하는 얘기. 공유를 끈 친구 얘기는 아무에게도 안 함 ──
    # (2026-10-30 현경 공유가 꺼져 있던 게 시트에 안 보여서 추가)
    friend_name = {f["id"]: f["name"] for f in data["friends"]}
    known: dict[int, dict[int, list[str]]] = {}
    for fs in data["friendships"]:
        if fs["friend_a"] not in friend_name or fs["friend_b"] not in friend_name:
            continue
        teller = (f"말해 준 친구 {friend_name[fs['told_by']]}" if fs["told_by"] in friend_name
                  else "관리자가 정함" if fs["told_by"] is None else None)
        parts = [x for x in (fs["label"] or "아는 사이", "가까운 사이" if fs["close"] else None, teller) if x]
        for me, other in ((fs["friend_a"], fs["friend_b"]), (fs["friend_b"], fs["friend_a"])):
            known.setdefault(me, {}).setdefault(other, []).extend(parts)
    for m in data["mates"]:
        if m["a"] in friend_name and m["b"] in friend_name:
            known.setdefault(m["a"], {}).setdefault(m["b"], []).append("같은 단체방")
    pairs = {(fs["friend_a"], fs["friend_b"]): fs for fs in data["friendships"]}
    by_id = {f["id"]: f for f in data["friends"]}
    asked: dict[int, list[str]] = {}  # 친구 → 대화로 한 요청(최신 먼저). 묶기 요청은 그 이름 친구에게 붙임
    loose: dict[str, list[dict]] = {}  # 어느 친구 줄에도 못 붙인 요청(친구에 안 묶인 키) → 키마다 한 줄
    for q in data["requests"]:
        if q["kind"] == "link":
            owners = [f for f in data["friends"] if q["detail"].get("name") == f["name"]]
        else:
            # 말한 사람은 그 키가 지금 묶인 친구. 관리자가 키를 다른 친구로 옮기면(admin link) 요청 때 친구는 키가 없어
            # 친구 목록에서 빠지므로 키 쪽을 먼저 본다
            f = by_id.get(q["key_friend"]) or by_id.get(q["friend_id"])
            owners = [f] if f else []
        for f in owners:
            asked.setdefault(f["id"], []).append(request_text(q, f, friend_name, pairs, tz))
        if not owners:
            loose.setdefault(q["user_key"], []).append(q)
    rows = []
    for f in data["friends"]:
        s = data["latest_shared"].get(f["id"])
        knows = sorted((friend_name[o], " · ".join(parts)) for o, parts in (known.get(f["id"]) or {}).items())
        if not f["share"]:
            light = close = "(공유 끔: 아무에게도 안 함)"
        elif s:
            light, close = s["content"] or "(없음)", s["close_content"] or "(없음)"
        else:
            light = close = "(아직 없음)"
        rows.append([f["name"], "켬" if f["share"] else "끔", "\n".join(f"{n}({how})" for n, how in knows) or "(아직 없음)",
                     light, close, "\n".join(asked.get(f["id"], [])[:REQUESTS_SHOWN]) or "(없음)",
                     at(s["created_at"]) if s else None, at(f["last"])])
    for k, qs in loose.items():
        who = f"{qs[0]['key_name'] or '이름 모름'}({key(k)}, 친구에 안 묶인 키)"
        texts = [request_text(q, None, friend_name, pairs, tz) for q in qs][:REQUESTS_SHOWN]
        rows.append([who, "-", "-", "-", "-", "\n".join(texts), None, at(qs[0]["key_seen"])])
    tabs.append(tab("친구·공유", ["친구", "공유", "아는 사이", "아는 친구 누구에게나: 가벼운 얘기",
                               "가까운 사이에게만: 요즘 근황", f"대화로 한 요청(최근 {REQUESTS_SHOWN}개)", "공유 메모 만든 시각",
                               "마지막으로 본 때"],
                    rows, [10, 6, 40, 50, 50, 60, 19, 19], wrap={3, 4, 5, 6}))

    calls_tab = call_sessions(c, start, until, tz)
    if calls_tab is not None:
        tabs.append(calls_tab)

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
        f"대화: 이 기간에 오간 채팅 메시지 {len(msgs)}개(친구 말 {len(msgs) - len(replies) - len(proactive)}, "
        f"마롱이 답 {len(replies)}, 선톡 {len(proactive)}). 현경이는 노랑, 마롱이는 파랑, 동희는 초록 줄이에요. "
        "그 외 친구는 분홍이고, 기록된 화자 이름을 기준으로 칠해요. "
        "마지막 칸은 그 답에 임베딩 검색으로 실제로 넣은 예전 기억 수예요.",
        f"임베딩: 이 기간에 만든 임베딩 {len(embs)}개. 메시지·요약을 숫자 벡터로 바꾼 것이고, 뜻이 비슷한 글끼리 숫자도 비슷해요."
        + ("" if vectors else " 벡터 전체는 엑셀(bash deploy/ovh.sh report)에만 있어요."),
        f"들어간 기억: 기억 기록이 있는 마롱이 말 {with_memory}개. 답마다 임베딩 검색으로 찾은 예전 대화를 한 줄씩 적고, "
        "실제로 답에 넣었는지(넣음·안 넣음)와 그 원문을 보여 줘요.",
        f"요약·메모: 이 기간에 만든 요약 {len(data['summaries'])}개, 친구 메모 {len(data['notes'])}줄, "
        f"공유 메모 {len(data['shared'])}줄(compact 된 기억).",
        f"친구·공유: 기간과 상관없이 지금 기준 친구 {len(data['friends'])}명. 친구마다 공유 켬·끔, 아는 사이(관리자가 정한 관계와 "
        "같은 단체방), 다른 친구에게 하는 얘기예요. 가까운 사이(연인·가족·절친)끼리는 1:1 방에서 요즘 근황까지 하고, 공유를 끈 "
        "친구 얘기는 아무에게도 안 해요. 공유 켬·끔, 아는 사이·가까운 사이, 새 키 묶기는 관리자만 정하고 친구 말로는 안 바뀌어요. "
        "대화로 한 요청과 정할 일(노트북에서 bash deploy/ovh.sh admin …)은 '대화로 한 요청' 칸에 있어요.",
        "",
        "■ 마롱이가 답할 때 넣는 기억",
        f"- 최근 대화 원문(같은 방에서 친구 말 {recent_turns}번이 들어가게 거슬러 올라감. 답 없는 선톡은 최근 3개만, "
        "많아야 60줄)",
        "- 그 방의 최근 요약 10개와 친구별 기억 메모",
        "- 지금 말과 비슷한 예전 대화: 지금 말을 임베딩한 검색과 두 글자 낱말 검색으로 같은 방의 예전 메시지·요약을 "
        "각각 12개까지 찾아 순위를 합쳐요(RRF). '뭔코트?'처럼 짧은 말은 바로 앞 두 마디를 붙여 찾아요. "
        f"비슷함 {threshold:g} 이상이거나 드문 낱말이 맞은 것 중 요약 3개·메시지 5개까지 넣고, 찾은 말은 그때 마롱이 답과 "
        "한 쌍으로 넣어요. 최근 대화와 이미 넣은 요약은 빼고 찾고, 임베딩이 준비 안 됐거나 1.5초를 넘기면 낱말 검색만 "
        "써요(2026-11-16부터. 그 전에는 임베딩 검색만, 요약 3개·메시지 4개).",
        "- 지금 친구와 아는 친구들의 가벼운 얘기(공유 메모). 연인·가족 같은 가까운 사이면 그 친구의 요즘 근황까지",
        "- 선톡은 그 방의 최근 대화·요약·메모만 보고 임베딩 검색은 하지 않아요.",
        "",
        "■ 참고",
        "- 탭마다 최신이 맨 위예요.",
        f"- '{UNRECORDED}'은 답마다 넣은 기억을 적기 시작한 2026-10-26 밤 11시쯤 전에 보낸 답이에요. "
        "그때도 임베딩 검색은 했지만 무엇을 찾아 넣었는지는 적지 않았어요.",
        "- '안 함(말이 짧아서)'은 'ㅋㅋ'처럼 짧은 말이라 검색하지 않은 것.",
        "- 시각은 모두 한국 시각이에요. 카카오 키 원문 대신 관리 명령(admin)과 같은 #짧은키를 적었어요.",
        "- 종류 칸의 '(앱)'은 마롱이 앱의 글 대화에서 오간 말이나 폰에 앱 알림으로 간 말이에요(방은 같은 Discord DM). "
        "'알림(전화 약속)'은 앱이 없어서 디스코드로 보낸 통화 초대, '알림(못 받은 전화)'는 마롱이가 건 전화를 못 받았을 때의 "
        "한마디, '(마롱이가 걺)'은 마롱이가 약속한 때 먼저 건 전화를 받은 통화예요.",
    ]
    if not vectors:
        lines.append("- 시트 메뉴 '마롱이 > 지금 새로고침'을 누르면 1분쯤 뒤에 새로 채워요. 안 눌러도 5분마다 새로 채워요.")
        lines.append("- 걸어 둔 필터는 새로 채운 뒤에도 그대로예요. 손으로 칠한 색·서식은 새로 채울 때 지워져요.")
    if calls_tab is not None:
        counts['calls'] = len(calls_tab['rows'])
        lines.append(f"- 통화 세션: 기간과 겹치는 통화 {len(calls_tab['rows'])}개. 통화 ID당 한 줄이며 자동 전환·재연결로 중복되지 않아요.")
        lines.append("- 세션 시간은 해당 통화의 서버 연결 구간을 합한 초예요(연결 대기 시간 제외, Google 청구 시간·요금 아님). 진행 중인 통화는 갱신 시각까지예요.")
        lines.append("- 통화 원문·요약·기억 내용·로그인 이메일은 이 탭에 보내지 않아요. 전송 방식 기록은 2026-11-13 배포 이후부터예요.")
    if voice:
        counts['call_transcripts'] = len(voice)
        lines.append(f"- 대화 탭에 저장된 통화 전사 {len(voice)}줄도 함께 표시해요. V로 시작하는 번호가 통화 발화이며 카톡·디스코드와 시각순으로 섞여 있어요.")
        lines.append("- '통화(전사 중)'은 아직 완성되지 않은 글로 다음 갱신에 같은 번호의 내용이 바뀌어요. '통화(중단)'은 중간에 끊긴 발화예요. 사용자 글 입력은 '통화(글)'로 구분해요.")
        lines.append("- 통화의 '전달됨: 미확인'은 실제 음성 청취 완료를 측정하지 않았다는 뜻이에요. 발화별 토큰·참고한 기억 수는 추정하지 않아요. 삭제·제외된 통화 발화는 내보내지 않아요.")
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
        colors, fills = t.get("colors") or [], {}
        for j, row in enumerate(t["rows"]):
            ws.append([clean(v) for v in row])
            color = colors[j] if j < len(colors) else None
            fill = fills.setdefault(color, PatternFill("solid", fgColor=color.lstrip("#").upper())) if color else None
            for c in ws[ws.max_row]:
                if isinstance(c.value, str) and c.value.startswith("="):
                    c.data_type = "s"  # '=' 로 시작하는 말을 수식으로 읽지 않게
                c.alignment = TOP_WRAP if c.column in wrap else TOP
                if fill:
                    c.fill = fill
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
    못 물었거나 물어보기를 모르는 예전 sheet.gs 면 False. 1분마다 도는 거라 까닭은 남기지 않음(5분 갱신이 남김)."""
    try:
        r = post(url, {"poll": True}, ASK_TIMEOUT_S, transport)
        answer = r.json() if r.status_code == 200 else None
    except Exception:  # 연결 실패·JSON 아닌 답(로그인 페이지 등)
        return False
    return (isinstance(answer, dict) and answer.get("ok") is True
            and isinstance(answer.get("asked"), (int, float)) and answer["asked"] > 0)


def send(url: str, payload: dict, transport=None) -> str | None:
    """시트 웹 앱(tools/sheet.gs)에 탭을 보냄. 잘 되면 None, 아니면 짧은 까닭(주소와 구글의 답 내용은 적지 않음)."""
    # Replacing the same snapshot is idempotent, including a partially written
    # Apps Script response. Retry transient HTTP/transport errors, not bad data.
    for attempt in range(2):
        try:
            r = post(url, payload, SHEET_TIMEOUT_S, transport)
        except (httpx.TransportError, OSError) as e:
            if attempt == 1: return type(e).__name__
        except Exception as e:  # 오류 글에 주소가 들어 있을 수 있어서 종류만
            return type(e).__name__
        else:
            if r.status_code not in (429, 500, 502, 503, 504) or attempt == 1: break
        time.sleep(2 ** (attempt + 1))
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
        if args.if_asked:  # 1분마다 같은 말을 남기지 않음(5분 갱신이 남김)
            return 0
        print("SHEET_URL 이 비었거나 Apps Script 웹 앱 주소가 아님(노트북에서 bash deploy/ovh.sh sheet url)", file=sys.stderr)
        return 1
    if args.if_asked and not asked(url, transport):
        return 0
    threshold = float(os.getenv("RECALL_MIN_SIMILARITY") or 0.4)
    recent_turns = int(os.getenv("REPLY_TURNS") or 15)  # 답할 때 넣는 최근 대화(봇의 REPLY_TURNS)
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
