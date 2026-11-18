"""Operator reports using only the isolated pet database."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from uuid import UUID

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.pet.cost import KST, timings
from marong.pet.settings import Settings, SettingsError


def report_command(conn, args):
    if args.action == "resolve":
        row = conn.execute(
            "UPDATE pet.reports SET status='resolved',resolved_at=COALESCE(resolved_at,now()) "
            "WHERE id=%s RETURNING id,resolved_at", (args.id,),
        ).fetchone()
        if row is None:
            return 1
        print(f"{row[0]}\t{row[1].isoformat()}")
        return 0
    if args.action == "show":
        row = conn.execute(
            "SELECT id,target_type,reason,note,copy_text,copy_media,status,created_at,resolved_at "
            "FROM pet.reports WHERE id=%s", (args.id,),
        ).fetchone()
        if row is None:
            return 1
        keys = ("id", "targetType", "reason", "note", "text", "mediaId", "status", "createdAt", "resolvedAt")
        print(json.dumps(dict(zip(keys, row)), default=str, ensure_ascii=False))
        return 0
    print("신고 ID\t대상\t이유\t접수 시각")
    for row in conn.execute(
        "SELECT id,target_type,reason,created_at FROM pet.reports WHERE status='open' "
        "ORDER BY created_at,id LIMIT %s", (args.limit,),
    ):
        print("\t".join(map(str, row)))
    return 0


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    timing = commands.add_parser("timing")
    timing.add_argument("--days", type=int, default=7)
    reports = commands.add_parser("report")
    actions = reports.add_subparsers(dest="action", required=True)
    actions.add_parser("list").add_argument("--limit", type=int, choices=range(1, 201), default=100, metavar="1–200")
    for action in ("show", "resolve"):
        actions.add_parser(action).add_argument("id", type=UUID)
    args = parser.parse_args()
    if args.command == "timing" and args.days < 1:
        parser.error("--days must be positive")
    try:
        settings = Settings.read(os.environ)
        with psycopg.connect(settings.db) as conn:
            if args.command == "report":
                return report_command(conn, args)
            rows = timings(conn, args.days, datetime.now(KST))
    except (SettingsError, psycopg.Error):
        print("반려동물 서비스 저장소를 확인해 주세요.", file=sys.stderr)
        return 2
    print("작업\t건수\tP50(ms)\tP95(ms)\t동시 작업 수")
    for kind, count, p50, p95, parallel in rows:
        print(f"{kind}\t{count}\t{int(p50)}\t{int(p95)}\t{parallel or 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
