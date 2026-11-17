"""Diary maintenance. Administrative output uses settings and aggregate counts only."""

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from .diary import KST, STOP_AT, WRITE_FROM, diary_day

USAGE = "diary status | diary month [YYYY-MM] | diary <친구|#키> on|off [--now]|run <YYYY-MM-DD>"


class DiaryAdminError(Exception):
    pass


def writes(args):
    return len(args) >= 2 and args[1] in ("on", "off", "run")


def setting(conn, friend, day):
    return conn.execute(
        "SELECT enabled, from_date, stop_now FROM marong.diary_settings "
        "WHERE friend_id=%s AND from_date<=%s ORDER BY id DESC LIMIT 1", (friend, day)
    ).fetchone()


def toggle(conn, friend, enabled: bool, immediate: bool, now: datetime) -> bool:
    today = diary_day(now)
    if immediate and enabled:
        raise DiaryAdminError(USAGE)
    when = today if immediate else today + timedelta(days=1)
    if immediate and time(4) <= now.astimezone(KST).time() < time(4, 10):
        when -= timedelta(days=1)
    previous = setting(conn, friend, when)
    changed = bool(previous and previous["enabled"]) != enabled
    if immediate and previous and not previous["stop_now"]:
        changed = True
    if changed:
        conn.execute(
            "INSERT INTO marong.diary_settings(friend_id, enabled, from_date, stop_now) VALUES (%s,%s,%s,%s)",
            (friend, enabled, when, immediate),
        )
    if immediate:
        unfinished = conn.execute(
            """UPDATE marong.diaries SET state='failed', fail_reason='off', lease_until=NULL, updated_at=%s
            WHERE friend_id=%s AND state IN ('pending','writing','drawing')""", (now, friend)
        )
        notices = conn.execute(
            """UPDATE marong.diaries SET notice_state='cancelled', notice_next_at=NULL, updated_at=%s
            WHERE friend_id=%s AND state='ready' AND notice_state IN ('none','waiting','failed')""",
            (now, friend),
        )
        changed = changed or bool(unfinished.rowcount or notices.rowcount)
    return changed


def rerun(conn, friend, day: date, now: datetime):
    age = (diary_day(now) - day).days
    if not 1 <= age <= 7:
        raise DiaryAdminError("끝난 일기 하루 중 최근 7일만 다시 돌릴 수 있어요.")
    enabled = setting(conn, friend, day)
    if not enabled or not enabled["enabled"]:
        raise DiaryAdminError("그 날은 일기가 꺼져 있었어요.")
    local = now.astimezone(KST)
    next_day = local.date() + timedelta(days=local.time() >= STOP_AT)
    next_at = max(now, datetime.combine(next_day, WRITE_FROM, KST))
    changed = conn.execute(
        """INSERT INTO marong.diaries(friend_id, diary_date, next_at, updated_at) VALUES (%s,%s,%s,%s)
        ON CONFLICT (friend_id, diary_date) DO UPDATE SET state='pending', fail_reason=NULL,
            attempts=0, draw_tries=0, next_at=EXCLUDED.next_at, lease_until=NULL, updated_at=EXCLUDED.next_at
        WHERE marong.diaries.state IN ('pending','skipped','failed')
        RETURNING id""", (friend, day, next_at, next_at),
    ).fetchone()
    if not changed:
        raise DiaryAdminError("이미 준비됐거나 쓰는 중인 일기는 다시 돌릴 수 없어요.")


