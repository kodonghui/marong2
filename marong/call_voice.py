"""Shared phone voice configuration for the app and the Live relay."""

import os
import re


VOICE_NAME = re.compile(r"[A-Za-z]{2,24}")


def configured_voices(env=os.environ):
    value = env.get("MARONG_CALL_VOICES", "Sulafat")
    choices = tuple(dict.fromkeys(v.strip() for v in value.split(",") if VOICE_NAME.fullmatch(v.strip())))
    return choices or ("Sulafat",)


def chosen_voice(selected=None, choices=None):
    choices = choices or configured_voices()
    if selected in choices:
        return selected
    return "Sulafat" if "Sulafat" in choices else choices[0]


def call_capacity(env=os.environ):
    value = env.get("MARONG_CALL_MAX", "3").strip()
    if not value.isdecimal() or int(value) < 1:
        raise ValueError("MARONG_CALL_MAX must be a positive integer")
    return int(value)
