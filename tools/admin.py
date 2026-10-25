"""마롱이 기록 보기(읽기만). 노트북에서: bash deploy/ovh.sh admin <명령>
  people                       친구 목록(이름·메시지 수·처음/마지막으로 본 때)
  rooms                        방 목록(1:1·단체, 친구들, 메시지 수, 마지막 대화, 선톡 끔)
  show <이름 또는 #키> [개수]   그 친구가 있는 방들의 최근 대화(기본 30개)와 기억 메모
  stats                        전체 개수와 최근 7일 토큰 사용량(대략의 비용)
기록을 지우거나 고치는 명령은 없다(봇 계정에는 그 권한도 없다). 카카오 키 원문 대신 #짧은키 로 보여 준다."""
import hashlib
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from marong.config import load_dotenv  # noqa: E402

# Haiku 5.5 가격(1M 토큰당 달러, 프롬프트 10만 토큰 이하). 캐시 읽기는 입력의 0.1배, 캐시 쓰기(5분)는 1.25배
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ, PRICE_CACHE_WRITE = 0.10, 0.50, 0.01, 0.125


def key(k: str | None) -> str:
    return "#" + hashlib.sha1((k or "").encode()).hexdigest()[:8]


def when(dt, tz) -> str:
    return dt.astimezone(tz).strftime("%m/%d %H:%M") if dt else "-"


def people(c, tz, _args):
    rows = c.execute(
        "SELECT p.user_key, p.name, p.first_seen, p.last_seen, count(m.id) AS n FROM marong.people p "
        "LEFT JOIN marong.messages m ON m.user_key = p.user_key GROUP BY p.user_key ORDER BY p.last_seen DESC").fetchall()
    for r in rows:
        print(f"{key(r['user_key'])}  {r['name'] or '(이름 모름)':<12} 메시지 {r['n']:>5}  "
              f"처음 {when(r['first_seen'], tz)}  마지막 {when(r['last_seen'], tz)}")
    print(f"친구 {len(rows)}명")


def rooms(c, tz, _args):
    rows = c.execute(
        "SELECT r.room_key, r.is_channel, r.proactive, count(m.id) AS n, max(m.created_at) AS last, "
        "  string_agg(DISTINCT coalesce(p.name, '?'), ', ') FILTER (WHERE m.user_key IS NOT NULL) AS who "
        "FROM marong.rooms r "
        "LEFT JOIN marong.messages m ON m.room_key = r.room_key "
        "LEFT JOIN marong.people p ON p.user_key = m.user_key "
        "GROUP BY r.room_key ORDER BY last DESC NULLS LAST").fetchall()
    for r in rows:
        kind = "1:1 " if r["is_channel"] else "단체"
        off = "  (선톡 끔)" if r["is_channel"] and not r["proactive"] else ""
        print(f"{key(r['room_key'])}  {kind}  메시지 {r['n']:>5}  마지막 {when(r['last'], tz)}  {r['who'] or ''}{off}")


def show(c, tz, args):
    if not args:
        sys.exit("사용: show <이름 또는 #키> [개수]")
    who, limit = args[0], int(args[1]) if len(args) > 1 else 30
    users = [r for r in c.execute("SELECT user_key, name FROM marong.people").fetchall()
             if key(r["user_key"]) == who or (r["name"] or "") == who]
    if not users:
        sys.exit(f"'{who}' 친구를 찾지 못함(people 로 목록 보기)")
    for u in users:
        room_keys = [r["room_key"] for r in c.execute(
            "SELECT DISTINCT room_key FROM marong.messages WHERE user_key = %s", (u["user_key"],)).fetchall()]
        for room in room_keys:
            print(f"── {u['name'] or '(이름 모름)'} {key(u['user_key'])} / 방 {key(room)} ──")
            for n in c.execute("SELECT DISTINCT ON (user_key) user_key, content FROM marong.notes "
                               "WHERE room_key = %s ORDER BY user_key, id DESC", (room,)).fetchall():
                print(f"[기억 메모 {key(n['user_key'])}]\n{n['content']}")
            rows = c.execute(
                "SELECT m.role, m.content, m.created_at, p.name, m.user_key, m.meta FROM marong.messages m "
                "LEFT JOIN marong.people p ON p.user_key = m.user_key WHERE m.room_key = %s "
                "ORDER BY m.id DESC LIMIT %s", (room, limit)).fetchall()
            for r in reversed(rows):
                speaker = "마롱이" if r["role"] == "assistant" else (r["name"] or key(r["user_key"]))
                tag = " (선톡)" if r["meta"].get("proactive") else ""
                lost = " (전달 안 됨)" if r["meta"].get("delivered") is False else ""
                print(f"{when(r['created_at'], tz)} {speaker}: {r['content']}{tag}{lost}")


def stats(c, tz, _args):
    n = c.execute(
        "SELECT (SELECT count(*) FROM marong.rooms) AS rooms, (SELECT count(*) FROM marong.people) AS people, "
        "(SELECT count(*) FROM marong.messages) AS messages, (SELECT count(*) FROM marong.summaries) AS summaries, "
        "(SELECT count(*) FROM marong.notes) AS notes, (SELECT count(*) FROM marong.embeddings) AS embeddings").fetchone()
    print("  ".join(f"{k} {v}" for k, v in n.items()))
    t = c.execute(
        "SELECT count(*) AS replies, coalesce(sum((meta->>'input_tokens')::bigint), 0)::bigint AS i, "
        "coalesce(sum((meta->>'output_tokens')::bigint), 0)::bigint AS o, "
        "coalesce(sum((meta->>'cache_read_tokens')::bigint), 0)::bigint AS cr, "
        "coalesce(sum((meta->>'cache_write_tokens')::bigint), 0)::bigint AS cw "
        "FROM marong.messages WHERE role = 'assistant' AND created_at > now() - interval '7 days'").fetchone()
    s = c.execute(
        "SELECT count(*) AS n, coalesce(sum((meta->>'input_tokens')::bigint), 0)::bigint AS i, "
        "coalesce(sum((meta->>'output_tokens')::bigint), 0)::bigint AS o "
        "FROM marong.summaries WHERE created_at > now() - interval '7 days'").fetchone()
    usd = ((t["i"] + s["i"]) * PRICE_IN + (t["o"] + s["o"]) * PRICE_OUT
           + t["cr"] * PRICE_CACHE_READ + t["cw"] * PRICE_CACHE_WRITE) / 1e6
    print(f"최근 7일: 답장 {t['replies']}개(입력 {t['i']:,} · 캐시 읽기 {t['cr']:,} · 캐시 쓰기 {t['cw']:,} · "
          f"출력 {t['o']:,} 토큰), "
          f"요약 {s['n']}개(입력 {s['i']:,} · 출력 {s['o']:,} 토큰) → 대략 ${usd:.2f}")


COMMANDS = {"people": people, "rooms": rooms, "show": show, "stats": stats}


def main() -> None:
    args = [a for a in sys.argv[1:] if a]
    if not args or args[0] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    load_dotenv(str(ROOT / ".env"))
    tz = ZoneInfo(os.getenv("TIMEZONE") or "Asia/Seoul")
    with psycopg.connect(os.getenv("DATABASE_URL") or "postgresql:///marong", row_factory=dict_row) as c:
        c.read_only = True
        COMMANDS[args[0]](c, tz, args[1:])


if __name__ == "__main__":
    main()
