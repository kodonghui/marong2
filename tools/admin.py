"""마롱이 기록 보기. 노트북에서: bash deploy/ovh.sh admin <명령>
  friends                      친구 목록(카카오 키들, 아는 사이, 다른 친구에게 하는 얘기=공유 메모: 가벼운 얘기와 가까운 사이에게만
                               하는 요즘 근황)
  people                       카카오 키 목록(이름·친구·메시지 수·처음/마지막으로 본 때)
  rooms                        방 목록(1:1·단체, 친구들, 메시지 수, 마지막 대화, 1:1 선톡 끔·단체방 선톡 켬, 기억 묶음)
  show <이름 또는 #키> [개수]   그 친구가 있는 방들의 최근 대화(기본 30개)와 기억 메모
  stats                        전체 개수와 최근 7일 토큰 사용량(대략의 비용)
  link <#키> <친구 이름 또는 #키>  그 키를 그 친구로 묶음(같은 사람. 이름이 같은 친구가 이미 있으면 새 키는 묶이지 않고
                               묶기 요청으로 남음)
  unlink <#키>                 그 키를 다른 친구와 따로 둠(이름만 같은 다른 사람. 안 묶인 키면 그 이름의 새 친구로)
  share <친구 이름 또는 #키> on|off  그 친구 얘기를 다른 친구에게 해도 되는지
  friendship <친구> <친구> <관계> [close]  두 친구를 아는 사이로 저장하거나 관계를 고침(예: friendship 동희 현경 연인 close).
                               close 를 붙이면 가까운 사이(서로 요즘 근황까지 들음), 빼면 가벼운 얘기만
  schedule <친구 이름 또는 #키> <하루 횟수> [시작-끝 시]  그 친구 1:1 방의 선톡 일정(예: schedule 현경 12 7-24.
                               시간을 빼면 횟수만 바꿈). schedule <친구> default 면 .env 기본값으로 되돌림,
                               schedule <친구> off|on 이면 선톡을 끄거나 다시 켬. 친구 대신 rooms 의 #방키를 주면 그 방
                               (단체방은 기본 꺼짐이라 schedule <#방키> on 으로 켬. 2026-11-05 부터 카카오가 1:1 선톡을 막음)
  merge <단체방 #방키> <친구 이름·#키 또는 1:1 #방키>  그 단체방을 그 친구 1:1 방과 묶음: 두 방이 기억(최근 대화·요약·메모·
                               비슷한 예전 대화)을 같이 쓰고, 그 단체방 선톡은 그 친구에게 1:1 처럼 감(친구와 마롱이만 있는
                               단체방을 1:1 대신 쓸 때). 기록은 옮기지 않음. merge <단체방 #방키> off 면 묶음을 풂
  topics status                선 전화·그림 화두: 친구마다 켜짐·꺼짐, 선 전화 시간대, 최근 화두 7개와 답
  topics <친구 이름 또는 #키> call on|off       그 친구에게 선 전화(약속 없이 마롱이가 먼저 거는 전화)를 걸지
  topics <친구 이름 또는 #키> pictures on|off   그 친구에게 그림 화두(마롱이 그림과 함께 꺼내는 이야깃거리)를 보낼지
  topics <친구 이름 또는 #키> window 19:00-21:30  선 전화를 걸어도 되는 시간대(한국 시각, 기본 19:00-21:30)
기록을 지우는 명령은 없다(봇 계정에는 그 권한도 없다). link·unlink·share·friendship·schedule·merge·topics 는 키가 어느
친구인지, 공유, 아는 사이, 선톡, 기억 묶음, 선 전화·그림 화두 설정만 바꾼다(topics 로 바꾸면 바꾼 사람이 admin 으로 남음).
선 전화·그림 화두 끄기·켜기는 친구가 대화로 정한 말로도 바뀐다(docs/04-functional-spec/call-first.md 3.7). 이 설정들은 관리자만 바꾸고 친구 말로는 안 바뀐다. 친구가 대화로 한 요청은 시트 '친구·공유' 탭과
friends 에 보인다.
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
from marong.topics import parse_window, prefs_of, window_text  # noqa: E402

# Haiku 5.5 가격(1M 토큰당 달러, 프롬프트 10만 토큰 이하). 캐시 읽기는 입력의 0.1배, 캐시 쓰기는 5분 1.25배·1시간 2배
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ, PRICE_CACHE_WRITE = 0.10, 0.50, 0.01, 0.125
PRICE_CACHE_WRITE_1H = 0.20  # 답 meta 의 cache_write_1h_tokens(cache_write_tokens 에 들어 있는 1시간 쓰기)


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


def find_room(c, who: str) -> dict:
    """rooms 의 #방키 → 방 줄(room_key, is_channel, memory_room). 없으면 끝냄."""
    k = who if who.startswith("#") else "#" + who
    rows = [r for r in c.execute("SELECT room_key, is_channel, memory_room FROM marong.rooms").fetchall()
            if key(r["room_key"]) == k]
    if len(rows) != 1:
        sys.exit(f"'{who}' 방을 찾지 못함(rooms 로 보기)")
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
            "SELECT o.name, fs.label, fs.close FROM marong.friendships fs JOIN marong.friends o "
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
        shared = c.execute("SELECT content, close_content, created_at FROM marong.shared_notes WHERE friend_id = %s "
                           "ORDER BY id DESC LIMIT 1", (f["id"],)).fetchone()
        known: dict[str, list[str]] = {}
        for r in told:
            known.setdefault(r["name"], []).append((r["label"] or "말해 준 사이") + (" · 가까운 사이" if r["close"] else ""))
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
            if shared["close_content"]:
                print("  요즘 근황(가까운 사이에게만):")
                for line in shared["close_content"].splitlines():
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
        "SELECT r.room_key, r.is_channel, r.proactive, r.group_proactive, r.proactive_per_day, r.proactive_start, "
        "  r.proactive_end, r.memory_room, "
        "  (SELECT count(*) FROM marong.rooms x WHERE x.memory_room = r.room_key) AS followers, "
        "  count(m.id) AS n, max(m.created_at) AS last, "
        "  string_agg(DISTINCT coalesce(p.name, '?'), ', ') FILTER (WHERE m.user_key IS NOT NULL) AS who "
        "FROM marong.rooms r "
        "LEFT JOIN marong.messages m ON m.room_key = r.room_key "
        "LEFT JOIN marong.people p ON p.user_key = m.user_key "
        "GROUP BY r.room_key ORDER BY last DESC NULLS LAST").fetchall()
    for r in rows:
        kind = "1:1 " if r["is_channel"] else "단체"
        if r["is_channel"]:
            off = "  (선톡 끔)" if not r["proactive"] else ""
        else:  # 단체방 선톡은 관리자가 켠 방만(기본 꺼짐)
            off = "  (선톡 켬)" if r["group_proactive"] else ""
        plan = f"  (선톡 일정 {plan_text(r)})" if (r["is_channel"] or r["group_proactive"]) and has_plan(r) else ""
        if r["memory_room"]:
            merged = f"  (기억 묶음: 1:1 방 {key(r['memory_room'])})"
        else:
            merged = f"  (기억 묶음: 단체방 {r['followers']}개)" if r["followers"] else ""
        print(f"{key(r['room_key'])}  {kind}  메시지 {r['n']:>5}  마지막 {when(r['last'], tz)}  {r['who'] or ''}{off}{plan}"
              f"{merged}")


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
        "coalesce(sum((meta->>'cache_write_tokens')::bigint), 0)::bigint AS cw, "
        "coalesce(sum((meta->>'cache_write_1h_tokens')::bigint), 0)::bigint AS cw1h "
        "FROM marong.messages WHERE role = 'assistant' AND created_at > now() - interval '7 days'").fetchone()
    s = c.execute(
        "SELECT count(*) AS n, coalesce(sum((meta->>'input_tokens')::bigint), 0)::bigint AS i, "
        "coalesce(sum((meta->>'output_tokens')::bigint), 0)::bigint AS o FROM ("
        "  SELECT meta FROM marong.summaries WHERE created_at > now() - interval '7 days' UNION ALL "
        "  SELECT meta FROM marong.shared_notes WHERE created_at > now() - interval '7 days') x").fetchone()
    usd = ((t["i"] + s["i"]) * PRICE_IN + (t["o"] + s["o"]) * PRICE_OUT
           + t["cr"] * PRICE_CACHE_READ + (t["cw"] - t["cw1h"]) * PRICE_CACHE_WRITE
           + t["cw1h"] * PRICE_CACHE_WRITE_1H) / 1e6
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
                "INSERT INTO marong.friendships (friend_a, friend_b, label, told_by, close) "
                "SELECT least(%(d)s, x.other), greatest(%(d)s, x.other), x.label, "
                "  CASE WHEN x.told_by = %(o)s THEN %(d)s ELSE x.told_by END, x.close FROM ("
                "  SELECT CASE WHEN friend_a = %(o)s THEN friend_b ELSE friend_a END AS other, label, told_by, close "
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
        if src["name"] is None:
            print("이미 어느 친구에도 안 묶여 있음(이름을 모르는 키)")
            return
        # 같은 이름 친구가 있어서 묶이지 않은 키: 다른 사람이면 그 이름의 새 친구로 따로 둔다
        new = c.execute("INSERT INTO marong.friends (name) VALUES (%s) RETURNING id", (src["name"],)).fetchone()["id"]
        c.execute("UPDATE marong.people SET friend_id = %s WHERE user_key = %s", (new, src["user_key"]))
        print(f"{key(src['user_key'])} 키를 '{src['name']}' 새 친구로 따로 둠")
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
    print(f"공유 {'켬' if args[1] == 'on' else '끔'}: " + ("이 친구의 가벼운 얘기는 아는 친구에게, 요즘 근황은 가까운 사이에게 "
                                                       "할 수 있음" if args[1] == "on" else "다른 친구에게 이 친구 얘기를 안 함"))


