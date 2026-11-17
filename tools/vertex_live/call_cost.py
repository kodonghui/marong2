"""UTC monthly cost and budget for the live call paths (SPEC-171–174)."""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from time import monotonic

log = logging.getLogger("call_cost")
STATE = (("warn", Decimal("0.8")), ("exhausted", Decimal("1.0")), ("hard_stop", Decimal("1.2")))
BLOCKED = {"exhausted", "hard_stop"}
MONTH = """
WITH limits AS (SELECT %s::timestamptz AS lo, %s::timestamptz AS hi),
turns AS (
    SELECT COALESCE(sum(usage.usd) FILTER (WHERE NOT EXISTS (
        SELECT 1 FROM call.segment_costs s WHERE s.segment_id=usage.segment_ref AND s.estimated
    ) AND NOT EXISTS (
        SELECT 1 FROM call.live_usage saved WHERE saved.segment_ref=usage.segment_ref AND saved.kind='estimate'
    )),0) AS live,
    COALESCE(sum(usage.searches),0) AS search_count
    FROM call.live_usage usage, limits WHERE usage.kind='turn' AND usage.received_at>=lo AND usage.received_at<hi
), estimates AS (
    SELECT COALESCE(sum(usd),0) AS estimated, count(*) AS estimated_segments FROM (
        SELECT s.usd FROM call.segment_costs s, limits WHERE s.opened_at>=lo AND s.opened_at<hi AND s.estimated
        UNION ALL
        SELECT u.usd FROM call.live_usage u, limits WHERE u.received_at>=lo AND u.received_at<hi AND u.kind='estimate'
    ) all_estimates
), searches AS (
    SELECT CASE WHEN p.id IS NULL THEN 0 ELSE
      greatest(0,t.search_count-p.search_free_per_month)*p.search_per_1000/1000 END AS search_usd
    FROM turns t CROSS JOIN limits LEFT JOIN LATERAL (
        SELECT id,search_free_per_month,search_per_1000 FROM call.live_prices
        WHERE starts_at<hi AND search_per_1000>0 ORDER BY starts_at DESC,id DESC LIMIT 1
    ) p ON true
), organizer AS (
    SELECT COALESCE(sum((COALESCE(r.input_tokens,0)::bigint*p.text_in+
      (COALESCE(r.output_tokens,0)::bigint+COALESCE(r.thoughts_tokens,0))*p.text_out)/1000000),0) AS organize,
      count(*) FILTER (WHERE p.id IS NULL) AS organize_unpriced
    FROM call.ai_runs r CROSS JOIN limits LEFT JOIN LATERAL (
      SELECT id,text_in,text_out FROM call.live_prices
      WHERE model=r.model AND starts_at<=r.sent_at ORDER BY starts_at DESC LIMIT 1
    ) p ON true
    WHERE r.kind='organize' AND r.sent_at>=lo AND r.sent_at<hi
)
SELECT live, estimated, estimated_segments, search_count, search_usd, organize, organize_unpriced,
       live+estimated+search_usd+organize AS total
FROM turns, estimates, searches, organizer
"""


def bounds(day):
    start = datetime(day.year, day.month, 1, tzinfo=timezone.utc)
    end = datetime(day.year + (day.month == 12), day.month % 12 + 1, 1, tzinfo=timezone.utc)
    return start, end


async def budget_status(store, entrypoint):
    ledger = getattr(store, "live_usage", None)
    if ledger is None or await ledger.mode() is None:
        return "unknown"
    return await store.monthly_cost.status(entrypoint)


class MonthlyCost:
    def __init__(self, store):
        self.store = store
        self.cached = None
        self.lock = asyncio.Lock()

    async def report(self, at, *, fresh=False):
        start, end = bounds(at.astimezone(timezone.utc))
        async with self.lock:
            if self.cached and self.cached[0] == start and monotonic() < self.cached[1] and not fresh:
                return self.cached[2]
            row = await self.store.one(MONTH, (start, end))
            if not fresh:
                self.cached = (start, monotonic() + 30, row)
            return row

    async def status(self, entrypoint, *, at=None):
        at = at or datetime.now(timezone.utc)
        start, _ = bounds(at.astimezone(timezone.utc))

        async def read():
            # Read the budget each time. An operator change must not wait for the totals cache.
            row = await self.store.one(
                "SELECT COALESCE((SELECT (value #>> '{}')::numeric FROM call.settings "
                "WHERE key='monthly_budget_usd'),150) AS budget"
            )
            budget = row["budget"]
            report = await self.report(at)
            if budget <= 0:
                return "ok"
            total = report["total"]
            events = [(start.date(), state, total, budget) for state, percent in STATE if total >= budget * percent]
            if events:
                async with self.store.pool.connection() as conn, conn.cursor() as cursor:
                    await cursor.executemany(
                        """INSERT INTO call.budget_events(month,kind,spent_usd,budget_usd)
                        VALUES (%s,%s,%s,%s) ON CONFLICT(month,kind) DO NOTHING""", events,
                    )
            return events[-1][1] if events else "ok"

        try:
            return await asyncio.wait_for(read(), 1)
        except Exception:
            self.store.live_usage.count("budget_unknown", entrypoint, at)
            log.warning("budget_unknown entrypoint=%s", entrypoint)
            return "unknown"
