"""마롱이 기록 보기. 노트북에서: bash deploy/ovh.sh admin <명령>
  friends                      친구 목록(카카오 키들, 아는 사이, 다른 친구에게 하는 가벼운 얘기=공유 메모)
  people                       카카오 키 목록(이름·친구·메시지 수·처음/마지막으로 본 때)
  rooms                        방 목록(1:1·단체, 친구들, 메시지 수, 마지막 대화, 선톡 끔)
  show <이름 또는 #키> [개수]   그 친구가 있는 방들의 최근 대화(기본 30개)와 기억 메모
  stats                        전체 개수와 최근 7일 토큰 사용량(대략의 비용)
  link <#키> <친구 이름 또는 #키>  그 키를 그 친구로 묶음(이름이 달라 따로 잡힌 같은 사람)
  unlink <#키>                 그 키를 친구에서 떼어 따로 둠(이름이 같아 잘못 묶인 다른 사람)
  share <친구 이름 또는 #키> on|off  그 친구 얘기를 다른 친구에게 해도 되는지
  schedule <친구 이름 또는 #키> <하루 횟수> [시작-끝 시]  그 친구 1:1 방의 선톡 일정(예: schedule 현경 12 7-24.
                               시간을 빼면 횟수만 바꿈). schedule <친구> default 면 .env 기본값으로 되돌림
기록을 지우는 명령은 없다(봇 계정에는 그 권한도 없다). link·unlink·share·schedule 은 키가 어느 친구인지, 공유, 선톡 일정만 바꾼다.
카카오 키 원문 대신 #짧은키 로 보여 준다(# 은 빼고 써도 된다)."""
import hashlib
import os
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from marong.config import PER_DAY_MAX, load_dotenv  # noqa: E402

# Haiku 5.5 가격(1M 토큰당 달러, 프롬프트 10만 토큰 이하). 캐시 읽기는 입력의 0.1배, 캐시 쓰기(5분)는 1.25배
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ, PRICE_CACHE_WRITE = 0.10, 0.50, 0.01, 0.125


def key(k: str | None) -> str:
    return "#" + hashlib.sha1((k or "").encode()).hexdigest()[:8]


def when(dt, tz) -> str:
    return dt.astimezone(tz).strftime("%m/%d %H:%M") if dt else "-"


def is_key(who: str) -> bool:
    return re.fullmatch(r"#?[0-9a-f]{8}", who) is not None


def find_key(c, who: str) -> dict:
    """#키 → 카카오 키 줄(user_key, name, friend_id). 없으면 끝냄."""
    k = who if who.startswith("#") else "#" + who
    rows = [r for r in c.execute("SELECT user_key, name, friend_id FROM marong.people").fetchall()
            if key(r["user_key"]) == k]
    if len(rows) != 1:
        sys.exit(f"'{who}' 키를 찾지 못함(friends·people 로 보기)")
    return rows[0]


def find_friend(c, who: str) -> int:
    """친구 이름 또는 #키 → 친구 id. 못 찾거나 같은 이름이 여럿이면 끝냄."""
    if is_key(who):
        friend_id = find_key(c, who)["friend_id"]
        if friend_id is None:
            sys.exit(f"{who} 키는 아직 어느 친구에도 안 묶였음(이름을 모름)")
        return friend_id
    found = c.execute("SELECT f.id FROM marong.friends f WHERE f.name = %s "
                      "AND EXISTS (SELECT 1 FROM marong.people p WHERE p.friend_id = f.id)", (who,)).fetchall()
    if len(found) != 1:
        sys.exit(f"'{who}' 친구가 " + ("없음" if not found else "여럿이라 #키로 지정해 주세요") + "(friends 로 보기)")
    return found[0]["id"]