def friendship(c, _tz, args):
    usage = "사용: friendship <친구 이름 또는 #키> <친구 이름 또는 #키> <관계> [close]"
    if len(args) not in (3, 4) or (len(args) == 4 and args[3] != "close"):
        sys.exit(usage)
    one, other = find_friend(c, args[0]), find_friend(c, args[1])
    label = " ".join(args[2].split())[:20].strip()
    if one == other or not label:
        sys.exit(usage + " (서로 다른 두 친구, 관계는 1~20자)")
    close = len(args) == 4
    a, b = sorted((one, other))
    # 관리자가 정한 사이는 말해 준 친구 없이(told_by 비움) 저장한다. 관계는 방향 없는 말(연인·부부·친구·회사 동기)이 좋다
    c.execute("INSERT INTO marong.friendships (friend_a, friend_b, label, told_by, close) VALUES (%s, %s, %s, NULL, %s) "
              "ON CONFLICT (friend_a, friend_b) DO UPDATE SET label = EXCLUDED.label, told_by = NULL, "
              "  close = EXCLUDED.close", (a, b, label, close))
    names = [r["name"] for r in c.execute("SELECT name FROM marong.friends WHERE id IN (%s, %s) ORDER BY id",
                                          (a, b)).fetchall()]
    print(f"{names[0]} · {names[1]}: {label}" + (" · 가까운 사이(서로 요즘 근황까지 들음)" if close
                                                 else " (서로 가벼운 얘기만 들음)"))


