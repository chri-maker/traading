"""Backtest the moving-average crossover strategy on Alpaca historical data.

    python -m scripts.run_backtest                 # uses SYMBOLS from .env
    python -m scripts.run_backtest AAPL --days 365
"""

from __future__ import annotations

import argparse
import logging

from traading.backtest import run_backtest
from traading.broker import Broker
from traading.config import load_config
from traading.strategy import MovingAverageCrossover


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    config = load_config()

    parser = argparse.ArgumentParser(description="Backtest MA crossover strategy.")
    parser.add_argument(
        "symbols",
        nargs="*",
        default=config.symbols,
        help="Symbols to backtest (default: SYMBOLS from .env).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="How many bars of history to request (default: 365).",
    )
    parser.add_argument(
        "--cash",
        type=float,
        default=10_000.0,
        help="Starting cash (default: 10000).",
    )
    args = parser.parse_args()

    broker = Broker(config)
    strategy = MovingAverageCrossover(config.fast_window, config.slow_window)
    symbols = args.symbols or config.symbols

    for symbol in symbols:
        closes = broker.recent_closes(symbol, limit=args.days)
        if len(closes) < config.slow_window:
            print(f"{symbol}: not enough data ({len(closes)} bars). Skipping.\n")
            continue
        result = run_backtest(closes, strategy, starting_cash=args.cash)
        print(f"=== {symbol}  ({len(closes)} bars, {config.timeframe}) ===")
        print(result.summary())
        print()


if __name__ == "__main__":
    main()
