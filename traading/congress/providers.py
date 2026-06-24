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
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_JUNK_TICKERS = {"--", "N/A", "NA", "NONE", "--.", "."}


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
    # Skip rows without a clean equity ticker (options, bonds, funds, "--").
    if not ticker or ticker in _JUNK_TICKERS or not _TICKER_RE.match(ticker):
        return None

    name = (
        record.get("representative")
        or record.get("senator")
        or " ".join(
            p for p in [record.get("firstName"), record.get("lastName")] if p
        ).strip()
        or record.get("office")
        or "Unknown"
    )
    # Stock Watcher prefixes House names with "Hon. " — drop it for consistency.
    name = str(name).strip()
    if name.startswith("Hon. "):
        name = name[5:].strip()

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
        asset_type=(record.get("assetType") or record.get("asset_type") or "stock").strip() or "stock",
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
        if resp.status_code != 200:
            # Surface FMP's actual message: distinguishes a bad key ("Invalid
            # API KEY") from a plan limit ("Exclusive Endpoint ... premium").
            body = resp.text[:300]
            raise RuntimeError(f"HTTP {resp.status_code} from FMP {feed}: {body}")
        data = resp.json()
        if isinstance(data, dict) and data.get("Error Message"):
            raise RuntimeError(f"FMP error on {feed}: {data['Error Message']}")
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


class StockWatcherProvider(DataProvider):
    """Free, no-API-key congressional data from the House/Senate Stock Watcher
    public datasets (https://github.com/timothycarambat). Tries S3 first, then
    the GitHub raw mirror, per chamber.
    """

    SOURCES = [
        (
            "House",
            [
                "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json",
                "https://raw.githubusercontent.com/timothycarambat/house-stock-watcher-data/master/data/all_transactions.json",
            ],
        ),
        (
            "Senate",
            [
                "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json",
                "https://raw.githubusercontent.com/timothycarambat/senate-stock-watcher-data/master/aggregate/all_transactions.json",
            ],
        ),
    ]

    def __init__(self, timeout: int = 60):
        self.timeout = timeout

    def _fetch_json(self, urls: list[str]) -> list[dict]:
        last_exc: Exception | None = None
        for url in urls:
            try:
                resp = requests.get(url, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    return data
            except Exception as exc:  # try the next mirror
                last_exc = exc
                log.warning("Stock Watcher fetch failed for %s: %s", url, exc)
        if last_exc:
            log.error("All Stock Watcher mirrors failed: %s", last_exc)
        return []

    def fetch_recent_trades(self, pages: int = 3) -> list[Trade]:
        trades: list[Trade] = []
        for chamber, urls in self.SOURCES:
            records = self._fetch_json(urls)
            for rec in records:
                trade = normalize_record(rec, chamber)
                if trade is not None:
                    trades.append(trade)
        trades.sort(key=lambda t: t.disclosed_date, reverse=True)
        log.info("Fetched %d congressional trades from Stock Watcher", len(trades))
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
    name = (name or "auto").lower()
    if name == "auto":
        # Use FMP (current data) when a key is present; otherwise the free
        # Stock Watcher archive.
        name = "fmp" if api_key else "stockwatcher"
    if name == "sample":
        return SampleProvider()
    if name in ("stockwatcher", "stock-watcher", "free"):
        return StockWatcherProvider()
    if name == "fmp":
        return FMPProvider(api_key)
    raise ValueError(
        f"Unknown data provider: {name!r} (use 'auto', 'stockwatcher', 'fmp', or 'sample')."
    )