def schedule(c, _tz, args):
    usage = (f"사용: schedule <친구 이름·#키 또는 #방키> <하루 횟수 1~{PER_DAY_MAX}> [시작-끝 시, 예: 7-24]"
             " | schedule <…> default | schedule <…> off|on")
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
    if not users and is_key(who):  # rooms 의 #방키: 1:1 방이나 관리자가 선톡을 켜는 단체방
        k = who if who.startswith("#") else "#" + who
        rooms_ = [r["room_key"] for r in c.execute("SELECT room_key FROM marong.rooms").fetchall()
                  if key(r["room_key"]) == k]
    if not rooms_:
        sys.exit(f"'{who}' 친구의 1:1 방이나 그 #방키의 방을 찾지 못함(rooms·people 로 보기)")
    switch = args[1] in ("on", "off") and len(args) == 2
    if switch:
        sets, values = None, (args[1] == "on",)  # 1:1 은 proactive, 단체방은 group_proactive(방마다 아래에서)
    elif args[1] == "default" and len(args) == 2:
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
        channel = c.execute("SELECT is_channel FROM marong.rooms WHERE room_key = %s", (room,)).fetchone()["is_channel"]
        col = sets or ("proactive = %s" if channel else "group_proactive = %s")
        r = c.execute(f"UPDATE marong.rooms SET {col} WHERE room_key = %s "
                      "RETURNING is_channel, proactive, group_proactive, proactive_per_day, proactive_start, proactive_end",
                      (*values, room)).fetchone()
        if r["is_channel"]:
            label, off = "방", " (선톡 꺼짐: 지금은 안 보냄)" if not r["proactive"] else ""
        else:
            label = "단체방"
            off = " (선톡 켜짐: 이 방에 먼저 말 걸어요)" if r["group_proactive"] else " (선톡 꺼짐: on 으로 켜야 보냄)"
        print(f"{label} {key(room)}: 선톡 일정 " + (plan_text(r) if has_plan(r) else ".env 기본값") + off)


