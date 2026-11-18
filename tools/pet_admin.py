"""Operator commands using only the isolated pet database."""

import argparse
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
from secrets import choice
import sys
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.pet.cost import KST, timings
from marong.pet.account import CODE, MEMBER_SYMBOLS
from marong.pet.settings import Settings, SettingsError

BUSINESS_FIELDS = ("사업자등록번호", "통신판매업 신고번호", "상호", "대표자", "주소", "연락처")


def store_setting(conn, key, value):
    conn.execute("""
        INSERT INTO pet.settings(key,value) VALUES (%s,%s)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=now()
    """, (key, Jsonb(value)))


def set_payments(conn, enabled, info=None):
    if enabled:
        if (not isinstance(info, dict) or set(info) != set(BUSINESS_FIELDS)
                or not all(isinstance(value, str) and 1 <= len(value.strip()) <= 200 for value in info.values())):
            raise ValueError("incomplete_business_info")
        store_setting(conn, "business_info", {key: value.strip() for key, value in info.items()})
    store_setting(conn, "payments_enabled", enabled)


def grant_ticket(conn, number, count, reason):
    if not CODE.fullmatch(number) or not 1 <= count <= 20 or reason not in ("test", "apology"):
        raise ValueError("invalid_grant")
    row = conn.execute("""
        UPDATE pet.members SET free_tickets=free_tickets+%s
        WHERE member_no=%s AND status='active' AND free_tickets+%s<=20 RETURNING id,free_tickets
    """, (count, number, count)).fetchone()
    if not row:
        raise ValueError("invalid_grant_target")
    store_setting(conn, f"ticket_grant:{row[0]}:{uuid4()}", {"count": count, "reason": reason})
    return row[1]


def create_invite(conn, uses):
    if not 1 <= uses <= 2_147_483_647:
        raise ValueError("invalid_invite_uses")
    for _ in range(8):
        code = "".join(choice(MEMBER_SYMBOLS) for _ in range(8))
        row = conn.execute("""
            INSERT INTO pet.invites(code_hash,uses_left) VALUES (%s,%s)
            ON CONFLICT(code_hash) DO NOTHING RETURNING id
        """, (sha256(code.encode("ascii")).digest(), uses)).fetchone()
        if row:
            return code
    raise RuntimeError("pet_invite_collision")


def main(argv=None):
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    timing = commands.add_parser("timing")
    timing.add_argument("--days", type=int, default=7)

    payments = commands.add_parser("payments")
    payments.add_argument("action", choices=("on", "off"))
    ticket = commands.add_parser("ticket").add_subparsers(dest="action", required=True)
    grant = ticket.add_parser("grant")
    grant.add_argument("member")
    grant.add_argument("--count", type=int, default=1)
    grant.add_argument("--reason", choices=("test", "apology"), required=True)
    invite = commands.add_parser("invite").add_subparsers(dest="action", required=True)
    create = invite.add_parser("create")
    create.add_argument("--uses", type=int, default=1)

    args = parser.parse_args(argv)
    if args.command == "timing" and args.days < 1:
        parser.error("--days must be positive")
    try:
        settings = Settings.read(os.environ)
        info = None
        if args.command == "payments" and args.action == "on":
            info = {name: input(f"{name} > ").strip() for name in BUSINESS_FIELDS}
        with psycopg.connect(settings.db) as conn:
            if args.command == "timing":
                rows = timings(conn, args.days, datetime.now(KST))
                result = None
            elif args.command == "payments":
                set_payments(conn, args.action == "on", info)
                result = args.action
            elif args.command == "ticket":
                result = grant_ticket(conn, args.member, args.count, args.reason)
            else:
                result = create_invite(conn, args.uses)
    except (SettingsError, psycopg.Error, EOFError, ValueError, RuntimeError):
        print("입력값과 반려동물 서비스 저장소를 확인해 주세요.", file=sys.stderr)
        return 2
    if result is not None:
        print(result)
        return 0
    print("작업\t건수\tP50(ms)\tP95(ms)\t동시 작업 수")
    for kind, count, p50, p95, parallel in rows:
        print(f"{kind}\t{count}\t{int(p50)}\t{int(p95)}\t{parallel or 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
