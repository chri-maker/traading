"""Translate a member's disclosed trades into target positions and orders.

Approach (all approximate, by necessity):
  1. Over the trailing window, net each ticker's disclosed buys minus sells
     (using dollar-range midpoints). Tickers with a positive net are treated as
     the member's implied long book.
  2. Convert net dollars into target portfolio *weights*.
  3. Deploy `allocation` of the account's equity across those weights, sized in
     whole shares at the latest price.
  4. Diff target shares against current holdings to produce buy/sell orders.

This mirrors direction and rough relative conviction, not exact size — the data
doesn't expose real position sizes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from .models import Trade

log = logging.getLogger(__name__)


class PriceSource(Protocol):
    def latest_price(self, symbol: str) -> float | None: ...


@dataclass(frozen=True)
class MirrorOrder:
    symbol: str
    side: str  # "buy" | "sell"
    qty: int
    target_shares: int
    current_shares: int
    reason: str = ""


def net_positions(
    member_trades: list[Trade], today: date, window_days: int
) -> dict[str, float]:
    """Net disclosed dollar exposure per ticker over the window (buys - sells)."""
    cutoff = today - timedelta(days=window_days)
    net: dict[str, float] = {}
    for t in member_trades:
        if t.tx_date < cutoff:
            continue
        net[t.ticker] = net.get(t.ticker, 0.0) + t.signed_amount
    # Keep only net-long tickers; we don't short in this strategy.
    return {sym: amt for sym, amt in net.items() if amt > 0}


def target_weights(net: dict[str, float]) -> dict[str, float]:
    total = sum(net.values())
    if total <= 0:
        return {}
    return {sym: amt / total for sym, amt in net.items()}


def cap_weights(weights: dict[str, float], cap: float | None) -> dict[str, float]:
    """Clip any single weight to `cap`, redistributing the excess proportionally.

    Prevents one huge disclosed buy from dominating the account. `cap` is a
    fraction in (0, 1]; None or >=1 means no cap.
    """
    if not cap or cap >= 1.0 or not weights:
        return weights
    w = dict(weights)
    for _ in range(20):
        over = {k: v for k, v in w.items() if v > cap + 1e-9}
        if not over:
            break
        capped = {k: cap for k in over}
        remaining = max(0.0, 1.0 - cap * len(over))
        under = {k: v for k, v in w.items() if k not in over}
        under_total = sum(under.values())
        if under_total <= 0:
            w = capped
            break
        w = {**capped, **{k: v / under_total * remaining for k, v in under.items()}}
    return w


def compute_mirror_orders(
    member_trades: list[Trade],
    prices: PriceSource,
    equity: float,
    current_positions: dict[str, float],
    today: date,
    window_days: int = 365,
    allocation: float = 0.5,
    max_positions: int | None = None,
    max_position_weight: float | None = None,
) -> list[MirrorOrder]:
    """Compute the orders needed to mirror a member's implied long book.

    `allocation` is the fraction of `equity` to deploy across the mirror.
    `max_position_weight` caps any single name's share of the mirror.
    `current_positions` maps symbol -> shares currently held.
    """
    net = net_positions(member_trades, today, window_days)
    weights = target_weights(net)
    if not weights:
        return []

    # Optionally cap to the largest N convictions.
    if max_positions is not None:
        top = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:max_positions]
        total = sum(w for _, w in top) or 1.0
        weights = {sym: w / total for sym, w in top}

    # Optionally cap any single name's weight (diversification guard).
    weights = cap_weights(weights, max_position_weight)

    deployable = max(equity, 0.0) * allocation
    orders: list[MirrorOrder] = []
    targets: dict[str, int] = {}

    for symbol, weight in weights.items():
        price = prices.latest_price(symbol)
        if not price or price <= 0:
            log.warning("No price for %s; skipping.", symbol)
            continue
        target_dollars = deployable * weight
        targets[symbol] = int(target_dollars // price)

    # Buys / adjustments for target tickers.
    for symbol, target_shares in targets.items():
        current = int(current_positions.get(symbol, 0))
        delta = target_shares - current
        if delta > 0:
            orders.append(
                MirrorOrder(symbol, "buy", delta, target_shares, current, "increase")
            )
        elif delta < 0:
            orders.append(
                MirrorOrder(symbol, "sell", -delta, target_shares, current, "trim")
            )

    # Exit anything held that is no longer in the member's book.
    for symbol, shares in current_positions.items():
        shares = int(shares)
        if shares > 0 and symbol not in targets:
            orders.append(
                MirrorOrder(symbol, "sell", shares, 0, shares, "exit (not in book)")
            )

    orders.sort(key=lambda o: (o.side != "sell", o.symbol))  # sells first
    return orders
