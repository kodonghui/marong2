"""Offline usage and price ledger checks with a disposable database (TC-173)."""

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter_ns
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from pg import ROOT, TestDB

from call_memory import MemoryStore, Principal
from call_usage import QUEUE_SIZE, Ledger, Meter, decode
from call_tuning import parse_tuning
from quiet_mic import QuietMic
from cost_admin import cli, run as run_admin

MODEL = "fixture-live"
AT = datetime(2026, 11, 17, tzinfo=timezone.utc)


def metadata(tokens):
    return {"promptTokenCount": tokens, "responseTokenCount": 0, "totalTokenCount": tokens}


async def scenario(db, store):
    assert await store.live_usage.mode() is None
    db.admin("INSERT INTO call.settings(key,value) VALUES ('usage_mode', to_jsonb(%s::text))", ("cumulative",))
    assert await store.live_usage.mode() == "cumulative"
    friend, = db.admin("INSERT INTO marong.friends(name) VALUES ('fixture-usage') RETURNING id")[0]
    caller, = db.admin("INSERT INTO call.callers(friend_id) VALUES (%s) RETURNING id", (friend,))[0]
    principal = Principal(caller, friend, "fixture-usage")
    client = str(uuid4())
    call, _ = await store.start_call(principal, client, "fixture", "fixture")
    segment = await store.start_segment(principal, call, client, MODEL)
    for when, rate in ((AT, 3), (AT + timedelta(seconds=1), 6)):
        db.admin(
            """INSERT INTO call.live_prices(model,starts_at,text_in,audio_in,image_in,text_out,audio_out,checked_on,source)
            VALUES (%s,%s,1,%s,1,1,1,'2026-11-17','fixture')""", (MODEL, when, rate),
        )
    ledger = store.live_usage
    meter = Meter(ledger, call, segment, "discord", MODEL, "cumulative", 2)
    meter.receive(metadata(10_000), 3, AT)
    meter.receive(metadata(11_000), 3, AT + timedelta(seconds=1))
    meter.receive(None, 4, AT)
    saved = tuple(meter.queue)
    assert [row.values[1] for row in saved] == [10_000, 1000]
    assert [row.searches for row in saved] == [1, 0]
    write = ledger.store_batch

    async def unavailable(*_):
        raise OSError("fixture database interruption")

    ledger.store_batch = unavailable
    assert not await meter._flush() and tuple(meter.queue) == saved
    ledger.store_batch = write
    assert await meter._flush() and not meter.queue
    await ledger.store_batch(meter, saved)
    assert db.admin("""SELECT seq,audio_in,searches,details_missing,usd FROM call.live_usage
                     WHERE segment_ref=%s ORDER BY seq""", (segment,)) == [
        (1, 10_000, 1, True, Decimal("0.030000")), (2, 1000, 0, True, Decimal("0.006000")),
    ]
    parsed, missing, fixed = decode({
        "promptTokenCount": 13,
        "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 5}, None,
                                {"modality": "IMAGE", "tokenCount": 1}],
        "responseTokenCount": 8,
        "responseTokensDetails": [{"modality": "TEXT", "tokenCount": 4},
                                   {"modality": "AUDIO", "tokenCount": -1}],
        "thoughtsTokenCount": "bad",
    })
    assert parsed == (5, 7, 1, 0, 0, 4, 4, 0, 0) and not missing and fixed
    timings = []
    for _ in range(QUEUE_SIZE + 3):
        begin = perf_counter_ns()
        meter.receive(metadata(12_000), 4, AT)
        timings.append(perf_counter_ns() - begin)
    p99_ms = sorted(timings)[int(len(timings) * 0.99)] / 1e6
    assert p99_ms < 1 and len(meter.queue) == QUEUE_SIZE and meter.dropped == 3
    await ledger.store_batch(meter, ())
    assert db.admin("SELECT name,count FROM call.live_counters WHERE entrypoint='discord'") == [
        ("usage_dropped", 3),
    ]
    await store.finish(principal, call, True)
    print(f"TC-173 usage: price boundary, numeric normalization, retry, idempotency, overflow, P99 {p99_ms:.3f}ms")


async def test(db):
    store = MemoryStore(db.admin_url.replace("postgres:@", "marong_call@", 1))
    await store.open()
    try:
        await scenario(db, store)
        await monthly(db, store)
    finally:
        await store.close()


