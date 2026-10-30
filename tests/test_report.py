"""tools/report.py(기록 리포트: 엑셀·구글 시트)를 진짜 Postgres 로 시험한다. 시트 웹 앱은 가짜(httpx.MockTransport).
실행(윈도우): .venv\\Scripts\\python tests\\test_report.py   (리눅스·맥: .venv/bin/python tests/test_report.py)
pgserver 가 필요함: pip install pgserver"""
import contextlib
import hashlib
import importlib.util
import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import httpx  # noqa: E402
import psycopg  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from pg import TestDB  # noqa: E402

CHECKS = 0
TZ = ZoneInfo("Asia/Seoul")
UNTIL = "2026-10-27T19:00+09:00"  # 기간: 10/26 19:00 ~ 10/27 19:00(한국)
SHEETS = ["읽는 법", "대화", "임베딩", "들어간 기억", "요약·메모", "친구·공유"]
RAW_KEYS = ("room-dm", "room-group", "room-g2", "room-anon", "u-dong", "u-hk", "u-anon", "u-ms")
SECRET = "AKfycbTESTSECRET"
SHEET_URL = f"https://script.google.com/macros/s/{SECRET}/exec"
ECHO_URL = "https://script.googleusercontent.com/macros/echo?user_content_key=abc"
STAMP = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")


def ok(cond, what):
    global CHECKS
    assert cond, what
    CHECKS += 1


def short(k):
    return "#" + hashlib.sha1(k.encode()).hexdigest()[:8]


def kst(text):
    return datetime.fromisoformat(text + "+09:00")


