"""Operator reports using only the isolated pet database."""

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.pet.cost import KST, timings
from marong.pet.settings import Settings, SettingsError


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    timing = commands.add_parser("timing")
    timing.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    try:
        settings = Settings.read(os.environ)
        with psycopg.connect(settings.db) as conn:
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
