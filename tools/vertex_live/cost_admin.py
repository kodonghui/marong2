"""Number-only call cost reports and settings (SPEC-172, SPEC-177, SPEC-180)."""

import argparse
import asyncio
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import re

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from call_cost import MONTH, STATE, bounds
from call_memory import MemoryStore
from call_tuning import parse_tuning

PRICE_FIELDS = ("text_in", "audio_in", "image_in", "text_out", "audio_out", "search_per_1000",
                "search_free_per_month", "checked_on", "source")
GROUPS = """SELECT entrypoint,tuning,grouping(entrypoint,tuning) AS grouping,
    count(DISTINCT call_id) AS calls,sum(seconds)/60 AS minutes,
    sum(usd) AS usd,sum(audio_in_tokens) AS audio,
    sum(unpriced_rows) AS unpriced
    FROM call.segment_costs WHERE opened_at>=%s AND opened_at<%s
    GROUP BY GROUPING SETS ((),(entrypoint),(tuning))
    ORDER BY grouping DESC,entrypoint NULLS FIRST,tuning NULLS FIRST"""


def cli():
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest="command", required=True)
    report = modes.add_parser("call-cost")
    report.add_argument("month", nargs="?")
    report.add_argument("--switch", action="store_true")
    modes.add_parser("call-budget").add_argument("amount", nargs="?")
    modes.add_parser("call-credit-checked").add_argument("date")
    prices = modes.add_parser("call-price").add_subparsers(dest="action", required=True)
    prices.add_parser("list")
    price = prices.add_parser("add")
    price.add_argument("model")
    price.add_argument("starts")
    price.add_argument("fields", nargs="+")
    tunings = modes.add_parser("call-tuning").add_subparsers(dest="action", required=True)
    tunings.add_parser("list")
    tuning = tunings.add_parser("add")
    tuning.add_argument("name")
    tuning.add_argument("fields", nargs="*")
    tunings.add_parser("use").add_argument("name")
    return parser


async def change(store, key, value):
    async with store.pool.connection() as conn:
        await conn.execute("""INSERT INTO call.settings(key,value) VALUES (%s,%s)
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value""", (key, Jsonb(value)))


async def setting(store, key, default=None):
    row = await store.one("SELECT value FROM call.settings WHERE key=%s", (key,))
    return row["value"] if row else default


def number(value, lower, upper):
    result = Decimal(value)
    if not result.is_finite() or not lower <= result <= upper:
        raise ValueError("invalid amount")
    return result


def day(raw):
    result = date.fromisoformat(raw)
    if str(result) != raw:
        raise ValueError("use YYYY-MM-DD")
    return result


async def report(store, args, now):
    if args.switch and args.month:
        raise ValueError("choose a month or --switch")
    if args.month and not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", args.month):
        raise ValueError("use YYYY-MM")
    at = datetime.fromisoformat(args.month + "-01T00:00:00+00:00") if args.month else now
    low, high = (now - timedelta(days=14), now) if args.switch else bounds(at)
    rows = await store.all(GROUPS, (low, high))
    groups = []
    for row in rows:
        minutes = row["minutes"] or 0
        usd = row["usd"] or Decimal(0)
        groups.append({**row, "minutes": round(minutes, 2), "usd_per_minute": usd / Decimal(minutes) if minutes else None,
                       "audio_tokens_per_minute": round((row["audio"] or 0) / minutes) if minutes else None})
    if args.switch:
        total = next(group for group in groups if group["grouping"] == 3)
        factor = Decimal(monthrange(now.year, now.month)[1]) / 14
        costs = await period_cost(store, low, high)
        return {"days": 14, "groups": groups, "cost_usd": costs,
                "usd_per_minute": costs["total"] / Decimal(str(total["minutes"])) if total["minutes"] else None,
                "projected_month_minutes": round(Decimal(str(total["minutes"])) * factor, 2),
                "projected_month_usd": round(costs["total"] * factor, 6),
                "projected_month_segment_usd": round((total["usd"] or 0) * factor, 6),
                "credit_checked_on": await setting(store, "credit_checked_on")}
    current = await store.monthly_cost.report(at, fresh=True)
    budget = Decimal(str(await setting(store, "monthly_budget_usd", 150)))
    fraction = current["total"] / budget
    state = next((name for name, ratio in reversed(STATE) if fraction >= ratio), "ok")
    counters = await store.all("SELECT entrypoint,name,count FROM call.live_counters WHERE month=%s ORDER BY 1,2", (low.date(),))
    oldest = await store.one("""SELECT min(p.checked_on) AS checked_on FROM call.live_prices p
        JOIN call.live_usage u ON u.price_id=p.id WHERE u.received_at>=%s AND u.received_at<%s""", (low, high))
    checked = oldest["checked_on"]
    return {"month": f"{at:%Y-%m}", "state": state, "budget_usd": budget, "percent": round(fraction * 100),
            "checked_on": checked, "recheck_prices": checked is not None and (now.date() - checked).days >= 90,
            "cost_usd": current, "groups": groups, "counters": counters}