def load_report():
    spec = importlib.util.spec_from_file_location("report", ROOT / "tools" / "report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(ws):
    return [list(r) for r in ws.iter_rows(min_row=2, values_only=True)]


def run(report, argv, transport=None) -> tuple[int, str]:
    """report.main 을 부르고 (종료 코드, stdout·stderr·INFO 로그를 합친 글). httpx INFO 로그로 주소가 새는지도 봄."""
    buf = io.StringIO()
    root, handler = logging.getLogger(), logging.StreamHandler(buf)
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = report.main(argv, transport=transport)
    finally:
        root.removeHandler(handler)
        root.setLevel(level)
    return code, buf.getvalue()


def web_app(answer):
    """가짜 Apps Script 웹 앱: POST 에는 302 로 결과 주소를 알려 주고, 따라온 GET 에 answer(request)를 돌려줌."""
    seen = []

    def handle(request):
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(302, headers={"Location": ECHO_URL})
        return answer(request)
    return httpx.MockTransport(handle), seen


def seed(db) -> dict:
    """기간 안팎의 대화·요약·메모·임베딩. 돌려주는 값은 만든 줄의 번호."""
    one = lambda sql, params: db.admin(sql + " RETURNING id", params)[0][0]  # noqa: E731

    def msg(room, user, role, content, at, reply_to=None, meta=None):
        return one("INSERT INTO marong.messages (room_key, user_key, role, content, reply_to, meta, created_at) "
                   "VALUES (%s, %s, %s, %s, %s, %s, %s)", (room, user, role, content, reply_to, Jsonb(meta or {}), kst(at)))

    def summary(room, first, last, content, at, meta=None):
        return one("INSERT INTO marong.summaries (room_key, first_id, last_id, content, meta, created_at) "
                   "VALUES (%s, %s, %s, %s, %s, %s)", (room, first, last, content, Jsonb(meta or {}), kst(at)))

    def note(room, user, content, at, summary_id=None):
        return one("INSERT INTO marong.notes (room_key, user_key, content, summary_id, created_at) "
                   "VALUES (%s, %s, %s, %s, %s)", (room, user, content, summary_id, kst(at)))

    def embed(kind, source, room, vector, at):
        db.admin("INSERT INTO marong.embeddings (model, source_type, source_id, room_key, embedding, created_at) "
                 "VALUES ('google/embeddinggemma-300m', %s, %s, %s, %s::vector, %s)", (kind, source, room, vector, kst(at)))

    db.admin("INSERT INTO marong.rooms (room_key, is_channel) VALUES ('room-dm', true), ('room-group', false)")
    f_dong = one("INSERT INTO marong.friends (name) VALUES (%s)", ("동희",))
    f_hk = one("INSERT INTO marong.friends (name) VALUES (%s)", ("현경",))
    db.admin("INSERT INTO marong.people (user_key, name, friend_id) VALUES ('u-dong', '동희', %s), ('u-hk', '현경', %s), "
             "('u-anon', NULL, NULL)", (f_dong, f_hk))
    # 친구·공유 탭(지금 기준): 동희가 말해 준 가까운 사이, 현경은 공유 끔, 민수는 동희와 같은 단체방(기간 밖 대화)
    db.admin("INSERT INTO marong.friendships (friend_a, friend_b, label, told_by, close) VALUES (%s, %s, '여자친구', %s, true)",
             (min(f_dong, f_hk), max(f_dong, f_hk), f_dong))
    db.admin("UPDATE marong.friends SET share = false WHERE id = %s", (f_hk,))
    f_ms = one("INSERT INTO marong.friends (name) VALUES (%s)", ("민수",))
    db.admin("INSERT INTO marong.people (user_key, name, friend_id) VALUES ('u-ms', '민수', %s)", (f_ms,))
    db.admin("INSERT INTO marong.rooms (room_key, is_channel) VALUES ('room-g2', false)")
    i = {}
    i["x1"] = msg("room-g2", "u-ms", "user", "다들 주말에 뭐 해", "2026-09-01T10:00")
    i["x2"] = msg("room-g2", "u-dong", "user", "난 집에 있을 듯", "2026-09-01T10:01")
    # 대화로 한 요청(설정은 관리자만 정해서 남기기만 함): 친구 줄에 붙이고, 친구에 안 묶인 키는 따로 한 줄
    db.admin("INSERT INTO marong.rooms (room_key, is_channel) VALUES ('room-anon', true)")

    def ask(user, friend, room, kind, detail, at):
        db.admin("INSERT INTO marong.requests (user_key, friend_id, room_key, kind, detail, created_at) "
                 "VALUES (%s, %s, %s, %s, %s, %s)", (user, friend, room, kind, Jsonb(detail), kst(at)))

    ask("u-hk", f_hk, None, "share_on", {}, "2026-10-28T09:00")
    ask("u-dong", f_dong, "room-dm", "friendship", {"name": "민수", "label": "대학 친구", "with": f_ms}, "2026-10-28T09:10")
    ask("u-dong", f_dong, "room-dm", "proactive_off", {}, "2026-10-28T09:20")
    ask("u-anon", None, "room-group", "link", {"name": "동희"}, "2026-10-28T09:30")
    ask("u-anon", None, "room-anon", "proactive_less", {"per_day": 3}, "2026-10-28T09:40")
    # 기간 밖(예전 기억)
    i["o1"] = msg("room-dm", "u-dong", "user", "작년에 제주도 가서 귤 따기 했어", "2026-10-20T20:00")
    i["o2"] = msg("room-dm", None, "assistant", "귤 따기 재밌었겠다 🍊", "2026-10-20T20:00:05", i["o1"])
    i["o3"] = msg("room-dm", "u-dong", "user", "회사 근처 마라탕 맛집 찾았어", "2026-10-20T21:00")
    i["s_old"] = summary("room-dm", i["o1"], i["o3"], "동희는 제주도 여행과 귤 따기를 좋아함", "2026-10-20T22:00")
    i["n_old"] = note("room-dm", "u-dong", "예전 메모: 마라탕 좋아함", "2026-10-20T22:00", i["s_old"])
    embed("message", i["o1"], "room-dm", "[9,9,9,9]", "2026-10-20T20:01")
    # 기간 안
    i["b0"] = msg("room-group", "u-hk", "user", "시작 시각에 한 말", "2026-10-26T19:00")  # 시작 시각은 넣음
    i["m1"] = msg("room-dm", "u-dong", "user", "제주도 또 가고 싶다", "2026-10-27T09:00")
    i["r1"] = msg("room-dm", None, "assistant", "제주도 좋지! " + "귤 따기 또 하자 🍊 " * 12, "2026-10-27T09:00:05", i["m1"], {
        "model": "claude-haiku-5-5", "effort": "xhigh", "input_tokens": 5000, "output_tokens": 800,
        "cache_read_tokens": 4000, "cache_write_tokens": 0, "delivered": True,
        "memory": {"recent": [i["m1"], i["m1"]], "summaries": [], "notes": [i["n_old"]], "recall": "ok",
                   "candidates": [{"type": "summary", "id": i["s_old"], "similarity": 0.812},
                                  {"type": "message", "id": i["o1"], "similarity": 0.734},
                                  {"type": "message", "id": i["o2"], "similarity": 0.61},
                                  {"type": "message", "id": i["o3"], "similarity": 0.215}],
                   "recalled": [{"type": "summary", "id": i["s_old"], "similarity": 0.812},
                                {"type": "message", "id": i["o1"], "similarity": 0.734}],
                   "friends": [f_dong, f_hk], "close": [f_hk]}})
    i["m2"] = msg("room-dm", "u-dong", "user", "ㅋㅋ", "2026-10-27T10:00")
    i["r2"] = msg("room-dm", None, "assistant", "ㅋㅋ 왜 웃어?", "2026-10-27T10:00:03", i["m2"], {
        "delivered": True, "memory": {"recent": [i["m1"], i["m2"]], "summaries": [i["s_old"]], "notes": [i["n_old"]],
                                      "recall": "short", "candidates": [], "recalled": [], "friends": []}})
    i["s_new"] = summary("room-dm", i["m1"], i["r2"], "동희가 제주도에 또 가고 싶어 함", "2026-10-27T11:00",
                         {"model": "claude-haiku-5-5", "effort": "low", "input_tokens": 1200, "output_tokens": 300})
    i["n1"] = note("room-dm", "u-dong", "제주도 좋아함 · 귤 따기", "2026-10-27T11:00", i["s_new"])
    i["sh1"] = one("INSERT INTO marong.shared_notes (friend_id, content, close_content, meta, created_at) "
                   "VALUES (%s, %s, %s, %s, %s)",
                   (f_dong, "제주도 여행을 좋아함", "- 발표 준비로 바쁨", Jsonb({"note_ids": [i["n1"]], "model": "claude-haiku-5-5"}),
                    kst("2026-10-27T11:05")))
    i["p1"] = msg("room-dm", None, "assistant", "동희야, 점심 뭐 먹었어? 🍜", "2026-10-27T12:00", None, {
        "proactive": True, "delivered": True,
        "memory": {"recent": [i["m1"], i["r2"]], "summaries": [i["s_new"]], "notes": [i["n1"]]}})
    i["g1"] = msg("room-group", "u-hk", "user", "=SUM(1,2) 이거 수식이야? 벨\x07소리", "2026-10-27T13:00")
    i["gr1"] = msg("room-group", None, "assistant", "현경아 그건 엑셀 수식이야 📊", "2026-10-27T13:00:04", i["g1"],
                   {"delivered": True})  # 기억 기록 전에 보낸 답
    i["g2"] = msg("room-group", "u-anon", "user", "누구게", "2026-10-27T14:00")
    i["gl"] = msg("room-group", None, "assistant", "잠깐만 기다려 줘", "2026-10-27T14:02", i["g2"],
                  {"late": True, "delivered": True})
    i["s_skip"] = summary("room-group", i["b0"], i["gl"], "", "2026-10-27T15:00", {"skipped": "JSON 아님"})
    embed("message", i["m1"], "room-dm", "[0.1,0.2,0.3,0.4]", "2026-10-27T09:00:10")
    embed("summary", i["s_new"], "room-dm", "[0.5,0.5,0.5,0.5]", "2026-10-27T11:00:10")
    # 끝 시각은 빼고
    i["z1"] = msg("room-dm", "u-dong", "user", "끝 시각에 한 말", "2026-10-27T19:00")
    return i


def check_tabs(report, db, i):
    """build: 탭(엑셀·시트 공용)의 내용."""
    with psycopg.connect(db.app_url, row_factory=dict_row) as c:  # 봇과 같은 marong 계정, 읽기만
        c.read_only = True
        tabs, n = report.build(c, kst("2026-10-26T19:00"), kst("2026-10-27T19:00"), TZ, now=kst("2026-10-27T19:30"))
    ok([t["name"] for t in tabs] == SHEETS, f"탭: {[t['name'] for t in tabs]}")
    ok(n == {"messages": 10, "replies": 4, "proactive": 1, "embeddings": 2, "with_memory": 3, "summaries": 2,
             "notes": 1, "shared": 1}, f"개수: {n}")
    values = [v for t in tabs for r in [t["headers"]] + t["rows"] for v in r]
    ok(all(v is None or type(v) in (str, int, float) for v in values), "칸 값은 글·정수·실수·빈칸만")
    ok(all(len(r) == len(t["headers"]) for t in tabs for r in t["rows"]), "줄마다 칸 수가 머리줄과 같음")
    ok(not any(k in v for v in values if isinstance(v, str) for k in RAW_KEYS), "카카오 키 원문이 없음")
    by = {t["name"]: t for t in tabs}

    readme = [r[0] for r in by["읽는 법"]["rows"]]
    ok(readme[:2] == ["기간: 2026-10-26 19:00:00 ~ 2026-10-27 19:00:00 (한국 시각, 끝 시각은 빼고)",
                      "마지막 갱신: 2026-10-27 19:30:00"], f"읽는 법 기간·갱신 시각: {readme[:2]}")
    ok(any("12개" in x and "0.4 이상" in x and "요약 3개·메시지 4개" in x for x in readme), "읽는 법에 기억 넣는 순서")
    ok(not any("지금 새로고침" in x or "필터" in x for x in readme), "엑셀 읽는 법에는 시트 메뉴·필터 얘기가 없음")
    ok("- 탭마다 최신이 맨 위예요." in readme
       and any(x.startswith("- '모름(기록 시작 전)'은") and "2026-10-26" in x for x in readme), "읽는 법: 최신이 위, '모름' 뜻")

    # 대화: 기간 안 메시지만(시작 시각은 넣고 끝 시각은 뺌), 최신이 위. 줄 색은 친구 말(분홍)·마롱이 말(파랑)
    talk = by["대화"]["rows"]
    ids = [r[0] for r in talk]
    ok(ids == [i[k] for k in ("gl", "g2", "gr1", "g1", "p1", "r2", "m2", "r1", "m1", "b0")], f"기간 안 메시지만, 최신이 위: {ids}")
    colors = by["대화"]["colors"]
    ok(colors == ["#e8f0fe" if r[3] == "마롱이" else "#fce8e6" for r in talk] and len(set(colors)) == 2, f"줄 색: {colors}")
    ok(all("colors" not in x for x in tabs if x["name"] != "대화"), "다른 탭은 줄 색 없음")
    t = {r[0]: r for r in talk}
    ok(t[i["m1"]][1] == "2026-10-27 09:00:00" and t[i["b0"]][1] == "2026-10-26 19:00:00", "시각은 한국 시각 글")
    ok(t[i["m1"]][2] == f"1:1 {short('room-dm')} 동희", t[i["m1"]][2])
    ok(t[i["g1"]][2] == f"단체 {short('room-group')} {short('u-anon')}, 현경", t[i["g1"]][2])
    ok(t[i["m1"]][3] == "동희" and t[i["r1"]][3] == "마롱이" and t[i["g2"]][3] == short("u-anon"), "보낸 쪽: 이름·마롱이·#키")
    ok([t[i[k]][4] for k in ("m1", "r1", "p1", "gl")] == ["친구 말", "답장", "선톡", "늦은 답(안내)"], "종류")
    ok(t[i["r1"]][6] == i["m1"] and t[i["r1"]][7] == "예" and t[i["m1"]][7] == "-", "답한 메시지·전달됨")
    ok(t[i["r1"]][8:14] == ["claude-haiku-5-5", "xhigh", 5000, 800, 4000, 0], f"모델·토큰: {t[i['r1']][8:14]}")
    used = {k: t[i[k]][14] for k in ("m1", "r1", "r2", "p1", "gr1", "gl")}
    ok(used == {"m1": None, "r1": 2, "r2": 0, "p1": "선톡(검색 안 함)", "gr1": "모름(기록 시작 전)", "gl": "기억 없이(늦음·오류)"},
       f"들어간 예전 기억 수: {used}")
    ok(t[i["g1"]][5] == "=SUM(1,2) 이거 수식이야? 벨소리", f"제어 문자는 뺌: {t[i['g1']][5]!r}")

    # 임베딩: 기간 안에서 만든 것만(최신이 위), 벡터 전체(엑셀용)
    emb = by["임베딩"]["rows"]
    ok(len(emb) == 2 and by["임베딩"]["headers"][-1] == "벡터 전체", f"임베딩 2개(기간 밖 1개는 뺌): {emb}")
    ok(emb[0][1:3] == ["요약", i["s_new"]] and emb[0][6] == "동희가 제주도에 또 가고 싶어 함", f"{emb[0]}")
    ok(emb[1][1:3] == ["메시지", i["m1"]] and emb[1][5] == 4 and emb[1][6] == "제주도 또 가고 싶다", f"{emb[1]}")
    ok(emb[1][7] == "0.1, 0.2, 0.3, 0.4" and emb[1][8] == "[0.1,0.2,0.3,0.4]", f"벡터: {emb[1][7:]}")

    # 들어간 기억: 찾은 것마다 한 줄, 넣음·안 넣음. 최신 답이 위, 한 답 안에서는 순위대로
    mem = by["들어간 기억"]["rows"]
    ok(len(mem) == 8, f"r1 후보 4줄 + r2·p1·gr1·gl 한 줄씩: {len(mem)}")
    ok([r[0] for r in mem] == [i[k] for k in ("gl", "gr1", "p1", "r2")] + [i["r1"]] * 4
       and [r[7] for r in mem[4:]] == [1, 2, 3, 4], f"순서: {[(r[0], r[7]) for r in mem]}")
    r1 = [r for r in mem if r[0] == i["r1"]]
    got = [(r[8], r[9], r[11], r[12]) for r in r1]
    ok(got == [("요약", i["s_old"], 0.812, "넣음"), ("메시지", i["o1"], 0.734, "넣음"),
               ("메시지", i["o2"], 0.61, "안 넣음(개수 초과)"), ("메시지", i["o3"], 0.215, "안 넣음(0.4 미만)")],
       f"후보와 판정: {got}")
    ok([r[10] for r in r1] == ["요약", "동희", "마롱이", "동희"], "누구 말")
    ok(r1[0][13] == "동희는 제주도 여행과 귤 따기를 좋아함" and r1[1][13] == "작년에 제주도 가서 귤 따기 했어", "찾은 것 원문")
    ok(r1[0][3] == "제주도 또 가고 싶다" and len(r1[0][4]) == 100 and r1[0][4].endswith("…"), "친구 말·답 앞 100자")
    ok(r1[0][5:7] == ["함", f"최근 대화 #{i['m1']}~#{i['m1']} · 메모 1개 · 친구 2명 · 근황 1명"], f"{r1[0][5:7]}")
    one = {r[0]: r for r in mem if r[0] != i["r1"]}
    ok(one[i["r2"]][5] == "안 함(말이 짧아서)" and one[i["r2"]][7] is None, f"짧은 말: {one[i['r2']]}")
    ok(one[i["p1"]][3] == "(선톡)" and one[i["p1"]][5] == "선톡(검색 안 함)"
       and one[i["p1"]][6] == f"최근 대화 #{i['m1']}~#{i['r2']} · 요약 1개 · 메모 1개", f"선톡: {one[i['p1']]}")
    ok(one[i["gr1"]][5] == "모름(기록 시작 전)" and one[i["gl"]][5] == "기억 없이(늦음·오류)", "기억 기록이 없는 답")

    # 요약·메모(compact): 셋을 섞어 만든 시각이 최신인 것부터(같은 시각이면 요약이 먼저)
    made = [(r[0], r[1]) for r in by["요약·메모"]["rows"]]
    ok(made == [("요약", i["s_skip"]), ("공유 메모", i["sh1"]), ("요약", i["s_new"]), ("친구 메모", i["n1"])],
       f"기간 안 요약·메모만, 최신이 위: {made}")
    comp = {(r[0], r[1]): r for r in by["요약·메모"]["rows"]}
    s_new = comp[("요약", i["s_new"])]
    ok(s_new[4] == "동희가 제주도에 또 가고 싶어 함" and s_new[5] == f"메시지 #{i['m1']}~#{i['r2']}"
       and s_new[6:10] == ["claude-haiku-5-5", "low", 1200, 300], f"요약: {s_new}")
    ok(comp[("요약", i["s_skip"])][4] == "(빈 요약)" and "건너뜀: JSON 아님" in comp[("요약", i["s_skip"])][5], "건너뛴 요약")
    ok(comp[("친구 메모", i["n1"])][3] == f"1:1 {short('room-dm')} 동희 · 동희"
       and comp[("친구 메모", i["n1"])][5] == f"요약 #{i['s_new']}", f"{comp[('친구 메모', i['n1'])]}")
    ok(comp[("공유 메모", i["sh1"])][3] == "동희" and comp[("공유 메모", i["sh1"])][5] == f"거른 메모 #{i['n1']}", "공유 메모")
    ok(comp[("공유 메모", i["sh1"])][4] == "제주도 여행을 좋아함\n[가까운 사이에게만: 요즘 근황]\n- 발표 준비로 바쁨",
       f"공유 메모는 가벼운 얘기와 근황을 같이: {comp[('공유 메모', i['sh1'])][4]!r}")

    # 친구·공유(지금 기준, 기간과 상관없음): 공유 켬·끔, 아는 사이, 다른 친구에게 하는 얘기
    pals = by["친구·공유"]
    ok(pals["headers"] == ["친구", "공유", "아는 사이", "아는 친구 누구에게나: 가벼운 얘기", "가까운 사이에게만: 요즘 근황",
                           "대화로 한 요청(최근 5개)", "공유 메모 만든 시각", "마지막으로 본 때"],
       f"친구·공유 머리줄: {pals['headers']}")
    pal = {r[0]: r for r in pals["rows"]}
    anon = "#" + hashlib.sha1(b"u-anon").hexdigest()[:8]
    ok(sorted(pal) == ["동희", "민수", "이름 모름(" + anon + ", 친구에 안 묶인 키)", "현경"],
       f"카카오 키가 묶인 친구, 그리고 요청을 남긴 안 묶인 키: {sorted(pal)}")
    ok(pal["동희"][1:7] == ["켬", "민수(같은 단체방)\n현경(여자친구 · 가까운 사이 · 말해 준 친구 동희)",
                          "제주도 여행을 좋아함", "- 발표 준비로 바쁨",
                          f"10/28 09:30 단체방: {anon} 키가 '동희'(이)라고 함 → 정할 일: 같은 사람이면 admin link {anon} 동희, "
                          f"다른 사람이면 admin unlink {anon}\n"
                          "10/28 09:20 1:1: 선톡 그만 보내 달라고 함 → 정할 일: admin schedule 동희 off\n"
                          "10/28 09:10 1:1: 민수(이)랑 '대학 친구' 사이라고 함 → 정할 일: admin friendship 동희 민수 "
                          "\"대학 친구\" [close]", "2026-10-27 11:05:00"]
       and STAMP.fullmatch(pal["동희"][7]), f"동희(요청은 최신 먼저, 할 명령까지): {pal['동희']}")
    ok(pal["현경"][1:7] == ["끔", "동희(여자친구 · 가까운 사이 · 말해 준 친구 동희)", "(공유 끔: 아무에게도 안 함)",
                          "(공유 끔: 아무에게도 안 함)", "10/28 09:00 방 모름: 공유 다시 켜 달라고 함 → 정할 일: "
                          "admin share 현경 on", None], f"공유를 끈 현경은 아무에게도 안 함: {pal['현경']}")
    ok(pal["민수"][1:7] == ["켬", "동희(같은 단체방)", "(아직 없음)", "(아직 없음)", "(없음)", None],
       f"기간 밖 단체방도 아는 사이, 공유 메모는 아직 없음: {pal['민수']}")
    ok(pal["이름 모름(" + anon + ", 친구에 안 묶인 키)"][5] == "10/28 09:40 1:1: 선톡 덜 보내 달라고 함(하루 3번) → "
       f"지금 하루 횟수 기본값, 정할 일: admin schedule {anon} <하루 횟수>", pal)
    ok(any(x.startswith("친구·공유: 기간과 상관없이 지금 기준 친구 3명") and "공유를 끈 친구" in x
           and "관리자만 정하고 친구 말로는 안 바뀌어요" in x for x in readme), "읽는 법에 친구·공유")
    return tabs


def check_xlsx(report, tabs, i, tmp):
    """엑셀: 탭 내용 그대로, 수식 막기·머리줄 고정. --hours·빈 기간·stdout."""
    out = tmp / "report.xlsx"
    code, _ = run(report, ["--until", UNTIL, "--out", str(out)])
    ok(code == 0 and out.exists(), "리포트 파일을 만듦")
    wb = load_workbook(out)
    ok(wb.sheetnames == SHEETS, f"시트: {wb.sheetnames}")
    ok(all(rows(wb[t["name"]]) == t["rows"] and [c.value for c in wb[t["name"]][1]] == t["headers"]
           for t in tabs[1:]), "엑셀 칸 = 탭 내용")
    ws = wb["대화"]
    g1 = ws.cell([r[0] for r in rows(ws)].index(i["g1"]) + 2, 6)
    ok(g1.value.startswith("=SUM") and g1.data_type == "s", f"'=' 로 시작해도 글: {g1.value!r}")
    with zipfile.ZipFile(out) as z:
        xml = [z.read(n) for n in z.namelist() if n.startswith("xl/worksheets/sheet")]
    ok(xml and not any(b"<f>" in x or b"<f " in x for x in xml), "수식으로 저장된 칸이 없음")
    ok(all(wb[n].freeze_panes == "A2" for n in SHEETS) and ws.auto_filter.ref, "머리줄 고정·거르기")
    paint = [({c.fill.fgColor.rgb[-6:] for c in r}, r[3].value) for r in ws.iter_rows(min_row=2)]
    ok(len(paint) == 10 and all(got == ({"E8F0FE"} if who == "마롱이" else {"FCE8E6"}) for got, who in paint)
       and ws["A1"].fill.fgColor.rgb.endswith("E8E3F3"), f"대화 줄 색(칸마다): {paint}")
    ok(all(c.fill.fill_type is None for n in SHEETS[2:] for r in wb[n].iter_rows(min_row=2) for c in r),
       "다른 탭은 줄 색 없음")

    out6 = tmp / "six.xlsx"
    ok(run(report, ["--hours", "6", "--until", UNTIL, "--out", str(out6)])[0] == 0, "6시간 리포트")
    ok([r[0] for r in rows(load_workbook(out6)["대화"])] == [i[k] for k in ("gl", "g2", "gr1", "g1")], "6시간 기간")
    empty = tmp / "empty.xlsx"
    ok(run(report, ["--until", "2026-10-01T00:00+09:00", "--out", str(empty)])[0] == 0, "빈 기간도 만듦")
    ok(all(load_workbook(empty)[n].max_row == 1 for n in SHEETS[1:-1])
       and load_workbook(empty)["친구·공유"].max_row == 5,
       "빈 기간은 머리줄만(친구·공유는 지금 기준이라 친구 3명과 요청을 남긴 안 묶인 키 1개)")

    # --out 이 없으면 stdout 으로(서버에서 ssh 로 받는 길). 요약 한 줄은 stderr
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "report.py"), "--until", UNTIL],
                       capture_output=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=120)
    err = p.stderr.decode("utf-8", "replace")
    ok(p.returncode == 0 and p.stdout[:2] == b"PK", f"stdout 이 엑셀: {err}")
    ok(load_workbook(io.BytesIO(p.stdout)).sheetnames == SHEETS, "stdout 엑셀 시트")
    ok("메시지 10개(마롱이 답 4·선톡 1)" in err and "임베딩 2개" in err and "기억 기록 있는 마롱이 말 3개" in err, err)
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            report.main(["--sheet", "--out", str(tmp / "x.xlsx")])
            exited = None
        except SystemExit as e:
            exited = e.code
    ok(exited == 2, "--out 과 --sheet 는 같이 못 씀")


