"""Where Marong's own messages go (D18) and sending them to the app (docs/app-chat.md SPEC-116~120,
docs/app-ring.md SPEC-129, SPEC-131).

A phone can take app notifications when the server has the FCM key and the phone has an FID, allowed notifications
and reported within 30 days. A friend with at least one gets proactive messages and reminders in the app only;
otherwise, or when every phone fails, they go to the Discord DM as before. A phone can ring when it can take
notifications and its app reported the 'Marong call' channel on.
"""
import asyncio
import logging

from . import fcm as fcm_messages

log = logging.getLogger("marong.app")

TALK, REMINDER = "marong_talk", "marong_reminder"   # the app's notification channels (SPEC-121)


def _why(device: dict) -> str | None:
    """Why this phone cannot take notifications (None: it can)."""
    if device["notifications"] != "granted":
        return "notifications_off"
    if not device["fresh"]:
        return "not_seen"
    if not device["fid"]:
        return "no_fid"
    return None


def _why_ring(device: dict) -> str | None:
    why = _why(device)
    if why:
        return why
    if device["ring_channel"] is None:
        return "old_app"
    if device["ring_channel"] != "enabled":
        return "ring_off"
    return None


def can_notify(device: dict) -> bool:
    return _why(device) is None


def can_ring(device: dict) -> bool:
    return _why_ring(device) is None


class AppPush:
    def __init__(self, store, sender=None, *, ring_enabled: bool = False):
        self.store = store
        self.fcm = sender                  # fcm.FCM, None until the key is on the server (SPEC-127)
        self.ring_enabled = ring_enabled   # MARONG_APP_RING=1 (docs/app-ring.md)

    @property
    def enabled(self) -> bool:
        return self.fcm is not None

    # ── what /me and the device report say (API-101, API-105) ──

    def delivery(self, devices: list[dict]) -> dict:
        if not self.enabled:
            return {"to": "discord", "reason": "fcm_off"}
        if not devices:
            return {"to": "discord", "reason": "no_device"}
        if any(can_notify(d) for d in devices):
            return {"to": "app", "reason": "app_on"}
        return {"to": "discord", "reason": _why(devices[0])}

    def ring_route(self, devices: list[dict]) -> dict:
        reported = [d for d in devices if d["full_screen"] is not None]
        ringing = [d for d in devices if can_ring(d)]
        shown = (ringing or reported or [None])[0]
        full = None if shown is None or shown["full_screen"] is None else shown["full_screen"] == "granted"
        if not self.ring_enabled:
            return {"to": "discord", "reason": "ring_disabled", "fullScreen": full}
        if not self.enabled:
            return {"to": "discord", "reason": "fcm_off", "fullScreen": full}
        if not devices:
            return {"to": "discord", "reason": "no_device", "fullScreen": full}
        if ringing:
            return {"to": "app", "reason": "app_on", "fullScreen": full}
        return {"to": "discord", "reason": _why_ring(devices[0]), "fullScreen": full}

    # ── sending ───────────────────────────────────────────────

    async def _send(self, device: dict, message: dict) -> str:
        result = await self.fcm.send(message)
        if result == "gone":
            try:
                await self.store.drop_fid(device["install_id"], device["fid"])
            except Exception as e:  # the next send sees the same answer and tries again
                log.warning("app_device_drop_failed %s", type(e).__name__)
        return result

    async def _fan_out(self, kind: str, devices: list[dict], make) -> int:
        if not devices:
            return 0
        results = await asyncio.gather(*(self._send(d, make(d["fid"])) for d in devices))
        ok = results.count("ok")
        log.info("fcm_send kind=%s devices=%d ok=%d gone=%d auth=%d failed=%d", kind, len(devices), ok,
                 results.count("gone"), results.count("auth"), results.count("failed"))
        return ok

    async def notify(self, friend_id: int, kind: str, text: str, *, channel: str = TALK, ttl_s: int = 3600,
                     open_path: str = "/chat/") -> tuple[int, int]:
        """Show `text` on the friend's phones: (phones FCM accepted, phones tried). (0, 0): no phone for the app."""
        if not self.enabled:
            return 0, 0
        devices = [d for d in await self.store.app_devices(friend_id) if can_notify(d)]
        ok = await self._fan_out(kind, devices, lambda fid: fcm_messages.notice(
            fid, kind, text, channel=channel, ttl_s=ttl_s, open_path=open_path))
        return ok, len(devices)

    async def ring_devices(self, friend_id: int) -> list[dict]:
        if not (self.enabled and self.ring_enabled):
            return []
        return [d for d in await self.store.app_devices(friend_id) if can_ring(d)]

    async def ring(self, devices: list[dict], ring_id: str, *, reason: str = "promise",
                   line: str | None = None) -> int:
        return await self._fan_out("ring", devices, lambda fid: fcm_messages.ring(fid, ring_id, reason, line))
