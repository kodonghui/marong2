"""Record per-account use and redeem overflow tickets without races."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import logging
import os
from zoneinfo import ZoneInfo


log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def usage_day(now, tz=KST):
    return (now.astimezone(tz) - timedelta(hours=4)).date()


def configured_limit(env=os.environ):
    value = env.get("MARONG_DAILY_UNITS", "").strip()
    if not value:
        return None
    if not value.isascii() or not value.isdecimal() or not 0 < int(value) <= 2_147_483_647:
        raise ValueError("MARONG_DAILY_UNITS must be a positive integer or empty")
    return int(value)


def configured_call_limit(env=os.environ):
    value = env.get("MARONG_CALL_PERSON_MONTHLY_USD", "").strip()
    if not value:
        return None
    try:
        budget = Decimal(value)
        if budget.is_finite() and budget >= 0:
            return budget
    except InvalidOperation:
        pass
    raise ValueError("Invalid MARONG_CALL_PERSON_MONTHLY_USD")


def effective_limits(profile, daily_default, call_default):
    if profile is None or profile["usage_unlimited"] is not False:
        return None, None
    daily, monthly = profile["daily_units"], profile["call_monthly_usd"]
    return (daily if daily is not None else daily_default,
            monthly if monthly is not None else call_default)


def month_bounds(day):
    start = datetime(day.year, day.month, 1, tzinfo=timezone.utc)
    end = datetime(day.year + (day.month == 12), day.month % 12 + 1, 1, tzinfo=timezone.utc)
    return start, end


class Usage:
    def __init__(self, pool, limit=None, clock=None, *, call_limit=None):
        self.pool = pool
        self.limit = limit
        self.call_limit = call_limit
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def _row(self, friend, day):
        async with self.pool.connection() as conn:
            cursor = await conn.execute("""
                SELECT p.tickets,p.usage_unlimited,p.daily_units,p.call_monthly_usd,
                       coalesce(u.chat_turns,0) AS chat_turns,
                       coalesce(u.call_seconds,0) AS call_seconds,coalesce(u.images,0) AS images,
                       coalesce(u.units,0) AS units
                FROM marong.friend_profiles p LEFT JOIN marong.usage_daily u ON u.friend_id=p.friend_id AND u.day=%s
                WHERE p.friend_id=%s
            """, (day, friend))
            return await cursor.fetchone()

    async def get(self, friend):
        now = self.clock()
        day = usage_day(now)
        row = await self._row(friend, day)
        if row is None:
            return None
        return await self.summary(friend, now, day, row)

    async def summary(self, friend, now, day, row):
        daily, monthly = effective_limits(row, self.limit, self.call_limit)
        call_month = {"limited": monthly is not None, "percent": None, "resetsAt": None}
        if monthly is not None:
            start, end = month_bounds(now.astimezone(timezone.utc))
            call_month["resetsAt"] = end.astimezone(KST).isoformat()
            try:
                async with asyncio.timeout(1), self.pool.connection() as conn:
                    cursor = await conn.execute(
                        "SELECT call.friend_month_usd(%s,%s,%s) AS usd", (friend, start, end))
                    usd = (await cursor.fetchone())["usd"]
                call_month["percent"] = int(usd * 100 // monthly) if monthly else 100
            except Exception as error:
                log.warning("usage_failed call_month %s", type(error).__name__)
        return {"day": day.isoformat(), "chatTurns": row["chat_turns"], "callSeconds": row["call_seconds"],
                "images": row["images"], "units": row["units"], "tickets": row["tickets"], "limit": daily,
                "callMonth": call_month}

    async def blocked(self, friend):
        try:
            async with asyncio.timeout(1):
                row = await self._row(friend, usage_day(self.clock()))
        except Exception as error:
            log.warning("usage_failed lookup %s", type(error).__name__)
            return False
        daily, _ = effective_limits(row, self.limit, self.call_limit)
        return daily is not None and row["units"] >= daily and row["tickets"] == 0

    async def record(self, friend, *, conn=None, chat=0, seconds=0, images=0, searches=0, shop_reads=0):
        values = (chat, seconds, images, searches, shop_reads)
        if not any(values):
            return
        try:
            async with asyncio.timeout(1):
                if conn is None:
                    async with self.pool.connection() as acquired, acquired.transaction():
                        await self._write(acquired, friend, values)
                else:
                    # Savepoint keeps the previously completed call or artwork when usage storage fails.
                    async with conn.transaction():
                        await self._write(conn, friend, values)
        except Exception as error:
            log.warning("usage_failed write %s", type(error).__name__)

    async def _write(self, conn, friend, values):
        cursor = await conn.execute("""
            SELECT tickets,usage_unlimited,daily_units,call_monthly_usd
            FROM marong.friend_profiles WHERE friend_id=%s FOR UPDATE
        """, (friend,))
        profile = await cursor.fetchone()
        if profile is None:
            return
        day = usage_day(self.clock())
        cursor = await conn.execute("SELECT units FROM marong.usage_daily WHERE friend_id=%s AND day=%s", (friend, day))
        previous = await cursor.fetchone()
        old = previous["units"] if previous else 0
        cursor = await conn.execute("""
            INSERT INTO marong.usage_daily AS u(friend_id,day,chat_turns,call_seconds,images,searches,shop_reads,units)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(friend_id,day) DO UPDATE SET
              chat_turns=u.chat_turns+excluded.chat_turns,call_seconds=u.call_seconds+excluded.call_seconds,
              images=u.images+excluded.images,searches=u.searches+excluded.searches,shop_reads=u.shop_reads+excluded.shop_reads,
              units=u.chat_turns+excluded.chat_turns+(u.call_seconds+excluded.call_seconds+1)/2+(u.images+excluded.images)*40
            RETURNING units
        """, (friend, day, *values, values[0] + (values[1]+1)//2 + values[2]*40))
        units = (await cursor.fetchone())["units"]
        daily, _ = effective_limits(profile, self.limit, self.call_limit)
        if daily is None:
            return
        redeemed = min(profile["tickets"], max(0, units - max(old, daily)))
        if redeemed:
            await conn.execute("""
                UPDATE marong.friend_profiles SET tickets=greatest(tickets-%s,0),updated_at=now() WHERE friend_id=%s
            """, (redeemed, friend))
            await conn.execute("""
                UPDATE marong.usage_daily SET tickets_used=tickets_used+%s WHERE friend_id=%s AND day=%s
            """, (redeemed, friend, day))
