"""Allowlisted, bounded call connection reports for SPEC-400 and SPEC-404."""

TIMING_POINTS = ("pageStart", "appStart", "statusReady", "micReady", "rtcReady", "liveOpen", "ready",
                 "audioReady", "firstAudioIn", "firstAudioPlayed")
TIMING_ENUMS = {"base": {"answer", "button", "page"}, "entry": {"ring", "button", "redial"}}
PLAYBACK_ENUMS = {
    "path": {"webrtc", "pcm"},
    "element": {"playing", "paused", "none"},
    "context": {"running", "suspended", "interrupted", "closed"},
    "playout": {"advancing", "stalled", "unsupported"},
    "device": {"speaker", "wired", "usb", "bluetooth", "earpiece", "unknown"},
    "ringer": {"normal", "vibrate", "silent", "unknown"},
}


def enum_values(data, fields):
    return {key: data[key] for key, choices in fields.items()
            if isinstance(data.get(key), str) and data[key] in choices}


def numbers(data, fields):
    return {key: data[key] for key, max_value in fields.items()
            if type(data.get(key)) is int and 0 <= data[key] <= max_value}


def timing_report(message):
    fields = message.get("client")
    if type(message.get("v")) is not int or message["v"] != 1 or not isinstance(fields, dict):
        return None
    report = enum_values(fields, TIMING_ENUMS)
    report.update(numbers(fields, {**dict.fromkeys(TIMING_POINTS, 600000), "cachedAssets": 20, "fetchedAssets": 20}))
    if type(fields.get("reloaded")) is bool:
        report["reloaded"] = fields["reloaded"]
    return report


def playback_report(message):
    if type(message.get("v")) is not int or message["v"] != 1:
        return None
    report = enum_values(message, PLAYBACK_ENUMS)
    report.update(numbers(message, {"silentMs": 600000, "voiceVolume": 100, "voiceVolumeMax": 100}))
    return report if "path" in report else None
