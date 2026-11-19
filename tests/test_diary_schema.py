"""TASK-138. Apply diary, listening and call-cost SQL to an isolated pgserver database."""

import re
import subprocess
import tempfile
from pathlib import Path

from pg import ROOT, TestDB

BOT = ROOT / "marong" / "migrations"
CALL = ROOT / "marong" / "call" / "migrations"
UPDATES = (
    BOT / "016_diary.sql",
    BOT / "017_listen_test.sql",
    CALL / "007_call_cost.sql",
)
TABLES = (
    "diary_settings", "diary_looks", "diaries", "diary_ai_runs", "diary_revisions",
    "diary_drawings", "diary_requests", "listen_scores",
    "live_prices", "live_tunings", "live_usage", "live_counters",
)


def snapshot(db):
    constraints = db.admin(
        """SELECT n.nspname, r.relname, c.conname, pg_get_constraintdef(c.oid)
        FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = r.relnamespace
        WHERE n.nspname IN ('marong', 'call') ORDER BY 1, 2, 3"""
    )
    prices = db.admin("SELECT * FROM call.live_prices ORDER BY id")
    tunings = db.admin("SELECT * FROM call.live_tunings ORDER BY name")
    return constraints, prices, tunings


def check_fixture(db):
    source = ROOT / "docs/05-erd/schema-check-2026-11-16.sql"
    fixture = source.read_text(encoding="utf-8")
    # The pre-existing design fixture has human labels. Execute with neutral stand-ins.
    fixture = re.sub(
        r"(INSERT INTO marong\.friends \(name\) VALUES )\('[^']+'\)",
        r"\1('fixture-' || gen_random_uuid()::text)", fixture,
    )
    fixture = re.sub(
        r"(?m)^(\s*)'[^'\n]+',(\n\s*'The little white character)",
        r"\1'오늘 함께 별을 보고 작은 밤을 구웠다. 반짝이는 하늘 아래 밤이 고소했다. 다음에도 같이 작은 바구니를 채우고 싶다.',\2",
        fixture,
    )
    with tempfile.TemporaryDirectory(prefix="marong-diary-schema-") as tmp:
        path = Path(tmp) / "test.sql"
        path.write_text(fixture, encoding="utf-8")
        result = subprocess.run(
            ["psql", "-X", "-At", "-q", "-f", str(path), db.admin_url],
            text=True, encoding="utf-8", capture_output=True, timeout=30,
        )
    if result.returncode:
        raise AssertionError(f"psql exit code {result.returncode}")
    lines = fixture.splitlines()
    expected = set()
    for index, line in enumerate(lines):
        if line.startswith(r"\echo -- expect error"):
            end = next(i for i in range(index + 1, len(lines)) if lines[i].rstrip().endswith(";"))
            expected.add(end + 1)
    seen = [int(number) for number in re.findall(r"test\.sql:(\d+): ERROR:", result.stderr)]
    assert len(expected) == len(seen) == 35 and set(seen) == expected, (sorted(expected), seen)
    assert "\nreconnect|1|f|0.034800\n" in result.stdout
    assert "\nhandoff|0|t|0.500000\n" in result.stdout
    assert "\n2|9000|900|0.534800|t|base-20261116\n" in result.stdout
    assert "\n2|t|0.534800\n" in result.stdout


def main():
    db = TestDB()
    try:
        db.admin((CALL.parent / "schema.sql").read_text(encoding="utf-8"), None)
        installed = db.admin(
            """SELECT table_name FROM information_schema.tables
            WHERE table_schema IN ('marong', 'call') AND table_name = ANY(%s)""", (list(TABLES),)
        )
        assert {name for name, in installed} == set(TABLES)
        prerequisites = (
            *sorted(CALL.glob("00[2-4]*.sql")), *sorted(BOT.glob("01[0-3]*.sql")),
            *sorted(CALL.glob("00[5-6]*.sql")), *sorted(BOT.glob("01[4-5]*.sql")),
        )
        for file in (*prerequisites, *UPDATES):
            db.admin(file.read_text(encoding="utf-8"), None)
        first = snapshot(db)
        for file in UPDATES:
            db.admin(file.read_text(encoding="utf-8"), None)
        assert snapshot(db) == first
        check_fixture(db)
        print("TASK-138: 12 tables, 2 migration passes, 35 expected errors and report totals verified")
    finally:
        db.close()


if __name__ == "__main__":
    main()
