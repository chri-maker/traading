import math

from traading.backtest import run_backtest
from traading.strategy import MovingAverageCrossover


def test_backtest_no_trades_on_flat_prices():
    strat = MovingAverageCrossover(fast_window=2, slow_window=4)
    prices = [10.0] * 20
    result = run_backtest(prices, strat, starting_cash=1000.0)
    assert result.closed_trades == []
    assert math.isclose(result.ending_equity, 1000.0)


def test_backtest_profits_in_uptrend():
    strat = MovingAverageCrossover(fast_window=2, slow_window=4)
    # Steady uptrend: strategy should go long and ride it up.
    prices = [float(p) for p in range(1, 51)]
    result = run_backtest(prices, strat, starting_cash=1000.0)
    assert result.ending_equity > 1000.0
    assert result.total_return_pct > 0


def test_backtest_round_trip_records_trade():
    strat = MovingAverageCrossover(fast_window=2, slow_window=4)
    # Up then down so we enter and then exit a position.
    prices = [float(p) for p in range(1, 21)] + [float(p) for p in range(20, 0, -1)]
    result = run_backtest(prices, strat, starting_cash=1000.0)
    assert len(result.closed_trades) >= 1
    for trade in result.closed_trades:
        assert trade.entry_price > 0
        assert trade.exit_price is not None
