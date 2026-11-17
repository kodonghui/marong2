"""TC-380/381 for the separate pet database and executable service."""

import asyncio
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from decimal import Decimal
from base64 import urlsafe_b64encode
from hashlib import sha256
from io import StringIO
from secrets import token_urlsafe
from unittest.mock import patch
from urllib.request import urlopen
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import psycopg
import jwt
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives.asymmetric import rsa
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from pg import ROOT, TestDB
from marong.pet.jobs import JobQueue
from marong.pet.cost import Budget, KST, Run, microusd, timings
from marong.pet.auth import AuthConfig, Provider, STATE_COOKIE, subject_hash
from marong.pet.http import COOKIE, Problem, cookie_hash, require_member
from marong.pet.log import member_ref
from marong.pet.settings import PRICE_FILE, Settings, SettingsError
from run_pet import make_app


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


async def check_http(admin_dsn, dsn, directory):
    media_dir = directory / "media"
    media_dir.mkdir()
    picture = media_dir / "sample.png"
    art = b"synthetic byte fixture"
    picture.write_bytes(art)
    secret = directory / "not-a-media-file"
    secret.write_bytes(b"must not be read as media")
    a, b, c = uuid4(), uuid4(), uuid4()
    token_a, token_b, expired = token_urlsafe(32), token_urlsafe(32), token_urlsafe(32)
    member_a, member_b = "FIXTURE1", "FIXTURE2"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        for ident, member, token in ((a, member_a, token_a), (b, member_b, token_b)):
            conn.execute("INSERT INTO pet.members(id,member_no,provider,sub_hash,adult_self_declared_at) "
                         "VALUES (%s,%s,'google',%s,now())", (ident, member, sha256(token.encode()).digest()))
            conn.execute(
                """INSERT INTO pet.sessions(token_hash,kind,member_id,expires_at,absolute_expires_at)
                VALUES (%s,'member',%s,now()+interval '1 day',now()+interval '3 days')""",
                (cookie_hash(token), ident),
            )
        conn.execute(
            """INSERT INTO pet.sessions(token_hash,kind,member_id,expires_at,absolute_expires_at)
            VALUES (%s,'member',%s,now()-interval '1 day',now()+interval '3 days')""",
            (cookie_hash(expired), a),
        )
        digest = sha256(art).digest()
        for ident, path, days in ((c, "sample.png", 2), (uuid4(), "../not-a-media-file", 2), (uuid4(), "old.png", -1)):
            conn.execute(
                """INSERT INTO pet.media(id,member_id,kind,storage_key,content_type,bytes,sha256,delete_after)
                VALUES (%s,%s,'preview',%s,'image/png',%s,%s,now()+%s)""",
                (ident, a, path, len(art), digest, timedelta(days=days)),
            )
        blocked_files = conn.execute("SELECT id FROM pet.media WHERE id<>%s", (c,)).fetchall()

    origin = "https://pet.example.test"
    settings = Settings.read({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "50000",
                              "PET_ORIGIN": origin, "PET_MEDIA_DIR": str(media_dir)})
    app = make_app(settings)
    counter = 0

    async def write(req):
        nonlocal counter
        await require_member(req)
        counter += 1
        return web.json_response({"ok": True})

    async def fail(req):
        await require_member(req)
        raise RuntimeError("member input fixture alice@example.test picture-example.png")

    app.router.add_put("/test/write", write)
    app.router.add_get("/test/fail", fail)
    logged = StringIO()
    lines = logging.StreamHandler(logged)
    target = logging.getLogger("pet")
    target.addHandler(lines)

    async def error(res, expected, status):
        assert res.status == status and res.content_type == "application/problem+json"
        assert res.headers["Cache-Control"] == "no-store"
        response = await res.json()
        assert response["status"] == status and response["code"] == expected
        assert len(response.pop("traceId")) == 32
        return response

    def headers(token, **extra):
        return {"Cookie": f"{COOKIE}={token}", **extra}

    try:
        async with TestClient(TestServer(app)) as client:
            url = f"/api/media/{c}"
            await error(await client.get(url), "unauthenticated", 401)
            await error(await client.get(url, headers=headers(expired)), "unauthenticated", 401)
            await error(await client.get("/api/media/wrong-id", headers=headers(token_a)), "invalid_input", 400)
            missing = await error(await client.get(f"/api/media/{uuid4()}", headers=headers(token_b)), "not_found", 404)
            other = await error(await client.get(url, headers=headers(token_b)), "not_found", 404)
            assert missing == other
            for item, in blocked_files:
                await error(await client.get(f"/api/media/{item}", headers=headers(token_a)), "not_found", 404)
            response = await client.get(url, headers=headers(token_a))
            assert response.status == 200 and response.content_type == "image/png"
            assert response.headers["Cache-Control"] == "private, max-age=31536000, immutable"
            assert await response.read() == art
            cookie = response.cookies[COOKIE]
            assert cookie["secure"] and cookie["httponly"] and cookie["samesite"] == "Lax"
            assert 0 < int(cookie["max-age"]) <= 3 * 24 * 3600

            write_route = "/test/write"
            await error(await client.put(write_route, headers=headers(token_a)), "cross_site", 403)
            separate = headers(token_a, Origin="https://other.test", **{"Sec-Fetch-Site": "same-origin"})
            await error(await client.put(write_route, headers=separate), "cross_site", 403)
            assert counter == 0
            assert (await client.put(write_route, headers=headers(token_a, Origin=origin))).status == 200
            assert (await client.put(write_route, headers=headers(token_a, **{"Sec-Fetch-Site": "same-origin"}))).status == 200
            assert counter == 2
            failure = await error(await client.get("/test/fail", headers=headers(token_a)), "server_error", 500)
            assert failure["detail"] == "잠시 뒤 다시 해 주세요."
    finally:
        target.removeHandler(lines)
    logs = logged.getvalue()
    assert member_ref(member_a) in logs
    for value in (member_a, member_b, token_a, token_b, "alice@example.test", "picture-example.png", "RuntimeError"):
        assert value not in logs


