"""Pet logs include fixed event labels and account hashes (SPEC-366)."""

from hashlib import sha256
import logging

logger = logging.getLogger("pet")


def member_ref(member_no: str) -> str:
    return sha256(member_no.strip().encode("utf-8")).hexdigest()[:8]