def friends(c, tz, _args):
    rows = c.execute(
        "SELECT f.id, f.name, f.share, max(p.last_seen) AS last FROM marong.friends f "
        "JOIN marong.people p ON p.friend_id = f.id GROUP BY f.id ORDER BY last DESC").fetchall()
    for f in rows:
        keys = c.execute(
            "SELECT p.user_key, p.name, bool_or(r.is_channel) AS one, bool_or(NOT r.is_channel) AS grp "
            "FROM marong.people p LEFT JOIN marong.messages m ON m.user_key = p.user_key "
            "LEFT JOIN marong.rooms r ON r.room_key = m.room_key WHERE p.friend_id = %s "
            "GROUP BY p.user_key ORDER BY p.first_seen", (f["id"],)).fetchall()
        told = c.execute(
            "SELECT o.name, fs.label FROM marong.friendships fs JOIN marong.friends o "
            "  ON o.id = CASE WHEN fs.friend_a = %(f)s THEN fs.friend_b ELSE fs.friend_a END "
            "WHERE %(f)s IN (fs.friend_a, fs.friend_b) "
            "  AND EXISTS (SELECT 1 FROM marong.people p WHERE p.friend_id = o.id) ORDER BY o.name",
            {"f": f["id"]}).fetchall()
        mates = c.execute(
            "SELECT DISTINCT o.name FROM marong.messages m JOIN marong.rooms r ON r.room_key = m.room_key "
            "JOIN marong.people op ON op.user_key = m.user_key JOIN marong.friends o ON o.id = op.friend_id "
            "WHERE NOT r.is_channel AND o.id <> %(f)s AND m.room_key IN (SELECT m2.room_key FROM marong.messages m2 "
            "  JOIN marong.people p2 ON p2.user_key = m2.user_key WHERE p2.friend_id = %(f)s) ORDER BY o.name",
            {"f": f["id"]}).fetchall()
        shared = c.execute("SELECT content, created_at FROM marong.shared_notes WHERE friend_id = %s "
                           "ORDER BY id DESC LIMIT 1", (f["id"],)).fetchone()
        known: dict[str, list[str]] = {}
        for r in told:
            known.setdefault(r["name"], []).append(r["label"] or "말해 준 사이")
        for r in mates:
            known.setdefault(r["name"], []).append("같은 단체방")
        print(f"{f['name']}  공유 {'켬' if f['share'] else '끔'}  마지막 {when(f['last'], tz)}")
        print("  카카오 키: " + ", ".join(
            f"{key(k['user_key'])} {'1:1' if k['one'] else '단체' if k['grp'] else '대화 없음'}"
            + (f"(이름 {k['name'] or '모름'})" if k["name"] != f["name"] else "") for k in keys))
        print("  아는 사이: " + (", ".join(f"{n}({', '.join(v)})" for n, v in known.items()) or "없음"))
        if not f["share"]:
            print("  공유 메모: 공유를 꺼서 다른 친구에게 이 친구 얘기를 안 함")
        elif shared is None:
            print("  공유 메모: 아직 없음")
        else:
            print(f"  공유 메모({when(shared['created_at'], tz)}):" + ("" if shared["content"] else " 넣을 만한 게 없음"))
            for line in shared["content"].splitlines():
                print(f"    {line}")
    alone = c.execute("SELECT count(*) AS n FROM marong.people WHERE friend_id IS NULL").fetchone()["n"]
    print(f"친구 {len(rows)}명" + (f" · 친구에 안 묶인 키 {alone}개(이름을 아직 모르거나 터미널 대화, people 로 보기)"
                                  if alone else ""))


def people(c, tz, _args):
    rows = c.execute(
        "SELECT p.user_key, p.name, p.first_seen, p.last_seen, f.name AS friend, count(m.id) AS n "
        "FROM marong.people p LEFT JOIN marong.friends f ON f.id = p.friend_id "
        "LEFT JOIN marong.messages m ON m.user_key = p.user_key GROUP BY p.user_key, f.name "
        "ORDER BY p.last_seen DESC").fetchall()
    for r in rows:
        print(f"{key(r['user_key'])}  {r['name'] or '(이름 모름)':<12} 친구 {r['friend'] or '-':<10} 메시지 {r['n']:>5}  "
              f"처음 {when(r['first_seen'], tz)}  마지막 {when(r['last_seen'], tz)}")
    print(f"카카오 키 {len(rows)}개")