def check_sheet(report, i):
    """--sheet: 가짜 웹 앱에 보내는 모양, 실패 처리, 주소를 어디에도 출력하지 않음."""
    os.environ["SHEET_URL"] = SHEET_URL
    transport, seen = web_app(lambda r: httpx.Response(200, json={"ok": True, "tabs": 5}))
    code, out = run(report, ["--sheet", "--until", UNTIL], transport)
    ok(code == 0 and out.startswith("시트 갱신 ") and "대화 13줄 · 임베딩 3줄 · 들어간 기억 9줄 · 요약·메모 6줄" in out,
       f"최근 30일(기본)을 보냄: {out}")
    ok(SECRET not in out, f"시트 주소는 출력하지 않음(INFO 로그 포함): {out}")
    ok([r.method for r in seen] == ["POST", "GET"] and str(seen[0].url) == SHEET_URL and str(seen[1].url) == ECHO_URL
       and not seen[1].content, "POST 뒤 302 를 GET 으로 따라감(내용은 다시 안 보냄)")
    ok(seen[0].headers["content-type"] == "application/json", "JSON 으로 보냄")
    payload = json.loads(seen[0].content)
    ok(set(payload) == {"updated", "tabs"} and STAMP.fullmatch(payload["updated"]), f"보내는 모양: {list(payload)}")
    tabs = {t["name"]: t for t in payload["tabs"]}
    ok(list(tabs) == SHEETS and all({"headers", "rows", "widths", "wrap"} <= set(t) for t in tabs.values()), "탭 모양")
    values = [v for t in tabs.values() for r in t["rows"] for v in r]
    ok(all(v is None or type(v) in (str, int, float) for v in values), "칸 값은 글·정수·실수·빈칸만")
    talk = {r[0]: r for r in tabs["대화"]["rows"]}
    ok(talk[i["o1"]][1] == "2026-10-20 20:00:00" and i["z1"] not in talk, "30일 안의 예전 대화는 넣고 끝 시각은 뺌")
    first, last = tabs["대화"]["rows"][0], tabs["대화"]["rows"][-1]
    ok(first[0] == i["gl"] and last[0] == i["o1"], f"최신이 위: {first[0]} … {last[0]}")
    colors = tabs["대화"]["colors"]
    ok(len(colors) == len(tabs["대화"]["rows"]) and colors[0] == "#e8f0fe" and colors[-1] == "#fce8e6"
       and all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in colors)
       and all("colors" not in t for n, t in tabs.items() if n != "대화"), "대화 탭만 줄마다 색을 보냄")
    ok("벡터 전체" not in tabs["임베딩"]["headers"] and all(len(r) == 8 for r in tabs["임베딩"]["rows"])
       and "0.1, 0.2, 0.3, 0.4" in [r[7] for r in tabs["임베딩"]["rows"]],
       "시트에는 벡터 전체를 안 보냄(무거워서). 앞 8개 값은 보냄")
    ok(tabs["읽는 법"]["rows"][1][0] == f"마지막 갱신: {payload['updated']}", "읽는 법에 갱신 시각")
    ok(any("'마롱이 > 지금 새로고침'" in r[0] for r in tabs["읽는 법"]["rows"]), "시트 읽는 법에 '지금 새로고침' 안내")
    ok(any("필터는 새로 채운 뒤에도 그대로" in r[0] and "지워져요" in r[0] for r in tabs["읽는 법"]["rows"]),
       "시트 읽는 법에 필터는 남고 손으로 칠한 색은 지워진다는 안내")

    os.environ["SHEET_DAYS"] = "1"
    transport, seen = web_app(lambda r: httpx.Response(200, json={"ok": True}))
    code, out = run(report, ["--sheet", "--until", UNTIL], transport)
    ok(code == 0 and "대화 10줄" in out, f"SHEET_DAYS: {out}")
    del os.environ["SHEET_DAYS"]

    # 실패: 종료 코드 1, 까닭은 짧게, 주소와 구글의 답 내용은 안 적음
    def down(request):
        raise httpx.ConnectError(f"연결 실패 {request.url}", request=request)
    cases = [
        ("스크립트 실패", web_app(lambda r: httpx.Response(200, json={"ok": False, "error": "비밀 " + SECRET}))[0],
         "시트 스크립트가 실패함"),
        ("JSON 아닌 답", web_app(lambda r: httpx.Response(200, text=f"<html>로그인 {SECRET}</html>"))[0], "답이 JSON 이 아님"),
        ("HTTP 오류", web_app(lambda r: httpx.Response(500, text=f"오류 {SECRET}"))[0], "HTTP 500"),
        ("연결 실패", httpx.MockTransport(down), "ConnectError"),
    ]
    for what, transport, why in cases:
        code, out = run(report, ["--sheet", "--until", UNTIL], transport)
        ok(code == 1 and f"시트 갱신 실패: {why}" in out and SECRET not in out and "비밀" not in out, f"{what}: {out}")

    for url in (None, "https://evil.example.com/macros/s/X/exec"):
        if url:
            os.environ["SHEET_URL"] = url
        else:
            del os.environ["SHEET_URL"]
        transport, seen = web_app(lambda r: httpx.Response(200, json={"ok": True}))
        code, out = run(report, ["--sheet"], transport)
        ok(code == 1 and not seen and "SHEET_URL" in out and "evil" not in out, f"주소가 없거나 구글이 아니면 안 보냄: {out}")
    os.environ.pop("SHEET_URL", None)