async def period_cost(store, low, high):
    """Subtract month-to-date totals so earlier searches consume the same monthly free allowance."""
    total = {}
    cursor = low
    while cursor < high:
        start, end = bounds(cursor)
        stop = min(end, high)
        upper = await store.one(MONTH, (start, stop))
        lower = await store.one(MONTH, (start, cursor))
        for key, value in upper.items():
            total[key] = total.get(key, 0) + value - lower[key]
        cursor = stop
    return total


async def add_price(store, args, now):
    starts = datetime.fromisoformat(args.starts)
    if starts.tzinfo is None or starts.utcoffset() != timedelta():
        raise ValueError("provide a UTC start")
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,100}", args.model):
        raise ValueError("invalid model label")
    fields = {}
    for item in args.fields:
        key, sep, value = item.partition("=")
        if not sep or key not in PRICE_FIELDS or key in fields:
            raise ValueError("invalid price field")
        fields[key] = value
    rates = [number(fields[field], 0, Decimal("999999.9999")) for field in PRICE_FIELDS[:5]]
    search = number(fields.get("search_per_1000", "0"), 0, Decimal("999999.9999"))
    free = int(fields.get("search_free_per_month", "0"))
    checked = day(fields["checked_on"])
    source = fields["source"]
    if not 0 <= free <= 2_147_483_647 or not 1 <= len(source) <= 200:
        raise ValueError("invalid price data")
    async with store.pool.connection() as conn:
        await conn.execute("""INSERT INTO call.live_prices(model,starts_at,text_in,audio_in,image_in,text_out,audio_out,
            search_per_1000,search_free_per_month,checked_on,source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (args.model, starts, *rates, search, free, checked, source))
    return {"added": True, "historical_price_is_unchanged": starts < now}


async def tune(store, args):
    if args.action == "list":
        return {"active": await setting(store, "live_tuning"), "tunings": await store.all(
            "SELECT * FROM call.live_tunings ORDER BY name")}
    if args.action == "use":
        if not await store.one("SELECT 1 FROM call.live_tunings WHERE name=%s", (args.name,)):
            raise ValueError("unknown tuning")
        await change(store, "live_tuning", args.name)
        return {"active": args.name}
    data = parse_tuning(args.name, args.fields)
    keys = sql.SQL(",").join(map(sql.Identifier, data))
    placeholders = sql.SQL(",").join(sql.Placeholder() for _ in data)
    async with store.pool.connection() as conn:
        await conn.execute(sql.SQL("INSERT INTO call.live_tunings({}) VALUES ({})").format(keys, placeholders),
                           tuple(data.values()))
    return {"added": args.name}


async def run(store, args, now):
    if args.command == "call-cost":
        return await report(store, args, now)
    if args.command == "call-budget":
        if args.amount is not None:
            value = number(args.amount, Decimal(".01"), 10000)
            if value.as_tuple().exponent < -2:
                raise ValueError("budget accepts two decimals")
            await change(store, "monthly_budget_usd", float(value))
        return {"monthly_budget_usd": await setting(store, "monthly_budget_usd", 150)}
    if args.command == "call-credit-checked":
        checked = day(args.date)
        await change(store, "credit_checked_on", str(checked))
        return {"credit_checked_on": checked}
    if args.command == "call-tuning":
        return await tune(store, args)
    if args.action == "list":
        return await store.all("""SELECT id,model,starts_at,text_in,audio_in,image_in,text_out,audio_out,
            search_per_1000,search_free_per_month,checked_on FROM call.live_prices ORDER BY starts_at DESC,id""")
    return await add_price(store, args, now)


async def execute(args):
    store = MemoryStore(os.environ.get("MARONG_CALL_DSN", "dbname=marong user=marong_call"))
    try:
        await store.open()
        result = await run(store, args, datetime.now(timezone.utc))
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    finally:
        await store.close()


if __name__ == "__main__":
    try:
        asyncio.run(execute(cli().parse_args()))
    except (ValueError, KeyError, InvalidOperation, psycopg.Error, OSError, RuntimeError):
        raise SystemExit("통화 설정이나 저장소를 확인해 주세요.") from None
