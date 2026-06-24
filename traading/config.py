"""Centralized configuration, loaded from environment variables / .env file.

Secrets are NEVER hardcoded here — they come from the environment so they can
stay out of version control. Copy .env.example to .env and fill it in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Load variables from a local .env file if present (no-op in production envs
# where the variables are already set).
load_dotenv()


def _get(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def _split_symbols(raw: str) -> list[str]:
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the bot."""

    api_key_id: str
    api_secret_key: str
    base_url: str

    symbols: list[str]
    fast_window: int
    slow_window: int
    timeframe: str
    position_size: float
    poll_interval: int

    @property
    def is_paper(self) -> bool:
        return "paper" in self.base_url

    def __post_init__(self) -> None:
        if self.fast_window >= self.slow_window:
            raise ValueError(
                f"FAST_WINDOW ({self.fast_window}) must be < SLOW_WINDOW "
                f"({self.slow_window})."
            )
        if not 0.0 < self.position_size <= 1.0:
            raise ValueError(
                f"POSITION_SIZE ({self.position_size}) must be in (0.0, 1.0]."
            )
        if not self.symbols:
            raise ValueError("SYMBOLS must contain at least one symbol.")


def load_config() -> Config:
    """Build a Config from the current environment."""
    return Config(
        api_key_id=_get("ALPACA_API_KEY_ID"),
        api_secret_key=_get("ALPACA_API_SECRET_KEY"),
        base_url=_get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        symbols=_split_symbols(_get("SYMBOLS", "AAPL,MSFT,SPY")),
        fast_window=int(_get("FAST_WINDOW", "10")),
        slow_window=int(_get("SLOW_WINDOW", "30")),
        timeframe=_get("TIMEFRAME", "1Day"),
        position_size=float(_get("POSITION_SIZE", "0.1")),
        poll_interval=int(_get("POLL_INTERVAL", "60")),
    )
