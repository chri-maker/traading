"""Estimate trailing-window performance per member of Congress.

IMPORTANT — this is an ESTIMATE built on disclosure data that is inherently
incomplete. We approximate each disclosed BUY as: invest the midpoint of the
disclosed dollar range at the transaction-date closing price, and hold to today.
The member's "return" is the amount-weighted average of those per-trade returns.

We deliberately do NOT try to model sells, options, cost basis, or pre-existing
holdings — the data doesn't support it. Treat the ranking as a rough heuristic,
not a measured track record.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Protocol

from .models import MemberPerformance, Trade

log = logging.getLogger(__name__)


class PriceSource(Protocol):
    def latest_price(self, symbol: str) -> float | None: ...
    def price_on(self, symbol: str, day: date) -> float | None: ...


def _trailing(trades: list[Trade], window_days: int, today: date) -> list[Trade]:
    cutoff = today - timedelta(days=window_days)
    return [t for t in trades if t.tx_date >= cutoff]


def estimate_member_return(
    member_trades: list[Trade],
    prices: PriceSource,
    _cache: dict | None = None,
) -> tuple[float, float]:
    """Return (weighted_return, invested_amount) for a member's buys.

    Returns (0.0, 0.0) when no buy can be priced.
    """
    cache = _cache if _cache is not None else {}
    weighted_sum = 0.0
    invested = 0.0
    for t in member_trades:
        if t.tx_type != "buy" or t.amount_mid <= 0:
            continue
        entry = cache.get(("on", t.ticker, t.tx_date))
        if entry is None:
            entry = prices.price_on(t.ticker, t.tx_date)
            cache[("on", t.ticker, t.tx_date)] = entry
        now = cache.get(("now", t.ticker))
        if now is None:
            now = prices.latest_price(t.ticker)
            cache[("now", t.ticker)] = now
        if not entry or not now or entry <= 0:
            continue
        ret = (now - entry) / entry
        weighted_sum += ret * t.amount_mid
        invested += t.amount_mid
    if invested <= 0:
        return (0.0, 0.0)
    return (weighted_sum / invested, invested)


def rank_members(
    trades: list[Trade],
    prices: PriceSource,
    today: date,
    window_days: int = 365,
    min_trades: int = 3,
    top_n: int | None = None,
) -> list[MemberPerformance]:
    """Rank the most active members by estimated trailing-window return.

    "Most active" = at least `min_trades` disclosed transactions in the window.
    Result is sorted by estimated return, descending.
    """
    window = _trailing(trades, window_days, today)
    by_member: dict[str, list[Trade]] = {}
    for t in window:
        by_member.setdefault(t.politician, []).append(t)

    cache: dict = {}
    results: list[MemberPerformance] = []
    for politician, member_trades in by_member.items():
        if len(member_trades) < min_trades:
            continue
        est_return, invested = estimate_member_return(member_trades, prices, cache)
        first = member_trades[0]
        results.append(
            MemberPerformance(
                politician=politician,
                chamber=first.chamber,
                party=first.party,
                num_trades=len(member_trades),
                estimated_return=est_return,
                invested_amount=invested,
                tickers=sorted({t.ticker for t in member_trades}),
            )
        )

    results.sort(key=lambda m: m.estimated_return, reverse=True)
    if top_n is not None:
        results = results[:top_n]
    return results
