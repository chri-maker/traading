"""Thin wrapper around the Alpaca SDK for the operations the bot needs.

Isolating the SDK here means the strategy and bot logic never import alpaca-py
directly, which keeps them easy to test and the SDK easy to swap/upgrade.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestTradeRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from .config import Config

log = logging.getLogger(__name__)

# Map human-friendly timeframe strings to Alpaca TimeFrame objects.
_TIMEFRAMES = {
    "1Min": TimeFrame(1, TimeFrameUnit.Minute),
    "5Min": TimeFrame(5, TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
    "1Day": TimeFrame(1, TimeFrameUnit.Day),
}


def parse_timeframe(name: str) -> TimeFrame:
    try:
        return _TIMEFRAMES[name]
    except KeyError:
        raise ValueError(
            f"Unsupported timeframe {name!r}. Choose one of {list(_TIMEFRAMES)}."
        ) from None


class Broker:
    """Account, market-data, and order operations against Alpaca."""

    def __init__(self, config: Config):
        self.config = config
        self.trading = TradingClient(
            api_key=config.api_key_id,
            secret_key=config.api_secret_key,
            paper=config.is_paper,
        )
        self.data = StockHistoricalDataClient(
            api_key=config.api_key_id,
            secret_key=config.api_secret_key,
        )

    # --- Account -----------------------------------------------------------
    def get_account(self):
        return self.trading.get_account()

    def buying_power(self) -> float:
        return float(self.get_account().buying_power)

    def is_market_open(self) -> bool:
        return bool(self.trading.get_clock().is_open)

    # --- Positions ---------------------------------------------------------
    def get_position_qty(self, symbol: str) -> float:
        """Return the held quantity for `symbol` (0.0 if none)."""
        try:
            position = self.trading.get_open_position(symbol)
            return float(position.qty)
        except Exception:
            # Alpaca raises if there is no open position for the symbol.
            return 0.0

    def is_long(self, symbol: str) -> bool:
        return self.get_position_qty(symbol) > 0

    def get_all_positions(self) -> dict[str, float]:
        """Map of symbol -> held quantity for every open position."""
        positions = self.trading.get_all_positions()
        return {p.symbol: float(p.qty) for p in positions}

    def tradable_symbols(self, candidates: list[str]) -> list[str]:
        """Filter `candidates` to active, tradable US equities on Alpaca.

        On any API error, returns the input unchanged — order submission still
        rejects bad symbols as a backstop.
        """
        try:
            from alpaca.trading.enums import AssetClass, AssetStatus
            from alpaca.trading.requests import GetAssetsRequest

            assets = self.trading.get_all_assets(
                GetAssetsRequest(
                    status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY
                )
            )
            ok = {a.symbol for a in assets if a.tradable}
            return [s for s in candidates if s in ok]
        except Exception:
            log.warning("tradable_symbols lookup failed; using candidates as-is", exc_info=True)
            return candidates

    def close_all_positions(self, cancel_orders: bool = True) -> list:
        """Liquidate every open position (market orders) and cancel open orders."""
        result = self.trading.close_all_positions(cancel_orders=cancel_orders)
        log.info("Submitted close-all for all positions")
        return result

    # --- Prices (for performance estimation / mirror sizing) ---------------
    def latest_price(self, symbol: str) -> float | None:
        try:
            request = StockLatestTradeRequest(symbol_or_symbols=symbol)
            result = self.data.get_stock_latest_trade(request)
            trade = result.get(symbol)
            return float(trade.price) if trade else None
        except Exception:
            log.warning("latest_price failed for %s", symbol, exc_info=True)
            return None

    def price_on(self, symbol: str, day: "date") -> float | None:
        """Closing price on `day`, or the most recent close before it."""
        from datetime import datetime as _dt
        from datetime import time as _time

        try:
            start = _dt.combine(day - timedelta(days=7), _time.min, tzinfo=timezone.utc)
            end = _dt.combine(day, _time.max, tzinfo=timezone.utc)
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame(1, TimeFrameUnit.Day),
                start=start,
                end=end,
            )
            bars = self.data.get_stock_bars(request)
            symbol_bars = bars.data.get(symbol, [])
            return float(symbol_bars[-1].close) if symbol_bars else None
        except Exception:
            log.warning("price_on failed for %s @ %s", symbol, day, exc_info=True)
            return None

    # --- Market data -------------------------------------------------------
    def recent_closes(self, symbol: str, limit: int) -> list[float]:
        """Return up to `limit` most recent closing prices for `symbol`."""
        timeframe = parse_timeframe(self.config.timeframe)
        # Look back generously so we have enough bars after market closures.
        start = datetime.now(timezone.utc) - timedelta(days=max(limit * 2, 30) + 5)
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=timeframe,
            start=start,
            limit=limit,
        )
        bars = self.data.get_stock_bars(request)
        symbol_bars = bars.data.get(symbol, [])
        return [float(bar.close) for bar in symbol_bars]

    # --- Orders ------------------------------------------------------------
    def submit_market_order(self, symbol: str, qty: float, side: OrderSide):
        order = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        log.info("Submitting %s order: %s x %s", side.value, qty, symbol)
        return self.trading.submit_order(order)

    def buy(self, symbol: str, qty: float):
        return self.submit_market_order(symbol, qty, OrderSide.BUY)

    def close_position(self, symbol: str):
        log.info("Closing position: %s", symbol)
        return self.trading.close_position(symbol)