def _month(conn, month: str, budget: Decimal):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
        raise DiaryAdminError(USAGE)
    start = date.fromisoformat(month + "-01")
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    stats = conn.execute(
        """WITH daily AS (
            SELECT friend_id, count(*) FILTER (WHERE state='ready') AS ready,
                count(*) FILTER (WHERE state='skipped') AS skipped,
                count(*) FILTER (WHERE state='failed') AS failed, sum(fixes_used) AS fixes,
                count(*) FILTER (WHERE state='ready' AND drawing_id IS NULL) AS placeholder
            FROM marong.diaries WHERE diary_date >= %s AND diary_date < %s GROUP BY friend_id
        ), drawings AS (
            SELECT d.friend_id, count(*) FILTER (WHERE g.origin='night') AS night,
                count(*) FILTER (WHERE g.origin='retry') AS retry, count(*) FILTER (WHERE g.origin='redraw') AS redraw
            FROM marong.diary_drawings g JOIN marong.diaries d ON d.id=g.diary_id
            WHERE d.diary_date >= %s AND d.diary_date < %s GROUP BY d.friend_id
        ), spend AS (
            SELECT d.friend_id, sum(r.cost_usd) AS usd,
                sum(r.cost_usd) FILTER (WHERE r.cost_estimated) AS estimated
            FROM marong.diary_ai_runs r JOIN marong.diaries d ON d.id=r.diary_id
            WHERE r.kind='draw' AND sent_at >= %s AND sent_at < %s GROUP BY d.friend_id
        )
        SELECT friend_id, ready, skipped, failed, fixes, night, retry, redraw, placeholder, usd, estimated
        FROM daily FULL JOIN drawings USING(friend_id) FULL JOIN spend USING(friend_id) ORDER BY friend_id
        """, (start, end, start, end, datetime.combine(start, time(), KST), datetime.combine(end, time(), KST)),
    ).fetchall()
    for row in stats:
        print(f"#{row['friend_id']} " + " ".join(
            f"{name}={row[name] or 0}" for name in ("ready", "skipped", "failed", "fixes", "night", "retry", "redraw", "placeholder")
        ) + f" 그림 비용=${row['usd'] or 0:.2f} 추정=${row['estimated'] or 0:.2f}")
    spent = sum((row["usd"] or 0 for row in stats), start=Decimal(0))
    print(f"그림 월 예산=${budget:.2f} 남음=${max(Decimal(0), budget - spent):.2f}")


def command(conn, args, find_friend, now: datetime, budget: Decimal):
    today = diary_day(now)
    if args == ["status"]:
        rows = conn.execute(
            """SELECT c.friend_id, COALESCE(s.enabled, false) AS enabled, s.from_date, d.state
            FROM call.callers c JOIN marong.discord_dm_links link USING(friend_id)
            LEFT JOIN LATERAL (
                SELECT enabled, from_date FROM marong.diary_settings
                WHERE friend_id=c.friend_id AND from_date<=%s ORDER BY id DESC LIMIT 1
            ) s ON true
            LEFT JOIN LATERAL (
                SELECT state FROM marong.diaries WHERE friend_id=c.friend_id ORDER BY diary_date DESC LIMIT 1
            ) d ON true
            WHERE c.enabled AND link.channel_id IS NOT NULL ORDER BY c.friend_id""", (today,),
        )
        for row in rows:
            print(f"#{row['friend_id']} {'켜짐' if row['enabled'] else '꺼짐'} "
                  f"{row['from_date'] or '—'} {row['state'] or '—'}")
        return
    if args and args[0] == "month" and len(args) <= 2:
        _month(conn, args[1] if len(args) == 2 else now.astimezone(KST).strftime("%Y-%m"), budget)
        return
    if len(args) < 2 or (args[1:] not in (["on"], ["off"], ["off", "--now"])
                         and not (len(args) == 3 and args[1] == "run")):
        raise DiaryAdminError(USAGE)
    friend = find_friend(conn, args[0])
    # Serialize maintenance for one friend. Workers still own each diary row.
    conn.execute("SELECT id FROM marong.friends WHERE id=%s FOR UPDATE", (friend,))
    allowed = conn.execute(
        "SELECT 1 FROM call.callers c JOIN marong.discord_dm_links d USING(friend_id) "
        "WHERE c.friend_id=%s AND c.enabled AND d.channel_id IS NOT NULL", (friend,),
    ).fetchone()
    if not allowed:
        raise DiaryAdminError("일기장을 열 수 없는 친구예요.")
    action = args[1]
    if action == "run":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", args[2]):
            raise DiaryAdminError(USAGE)
        rerun(conn, friend, date.fromisoformat(args[2]), now)
        print("다시 쓰기를 예약했어요.")
        return
    enabled = action == "on"
    changed = toggle(conn, friend, enabled, args[2:] == ["--now"], now)
    print(("일기를 켰어요." if enabled else "일기를 껐어요.") if changed
          else ("이미 켜져 있어요." if enabled else "이미 꺼져 있어요."))
