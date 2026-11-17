"""TC-380/381 for the separate pet database and executable service."""

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from urllib.request import urlopen
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from pg import ROOT, TestDB
from marong.pet.jobs import JobQueue
from marong.pet.settings import PRICE_FILE, Settings, SettingsError


def fixtures(db):
    with psycopg.connect(db.srv.get_uri(), autocommit=True) as conn:
        conn.execute("CREATE DATABASE marong_pet")
        # Limit CONNECT in the disposable cluster. Deployment must configure the corresponding server access rule.
        conn.execute("REVOKE CONNECT ON DATABASE marong FROM PUBLIC")
    dsn = db.srv.get_uri("marong_pet")
    source = (ROOT / "marong/pet/schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(source)
        conn.execute(source)
        keys = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='pet'").fetchall()
        assert len(keys) == 24
        conn.execute("REVOKE CONNECT ON DATABASE marong_pet FROM PUBLIC")
        conn.execute("GRANT CONNECT ON DATABASE marong_pet TO marong_pet")

    with psycopg.connect(make_conninfo(dsn, user="marong_pet")) as conn:
        for table, in keys:
            assert conn.execute(
                """SELECT has_table_privilege(%s,'SELECT'),has_table_privilege(%s,'INSERT'),
                has_table_privilege(%s,'UPDATE'),has_table_privilege(%s,'DELETE')""",
                (f"pet.{table}",) * 4,
            ).fetchone() == (True, True, table != "consents", True)
    try:
        with psycopg.connect(make_conninfo(db.admin_url, user="marong_pet")):
            raise AssertionError("pet role connected to the private companion database")
    except psycopg.OperationalError as error:
        assert "permission denied" in str(error)
    return dsn, make_conninfo(dsn, user="marong_pet")


def launch(env, *, assert_health):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**env, "PET_PORT": str(port)}
    command = [sys.executable, str(ROOT / "run_pet.py")]
    if not assert_health:
        return subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", timeout=8)
    with subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) as process:
        try:
            until = time.monotonic() + 6
            while time.monotonic() < until:
                if process.poll() is not None:
                    raise AssertionError(f"pet test listener exited with {process.returncode}")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.2) as response:
                        assert response.status == 200 and json.load(response) == {"ok": True}
                        assert response.headers["Cache-Control"] == "no-store"
                    return
                except OSError:
                    time.sleep(0.05)
            raise AssertionError("pet test listener did not start")
        finally:
            process.terminate()
            process.wait(timeout=5)


def check_startup(dsn):
    env = {k: value for k, value in os.environ.items() if not k.startswith("PET_")}
    env.update({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "50000"})
    assert Settings.read(env).signup == "invite"
    failed = launch({k: value for k, value in env.items() if k != "PET_MONTHLY_BUDGET_KRW"}, assert_health=False)
    assert failed.returncode == 2 and len(failed.stderr.splitlines()) == 1
    failed = launch({**env, "PET_IMAGE_MODEL": "synthetic-secret-marker"}, assert_health=False)
    assert failed.returncode == 2 and "outside the allowed list" in failed.stderr
    assert "synthetic-secret-marker" not in failed.stderr
    denied = launch({**env, "PET_DATABASE_URL": make_conninfo(dsn, dbname="marong")}, assert_health=False)
    assert denied.returncode == 2 and "separate pet database" in denied.stderr

    prices = json.loads(PRICE_FILE.read_text(encoding="utf-8"))
    prices["models"].pop("claude-haiku-5-5")
    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp) / "prices.json"
        file.write_text(json.dumps(prices), encoding="utf-8")
        try:
            Settings.read(env, price_file=file)
        except SettingsError as error:
            assert str(error) == "PET_CHAT_MODEL has no price"
        else:
            raise AssertionError("a missing price did not block startup")
    launch(env, assert_health=True)
    launch({**env, "PET_CHAT_MODEL": "claude-sonnet-5-5"}, assert_health=True)


async def check_jobs(admin_dsn, dsn):
    def put(job):
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute("INSERT INTO pet.jobs(id,kind) VALUES (%s,'cleanup')", (job,))

    def expire(job):
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute("UPDATE pet.jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (job,))

    def status(job):
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            return conn.execute("SELECT status, attempts, error_code FROM pet.jobs WHERE id=%s", (job,)).fetchone()

    job = uuid4()
    put(job)
    lease = timedelta(seconds=5)
    async with AsyncConnectionPool(dsn, open=False, kwargs={"row_factory": dict_row}) as pool:
        queue = JobQueue(pool)
        async def claim():
            return await queue.claim(["cleanup"], lease=lease, attempts=2)
        first, second = await asyncio.gather(claim(), claim())
        assert sum(item is not None for item in (first, second)) == 1
        taken = first or second
        assert taken["attempts"] == 1
        assert await queue.fail(taken, "temporary", retry_after=timedelta(), attempts=2)
        assert status(job) == ("queued", 1, "temporary")
        again = await claim()
        assert again["attempts"] == 2
        assert not await queue.complete(taken)
        assert await queue.complete(again)
        assert status(job) == ("done", 2, None)

        finished = uuid4()
        put(finished)
        abandoned = await claim()
        expire(finished)
        recovered = await claim()
        assert recovered["id"] == finished and recovered["attempts"] == 2
        assert not await queue.complete(abandoned)
        expire(finished)
        assert await claim() is None and status(finished) == ("failed", 2, "deadline")


if __name__ == "__main__":
    db = TestDB()
    try:
        admin, pet = fixtures(db)
        check_startup(pet)
        asyncio.run(check_jobs(admin, pet))
    finally:
        db.close()
    print("TC-380/381: 24 tables, separate DB connection, startup, health and queue verified")