async def check_cost(admin_dsn, dsn):
    settings = Settings.read({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "1337"})
    now = datetime(2026, 11, 30, 23, 59, 59, tzinfo=KST)
    image = Run(uuid4(), "AI-31", "image", settings.image_model, "fixture", "ok",
                images=1, input_tokens=700, image_input=400, output_tokens=600)
    voice = Run(uuid4(), "AI-35", "call_minute", "gemini-3.8-live", "fixture", "ok", seconds=Decimal(60))
    assert microusd(settings.prices, image) == 22700
    assert microusd(settings.prices, voice) == 26926
    assert max(pics * Decimal(53) + minutes * Decimal(36)
               for pics in range(3) for minutes in range(4) if pics*40 + minutes*30 <= 100) <= 150

    def text(cost):
        return Run(uuid4(), "AI-32", "chat", settings.chat_model, "fixture", "ok", output_tokens=cost * 2)

    async with AsyncConnectionPool(dsn, open=False, kwargs={"row_factory": dict_row}) as pool:
        budget = Budget(pool, settings, clock=lambda: now)
        await budget.allow("preview")
        assert await budget.record(text(790000)) == 790000
        await asyncio.gather(budget.record(text(5000)), budget.record(text(5000)))
        assert await budget.record(text(200000)) == 200000
        for action in ("preview", "redraw", "farewell", "call"):
            try:
                await budget.allow(action)
            except Problem as error:
                assert error.code == "budget_paused"
            else:
                raise AssertionError(f"cost gate allowed {action}")
        await budget.allow("chat")
        await budget.allow("candidate", paid=True)
        await budget.allow("candidate", paid=True)
        with psycopg.connect(admin_dsn) as conn:
            events = conn.execute("SELECT key FROM pet.settings WHERE key LIKE 'budget:%' ORDER BY key").fetchall()
            assert events == [("budget:2026-11:paid_creation_continues",), ("budget:2026-11:warn",)]
            assert conn.execute("SELECT count(*),sum(est_cost_microusd) FROM pet.ai_runs").fetchone() == (4, 1000000)
        now += timedelta(seconds=1)
        await budget.allow("preview")
        await budget.allow("redraw")
        await budget.allow("call")

    current = datetime.now(KST)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        for kind in ("preview", "candidates", "sheet", "reply"):
            conn.execute(
                """INSERT INTO pet.jobs(kind,status,queued_at,started_at,finished_at,running_at_start)
                VALUES (%s,'done',%s,%s,%s,2)""",
                (kind, current - timedelta(seconds=5), current - timedelta(seconds=5), current),
            )
        rows = timings(conn, 7, current)
        assert len(rows) == 4
        assert all(value[1:] == (1, 5000, 5000, 2) for value in rows)