async def monthly(db, store):
    at = datetime(2040, 12, 9, tzinfo=timezone.utc)
    friend, = db.admin("INSERT INTO marong.friends(name) VALUES ('fixture-month') RETURNING id")[0]
    caller, = db.admin("INSERT INTO call.callers(friend_id) VALUES (%s) RETURNING id", (friend,))[0]
    principal = Principal(caller, friend, "fixture-month")
    client = str(uuid4())
    call, _ = await store.start_call(principal, client, "fixture", "fixture")
    measured = await store.start_segment(principal, call, client, MODEL)
    estimated = await store.start_segment(principal, call, client, MODEL)
    await store.finish(principal, call, True)
    db.admin("UPDATE call.segments SET opened_at=%s,closed_at=%s WHERE call_id=%s",
             (at - timedelta(minutes=10), at, call))
    price_id, = db.admin(
        """INSERT INTO call.live_prices(model,starts_at,text_in,audio_in,image_in,text_out,audio_out,
          search_per_1000,search_free_per_month,checked_on,source)
        VALUES (%s,%s,1,3,1,2,1,14,5000,'2040-12-09','fixture') RETURNING id""", (MODEL, at),
    )[0]
    db.admin(
        """INSERT INTO call.live_usage(call_id,segment_id,segment_ref,seq,received_at,entrypoint,model,
             searches,price_id,usd) VALUES (%s,%s,%s,1,%s,'web',%s,5200,%s,12.3)""",
        (call, measured, measured, at, MODEL, price_id),
    )
    db.admin(
        """INSERT INTO call.ai_runs(kind,call_id,trace_id,model,prompt_version,sent_at,input_tokens,output_tokens,
            thoughts_tokens,outcome) VALUES ('organize',%s,'fixture-cost',%s,'fixture',%s,100000,25000,25000,'ok')""",
        (call, MODEL, at),
    )
    report = await store.monthly_cost.report(at, fresh=True)
    assert tuple(report[key] for key in ("live", "estimated", "search_usd", "organize", "total")) == (
        Decimal("12.30"), Decimal("0.50"), Decimal("2.80"), Decimal("0.20"), Decimal("15.80"),
    ), report
    for budget, expected in ((20, "ok"), (18, "warn"), (15, "exhausted"), (13, "hard_stop"), (20, "ok")):
        db.admin("""INSERT INTO call.settings(key,value) VALUES ('monthly_budget_usd',to_jsonb(%s::int))
                  ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""", (budget,))
        assert await store.monthly_cost.status("web", at=at) == expected
    assert db.admin("SELECT kind FROM call.budget_events WHERE month='2040-12-01' ORDER BY kind") == [
        ("exhausted",), ("hard_stop",), ("warn",),
    ]
    parser = cli()

    async def admin(*words):
        return await run_admin(store, parser.parse_args(words), at)

    assert (await admin("call-cost", "2040-12"))["cost_usd"]["total"] == Decimal("15.80")
    switch = await admin("call-cost", "--switch")
    assert switch["days"] == 14
    assert switch["groups"][0]["grouping"] == 3
    assert switch["groups"][0]["minutes"] == 20
    assert switch["projected_month_minutes"] == Decimal("44.29")
    switch = await run_admin(store, parser.parse_args(["call-cost", "--switch"]), at+timedelta(seconds=1))
    assert switch["cost_usd"]["total"] == Decimal("15.80")
    assert switch["usd_per_minute"] == Decimal(".79")
    assert switch["projected_month_usd"] == Decimal("34.985714")
    assert await admin("call-tuning", "add", "fixture-t2", "max_output_tokens=512") == {"added": "fixture-t2"}
    assert await admin("call-tuning", "use", "fixture-t2") == {"active": "fixture-t2"}
    assert (await store.tuning())["max_output_tokens"] == 512
    assert (await admin("call-credit-checked", "2040-12-09"))["credit_checked_on"] == at.date()
    assert (await admin("call-budget", "123.45"))["monthly_budget_usd"] == 123.45
    assert await admin("call-price", "add", MODEL, "2040-12-08T00:00:00Z", "text_in=1", "audio_in=3",
                       "image_in=1", "text_out=1", "audio_out=3", "checked_on=2040-12-09", "source=fixture") == {
        "added": True, "historical_price_is_unchanged": True,
    }
    db.admin("UPDATE call.calls SET started_at=%s,ended_at=%s WHERE id=%s",
             (at - timedelta(minutes=10), at, call))
    check_sheet(db, at, call)
    await store.delete_call(principal, call)
    assert db.admin("SELECT kind,call_id,segment_id,usd FROM call.live_usage WHERE segment_ref=%s", (estimated,)) == [
        ("estimate", None, None, Decimal("0.500000")),
    ]
    assert await store.monthly_cost.report(at, fresh=True) == report
    january = at.replace(year=2041, month=1)
    assert (await store.monthly_cost.report(january))["total"] == 0
    print("TC-174 calculation: UTC month, $15.80, estimates survive erasure, threshold events, immediate budget edit")


