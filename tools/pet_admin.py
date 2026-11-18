"""Operator reports using only the isolated pet database."""

import argparse
import asyncio
from datetime import date, datetime
import os
from pathlib import Path
import sys
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.pet.cost import KST, timings
from marong.pet.item_admin import ItemError, add_item, end_item, reopen_item
from marong.pet.push import VapidSender
from marong.pet.settings import Settings, SettingsError
from marong.pet.subscriptions import PriceChangeError, announce_price


ASSETS = Path(__file__).resolve().parents[1] / "design" / "pet"


def manage_item(conn, settings, args):
    if args.action == "add":
        print(add_item(conn, settings, args.folder, ASSETS / "templates", ASSETS / "licenses.csv"))
    elif args.action == "list":
        print("아이템 ID\t이름\t종류\t판매")
        for ident, name, kind, selling in conn.execute(
                "SELECT id,name,kind,sellable FROM pet.items ORDER BY created_at,id"):
            print(f"{ident}\t{name}\t{kind}\t{'예' if selling else '아니요'}")
    elif args.action == "reopen":
        reopen_item(conn, args.id)
    elif not end_item(conn, args.id):
        raise ItemError("item_not_found")


async def schedule_price(settings, amount, effective, sender):
    async with AsyncConnectionPool(settings.db, open=False, min_size=1, max_size=2, timeout=3,
                                   kwargs={"row_factory": dict_row}) as pool:
        return await announce_price(pool, amount, effective, datetime.now(KST), sender)


def main(argv=None):
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    timing = commands.add_parser("timing")
    timing.add_argument("--days", type=int, default=7)
    items = commands.add_parser("item").add_subparsers(dest="action", required=True)
    items.add_parser("add").add_argument("folder", type=Path)
    items.add_parser("list")
    for action in ("end", "reopen"):
        items.add_parser(action).add_argument("id", type=UUID)
    subscription = commands.add_parser("subscription").add_subparsers(dest="action", required=True)
    price = subscription.add_parser("announce-price")
    price.add_argument("amount", type=int)
    price.add_argument("effective", type=date.fromisoformat)
    args = parser.parse_args(argv)
    if args.command == "timing" and args.days < 1:
        parser.error("--days must be positive")
    try:
        settings = Settings.read(os.environ)
        if args.command == "subscription":
            key, subject = os.environ.get("PET_VAPID_PRIVATE_KEY"), os.environ.get("PET_VAPID_SUBJECT")
            if bool(key) != bool(subject):
                raise SettingsError("pet push key and contact must be configured together")
            sender = VapidSender(key, subject) if key else None
            stored, sent = asyncio.run(schedule_price(settings, args.amount, args.effective, sender))
            print(f"가격 고지 {stored}건 · 푸시 전달 {sent}건")
            return 0
        with psycopg.connect(settings.db) as conn:
            if args.command == "item":
                manage_item(conn, settings, args)
                return 0
            rows = timings(conn, args.days, datetime.now(KST))
    except (ItemError, PriceChangeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except (SettingsError, psycopg.Error, OSError):
        print("반려동물 서비스 저장소를 확인해 주세요.", file=sys.stderr)
        return 2
    print("작업\t건수\tP50(ms)\tP95(ms)\t동시 작업 수")
    for kind, count, p50, p95, parallel in rows:
        print(f"{kind}\t{count}\t{int(p50)}\t{int(p95)}\t{parallel or 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
