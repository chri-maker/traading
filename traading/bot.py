"""Live (paper) trading loop.

On each cycle, for every configured symbol it:
  1. fetches recent closing prices,
  2. asks the strategy for an action given the current position,
  3. executes a market BUY (allocating a slice of buying power) or closes the
     position on a SELL.

Designed for paper trading. Running against a live endpoint trades real money —
do so only if you understand the risk.
"""

from __future__ import annotations

import logging
import time

from .broker import Broker
from .config import Config, load_config
from .strategy import Action, MovingAverageCrossover

log = logging.getLogger("traading.bot")


class TradingBot:
    def __init__(self, config: Config, broker: Broker | None = None):
        self.config = config
        self.broker = broker or Broker(config)
        self.strategy = MovingAverageCrossover(
            fast_window=config.fast_window,
            slow_window=config.slow_window,
        )

    def evaluate_symbol(self, symbol: str) -> None:
        # Pull a bit more than slow_window so the MAs are well-defined.
        closes = self.broker.recent_closes(symbol, limit=self.config.slow_window + 5)
        if len(closes) < self.config.slow_window:
            log.info("%s: not enough bars (%d), skipping.", symbol, len(closes))
            return

        currently_long = self.broker.is_long(symbol)
        action = self.strategy.decide(closes, currently_long)
        price = closes[-1]
        log.info(
            "%s: price=%.2f long=%s -> %s",
            symbol,
            price,
            currently_long,
            action.value,
        )

        if action is Action.BUY:
            allocation = self.broker.buying_power() * self.config.position_size
            qty = allocation / price
            if qty <= 0:
                log.warning("%s: zero buying power, cannot buy.", symbol)
                return
            # Whole shares keep things simple and broadly compatible.
            qty = int(qty)
            if qty < 1:
                log.warning(
                    "%s: allocation $%.2f < 1 share at $%.2f, skipping.",
                    symbol,
                    allocation,
                    price,
                )
                return
            self.broker.buy(symbol, qty)
        elif action is Action.SELL:
            self.broker.close_position(symbol)

    def run_once(self) -> None:
        if not self.broker.is_market_open():
            log.info("Market closed; skipping cycle.")
            return
        for symbol in self.config.symbols:
            try:
                self.evaluate_symbol(symbol)
            except Exception:  # keep the loop alive on per-symbol failures
                log.exception("Error evaluating %s", symbol)

    def run_forever(self) -> None:
        mode = "PAPER" if self.config.is_paper else "LIVE"
        log.info(
            "Starting bot [%s] symbols=%s fast=%d slow=%d interval=%ds",
            mode,
            ",".join(self.config.symbols),
            self.config.fast_window,
            self.config.slow_window,
            self.config.poll_interval,
        )
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("Cycle failed")
            time.sleep(self.config.poll_interval)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    if not config.is_paper:
        log.warning("Configured for a NON-PAPER endpoint: %s", config.base_url)
    TradingBot(config).run_forever()


if __name__ == "__main__":
    main()
