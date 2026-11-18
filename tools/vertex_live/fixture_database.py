"""Fresh call-test PostgreSQL using the repository's pgserver fixtures."""
import atexit
import json
from pathlib import Path
import sys

import psycopg
from psycopg.conninfo import make_conninfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from pg import TestDB
from test_persona_schema import prepare

database = TestDB()
atexit.register(database.close)
prepare(database)
CALL_DSN = make_conninfo(database.admin_url, user="marong_call")
BOT_DSN = make_conninfo(database.admin_url, user="marong")


def admin(statement):
    """Keep psql's unaligned scalar output for the existing test assertions."""
    output = []
    with psycopg.connect(database.admin_url, autocommit=True) as connection:
        cursor = connection.execute(statement, prepare=False)
        while True:
            if cursor.description:
                for row in cursor.fetchall():
                    values = []
                    for value in row:
                        if isinstance(value, bool):
                            values.append("t" if value else "f")
                        elif isinstance(value, (dict, list)):
                            values.append(json.dumps(value, ensure_ascii=False, default=str))
                        else:
                            values.append("" if value is None else str(value))
                    output.append("|".join(values))
            if not cursor.nextset():
                break
    return "\n".join(output)