def sheet_app(poll, upload=lambda: httpx.Response(200, json={"ok": True, "tabs": 5})):
    """가짜 sheet.gs 웹 앱: 물어보기({"poll": true})에는 poll(), 탭을 받으면 upload() 로 답함(둘 다 302 를 따라온 GET 에).
    받은 POST 내용을 차례로 남김."""
    posts = []

    def handle(request):
        if request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(302, headers={"Location": ECHO_URL})
        return poll() if posts[-1].get("poll") else upload()
    return httpx.MockTransport(handle), posts


def check_ask(report):
    """--sheet --if-asked: 시트에서 '지금 새로고침'을 눌렀을 때만 보내고, 할 일이 없거나 못 물으면 아무것도 안 남김."""
    os.environ["SHEET_URL"] = SHEET_URL
    argv = ["--sheet", "--if-asked", "--until", UNTIL]
    transport, posts = sheet_app(lambda: httpx.Response(200, json={"ok": True, "asked": 0}))
    code, out = run(report, argv, transport)
    ok(code == 0 and out == "" and posts == [{"poll": True}], f"안 눌렀으면 묻기만 하고 조용히 끝: {posts} {out!r}")

    transport, posts = sheet_app(lambda: httpx.Response(200, json={"ok": True, "asked": 1793023200000}))
    code, out = run(report, argv, transport)
    ok(code == 0 and len(posts) == 2 and posts[0] == {"poll": True} and set(posts[1]) == {"updated", "tabs"},
       f"눌렀으면 물은 뒤 탭을 통째로 보냄: {[list(x) for x in posts]}")
    ok(out.startswith("시트 갱신(시트에서 누름) ") and "대화 13줄 · 임베딩 3줄" in out and SECRET not in out,
       f"보낸 결과만 남김: {out}")

    def down():
        raise httpx.ConnectError("연결 실패 " + SHEET_URL)
    quiet = [
        ("물어보기를 모르는 예전 sheet.gs", lambda: httpx.Response(200, json={"ok": False, "error": "tabs 없음"})),
        ("JSON 아닌 답", lambda: httpx.Response(200, text=f"<html>로그인 {SECRET}</html>")),
        ("HTTP 오류", lambda: httpx.Response(500, json={"ok": True, "asked": 1})),
        ("연결 실패", down),
        ("이상한 답", lambda: httpx.Response(200, json={"ok": True, "asked": "1793023200000"})),
    ]
    for what, poll in quiet:
        transport, posts = sheet_app(poll)
        code, out = run(report, argv, transport)
        ok(code == 0 and out == "" and posts == [{"poll": True}], f"{what}: 보내지 않고 조용히 끝 {out!r}")

    transport, posts = sheet_app(lambda: httpx.Response(200, json={"ok": True, "asked": 1793023200000}),
                                 lambda: httpx.Response(200, json={"ok": False, "error": "비밀 " + SECRET}))
    code, out = run(report, argv, transport)
    ok(code == 1 and "시트 갱신(시트에서 누름) 실패: 시트 스크립트가 실패함" in out and SECRET not in out
       and len(posts) == 2, f"눌렀는데 못 보내면 실패로 남김(다시 묻지는 않음): {out}")

    del os.environ["SHEET_URL"]
    transport, posts = sheet_app(lambda: httpx.Response(200, json={"ok": True, "asked": 1}))
    code, out = run(report, argv, transport)
    ok(code == 0 and out == "" and not posts, f"주소가 없으면 묻지 않고 조용히 끝(30분 갱신이 알림): {out!r}")
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            report.main(["--if-asked"])
            exited = None
        except SystemExit as e:
            exited = e.code
    ok(exited == 2, "--if-asked 는 --sheet 와 같이만")


