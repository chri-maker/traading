"""Rules-based diversified basket strategy (stocks + crypto), equal-weight.

No AI, no external data, no API key beyond Alpaca. Holds ~N equal-weight
positions across a fixed universe of liquid stocks and a few cryptocurrencies,
and rebalances toward those targets. Crypto is sized fractionally; stocks in
whole shares. Anything held but not in the basket is exited.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)


def canon(symbol: str) -> str:
    """Canonical key so 'BTC/USD' and Alpaca's 'BTCUSD' match."""
    return symbol.replace("/", "").upper()


def is_crypto(symbol: str) -> bool:
    # Targets use the slash form ("BTC/USD"); Alpaca reports held crypto
    # positions without it ("BTCUSD"). Treat both as crypto so exits aren't
    # gated behind stock-market hours.
    s = symbol.upper()
    return "/" in s or s.endswith("USD")


def equal_weights(symbols: list[str], size: int) -> dict[str, float]:
    """Equal weight across the first `size` symbols (dedup, order-preserving)."""
    seen: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.append(s)
    chosen = seen[:size]
    if not chosen:
        return {}
    w = 1.0 / len(chosen)
    return {s: w for s in chosen}


@dataclass(frozen=True)
class BasketOrder:
    symbol: str  # symbol to send to the broker (e.g. "AAPL" or "BTC/USD"); for
    # exits this is the symbol exactly as Alpaca reports the held position
    side: str  # "buy" | "sell" | "exit"
    qty: float
    is_crypto: bool
    reason: str = ""


def compute_basket_orders(
    weights: dict[str, float],
    price_fn: Callable[[str], float | None],
    equity: float,
    current: dict[str, tuple[str, float]],
    allocation: float = 0.95,
    min_notional: float = 10.0,  # Alpaca rejects crypto orders below $10
) -> list[BasketOrder]:
    """Diff target equal-weight basket against current holdings.

    `current` maps canonical symbol -> (alpaca_symbol, qty_held).
    Returns buy/sell orders for target names and exit orders for the rest.
    """
    deployable = max(equity, 0.0) * allocation
    targets: dict[str, dict] = {}
    for sym, wt in weights.items():
        price = price_fn(sym)
        if not price or price <= 0:
            log.warning("No price for %s; skipping.", sym)
            continue
        dollars = deployable * wt
        if is_crypto(sym):
            qty = round(dollars / price, 6)
        else:
            qty = float(int(dollars // price))
        if qty <= 0:
            continue
        targets[canon(sym)] = {"symbol": sym, "qty": qty, "price": price, "crypto": is_crypto(sym)}

    orders: list[BasketOrder] = []

    # Adjust / open target positions.
    for c, t in targets.items():
        held = current.get(c)
        held_qty = held[1] if held else 0.0
        delta = t["qty"] - held_qty
        if t["crypto"]:
            if abs(delta) * t["price"] < min_notional:
                continue
        else:
            if abs(delta) < 1:
                continue
            delta = float(int(delta))
        if delta > 0:
            orders.append(BasketOrder(t["symbol"], "buy", delta, t["crypto"], "open/increase"))
        elif delta < 0:
            orders.append(BasketOrder(t["symbol"], "sell", -delta, t["crypto"], "trim"))

    # Exit anything held that isn't a target.
    for c, (alpaca_symbol, qty) in current.items():
        if c not in targets and qty > 0:
            orders.append(BasketOrder(alpaca_symbol, "exit", qty, is_crypto(alpaca_symbol), "exit (not in basket)"))

    orders.sort(key=lambda o: (o.side == "buy", o.symbol))  # exits/sells first
    return orders