def merge(c, _tz, args):
    """단체방을 한 친구의 1:1 방에 묶거나(기억을 같이 쓰고 선톡은 그 친구에게 1:1 처럼) 묶음을 푼다. 기록은 옮기지 않는다."""
    usage = "사용: merge <단체방 #방키> <친구 이름·#키 또는 1:1 #방키> | merge <단체방 #방키> off"
    if len(args) != 2 or not is_key(args[0]):
        sys.exit(usage)
    group = find_room(c, args[0])
    if group["is_channel"]:
        sys.exit(f"{args[0]} 는 1:1 방이에요. 앞에는 묶을 단체방 #방키를 주세요(rooms 로 보기)")
    if args[1] == "off":
        c.execute("UPDATE marong.rooms SET memory_room = NULL WHERE room_key = %s", (group["room_key"],))
        print(f"단체방 {key(group['room_key'])}: 묶음 풂. 이제 이 방 기억만 쓰고 선톡은 단체방처럼 가요(쌓인 기록은 그대로)")
        return
    who = args[1]
    users = [r["user_key"] for r in c.execute(
        "SELECT p.user_key, p.name, f.name AS friend FROM marong.people p "
        "LEFT JOIN marong.friends f ON f.id = p.friend_id").fetchall()
        if key(r["user_key"]) == (who if who.startswith("#") else "#" + who) or who in (r["name"], r["friend"])]
    if users:  # 그 친구가 말한 1:1 방
        targets = [r["room_key"] for r in c.execute(
            "SELECT DISTINCT m.room_key FROM marong.messages m JOIN marong.rooms r ON r.room_key = m.room_key "
            "WHERE r.is_channel AND m.user_key = ANY(%s)", (users,)).fetchall()]
    else:
        targets = [find_room(c, who)["room_key"]] if is_key(who) else []
    if len(targets) != 1:
        sys.exit(f"'{who}' 의 1:1 방을 하나로 못 정함(찾은 방 {len(targets)}개). rooms 의 1:1 #방키로 주세요")
    target = c.execute("SELECT room_key, is_channel FROM marong.rooms WHERE room_key = %s", (targets[0],)).fetchone()
    if not target["is_channel"]:
        sys.exit(f"{key(target['room_key'])} 는 단체방이에요. 1:1 방에만 묶을 수 있어요")
    if c.execute("SELECT 1 FROM marong.rooms WHERE memory_room = %s", (group["room_key"],)).fetchone():
        sys.exit(f"{key(group['room_key'])} 에 다른 방이 묶여 있어요(묶음은 한 단계만)")
    c.execute("UPDATE marong.rooms SET memory_room = %s WHERE room_key = %s", (target["room_key"], group["room_key"]))
    row = c.execute("SELECT p.name FROM marong.messages m JOIN marong.people p ON p.user_key = m.user_key "
                    "WHERE m.room_key = %s AND m.role = 'user' ORDER BY m.id DESC LIMIT 1", (target["room_key"],)).fetchone()
    friend = (row or {}).get("name") or "이름 모르는 친구"
    print(f"단체방 {key(group['room_key'])} → {friend} 1:1 방 {key(target['room_key'])}: 기억(최근 대화·요약·메모)을 같이 "
          "써요. 이 단체방 선톡은 그 친구에게 1:1 처럼 가요(켜기·일정은 schedule <#방키>). 기록은 옮기지 않아요")


TOPIC_KIND = {"text": "그림 글", "call": "선 전화"}
TOPIC_STATUS = {"sending": "보내는 중", "sent": "보냄", "failed": "실패"}
TOPIC_ANSWER = {"answered": "답 있음", "none": "답 없음", None: "답 기다림"}
TOPIC_FIELDS = {"call": "hello_call", "pictures": "pictures"}


