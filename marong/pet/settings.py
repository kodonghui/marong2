"""Startup configuration for the separate pet service (SPEC-367, SPEC-368)."""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg.conninfo import conninfo_to_dict

PRICE_FILE = Path(__file__).with_name("prices.json")
TEXT_MODELS = frozenset({"claude-haiku-5-5", "claude-sonnet-5-5"})
IMAGE_MODELS = frozenset({"gpt-image-2.5-flare"})
DEFAULTS = {
    "PET_VISION_MODEL": ("claude-sonnet-5-5", TEXT_MODELS),
    "PET_IMAGE_MODEL": ("gpt-image-2.5-flare", IMAGE_MODELS),
    "PET_IMAGE_FALLBACK_MODEL": ("", IMAGE_MODELS | {""}),
    "PET_CHAT_MODEL": ("claude-haiku-5-5", TEXT_MODELS),
    "PET_DIARY_MODEL": ("claude-haiku-5-5", TEXT_MODELS),
}
PRICE_KINDS = {
    "text": {"input", "output", "cache_read", "cache_write"},
    "image": {"text_input", "image_input", "image_output"},
    "minute": {"minute"},
}


class SettingsError(ValueError):
    """Only fixed messages may be reported by the command line."""


@dataclass(frozen=True)
class Price:
    rates: dict[str, Decimal]
    source: str


@dataclass(frozen=True)
class PriceBook:
    version: str
    prices: dict[str, Price]

    @classmethod
    def read(cls, source: Path):
        try:
            data = json.loads(source.read_text(encoding="utf-8"), parse_float=Decimal)
            version = data["version"]
            if not isinstance(version, str) or not version:
                raise ValueError
            prices = {}
            for name, row in data["models"].items():
                rates = row["usd"]
                kind = row["kind"]
                if not isinstance(row["source"], str) or not row["source"] or set(rates) != PRICE_KINDS[kind]:
                    raise ValueError
                if any(type(value) not in (int, Decimal) or not Decimal(value).is_finite() or value < 0
                       for value in rates.values()):
                    raise ValueError
                prices[name] = Price({key: Decimal(value) for key, value in rates.items()}, row["source"])
        except (OSError, UnicodeError, KeyError, TypeError, ValueError, AttributeError):
            raise SettingsError("price book is unavailable or invalid") from None
        return cls(version, prices)


def _positive(env, key, default=None):
    raw = env.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise SettingsError(f"{key} is missing or invalid") from None
    if value <= 0:
        raise SettingsError(f"{key} must be positive")
    return value


def _origin(raw):
    try:
        parsed = urlsplit(raw)
        local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        if ((parsed.scheme != "https" and not (parsed.scheme == "http" and local))
                or not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or (parsed.port is not None and parsed.port < 1)):
            raise ValueError
    except ValueError:
        raise SettingsError("PET_ORIGIN is invalid") from None
    return raw.rstrip("/")


@dataclass(frozen=True)
class Settings:
    db: str = field(repr=False)
    port: int
    origin: str
    media_dir: Path
    signup: str
    budget_krw: int
    krw_per_usd: int
    vision_model: str
    image_model: str
    image_fallback_model: str | None
    chat_model: str
    diary_model: str
    prices: PriceBook

    @classmethod
    def read(cls, env, *, price_file=PRICE_FILE):
        budget = _positive(env, "PET_MONTHLY_BUDGET_KRW")
        rate = _positive(env, "PET_KRW_PER_USD", "1337")
        prices = PriceBook.read(price_file)
        models = {}
        for key, (default, allowed) in DEFAULTS.items():
            model = env.get(key, default).strip()
            if model not in allowed:
                raise SettingsError(f"{key} is outside the allowed list")
            if model and model not in prices.prices:
                raise SettingsError(f"{key} has no price")
            models[key] = model or None
        signup = env.get("PET_SIGNUP", "invite")
        if signup not in ("invite", "open"):
            raise SettingsError("PET_SIGNUP is invalid")
        db = env.get("PET_DATABASE_URL", "")
        try:
            parsed = conninfo_to_dict(db)
        except psycopg.ProgrammingError:
            raise SettingsError("PET_DATABASE_URL is invalid") from None
        if parsed.get("dbname") != "marong_pet" or parsed.get("user") != "marong_pet":
            raise SettingsError("PET_DATABASE_URL must select the separate pet database and role")
        port = _positive(env, "PET_PORT", "8797")
        if not 1024 <= port <= 65535:
            raise SettingsError("PET_PORT is outside the allowed range")
        origin = _origin(env.get("PET_ORIGIN", f"http://127.0.0.1:{port}"))
        media_dir = Path(env.get("PET_MEDIA_DIR", "/var/lib/marong-pet/media"))
        return cls(db, port, origin, media_dir, signup, budget, rate, models["PET_VISION_MODEL"], models["PET_IMAGE_MODEL"],
                   models["PET_IMAGE_FALLBACK_MODEL"], models["PET_CHAT_MODEL"], models["PET_DIARY_MODEL"], prices)