def rooms(c, tz, _args):
    rows = c.execute(
        "SELECT r.room_key, r.is_channel, r.proactive, r.proactive_per_day, r.proactive_start, r.proactive_end, "
        "  count(m.id) AS n, max(m.created_at) AS last, "
        "  string_agg(DISTINCT coalesce(p.name, '?'), ', ') FILTER (WHERE m.user_key IS NOT NULL) AS who "
        "FROM marong.rooms r "
        "LEFT JOIN marong.messages m ON m.room_key = r.room_key "
        "LEFT JOIN marong.people p ON p.user_key = m.user_key "
        "GROUP BY r.room_key ORDER BY last DESC NULLS LAST").fetchall()
    for r in rows:
        kind = "1:1 " if r["is_channel"] else "단체"
        off = "  (선톡 끔)" if r["is_channel"] and not r["proactive"] else ""
        plan = f"  (선톡 일정 {plan_text(r)})" if r["is_channel"] and has_plan(r) else ""
        print(f"{key(r['room_key'])}  {kind}  메시지 {r['n']:>5}  마지막 {when(r['last'], tz)}  {r['who'] or ''}{off}{plan}")


def has_plan(r) -> bool:
    return any(r[k] is not None for k in ("proactive_per_day", "proactive_start", "proactive_end"))


def plan_text(r) -> str:
    """방에 정한 선톡 일정. 비어 있는 값은 .env 기본값을 씀."""
    per_day = f"하루 {r['proactive_per_day']}번" if r["proactive_per_day"] is not None else "하루 횟수 기본값"
    if r["proactive_start"] is None and r["proactive_end"] is None:
        return f"{per_day}, 시간 기본값"
    start = "기본" if r["proactive_start"] is None else r["proactive_start"]
    end = "기본" if r["proactive_end"] is None else r["proactive_end"]
    return f"{per_day}, {start}~{end}시"


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
        "(SELECT count(*) FROM marong.friends f WHERE EXISTS (SELECT 1 FROM marong.people p "
        "  WHERE p.friend_id = f.id)) AS friends, (SELECT count(*) FROM marong.friendships) AS friendships, "
        "(SELECT count(*) FROM marong.messages) AS messages, (SELECT count(*) FROM marong.summaries) AS summaries, "
        "(SELECT count(*) FROM marong.notes) AS notes, (SELECT count(*) FROM marong.shared_notes) AS shared_notes, "
        "(SELECT count(*) FROM marong.embeddings) AS embeddings").fetchone()
    print("  ".join(f"{k} {v}" for k, v in n.items()))
    t = c.execute(
        "SELECT count(*) AS replies, coalesce(sum((meta->>'input_tokens')::bigint), 0)::bigint AS i, "
        "coalesce(sum((meta->>'output_tokens')::bigint), 0)::bigint AS o, "
        "coalesce(sum((meta->>'cache_read_tokens')::bigint), 0)::bigint AS cr, "
        "coalesce(sum((meta->>'cache_write_tokens')::bigint), 0)::bigint AS cw "
        "FROM marong.messages WHERE role = 'assistant' AND created_at > now() - interval '7 days'").fetchone()
    s = c.execute(
        "SELECT count(*) AS n, coalesce(sum((meta->>'input_tokens')::bigint), 0)::bigint AS i, "
        "coalesce(sum((meta->>'output_tokens')::bigint), 0)::bigint AS o FROM ("
        "  SELECT meta FROM marong.summaries WHERE created_at > now() - interval '7 days' UNION ALL "
        "  SELECT meta FROM marong.shared_notes WHERE created_at > now() - interval '7 days') x").fetchone()
    usd = ((t["i"] + s["i"]) * PRICE_IN + (t["o"] + s["o"]) * PRICE_OUT
           + t["cr"] * PRICE_CACHE_READ + t["cw"] * PRICE_CACHE_WRITE) / 1e6
    print(f"최근 7일: 답장 {t['replies']}개(입력 {t['i']:,} · 캐시 읽기 {t['cr']:,} · 캐시 쓰기 {t['cw']:,} · "
          f"출력 {t['o']:,} 토큰), "
          f"요약·공유 메모 {s['n']}개(입력 {s['i']:,} · 출력 {s['o']:,} 토큰) → 대략 ${usd:.2f}")