def topics(c, tz, args):
    """선 전화·그림 화두 설정 보기와 바꾸기(docs/04-functional-spec/call-first.md SPEC-279, TBL-125·126)."""
    usage = ("사용: topics status | topics <친구 이름 또는 #키> call on|off | topics <친구> pictures on|off"
             " | topics <친구> window 19:00-21:30")
    if args == ["status"]:
        rows = c.execute(
            "SELECT f.id, f.name, t.hello_call, t.pictures, t.call_from, t.call_until, t.updated_at, t.updated_by "
            "FROM marong.friends f LEFT JOIN marong.topic_prefs t ON t.friend_id = f.id "
            "WHERE EXISTS (SELECT 1 FROM marong.discord_dm_links d WHERE d.friend_id = f.id) "
            "   OR EXISTS (SELECT 1 FROM call.callers k WHERE k.friend_id = f.id) ORDER BY f.id").fetchall()
        if not rows:
            print("디스코드 DM이나 통화가 연결된 친구가 없어요")
        for r in rows:
            prefs = prefs_of(r if r["hello_call"] is not None else None)
            changed = (f" (바꾼 때 {when(r['updated_at'], tz)} {'관리자' if r['updated_by'] == 'admin' else '친구 말'})"
                       if r["updated_at"] else " (기본값)")
            print(f"{r['name']}  선 전화 {'켬' if prefs['hello_call'] else '끔'} · 그림 화두 "
                  f"{'켬' if prefs['pictures'] else '끔'} · 선 전화 시간대 {window_text(prefs['window'])}{changed}")
            sent = c.execute("SELECT day, picture, kind, status, via, answer FROM marong.topic_sends "
                             "WHERE friend_id = %s ORDER BY day DESC LIMIT 7", (r["id"],)).fetchall()
            if not sent:
                print("  (아직 보낸 화두 없음)")
            for t in sent:
                via = f"({'앱' if t['via'] == 'app' else '디스코드'})" if t["via"] else ""
                print(f"  {t['day']:%m/%d}  {t['picture']}  {TOPIC_KIND[t['kind']]} → "
                      f"{TOPIC_STATUS[t['status']]}{via} · {TOPIC_ANSWER.get(t['answer'], t['answer'])}")
        return
    if len(args) != 3 or args[1] not in (*TOPIC_FIELDS, "window"):
        sys.exit(usage)
    friend = find_friend(c, args[0])
    name = c.execute("SELECT name FROM marong.friends WHERE id = %s", (friend,)).fetchone()["name"]
    if args[1] == "window":
        window = parse_window(args[2])
        if window is None:
            sys.exit("시간대는 19:00-21:30 처럼 HH:MM-HH:MM, 시작이 끝보다 앞이어야 해요. " + usage)
        c.execute("INSERT INTO marong.topic_prefs (friend_id, call_from, call_until, updated_by) "
                  "VALUES (%s, %s, %s, 'admin') ON CONFLICT (friend_id) DO UPDATE SET call_from = EXCLUDED.call_from, "
                  "call_until = EXCLUDED.call_until, updated_at = now(), updated_by = 'admin'", (friend, *window))
        print(f"{name}: 선 전화 시간대 {window_text(window)}(한국 시각)")
        return
    if args[2] not in ("on", "off"):
        sys.exit(usage)
    field, on = TOPIC_FIELDS[args[1]], args[2] == "on"
    c.execute(f"INSERT INTO marong.topic_prefs (friend_id, {field}, updated_by) VALUES (%s, %s, 'admin') "
              f"ON CONFLICT (friend_id) DO UPDATE SET {field} = EXCLUDED.{field}, updated_at = now(), "
              "updated_by = 'admin'", (friend, on))
    print(f"{name}: {'선 전화' if field == 'hello_call' else '그림 화두'} {'켬' if on else '끔'}")


COMMANDS = {"friends": friends, "people": people, "rooms": rooms, "show": show, "stats": stats,
            "link": link, "unlink": unlink, "share": share, "friendship": friendship, "schedule": schedule,
            "merge": merge, "topics": topics}
WRITES = {"link", "unlink", "share", "friendship", "schedule", "merge"}


def writes(args: list[str]) -> bool:
    return args[0] in WRITES or (args[0] == "topics" and args[1:] != ["status"])


def main() -> None:
    args = [a for a in sys.argv[1:] if a]
    if not args or args[0] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    load_dotenv(str(ROOT / ".env"))
    tz = ZoneInfo(os.getenv("TIMEZONE") or "Asia/Seoul")
    with psycopg.connect(os.getenv("DATABASE_URL") or "postgresql:///marong", row_factory=dict_row) as c:
        c.read_only = not writes(args)
        COMMANDS[args[0]](c, tz, args[1:])


if __name__ == "__main__":
    main()
