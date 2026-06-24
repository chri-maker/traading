"""A minimal vectorless backtester for the moving-average crossover strategy.

It walks a price series bar-by-bar, applying the same `decide()` logic the live
bot uses, and tracks equity assuming all-in long / flat positions. This is meant
for sanity-checking strategy behavior, not for production-grade simulation
(no slippage, commissions, or partial fills).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .strategy import Action, MovingAverageCrossover


@dataclass
class Trade:
    entry_index: int
    entry_price: float
    exit_index: int | None = None
    exit_price: float | None = None

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    @property
    def return_pct(self) -> float | None:
        if self.exit_price is None:
            return None
        return (self.exit_price - self.entry_price) / self.entry_price


@dataclass
class BacktestResult:
    starting_cash: float
    ending_equity: float
    trades: list[Trade] = field(default_factory=list)

    @property
    def total_return_pct(self) -> float:
        return (self.ending_equity - self.starting_cash) / self.starting_cash

    @property
    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if not t.is_open]

    @property
    def win_rate(self) -> float | None:
        closed = self.closed_trades
        if not closed:
            return None
        wins = sum(1 for t in closed if (t.return_pct or 0) > 0)
        return wins / len(closed)

    def summary(self) -> str:
        wr = self.win_rate
        wr_str = f"{wr:.1%}" if wr is not None else "n/a"
        return (
            f"Starting cash : ${self.starting_cash:,.2f}\n"
            f"Ending equity : ${self.ending_equity:,.2f}\n"
            f"Total return  : {self.total_return_pct:+.2%}\n"
            f"Closed trades : {len(self.closed_trades)}\n"
            f"Win rate      : {wr_str}"
        )


def run_backtest(
    prices: list[float],
    strategy: MovingAverageCrossover,
    starting_cash: float = 10_000.0,
) -> BacktestResult:
    """Simulate the strategy over `prices`, going all-in long or flat."""
    cash = starting_cash
    shares = 0.0
    trades: list[Trade] = []

    for i in range(1, len(prices) + 1):
        window = prices[:i]
        price = window[-1]
        currently_long = shares > 0
        action = strategy.decide(window, currently_long)

        if action is Action.BUY:
            shares = cash / price
            cash = 0.0
            trades.append(Trade(entry_index=i - 1, entry_price=price))
        elif action is Action.SELL:
            cash = shares * price
            shares = 0.0
            if trades and trades[-1].is_open:
                trades[-1].exit_index = i - 1
                trades[-1].exit_price = price

    ending_equity = cash + shares * prices[-1] if prices else starting_cash
    return BacktestResult(
        starting_cash=starting_cash,
        ending_equity=ending_equity,
        trades=trades,
    )
