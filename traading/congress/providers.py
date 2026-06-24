"""Data providers for congressional trade disclosures.

`DataProvider` is the interface the rest of the app depends on. `FMPProvider`
implements it against Financial Modeling Prep (free tier covers House + Senate).
`SampleProvider` returns bundled fixture data so the pipeline can be exercised
offline and in tests without an API key or network access.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path

import requests

from .models import Trade

log = logging.getLogger(__name__)

_AMOUNT_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)")


def parse_amount_range(text: str | None) -> tuple[float, float]:
    """Parse a disclosed dollar range like '$1,001 - $15,000' -> (1001, 15000).

    Handles open-ended ('Over $50,000,000') and single-value strings. Returns
    (0, 0) when nothing parseable is found.
    """
    if not text:
        return (0.0, 0.0)
    nums = [float(m.replace(",", "")) for m in _AMOUNT_RE.findall(text)]
    if not nums:
        return (0.0, 0.0)
    if len(nums) == 1:
        return (nums[0], nums[0])
    return (min(nums), max(nums))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value[: len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _normalize_type(raw: str | None) -> str:
    t = (raw or "").lower()
    if "purchase" in t or t == "buy":
        return "buy"
    if "sale" in t or t == "sell":
        return "sell"
    if "exchange" in t:
        return "exchange"
    return t or "unknown"


def normalize_record(record: dict, chamber: str) -> Trade | None:
    """Convert one FMP record (House or Senate shape) into a Trade, or None.

    The two FMP endpoints use slightly different field names, so we look for
    several variants of each field defensively.
    """
    ticker = (record.get("symbol") or record.get("ticker") or "").strip().upper()
    if not ticker:
        return None  # options/bonds/funds without a clean ticker: skip

    name = (
        record.get("representative")
        or record.get("senator")
        or " ".join(
            p for p in [record.get("firstName"), record.get("lastName")] if p
        ).strip()
        or record.get("office")
        or "Unknown"
    )

    tx_date = _parse_date(
        record.get("transactionDate") or record.get("transaction_date")
    )
    disclosed = _parse_date(
        record.get("disclosureDate")
        or record.get("dateRecieved")
        or record.get("dateReceived")
        or record.get("disclosure_date")
    )
    if tx_date is None:
        return None
    if disclosed is None:
        disclosed = tx_date

    low, high = parse_amount_range(record.get("amount"))

    return Trade(
        politician=str(name).strip(),
        chamber=chamber,
        party=(record.get("party") or "").strip(),
        ticker=ticker,
        tx_type=_normalize_type(record.get("type")),
        tx_date=tx_date,
        disclosed_date=disclosed,
        amount_low=low,
        amount_high=high,
        asset_type=(record.get("assetType") or "stock").strip() or "stock",
    )


class DataProvider(ABC):
    @abstractmethod
    def fetch_recent_trades(self, pages: int = 3) -> list[Trade]:
        """Return recent disclosed trades, newest first."""


class FMPProvider(DataProvider):
    """Financial Modeling Prep congressional-trading endpoints."""

    BASE = "https://financialmodelingprep.com/api/v4"
    FEEDS = [
        ("senate-trading-rss-feed", "Senate"),
        ("senate-disclosure-rss-feed", "House"),
    ]

    def __init__(self, api_key: str, timeout: int = 20):
        if not api_key:
            raise ValueError("FMP API key is required (set FMP_API_KEY).")
        self.api_key = api_key
        self.timeout = timeout

    def _get(self, feed: str, page: int) -> list[dict]:
        url = f"{self.BASE}/{feed}"
        resp = requests.get(
            url,
            params={"page": page, "apikey": self.api_key},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []

    def fetch_recent_trades(self, pages: int = 3) -> list[Trade]:
        trades: list[Trade] = []
        for feed, chamber in self.FEEDS:
            for page in range(pages):
                try:
                    records = self._get(feed, page)
                except Exception as exc:  # network / rate-limit / shape change
                    log.warning("FMP %s page %d failed: %s", feed, page, exc)
                    break
                if not records:
                    break
                for rec in records:
                    trade = normalize_record(rec, chamber)
                    if trade is not None:
                        trades.append(trade)
        trades.sort(key=lambda t: t.disclosed_date, reverse=True)
        log.info("Fetched %d congressional trades from FMP", len(trades))
        return trades


class SampleProvider(DataProvider):
    """Loads bundled fixture data — no network or API key needed."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else (
            Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sample_trades.json"
        )

    def fetch_recent_trades(self, pages: int = 3) -> list[Trade]:
        records = json.loads(self.path.read_text())
        trades = [
            t
            for rec in records
            if (t := normalize_record(rec, rec.get("chamber", ""))) is not None
        ]
        trades.sort(key=lambda t: t.disclosed_date, reverse=True)
        return trades


def build_provider(name: str, api_key: str = "") -> DataProvider:
    name = (name or "fmp").lower()
    if name == "sample":
        return SampleProvider()
    if name == "fmp":
        return FMPProvider(api_key)
    raise ValueError(f"Unknown data provider: {name!r} (use 'fmp' or 'sample').")