def link(c, _tz, args):
    if len(args) != 2 or not is_key(args[0]):
        sys.exit("사용: link <#키> <친구 이름 또는 #키>")
    src = find_key(c, args[0])
    dst = find_friend(c, args[1])
    old = src["friend_id"]
    if old == dst:
        print("이미 그 친구에 묶여 있음")
        return
    c.execute("UPDATE marong.people SET friend_id = %s WHERE user_key = %s", (dst, src["user_key"]))
    if old is not None:
        # 옛 친구에서 공유를 껐으면 묶은 친구도 끈다(더 조심스러운 쪽)
        c.execute("UPDATE marong.friends SET share = share AND (SELECT share FROM marong.friends WHERE id = %s) "
                  "WHERE id = %s", (old, dst))
        if not c.execute("SELECT 1 FROM marong.people WHERE friend_id = %s LIMIT 1", (old,)).fetchone():
            # 옛 친구에 남은 키가 없으면 그 친구에 저장된 '아는 사이'를 묶은 친구로 옮긴다(옛 줄은 남지만 안 쓰임)
            c.execute(
                "INSERT INTO marong.friendships (friend_a, friend_b, label, told_by) "
                "SELECT least(%(d)s, x.other), greatest(%(d)s, x.other), x.label, "
                "  CASE WHEN x.told_by = %(o)s THEN %(d)s ELSE x.told_by END FROM ("
                "  SELECT CASE WHEN friend_a = %(o)s THEN friend_b ELSE friend_a END AS other, label, told_by "
                "  FROM marong.friendships WHERE %(o)s IN (friend_a, friend_b)) x WHERE x.other <> %(d)s "
                "ON CONFLICT (friend_a, friend_b) DO NOTHING", {"o": old, "d": dst})
    name = c.execute("SELECT name, share FROM marong.friends WHERE id = %s", (dst,)).fetchone()
    print(f"{key(src['user_key'])} 키를 '{name['name']}' 친구로 묶음(공유 {'켬' if name['share'] else '끔'}). "
          "공유 메모는 몇 분 안에 다시 걸러져요.")


def unlink(c, _tz, args):
    if len(args) != 1 or not is_key(args[0]):
        sys.exit("사용: unlink <#키>")
    src = find_key(c, args[0])
    old = src["friend_id"]
    if old is None:
        print("이미 어느 친구에도 안 묶여 있음")
        return
    if c.execute("SELECT count(*) AS n FROM marong.people WHERE friend_id = %s", (old,)).fetchone()["n"] == 1:
        print("이 키만 있는 친구라서 이미 따로임")
        return
    if src["name"] is None:  # 이름을 모르는 키는 친구 없이 둔다(이름을 알려 주면 그때 다시 묶임)
        c.execute("UPDATE marong.people SET friend_id = NULL WHERE user_key = %s", (src["user_key"],))
        print(f"{key(src['user_key'])} 키를 떼어 냄(이름을 모르는 키라 친구 없이 둠)")
        return
    # 새 친구로 따로 둔다(공유 설정은 그대로). 같은 이름 친구가 둘이 되어서 다음 새 키는 자동으로 묶이지 않는다.
    new = c.execute("INSERT INTO marong.friends (name, share) SELECT %s, share FROM marong.friends WHERE id = %s "
                    "RETURNING id", (src["name"], old)).fetchone()["id"]
    c.execute("UPDATE marong.people SET friend_id = %s WHERE user_key = %s", (new, src["user_key"]))
    print(f"{key(src['user_key'])} 키를 떼어 '{src['name']}' 친구로 따로 둠")


