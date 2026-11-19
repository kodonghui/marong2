"""Record per-account use and redeem overflow tickets without races."""

import asyncio
from datetime import datetime, timedelta, timezone
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


class Usage:
    def __init__(self, pool, limit=None, clock=None):
        self.pool = pool
        self.limit = limit
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def get(self, friend):
        day = usage_day(self.clock())
        async with self.pool.connection() as conn:
            cursor = await conn.execute("""
                SELECT p.tickets,coalesce(u.chat_turns,0) AS chat_turns,
                       coalesce(u.call_seconds,0) AS call_seconds,coalesce(u.images,0) AS images,
                       coalesce(u.units,0) AS units
                FROM marong.friend_profiles p LEFT JOIN marong.usage_daily u ON u.friend_id=p.friend_id AND u.day=%s
                WHERE p.friend_id=%s
            """, (day, friend))
            row = await cursor.fetchone()
        if row is None:
            return None
        return {"day": day.isoformat(), "chatTurns": row["chat_turns"], "callSeconds": row["call_seconds"],
                "images": row["images"], "units": row["units"], "tickets": row["tickets"], "limit": self.limit}

    async def blocked(self, friend):
        if self.limit is None:
            return False
        try:
            async with asyncio.timeout(1):
                values = await self.get(friend)
        except Exception as error:
            log.warning("usage_failed lookup %s", type(error).__name__)
            return False
        return bool(values and values["units"] >= self.limit and values["tickets"] == 0)

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
            SELECT tickets FROM marong.friend_profiles WHERE friend_id=%s FOR UPDATE
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
        if self.limit is None:
            return
        redeemed = min(profile["tickets"], max(0, units - max(old, self.limit)))
        if redeemed:
            await conn.execute("""
                UPDATE marong.friend_profiles SET tickets=greatest(tickets-%s,0),updated_at=now() WHERE friend_id=%s
            """, (redeemed, friend))
            await conn.execute("""
                UPDATE marong.usage_daily SET tickets_used=tickets_used+%s WHERE friend_id=%s AND day=%s
            """, (redeemed, friend, day))
