"""Non-blocking Gemini turn accounting (SPEC-169–172)."""

import asyncio
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import logging
from time import monotonic

log = logging.getLogger("call_usage")
QUEUE_SIZE = 2000
FIELDS = ("text_in", "audio_in", "image_in", "tool_in", "cached_in", "text_out", "audio_out", "thoughts", "total_tokens")
_INSERT = """INSERT INTO call.live_usage (
    call_id,segment_id,segment_ref,seq,received_at,entrypoint,tuning,model,
    text_in,audio_in,image_in,tool_in,cached_in,text_out,audio_out,thoughts,total_tokens,
    searches,details_missing,values_fixed,price_id,usd
) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (segment_ref,seq) DO NOTHING"""
_COUNTER = """INSERT INTO call.live_counters (month,entrypoint,name,count) VALUES (%s,%s,%s,%s)
ON CONFLICT (month,entrypoint,name) DO UPDATE SET
count=call.live_counters.count+EXCLUDED.count,updated_at=now()"""


def decode(raw):
    """Keep only numeric provider fields. Undescribed or unrecognised tokens are costed as audio."""
    bad = False

    def count(value):
        nonlocal bad
        if type(value) is int and 0 <= value <= 2_147_483_647:
            return value
        bad = True
        return 0

    def split(total_key, details_key, allowed):
        nonlocal bad
        details = raw.get(details_key)
        total = count(raw.get(total_key, 0))
        if not isinstance(details, list) or not details:
            return (0, total, 0), True
        text = audio = image = 0
        seen = False
        for entry in details[:16]:
            if not isinstance(entry, dict):
                bad = True
                continue
            value = count(entry.get("tokenCount", 0))
            modality = entry.get("modality")
            seen = True
            if modality == "TEXT":
                text = min(2_147_483_647, text + value)
            elif modality in allowed:
                image = min(2_147_483_647, image + value)
            else:
                audio = min(2_147_483_647, audio + value)
        return (text, max(audio, total - text - image), image), not seen

    (text, audio, image), missing_in = split("promptTokenCount", "promptTokensDetails", ("IMAGE", "VIDEO"))
    (text_out, audio_out, _), missing_out = split("responseTokenCount", "responseTokensDetails", ())
    values = (text, audio, image, count(raw.get("toolUsePromptTokenCount", 0)),
              count(raw.get("cachedContentTokenCount", 0)), text_out, audio_out,
              count(raw.get("thoughtsTokenCount", 0)), count(raw.get("totalTokenCount", 0)))
    return values, missing_in or missing_out, bad


def dollars(values, price):
    text, audio, image, tool, _, text_out, audio_out, thoughts, _ = values
    value = ((text + tool) * price["text_in"] + audio * price["audio_in"] + image * price["image_in"]
             + (text_out + thoughts) * price["text_out"] + audio_out * price["audio_out"]) / Decimal(1_000_000)
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TurnUsage:
    seq: int
    received: datetime
    values: tuple
    searches: int
    missing: bool
    fixed: bool


