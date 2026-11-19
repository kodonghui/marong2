"""Copy private contact state while changing which process runs the loops."""

import argparse
import os

import psycopg


COLUMNS = (
    "opted_in_at", "proactive_moved_at", "per_day", "start_hour", "end_hour",
    "last_incoming_at", "last_slot", "last_attempt_at", "failures",
)


def move_contacts(conn, destination):
    if destination == "app":
        columns = ", ".join(COLUMNS)
        updates = ", ".join(f"{key}=EXCLUDED.{key}" for key in COLUMNS)
        sql = f"""
            INSERT INTO marong.contact_settings(friend_id,{columns})
            SELECT friend_id,{columns} FROM marong.discord_dm_links
            ON CONFLICT (friend_id) DO UPDATE SET {updates},updated_at=now()
        """
    elif destination == "bot":
        updates = ", ".join(f"{key}=s.{key}" for key in COLUMNS)
        sql = f"""
            UPDATE marong.discord_dm_links d SET {updates}
            FROM marong.contact_settings s WHERE s.friend_id=d.friend_id
        """
    else:
        raise ValueError("invalid contact state destination")
    return conn.execute(sql).rowcount


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", choices=("app", "bot"))
    args = parser.parse_args()
    with psycopg.connect(os.environ.get("DATABASE_URL") or "postgresql:///marong") as conn:
        moved = move_contacts(conn, args.destination)
    print(f"contact_state_copied destination={args.destination} rows={moved}")


if __name__ == "__main__":
    main()
