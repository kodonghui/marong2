"""Operator reports using only the isolated pet database."""

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
from uuid import UUID

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.pet.cost import KST, timings
from marong.pet.item_admin import ItemError, add_item, end_item, reopen_item
from marong.pet.settings import Settings, SettingsError


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
    args = parser.parse_args(argv)
    if args.command == "timing" and args.days < 1:
        parser.error("--days must be positive")
    try:
        settings = Settings.read(os.environ)
        with psycopg.connect(settings.db) as conn:
            if args.command == "item":
                manage_item(conn, settings, args)
                return 0
            rows = timings(conn, args.days, datetime.now(KST))
    except ItemError as error:
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
