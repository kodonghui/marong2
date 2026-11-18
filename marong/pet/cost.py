"""Private cost records and the public service's monthly limit (SPEC-363, SPEC-369)."""

from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .http import Problem
from .log import logger

KST = ZoneInfo("Asia/Seoul")
MICRO = 1_000_000
COST_GATE = {"preview", "redraw", "farewell", "call", "candidate", "sheet", "expression"}
PAID_CREATION = {"candidate", "sheet", "expression"}
TIMED_JOBS = ("preview", "candidates", "sheet", "reply")


def month_bounds(now):
    start = now.astimezone(KST).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


@dataclass(frozen=True)
class Run:
    trace: UUID
    entry: str
    kind: str
    model: str
    prompt_version: str
    result: str
    member_id: UUID | None = field(default=None, repr=False)
    pet_id: UUID | None = field(default=None, repr=False)
    purpose: str | None = None
    effort: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
    image_input: int | None = None
    images: int | None = None
    seconds: Decimal | None = None
    first_ms: int | None = None
    total_ms: int | None = None
    stop: str | None = None
    fallback: str | None = None


def microusd(prices, run):
    price = prices.prices[run.model].rates
    if run.kind == "call_minute":
        charge = price["minute"] * (run.seconds or 0) * MICRO / 60
    elif run.kind == "image":
        if run.input_tokens is None or run.output_tokens is None:
            # The product's drawing accounting uses an estimate until the provider returns usage.
            charge = Decimal("40000") * (run.images or 0)
        else:
            image = run.image_input or 0
            text = max(0, run.input_tokens - image)
            charge = text * price["text_input"] + image * price["image_input"] + run.output_tokens * price["image_output"]
    else:
        charge = sum((value or 0) * price[key] for key, value in (
            ("input", run.input_tokens), ("output", run.output_tokens),
            ("cache_read", run.cache_read), ("cache_write", run.cache_write),
        ))
    return int(max(Decimal(0), charge).to_integral_value(rounding=ROUND_HALF_UP))


class Budget:
    def __init__(self, pool, settings, *, clock=None):
        self.pool = pool
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(KST))

    async def _total(self, conn, start, end):
        cur = await conn.execute(
            """SELECT COALESCE(sum(est_cost_microusd),0) AS cost FROM pet.ai_runs
            WHERE created_at >= %s AND created_at < %s""", (start, end),
        )
        return (await cur.fetchone())["cost"]

    def _at(self, percent, cost):
        return cost * self.settings.krw_per_usd * 100 >= (
            self.settings.budget_krw * MICRO * percent
        )

    async def _flag(self, conn, start, event, cost):
        month = start.strftime("%Y-%m")
        cur = await conn.execute(
            """INSERT INTO pet.settings(key,value) VALUES (%s,%s) ON CONFLICT (key) DO NOTHING RETURNING key""",
            (f"budget:{month}:{event}", Jsonb({"cost_microusd": int(cost)})),
        )
        return await cur.fetchone() is not None

    async def record(self, run: Run, *, conn=None):
        connection = self.pool.connection() if conn is None else nullcontext(conn)
        async with connection as target, target.transaction():
            booked, warning = await self.record_on(target, run, self.clock())
        self.warn(warning)
        return booked

    async def record_on(self, conn, run: Run, now):
        """Write cost inside a caller's transaction when usage and a counter must commit together."""
        booked = microusd(self.settings.prices, run)
        start, end = month_bounds(now)
        await conn.execute(
            """INSERT INTO pet.ai_runs(
                trace_id,member_id,pet_id,entry,cost_kind,purpose,model,prompt_version,price_version,effort,
                input_tokens,output_tokens,cache_read_tokens,cache_write_tokens,images,first_token_ms,total_ms,
                result,stop_reason,fallback_reason,est_cost_microusd,created_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run.trace, run.member_id, run.pet_id, run.entry, run.kind, run.purpose, run.model,
             run.prompt_version, self.settings.prices.version, run.effort, run.input_tokens, run.output_tokens,
             run.cache_read, run.cache_write, run.images, run.first_ms, run.total_ms,
             run.result, run.stop, run.fallback, booked, now),
        )
        # Serialise threshold calculation after insertion so two smaller concurrent runs can cross it together.
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                           ("pet:budget:" + start.strftime("%Y-%m"),))
        cost = await self._total(conn, start, end)
        alert = self._at(80, cost) and await self._flag(conn, start, "warn", cost)
        return booked, (start.strftime("%Y-%m"), cost) if alert else None

    @staticmethod
    def warn(warning):
        if warning:
            logger.warning("pet_budget_warn month=%s cost_microusd=%s", *warning)

    async def allow(self, action, *, paid=False):
        if action not in COST_GATE:
            return
        start, end = month_bounds(self.clock())
        alert = False
        async with self.pool.connection() as conn, conn.transaction():
            cost = await self._total(conn, start, end)
            if self._at(100, cost):
                if not paid or action not in PAID_CREATION:
                    raise Problem("budget_paused")
                alert = await self._flag(conn, start, "paid_creation_continues", cost)
        if alert:
            logger.warning("pet_budget_paid_creation month=%s cost_microusd=%s", start.strftime("%Y-%m"), cost)


def timings(conn, days, now):
    since = now - timedelta(days=days)
    return conn.execute(
        """WITH pet_timing AS (
          SELECT kind,extract(epoch FROM (finished_at-queued_at))*1000 AS ms,running_at_start
          FROM pet.jobs WHERE kind=ANY(%s::text[]) AND status='done'
            AND finished_at>=%s AND finished_at<=%s AND finished_at>=queued_at
        )
        SELECT kind,count(*) AS count,
          round(percentile_cont(0.50) WITHIN GROUP (ORDER BY ms)) AS p50_ms,
          round(percentile_cont(0.95) WITHIN GROUP (ORDER BY ms)) AS p95_ms,
          max(running_at_start) AS parallel
        FROM pet_timing GROUP BY kind ORDER BY kind""",
        (list(TIMED_JOBS), since, now),
    ).fetchall()
