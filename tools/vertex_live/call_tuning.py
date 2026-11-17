"""Immutable call settings for one provider segment (SPEC-177)."""

import re
from decimal import Decimal, InvalidOperation

BASE = "base-20261116"
DEFAULTS = {
    "compression_trigger": 8192, "compression_target": 4096, "vad_silence_ms": 700,
    "vad_prefix_ms": 100, "max_output_tokens": 1024, "seed_call_memories": 30, "web_quiet_mic": False,
    "quiet_rms": Decimal("0.018"), "text_handoff": False, "handoff_tokens": 7000, "handoff_chars": 4000,
}
RANGES = {
    "compression_trigger": (2048, 32768), "compression_target": (1024, 16384),
    "vad_silence_ms": (300, 2000), "vad_prefix_ms": (0, 500), "max_output_tokens": (256, 2048),
    "seed_call_memories": (0, 30), "quiet_rms": (Decimal("0.005"), Decimal("0.05")),
    "handoff_tokens": (3000, 30000), "handoff_chars": (1000, 8000),
}


def parse_tuning(name, options):
    if not re.fullmatch(r"[a-z0-9-]{2,40}", name):
        raise ValueError("invalid tuning name")
    fields = dict(DEFAULTS)
    seen = set()
    for text in options:
        key, sep, value = text.partition("=")
        if not sep or key not in fields or key in seen:
            raise ValueError("invalid tuning field")
        seen.add(key)
        default = DEFAULTS[key]
        if type(default) is bool:
            if value not in ("on", "off"):
                raise ValueError("invalid flag")
            fields[key] = value == "on"
        else:
            try:
                number = type(default)(value)
                low, high = RANGES[key]
                if not low <= number <= high:
                    raise ValueError("tuning value outside range")
                fields[key] = number
            except (ValueError, InvalidOperation):
                raise ValueError("invalid tuning value") from None
    if fields["compression_target"] * 2 > fields["compression_trigger"]:
        raise ValueError("compression target exceeds half the trigger")
    return {"name": name, **fields}