def check_sheet(db, call_time, call):
    import psycopg
    from psycopg.rows import dict_row
    from tools.report import call_sessions

    dsn = db.app_url
    start = call_time - timedelta(days=1)
    until = call_time + timedelta(days=1)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        exported = call_sessions(conn, start, until, timezone.utc)
        row = next(row for row in exported["rows"] if row[0] == call)
        assert row[11:] == [0, 0, 12.8, "추정", ""]


def check_quiet():
    gate = QuietMic(0.018)
    soft = b"\0" * 640
    loud = b"\0\x10" * 320
    assert list(gate.feed(soft * 20 + loud)) == []
    assert list(gate.feed(loud)) == [soft * 13 + loud * 2]
    assert list(gate.feed(soft * 49)) == [soft] * 49
    assert list(gate.feed(soft[:200])) == []
    assert list(gate.feed(soft[200:])) == [soft, None]
    assert list(gate.feed(soft * 5)) == []
    assert gate.counts() == (1300, 240)
    assert gate.counts() == (0, 0)


async def check_budget_end():
    from test_hangup import Store, audio, call, check_setup, until
    import live_session
    server = await check_setup()
    tuning = parse_tuning("fixture-run", ["vad_silence_ms=1000", "compression_trigger=5120", "compression_target=2048"])
    setup = server.setup(tuning=tuning)["setup"]
    assert setup["contextWindowCompression"] == {"triggerTokens": 5120, "slidingWindow": {"targetTokens": 2048}}
    assert setup["realtimeInputConfig"]["automaticActivityDetection"]["silenceDurationMs"] == 1000
    assert setup["generationConfig"]["speechConfig"] == server.setup()["setup"]["generationConfig"]["speechConfig"]
    for tampered in ("voice=changed", "vad_silence_ms=2500", "quiet_rms=nan"):
        try:
            parse_tuning("fixture-run", [tampered])
        except ValueError:
            pass
        else:
            raise AssertionError(tampered)
    with patch.object(live_session, "HANGUP_MAX_S", .9):
        store = Store()
        async def no_ring(*_):
            return None
        store.claim_ring = no_ring
        session, upstream, browser, _, task = await call(server, store=store)
        session.begin_budget_goodbye()
        browser.mic()
        browser.say({"type": "text", "text": "fixture microphone blocked"})
        await until(lambda: any("clientContent" in item for _, item in upstream.sent))
        upstream.queue.put_nowait(audio("시험 인사", complete=True))
        await until(lambda: browser.hangups())
        await asyncio.wait_for(task, 1.5)
        assert browser.kinds().index("bytes") < browser.kinds().index("hangup")
        assert store.finished == [(True, "budget_hard_stop")]
        assert not any("realtimeInput" in item for _, item in upstream.sent)
        lines = [item["clientContent"]["turns"][0]["parts"][0]["text"] for _, item in upstream.sent if "clientContent" in item]
        assert lines == [live_session.BUDGET_GOODBYE]
    print("TC-175 fake audio cutoff and goodbye deadline; TC-176 tuning validation and PCM gate")


async def check_admission():
    from aiohttp.test_utils import TestClient, TestServer
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from test_hangup import check_setup
    from discord_relay import DiscordRelay
    server = await check_setup()
    identity = AsyncMock(return_value={"owner": "fixture", "email_hash": None})
    with patch.object(server, "identity", identity), patch.object(server, "budget_status", AsyncMock(return_value="exhausted")):
        async with TestClient(TestServer(server.app)) as client:
            async with client.get("/api/me") as result:
                state = await result.json()
                assert state["canCall"] is False and state["blockedReason"] == "budget"
            async with client.ws_connect("/live", headers={"Origin": str(client.make_url("/")).rstrip("/")}) as ws:
                assert await ws.receive_json() == {"type": "budget_exhausted"}
    client_id = str(uuid4())
    resume = AsyncMock(return_value=False)
    relay = DiscordRelay(SimpleNamespace(can_resume_call=resume), None, ())
    from aiohttp import web
    with patch("discord_relay.budget_status", AsyncMock(return_value="exhausted")):
        try:
            await relay.check_budget(None, client_id)
        except web.HTTPTooManyRequests as problem:
            assert problem.content_type == "application/problem+json" and "budget_exhausted" in problem.text
        else:
            raise AssertionError("Discord accepted a new call at the limit")
        resume.return_value = True
        await relay.check_budget(None, client_id)
    print("TC-174 fake web WebSocket cutoff, Discord 429 and Discord resumption")


