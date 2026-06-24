from traading.strategy import (
    Action,
    MovingAverageCrossover,
    simple_moving_average,
)


def test_sma_insufficient_data():
    assert simple_moving_average([1, 2], 3) is None


def test_sma_basic():
    assert simple_moving_average([1, 2, 3, 4], 2) == 3.5


def test_signal_flat_when_insufficient_data():
    strat = MovingAverageCrossover(fast_window=2, slow_window=4)
    assert strat.signal([1, 2, 3]) == 0


def test_signal_long_on_uptrend():
    strat = MovingAverageCrossover(fast_window=2, slow_window=4)
    # Rising prices: fast MA above slow MA -> long.
    assert strat.signal([1, 2, 3, 4, 5, 6]) == 1


def test_signal_flat_on_downtrend():
    strat = MovingAverageCrossover(fast_window=2, slow_window=4)
    assert strat.signal([6, 5, 4, 3, 2, 1]) == 0


def test_decide_buy_on_cross_up():
    strat = MovingAverageCrossover(fast_window=2, slow_window=4)
    assert strat.decide([1, 2, 3, 4, 5, 6], currently_long=False) is Action.BUY


def test_decide_hold_when_already_long():
    strat = MovingAverageCrossover(fast_window=2, slow_window=4)
    assert strat.decide([1, 2, 3, 4, 5, 6], currently_long=True) is Action.HOLD


def test_decide_sell_on_cross_down():
    strat = MovingAverageCrossover(fast_window=2, slow_window=4)
    assert strat.decide([6, 5, 4, 3, 2, 1], currently_long=True) is Action.SELL


def test_invalid_windows():
    import pytest

    with pytest.raises(ValueError):
        MovingAverageCrossover(fast_window=4, slow_window=2)
