"""Daily quota and transactional reservations (SPEC-353–354)."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from aiohttp import web

from .http import POOL, Problem, require_member

KST = ZoneInfo("Asia/Seoul")
BOUNDARY = timedelta(hours=4)
HOLD_TTL = timedelta(minutes=10)
UNITS = {"call_minute": 30, "new_picture": 40}


def quota_day(at):
    return (at.astimezone(KST) - BOUNDARY).date()


async def _day(conn, member, at):
    day = quota_day(at)
    cur = await conn.execute(
        """INSERT INTO pet.member_days AS days(member_id,day,quota_limit)
        SELECT %s,%s,CASE WHEN EXISTS (SELECT 1 FROM pet.subscriptions
          WHERE member_id=%s AND status IN ('active','canceling') AND period_start<=%s AND period_end>%s)
          THEN 200 ELSE 100 END
        ON CONFLICT (member_id,day) DO UPDATE SET quota_limit=greatest(days.quota_limit,EXCLUDED.quota_limit)
        RETURNING *""", (member, day, member, at, at),
    )
    return await cur.fetchone()


async def reserve(conn, member, purpose, *, at, memorial=False, call=None, diary=None):
    """Hold units in the caller's transaction. Return (hold_id, error).

    Commit an exhausted result before raising it so the day's first recharge prompt is counted once.
    """
    units = UNITS[purpose]
    row = await _day(conn, member, at)
    day = row["day"]
    cur = await conn.execute(
        """UPDATE pet.member_days SET used_units=used_units+%s
        WHERE member_id=%s AND day=%s AND used_units+%s<=quota_limit RETURNING member_id""",
        (units, member, day, units),
    )
    if await cur.fetchone():
        hold = await conn.execute(
            """INSERT INTO pet.quota_holds(member_id,day,units,purpose,call_id,diary_id,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (member, day, units, purpose, call, diary, at),
        )
        return (await hold.fetchone())["id"], None
    prompt = "none" if memorial else "brief"
    if not memorial and row["recharge_prompted_at"] is None:
        await conn.execute("UPDATE pet.member_days SET recharge_prompted_at=%s WHERE member_id=%s AND day=%s",
                           (at, member, day))
        prompt = "recharge"
    return None, Problem("quota_exhausted", extra={"prompt": prompt})


async def settle(conn, member, hold, *, at, commit):
    cur = await conn.execute(
        """SELECT d.day FROM pet.member_days d JOIN pet.quota_holds h USING(member_id,day)
        WHERE h.member_id=%s AND h.id=%s AND h.status='held' FOR UPDATE OF d""", (member, hold),
    )
    day = await cur.fetchone()
    if not day:
        return False
    row = await conn.execute(
        """UPDATE pet.quota_holds SET status=%s,settled_at=%s
        WHERE member_id=%s AND id=%s AND status='held' RETURNING units""",
        ("committed" if commit else "released", at, member, hold),
    )
    changed = await row.fetchone()
    if changed and not commit:
        await conn.execute(
            """UPDATE pet.member_days SET used_units=greatest(0,used_units-%s)
            WHERE member_id=%s AND day=%s""", (changed["units"], member, day["day"]),
        )
    return changed is not None


async def release_expired(pool, at, *, batch=100):
    async with pool.connection() as conn:
        cur = await conn.execute(
            """SELECT member_id,id FROM pet.quota_holds WHERE status='held' AND created_at<%s
            ORDER BY created_at,id LIMIT %s""", (at - HOLD_TTL, batch),
        )
        candidates = await cur.fetchall()
    released = 0
    for row in candidates:
        async with pool.connection() as conn, conn.transaction():
            released += await settle(conn, row["member_id"], row["id"], at=at, commit=False)
    return released


async def read_quota(req):
    member = await require_member(req)
    at = datetime.now(timezone.utc)
    async with req.app[POOL].connection() as conn, conn.transaction():
        row = await _day(conn, member["id"], at)
    reset = datetime.combine(row["day"] + timedelta(days=1), time(4), KST)
    percent = 100 * (row["quota_limit"] - row["used_units"]) // row["quota_limit"]
    return web.json_response({"percent": percent, "resetsAt": reset.isoformat()})


def register(app):
    app.router.add_get("/api/me/quota", read_quota, allow_head=False)