async def check_handoff():
    from test_hangup import Browser, HTTP, Store, Upstream, check_setup, until
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import live_session
    server = await check_setup()
    tuning = parse_tuning("fixture-handoff", ["text_handoff=on", "max_output_tokens=768"])

    class Warm(Upstream):
        def __init__(self, pending):
            super().__init__()
            self.pending = pending
            self.closed = False

        async def receive(self, timeout=None):
            await self.pending.wait()
            return await super().receive(timeout)

        async def __aexit__(self, *_):
            self.closed = True

    async def try_swap(speech):
        gate = asyncio.Event()
        old = Upstream()
        candidate = Warm(gate)
        connections = iter((old, candidate))
        store = Store()
        store.live_usage = Ledger(store)
        store.live_usage.mode = AsyncMock(return_value="turn")
        store.live_usage.store_batch = AsyncMock()
        store.monthly_cost = SimpleNamespace(status=AsyncMock(return_value="ok"))
        store.tuning = AsyncMock(return_value=tuning)
        store.seed = AsyncMock(return_value='{"current_call":[]}')
        store.start_segment = AsyncMock(side_effect=("segment-1", "segment-2"))
        store.claim_ring = AsyncMock(return_value=None)
        browser = Browser()
        session = live_session.LiveSession(browser, "fixture", store, SimpleNamespace(revision=0), server.setup,
            AsyncMock(return_value={}), {}, {}, "fixture", MODEL, "fixture", str(uuid4()))
        with patch.object(live_session, "ClientSession", lambda **_: HTTP(next(connections))), patch.object(
            live_session, "SEARCH_CUT_SLACK_S", .1
        ):
            task = asyncio.create_task(session.run())
            try:
                await until(lambda: browser.kinds().count("ready") == 1)
                await old.queue.put({"serverContent": {"turnComplete": True}, "usageMetadata": metadata(8000)})
                await until(lambda: bool(candidate.sent))
                setup = candidate.sent[0][1]["setup"]
                assert "handle" not in setup["sessionResumption"]
                assert setup["systemInstruction"]["parts"][-1]["text"] == "이어지는 통화"
                assert store.start_segment.await_count == 1
                browser.mic()
                await until(lambda: any("realtimeInput" in item for _, item in old.sent))
                if speech:
                    await old.queue.put({"serverContent": {"speechState": "SPEECH"}})
                    await until(lambda: session.activity_at > (session.turn_done_at or 0))
                gate.set()
                if speech:
                    await until(lambda: candidate.closed)
                    assert store.start_segment.await_count == 1 and browser.kinds().count("ready") == 1
                    browser.mic()
                    await until(lambda: len(old.microphone_after(0)) == 2)
                else:
                    await until(lambda: browser.kinds().count("ready") == 2)
                    await until(lambda: bool(candidate.microphone_after(0)))
                    assert store.start_segment.await_args.kwargs["handoff_from"] == "segment-1"
                    assert "reconnecting" not in browser.kinds()
            finally:
                browser.say({"type": "stop"})
                await asyncio.wait_for(task, 4)
                await store.live_usage.close()

    await try_swap(False)
    await try_swap(True)
    print("TC-176 fake handoff kept former connection through setup, preserved speech, and sent the lead-in")


def main():
    db = TestDB()
    try:
        call = ROOT / "marong/call"
        bot = ROOT / "marong/migrations"
        db.admin((call / "schema.sql").read_text(encoding="utf-8"), None)
        paths = (*sorted((call / "migrations").glob("00[2-4]*.sql")), *sorted(bot.glob("01[0-3]*.sql")),
                 *sorted((call / "migrations").glob("00[5-7]*.sql")))
        for path in paths:
            db.admin(path.read_text(encoding="utf-8"), None)
        asyncio.run(test(db))
    finally:
        db.close()
    check_quiet()
    asyncio.run(check_budget_end())
    asyncio.run(check_admission())
    asyncio.run(check_handoff())


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