class Ledger:
    """One price cache and bounded counter journal per call-server process."""

    def __init__(self, store):
        self.store = store
        self.prices = {}
        self.counts = Counter()
        self.lock = asyncio.Lock()
        self.tasks = set()

    async def mode(self):
        try:
            row = await asyncio.wait_for(self.store.one("SELECT value FROM call.settings WHERE key='usage_mode'"), 0.4)
        except Exception:
            return None
        mode = row["value"] if row else None
        return mode if mode in ("turn", "cumulative") else None

    def meter(self, call, segment, entrypoint, model, mode, searches, tuning=None, after_flush=None):
        meter = Meter(self, call, segment, entrypoint, model.rsplit("/", 1)[-1], mode, searches,
                      tuning=tuning, after_flush=after_flush)
        task = asyncio.create_task(meter.worker())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return meter

    async def close(self):
        if self.tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*self.tasks, return_exceptions=True), 25)
            except TimeoutError:
                log.warning("usage_writer_timeout n=%s", len(self.tasks))
        if self.counts:
            log.warning("usage_counters_unstored n=%s", sum(self.counts.values()))

    def count(self, name, entrypoint, at, value=1):
        month = at.astimezone(timezone.utc).date().replace(day=1)
        self.counts[(month, entrypoint, name)] += value

    async def _prices(self, model):
        now = monotonic()
        cached = self.prices.get(model)
        if cached and now < cached[0]:
            return cached[1]
        rows = await self.store.all("SELECT * FROM call.live_prices WHERE model=%s ORDER BY starts_at DESC", (model,))
        self.prices[model] = (now + 600, rows)
        return rows

    async def store_batch(self, meter, batch):
        async with self.lock:
            prices = await self._prices(meter.model) if batch else ()
            counters = dict(self.counts)
            if not batch and not counters:
                return
            async with self.store.pool.connection() as conn, conn.transaction():
                params = []
                if batch:
                    cur = await conn.execute("SELECT id FROM call.calls WHERE id=%s FOR KEY SHARE", (meter.call,))
                    call = (await cur.fetchone()) or {}
                    cur = await conn.execute("SELECT id FROM call.segments WHERE id=%s FOR KEY SHARE", (meter.segment,))
                    segment = (await cur.fetchone()) or {}
                    for turn in batch:
                        price = next((row for row in prices if row["starts_at"] <= turn.received), None)
                        params.append((call.get("id"), segment.get("id"), meter.segment, turn.seq, turn.received,
                                       meter.entrypoint, meter.tuning, meter.model, *turn.values, turn.searches,
                                       turn.missing, turn.fixed, price["id"] if price else None,
                                       dollars(turn.values, price) if price else None))
                if params or counters:
                    async with conn.cursor() as cursor:
                        if params:
                            await cursor.executemany(_INSERT, params)
                        if counters:
                            await cursor.executemany(_COUNTER, [(*key, value) for key, value in counters.items()])
            self.counts.subtract(counters)
            for key in counters:
                if not self.counts[key]:
                    self.counts.pop(key)


class Meter:
    def __init__(self, ledger, call, segment, entrypoint, model, mode, searches, *, tuning=None, after_flush=None):
        self.ledger, self.call, self.segment = ledger, call, segment
        self.entrypoint, self.model, self.mode, self.tuning = entrypoint, model, mode, tuning
        self.seq = 0
        self.last_searches = searches
        self.previous = (0,) * len(FIELDS)
        self.queue = deque(maxlen=QUEUE_SIZE)
        self.closed = asyncio.Event()
        self.missing = self.fixed = self.dropped = 0
        self.after_flush = after_flush

    def receive(self, metadata, searches, received):
        if not isinstance(metadata, dict):
            return
        values, missing, fixed = decode(metadata)
        if self.mode == "cumulative":
            previous, self.previous = self.previous, values
            if values[-1] >= previous[-1]:
                values = tuple(max(0, value - prior) for value, prior in zip(values, previous))
        self.seq += 1
        count = min(32767, max(0, searches - self.last_searches))
        self.last_searches = searches
        if len(self.queue) == self.queue.maxlen:
            self.ledger.count("usage_dropped", self.entrypoint, self.queue[0].received)
            self.dropped += 1
        turn = TurnUsage(self.seq, received, values, count, missing, fixed)
        self.queue.append(turn)
        self.missing += missing
        self.fixed += fixed
        return turn

    def close(self):
        self.closed.set()

    async def _flush(self):
        batch = tuple(self.queue)
        try:
            await self.ledger.store_batch(self, batch)
        except Exception:
            return False
        if batch:
            high = batch[-1].seq
            while self.queue and self.queue[0].seq <= high:
                self.queue.popleft()
            if self.after_flush and not self.closed.is_set():
                await self.after_flush()
        return True

    async def worker(self):
        while not self.closed.is_set():
            try:
                await asyncio.wait_for(self.closed.wait(), 2)
            except TimeoutError:
                await self._flush()
        if not await self._flush():
            for _ in range(3):
                await asyncio.sleep(5)
                if await self._flush():
                    break
            else:
                count = len(self.queue)
                for turn in self.queue:
                    self.ledger.count("usage_lost", self.entrypoint, turn.received)
                if count:
                    log.warning("usage_lost n=%s", count)
                self.queue.clear()
        if self.dropped or self.missing or self.fixed:
            log.info("usage_counts usage_dropped=%s details_missing=%s usage_bad=%s",
                     self.dropped, self.missing, self.fixed)
