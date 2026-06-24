"""Moving-average crossover strategy.

The logic is intentionally pure: it operates on a sequence of closing prices and
returns a target signal. This keeps it identical between backtest and live
trading, and makes it trivial to unit-test without any network access.

Signal semantics:
    +1  -> want to be LONG  (fast MA above slow MA)
     0  -> want to be FLAT  (not enough data, or fast MA below slow MA)

A *buy* happens on the transition 0 -> +1 (golden cross).
A *sell* happens on the transition +1 -> 0 (death cross).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


def simple_moving_average(prices: list[float], window: int) -> float | None:
    """Return the SMA of the last `window` prices, or None if insufficient data."""
    if window <= 0:
        raise ValueError("window must be positive")
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window


@dataclass(frozen=True)
class MovingAverageCrossover:
    """Fast/slow SMA crossover strategy."""

    fast_window: int
    slow_window: int

    def __post_init__(self) -> None:
        if self.fast_window <= 0 or self.slow_window <= 0:
            raise ValueError("windows must be positive")
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be < slow_window")

    def signal(self, prices: list[float]) -> int:
        """Return the desired position for the latest bar: +1 (long) or 0 (flat)."""
        fast = simple_moving_average(prices, self.fast_window)
        slow = simple_moving_average(prices, self.slow_window)
        if fast is None or slow is None:
            return 0
        return 1 if fast > slow else 0

    def decide(self, prices: list[float], currently_long: bool) -> Action:
        """Map the current signal + position into a concrete action.

        `prices` should be the closing prices up to and including the latest bar.
        `currently_long` is whether we already hold a long position.
        """
        want_long = self.signal(prices) == 1
        if want_long and not currently_long:
            return Action.BUY
        if not want_long and currently_long:
            return Action.SELL
        return Action.HOLD
