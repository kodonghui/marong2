"""Poll for newly published app versions and send the SPEC-430 update signal."""
import asyncio
import logging
import time

import psycopg

from .app_release import version_parts
from .fcm import app_update

log = logging.getLogger(__name__)
POLL_SECONDS = 30
SWEEP_SECONDS = 600
BATCH = 100
SEND_CONCURRENCY = 4
FAILURE_STATUS = {"gone": 410, "auth": 401, "failed": 500}


class AppUpdatePush:
    def __init__(self, store, releases, fcm, *, clock=time.monotonic, sleep=asyncio.sleep):
        self.store = store
        self.releases = releases
        self.fcm = fcm
        self.clock = clock
        self.sleep = sleep
        self.code = None
        self.next_sweep = 0.0
        self.pending = False
        self.sends = asyncio.Semaphore(SEND_CONCURRENCY)

    async def run(self) -> None:
        log.info("app_update push started")
        while True:
            start = self.clock()
            await self.poll()
            await self.sleep(max(0, POLL_SECONDS - (self.clock() - start)))

    async def poll(self) -> None:
        release = await asyncio.to_thread(self.releases.latest)
        if release is None:
            self.code = None
            self.pending = False
            return
        if release.code == self.code and not self.pending and self.clock() < self.next_sweep:
            return
        self.code = release.code
        version = version_parts(release.name)
        try:
            targets = await self.store.app_update_targets(release.code, version, BATCH)
        except (psycopg.Error, TimeoutError):
            log.warning("app_update record failed kind=pushed")
            self.pending = True
            return
        left = targets[0]["total"] - len(targets) if targets else 0
        self.pending = left > 0
        outcomes = await asyncio.gather(*(self._send(target, release.code, version) for target in targets))
        self.next_sweep = self.clock() + SWEEP_SECONDS
        log.info("app_update push code=%d sent=%d failed=%d left=%d", release.code, outcomes.count("ok"),
                 sum(outcome in FAILURE_STATUS for outcome in outcomes), left)

    async def _send(self, target: dict, code: int, version: tuple[int, ...]) -> str | None:
        async with self.sends:
            try:
                if not await self.store.app_update_claim(target, code, version):
                    return None
            except (psycopg.Error, TimeoutError):
                log.warning("app_update record failed kind=pushed")
                return None
            result = await self.fcm.send(app_update(target["fid"], code))
            if result != "ok":
                try:
                    await self.store.app_update_push_failed(target, code, FAILURE_STATUS[result])
                except (psycopg.Error, TimeoutError):
                    log.warning("app_update record failed kind=push_failed")
            if result == "gone":
                try:
                    await self.store.drop_fid(target["install_id"], target["fid"])
                except (psycopg.Error, TimeoutError):
                    log.warning("app_update drop failed")
            return result