def check_moved(report, db):
    """요청한 뒤 관리자가 키를 다른 친구로 옮기거나 떼어 낸 경우, 정해진 것과 다른 관계를 말한 경우(2026-10-30 리뷰)."""
    one = lambda sql, params: db.admin(sql + " RETURNING id", params)[0][0]  # noqa: E731
    f_dong, f_hk = (db.admin("SELECT id FROM marong.friends WHERE name = %s", (n,))[0][0] for n in ("동희", "현경"))

    def ask(user, friend, room, kind, detail, at):
        db.admin("INSERT INTO marong.requests (user_key, friend_id, room_key, kind, detail, created_at) "
                 "VALUES (%s, %s, %s, %s, %s, %s)", (user, friend, room, kind, Jsonb(detail), kst(at)))

    # 현경의 다른 키가 '현경이'라는 새 친구로 잡혀 요청을 남긴 뒤, 관리자가 그 키를 현경에 묶음 → '현경이'는 키가 없어 빠짐
    f_hk2 = one("INSERT INTO marong.friends (name) VALUES (%s)", ("현경이",))
    db.admin("INSERT INTO marong.people (user_key, name, friend_id) VALUES ('u-hk2', '현경이', %s)", (f_hk2,))
    ask("u-hk2", f_hk2, None, "share_off", {}, "2026-10-29T10:00")
    ask("u-hk2", f_hk2, None, "friendship", {"name": "동희", "label": "남자친구", "with": f_dong}, "2026-10-29T10:10")
    ask("u-dong", f_dong, "room-dm", "friendship", {"name": "현경", "label": "여자친구", "with": f_hk}, "2026-10-29T10:20")
    db.admin("UPDATE marong.people SET friend_id = %s WHERE user_key = 'u-hk2'", (f_hk,))
    # 요청한 키를 관리자가 떼어 내 지금은 어느 친구에도 안 묶임(그 친구도 키가 없어 빠짐)
    f_gone = one("INSERT INTO marong.friends (name) VALUES (%s)", ("지민",))
    db.admin("INSERT INTO marong.people (user_key, name, friend_id) VALUES ('u-gone', '지민', %s)", (f_gone,))
    ask("u-gone", f_gone, None, "share_off", {}, "2026-10-29T10:30")
    db.admin("UPDATE marong.people SET friend_id = NULL WHERE user_key = 'u-gone'")

    with psycopg.connect(db.app_url, row_factory=dict_row) as c:
        c.read_only = True
        tabs, _ = report.build(c, kst("2026-10-26T19:00"), kst("2026-10-27T19:00"), TZ, now=kst("2026-10-29T11:00"))
    pal = {r[0]: r for r in next(t for t in tabs if t["name"] == "친구·공유")["rows"]}
    gone = f"지민({short('u-gone')}, 친구에 안 묶인 키)"
    ok("현경이" not in pal and gone in pal, f"키가 없는 친구는 빠지고, 떼어 낸 키는 따로 한 줄: {sorted(pal)}")
    ok(pal["현경"][5] == "10/29 10:10 방 모름: 동희(이)랑 '남자친구' 사이라고 함 → 지금은 '여자친구 · 가까운 사이'(으)로 "
       "정해져 있음, 바꾸려면: admin friendship 현경 동희 남자친구 [close]\n"
       "10/29 10:00 방 모름: 공유 꺼 달라고 함 → 지금 꺼져 있음\n"
       "10/28 09:00 방 모름: 공유 다시 켜 달라고 함 → 정할 일: admin share 현경 on",
       f"옮긴 키의 요청은 키가 지금 묶인 친구에게, 다른 관계를 말하면 바꿀 명령까지: {pal['현경'][5]}")
    ok(pal["동희"][5].startswith("10/29 10:20 1:1: 현경(이)랑 '여자친구' 사이라고 함 → 지금 '여자친구 · 가까운 사이'(으)로 "
                                "정해져 있음\n"), f"정해진 관계와 같으면 명령 없이: {pal['동희'][5]}")
    ok(pal[gone][5] == "10/29 10:30 방 모름: 공유 꺼 달라고 함 → 이 키는 지금 어느 친구에도 안 묶여 있음, "
       f"정할 일: 먼저 admin link {short('u-gone')} <친구>", f"떼어 낸 키의 요청: {pal[gone]}")


def main():
    db = TestDB()
    os.environ.update({"DATABASE_URL": db.app_url, "TIMEZONE": "Asia/Seoul"})  # 봇과 같은 marong 계정(읽기)
    for name in ("RECALL_MIN_SIMILARITY", "RECENT_TURNS", "SHEET_URL", "SHEET_DAYS"):
        os.environ.pop(name, None)
    report = load_report()
    i = seed(db)
    tabs = check_tabs(report, db, i)
    with tempfile.TemporaryDirectory(prefix="marong-report-", ignore_cleanup_errors=True) as tmp:
        check_xlsx(report, tabs, i, Path(tmp))
    check_sheet(report, i)
    check_ask(report)
    check_moved(report, db)
    db.close()
    print(f"report: all {CHECKS} checks passed")


if __name__ == "__main__":
    main()
