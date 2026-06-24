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


def _opt(name: str) -> int | None:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else None


def _optf(name: str) -> float | None:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else None


@dataclass(frozen=True)
class CongressConfig:
    """Configuration for the congressional-trade mirroring bot."""

    provider: str
    fmp_api_key: str
    fetch_pages: int
    window_days: int
    min_trades: int
    mirror_allocation: float
    max_positions: int | None
    max_position_weight: float | None
    allow_live: bool
    dry_run: bool

    # Email (SMTP)
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    email_from: str
    email_to: str

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.email_to)


def load_congress_config() -> CongressConfig:
    """Build a CongressConfig from the environment (secrets optional until used)."""
    return CongressConfig(
        provider=os.getenv("CONGRESS_PROVIDER", "auto"),
        fmp_api_key=os.getenv("FMP_API_KEY", ""),
        fetch_pages=int(os.getenv("CONGRESS_FETCH_PAGES", "40")),
        window_days=int(os.getenv("CONGRESS_WINDOW_DAYS", "365")),
        min_trades=int(os.getenv("CONGRESS_MIN_TRADES", "3")),
        mirror_allocation=float(os.getenv("MIRROR_ALLOCATION", "0.5")),
        max_positions=_opt("MIRROR_MAX_POSITIONS"),
        max_position_weight=_optf("MIRROR_MAX_POSITION_PCT"),
        allow_live=os.getenv("MIRROR_ALLOW_LIVE", "false").lower() in ("1", "true", "yes"),
        dry_run=os.getenv("MIRROR_DRY_RUN", "false").lower() in ("1", "true", "yes"),
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_pass=os.getenv("SMTP_PASS", ""),
        email_from=os.getenv("EMAIL_FROM", os.getenv("SMTP_USER", "")),
        email_to=os.getenv("EMAIL_TO", ""),
    )


# Default tradable universe: liquid US large-caps. Override with AI_UNIVERSE.
DEFAULT_UNIVERSE = (
    "AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,AVGO,JPM,V,UNH,XOM,JNJ,WMT,PG,MA,"
    "HD,COST,ABBV,CVX,KO,PEP,BAC,LLY,AMD,NFLX,DIS,INTC,CSCO,CRM,ORCL,QCOM"
)


@dataclass(frozen=True)
class AIConfig:
    """Configuration for the AI-driven trading strategy."""

    anthropic_api_key: str
    model: str
    max_tokens: int
    universe: list[str]
    use_congress: bool
    allocation: float
    max_positions: int
    max_position_weight: float
    allow_live: bool
    dry_run: bool

    @property
    def ai_configured(self) -> bool:
        return bool(self.anthropic_api_key)


# Default diversified basket: ~32 liquid stocks across sectors + 8 cryptos.
DEFAULT_BASKET = (
    # tech / semis
    "AAPL,MSFT,NVDA,AMZN,GOOGL,META,AVGO,AMD,ORCL,CRM,ADBE,QCOM,CSCO,"
    # financials
    "JPM,V,MA,BAC,GS,"
    # healthcare
    "UNH,JNJ,LLY,ABBV,MRK,"
    # consumer
    "WMT,PG,KO,PEP,COST,HD,MCD,"
    # energy
    "XOM,CVX,"
    # crypto
    "BTC/USD,ETH/USD,SOL/USD,UNI/USD,LINK/USD,DOGE/USD,LTC/USD,BCH/USD"
)


@dataclass(frozen=True)
class BasketConfig:
    """Configuration for the rules-based diversified basket strategy."""

    universe: list[str]
    size: int
    allocation: float
    allow_live: bool
    dry_run: bool


def load_basket_config() -> BasketConfig:
    raw = os.getenv("BASKET_UNIVERSE", "") or DEFAULT_BASKET
    # Keep crypto slashes; only upper/strip. (Can't reuse _split_symbols — it's
    # fine here since symbols have no lowercase, but do it explicitly.)
    universe = [s.strip().upper() for s in raw.split(",") if s.strip()]
    return BasketConfig(
        universe=universe,
        size=int(os.getenv("BASKET_SIZE", "40")),
        allocation=float(os.getenv("BASKET_ALLOCATION", "1.8")),
        allow_live=os.getenv("BASKET_ALLOW_LIVE", "false").lower() in ("1", "true", "yes"),
        dry_run=os.getenv("BASKET_DRY_RUN", "false").lower() in ("1", "true", "yes"),
    )


def load_ai_config() -> AIConfig:
    """Build an AIConfig from the environment (Anthropic key optional until used)."""
    return AIConfig(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        model=os.getenv("AI_MODEL", "claude-sonnet-4-6"),
        max_tokens=int(os.getenv("AI_MAX_TOKENS", "2000")),
        universe=_split_symbols(os.getenv("AI_UNIVERSE", "") or DEFAULT_UNIVERSE),
        use_congress=os.getenv("AI_USE_CONGRESS", "true").lower() in ("1", "true", "yes"),
        allocation=float(os.getenv("AI_ALLOCATION", "0.5")),
        max_positions=int(os.getenv("AI_MAX_POSITIONS", "8")),
        max_position_weight=float(os.getenv("AI_MAX_POSITION_PCT", "0.25")),
        allow_live=os.getenv("AI_ALLOW_LIVE", "false").lower() in ("1", "true", "yes"),
        dry_run=os.getenv("AI_DRY_RUN", "false").lower() in ("1", "true", "yes"),
    )
