"""Fetch congressional disclosures and print the member leaderboard.

    python -m scripts.rank_members            # live: needs FMP_API_KEY + Alpaca keys
    python -m scripts.rank_members --sample   # offline: bundled fixture + fake prices
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timezone

from traading.broker import Broker
from traading.config import load_config, load_congress_config
from traading.congress.performance import rank_members
from traading.congress.providers import build_provider


class _SampleParty:
    """Deterministic fake prices so --sample works without network/keys."""

    def latest_price(self, symbol: str) -> float:
        return 100.0 + (sum(map(ord, symbol)) % 50)

    def price_on(self, symbol: str, day: date) -> float:
        return 90.0 + (sum(map(ord, symbol)) % 40)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description="Rank members of Congress.")
    parser.add_argument("--sample", action="store_true", help="Use offline fixtures.")
    args = parser.parse_args()

    cc = load_congress_config()
    today = datetime.now(timezone.utc).date()

    if args.sample:
        provider = build_provider("sample")
        prices = _SampleParty()
    else:
        provider = build_provider(cc.provider, cc.fmp_api_key)
        prices = Broker(load_config())

    trades = provider.fetch_recent_trades(pages=cc.fetch_pages)
    ranking = rank_members(
        trades, prices, today,
        window_days=cc.window_days, min_trades=cc.min_trades,
    )

    print(f"Fetched {len(trades)} disclosed trades.")
    print(f"Members with >= {cc.min_trades} trades in last {cc.window_days}d, "
          f"ranked by estimated return:\n")
    for i, m in enumerate(ranking, 1):
        print(f"{i:>2}. {m.as_row()}")
    if not ranking:
        print("(no qualifying members)")


if __name__ == "__main__":
    main()