def share(c, _tz, args):
    if len(args) != 2 or args[1] not in ("on", "off"):
        sys.exit("사용: share <친구 이름 또는 #키> on|off")
    friend_id = find_friend(c, args[0])
    c.execute("UPDATE marong.friends SET share = %s WHERE id = %s", (args[1] == "on", friend_id))
    print(f"공유 {'켬' if args[1] == 'on' else '끔'}: " + ("이 친구의 가벼운 얘기를 아는 친구에게 할 수 있음"
                                                       if args[1] == "on" else "다른 친구에게 이 친구 얘기를 안 함"))


def schedule(c, _tz, args):
    usage = f"사용: schedule <친구 이름 또는 #키> <하루 횟수 1~{PER_DAY_MAX}> [시작-끝 시, 예: 7-24] | schedule <친구> default"
    if len(args) not in (2, 3):
        sys.exit(usage)
    who = args[0]
    users = [r["user_key"] for r in c.execute(
        "SELECT p.user_key, p.name, f.name AS friend FROM marong.people p "
        "LEFT JOIN marong.friends f ON f.id = p.friend_id").fetchall()
        if key(r["user_key"]) == (who if who.startswith("#") else "#" + who) or who in (r["name"], r["friend"])]
    rooms_ = [r["room_key"] for r in c.execute(
        "SELECT DISTINCT m.room_key FROM marong.messages m JOIN marong.rooms r ON r.room_key = m.room_key "
        "WHERE r.is_channel AND m.user_key = ANY(%s)", (users,)).fetchall()] if users else []
    if not rooms_:
        sys.exit(f"'{who}' 친구의 1:1 방을 찾지 못함(rooms·people 로 보기)")
    if args[1] == "default" and len(args) == 2:
        sets, values = "proactive_per_day = NULL, proactive_start = NULL, proactive_end = NULL", ()
    else:
        try:
            per_day = int(args[1])
        except ValueError:
            sys.exit(usage)
        if not 1 <= per_day <= PER_DAY_MAX:
            sys.exit(usage)
        sets, values = "proactive_per_day = %s", (per_day,)
        if len(args) == 3:
            m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", args[2])
            if not m or not 0 <= int(m[1]) < int(m[2]) <= 24:
                sys.exit("시작-끝 시는 0~24, 시작이 끝보다 앞이어야 해요(예: 7-24)")
            sets, values = sets + ", proactive_start = %s, proactive_end = %s", (per_day, int(m[1]), int(m[2]))
    for room in rooms_:
        r = c.execute(f"UPDATE marong.rooms SET {sets} WHERE room_key = %s "
                      "RETURNING proactive, proactive_per_day, proactive_start, proactive_end", (*values, room)).fetchone()
        off = " (친구가 선톡을 꺼 둬서 지금은 안 보냄)" if not r["proactive"] else ""
        print(f"방 {key(room)}: 선톡 일정 " + (plan_text(r) if has_plan(r) else ".env 기본값") + off)


COMMANDS = {"friends": friends, "people": people, "rooms": rooms, "show": show, "stats": stats,
            "link": link, "unlink": unlink, "share": share, "schedule": schedule}
WRITES = {"link", "unlink", "share", "schedule"}


def main() -> None:
    args = [a for a in sys.argv[1:] if a]
    if not args or args[0] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    load_dotenv(str(ROOT / ".env"))
    tz = ZoneInfo(os.getenv("TIMEZONE") or "Asia/Seoul")
    with psycopg.connect(os.getenv("DATABASE_URL") or "postgresql:///marong", row_factory=dict_row) as c:
        c.read_only = args[0] not in WRITES
        COMMANDS[args[0]](c, tz, args[1:])


if __name__ == "__main__":
    main()