async def check_oidc(admin_dsn, dsn):
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    unrelated = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = jwt.algorithms.RSAAlgorithm.to_jwk(signing.public_key(), as_dict=True)
    key["kid"] = "fixture-key"
    jobs = {}
    requests = 0
    app = web.Application()

    async def token(req):
        nonlocal requests
        requests += 1
        service = req.match_info["provider"]
        posted = await req.post()
        attributes, claims, outcome = jobs.pop(posted["code"])
        challenge = urlsafe_b64encode(sha256(posted["code_verifier"].encode()).digest()).decode().rstrip("=")
        assert challenge == attributes["code_challenge"][0]
        assert posted["redirect_uri"] == attributes["redirect_uri"][0] and posted["client_id"] == f"fixture-{service}"
        assert posted["grant_type"] == "authorization_code"
        if outcome == "provider_error":
            return web.json_response({"error": "fixture-secret-error"}, status=400)
        return web.json_response({"id_token": jwt.encode(
            claims, unrelated if outcome == "wrong_key" else signing, algorithm="RS256", headers={"kid": key["kid"]},
        )})

    async def jwks(req):
        return web.json_response({"keys": [key]})

    app.router.add_post("/token/{provider}", token)
    app.router.add_get("/keys", jwks)
    origin = "https://pet.example.test"
    secret = b"fixture-signing-secret-for-this-test-only"
    sub = "fixture-provider-subject"
    user_id = uuid4()
    settings = Settings.read({"PET_DATABASE_URL": dsn, "PET_MONTHLY_BUDGET_KRW": "50000", "PET_ORIGIN": origin})
    async with TestServer(app) as provider_server:
        providers = {}
        for name in ("google", "kakao"):
            host = str(provider_server.make_url("/")).rstrip("/")
            issuers = (f"{host}/issuer/{name}",)
            providers[name] = Provider(f"fixture-{name}", "fixture-secret", f"{host}/authorize/{name}",
                                       f"{host}/token/{name}", f"{host}/keys", issuers)
        config = AuthConfig(providers, secret)
        async with TestClient(TestServer(make_app(settings, auth_config=config))) as client:
            async def begin(service="google"):
                resp = await client.get(f"/api/auth/{service}/start", allow_redirects=False)
                assert resp.status == 302 and resp.headers["Cache-Control"] == "no-store"
                attrs = parse_qs(urlsplit(resp.headers["Location"]).query)
                assert attrs["scope"] == ["openid"] and attrs["code_challenge_method"] == ["S256"]
                assert "code_verifier" not in attrs and "client_secret" not in attrs
                cookie = resp.cookies[STATE_COOKIE]
                assert cookie["secure"] and cookie["httponly"] and cookie["max-age"] == "600"
                return attrs, cookie.value

            async def finish(flow, *, service="google", claims=None, state=None, outcome=None):
                attrs, cookie = flow
                code = uuid4().hex
                payload = {"iss": providers[service].issuers[0], "aud": [f"fixture-{service}"],
                           "exp": int(time.time()) + 60, "sub": sub, "nonce": attrs["nonce"][0]}
                jobs[code] = (attrs, {**payload, **(claims or {})}, outcome)
                return await client.get(f"/api/auth/{service}/callback",
                                        params={"code": code, "state": state or attrs["state"][0]},
                                        headers={"Cookie": f"{STATE_COOKIE}={cookie}"}, allow_redirects=False)

            def destination(resp, where):
                assert resp.status == 302 and resp.headers["Location"] == where
                assert resp.cookies[STATE_COOKIE]["max-age"] == "0"

            before = requests
            for service in ("kakao", "google"):
                pending = await finish(await begin(service), service=service)
                destination(pending, "/signup")
                cookie = pending.cookies[COOKIE]
                assert cookie["secure"] and cookie["httponly"] and cookie["samesite"] == "Lax"
                assert cookie["max-age"] == "1800"
                with psycopg.connect(admin_dsn) as conn:
                    stored = conn.execute("SELECT kind,sub_hash,expires_at=absolute_expires_at FROM pet.sessions "
                                          "WHERE token_hash=%s", (cookie_hash(cookie.value),)).fetchone()
                    assert stored == ("pending", subject_hash(secret, service, sub), True)
                unsigned = await client.get("/api/media/" + str(uuid4()), headers={"Cookie": f"{COOKIE}={cookie.value}"})
                assert unsigned.status == 401
            assert requests - before == 2

            before = requests
            state_bad = await finish(await begin(), state="wrong")
            destination(state_bad, "/?loginError=auth_state")
            flow = await begin()
            with patch("marong.pet.auth.time", return_value=time.time() + 601):
                old_state = await finish(flow)
            destination(old_state, "/?loginError=auth_state")
            assert requests == before
            for claims, outcome in (({}, "wrong_key"), ({}, "provider_error"), ({"iss": "https://wrong.test"}, None),
                                    ({"aud": "wrong"}, None), ({"nonce": "wrong"}, None), ({"exp": 1}, None)):
                rejected = await finish(await begin(), claims=claims, outcome=outcome)
                destination(rejected, "/?loginError=auth_provider")
                assert COOKIE not in rejected.cookies

            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute("INSERT INTO pet.members(id,member_no,provider,sub_hash,adult_self_declared_at) "
                             "VALUES (%s,'FIXTURE3','google',%s,now())", (user_id, subject_hash(secret, "google", sub)))
            logged_in = await finish(await begin())
            destination(logged_in, "/")
            raw = logged_in.cookies[COOKIE].value
            headers = {"Cookie": f"{COOKIE}={raw}", "Origin": origin}
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute("UPDATE pet.sessions SET created_at=now()-interval '29 days', "
                             "expires_at=now()+interval '1 day',absolute_expires_at=now()+interval '61 days' "
                             "WHERE token_hash=%s AND member_id=%s", (cookie_hash(raw), user_id))
            active = await client.get("/api/media/" + str(uuid4()), headers=headers)
            assert active.status == 404 and int(active.cookies[COOKIE]["max-age"]) > 29 * 86400
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute("UPDATE pet.sessions SET created_at=now()-interval '91 days', "
                             "absolute_expires_at=now()-interval '1 day' WHERE token_hash=%s", (cookie_hash(raw),))
            too_old = await client.get("/api/media/" + str(uuid4()), headers=headers)
            assert too_old.status == 401
            second = await finish(await begin())
            raw = second.cookies[COOKIE].value
            headers["Cookie"] = f"{COOKIE}={raw}"
            cross = await client.post("/api/auth/logout", headers={**headers, "Origin": "https://other.test"})
            assert cross.status == 403
            exit = await client.post("/api/auth/logout", headers=headers)
            assert exit.status == 204 and exit.cookies[COOKIE]["max-age"] == "0"
            assert (await client.post("/api/auth/logout", headers=headers)).status == 401
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute("UPDATE pet.members SET status='deleting',deleting_since=now(),sub_hash=NULL WHERE id=%s",
                             (user_id,))
            got = await finish(await begin())
            destination(got, "/signup")


if __name__ == "__main__":
    db = TestDB()
    try:
        admin, pet = fixtures(db)
        check_startup(pet)
        asyncio.run(check_jobs(admin, pet))
        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(check_http(admin, pet, Path(tmp)))
        asyncio.run(check_cost(admin, pet))
        asyncio.run(check_oidc(admin, pet))
    finally:
        db.close()
    print("TC-380–388: isolated database, startup, access, origin, timing, costs, and signed OIDC fixtures verified")
