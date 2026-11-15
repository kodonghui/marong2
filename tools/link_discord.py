"""Owner-only CLI for binding a verified Discord numeric ID to a Marong friend."""
import argparse
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.discord_store import bind_dm


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("discord_id")
    p.add_argument("friend_id", type=int)
    p.add_argument("per_day", type=int)
    p.add_argument("start", type=int)
    p.add_argument("end", type=int)
    p.add_argument("--database", default="marong")
    a = p.parse_args()
    with psycopg.connect(dbname=a.database) as conn:
        bind_dm(conn, a.discord_id, a.friend_id, a.per_day, a.start, a.end)
    print("Verified Discord account linked. Proactive DMs require the recipient to opt in.")


if __name__ == "__main__":
    main()
