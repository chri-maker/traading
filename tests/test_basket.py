from traading.basket import (
    BasketOrder,
    canon,
    compute_basket_orders,
    equal_weights,
    is_crypto,
)

PRICES = {
    "AAPL": 200.0,
    "MSFT": 400.0,
    "BTC/USD": 100_000.0,
    "ETH/USD": 2_500.0,
}


def price_fn(sym):
    return PRICES.get(sym)


def test_canon_matches_crypto_forms():
    assert canon("BTC/USD") == canon("BTCUSD") == "BTCUSD"


def test_is_crypto():
    assert is_crypto("BTC/USD") and not is_crypto("AAPL")


def test_equal_weights_caps_and_dedups():
    w = equal_weights(["AAPL", "AAPL", "MSFT", "NVDA"], size=2)
    assert set(w) == {"AAPL", "MSFT"}
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_equal_weights_sum_to_one():
    w = equal_weights(["AAPL", "MSFT", "BTC/USD", "ETH/USD"], size=4)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(abs(v - 0.25) < 1e-9 for v in w.values())


def test_stock_whole_shares_crypto_fractional():
    weights = {"AAPL": 0.5, "BTC/USD": 0.5}
    orders = compute_basket_orders(
        weights, price_fn, equity=100_000.0, current={}, allocation=1.0
    )
    by = {o.symbol: o for o in orders}
    # 50k / $200 = 250 whole shares
    assert by["AAPL"].qty == 250 and not by["AAPL"].is_crypto
    # 50k / 100k = 0.5 BTC, fractional
    assert abs(by["BTC/USD"].qty - 0.5) < 1e-9 and by["BTC/USD"].is_crypto
    assert all(o.side == "buy" for o in orders)


def test_exits_positions_not_in_basket():
    weights = {"AAPL": 1.0}
    current = {canon("TSM"): ("TSM", 114.0), canon("BTC/USD"): ("BTCUSD", 0.3)}
    orders = compute_basket_orders(
        weights, price_fn, equity=100_000.0, current=current, allocation=1.0
    )
    exits = {o.symbol: o for o in orders if o.side == "exit"}
    assert exits["TSM"].qty == 114.0
    assert exits["BTCUSD"].qty == 0.3  # held crypto not in basket -> exit


def test_skips_dust_when_already_at_target():
    weights = {"AAPL": 1.0}
    # Already holding the ~500 shares 100k/200 would buy -> no new order.
    current = {canon("AAPL"): ("AAPL", 500.0)}
    orders = compute_basket_orders(
        weights, price_fn, equity=100_000.0, current=current, allocation=1.0
    )
    assert [o for o in orders if o.symbol == "AAPL"] == []


def test_empty_universe_env_falls_back_to_default(monkeypatch):
    from traading.config import DEFAULT_BASKET, load_basket_config

    monkeypatch.setenv("BASKET_UNIVERSE", "")  # workflow passes empty when unset
    cfg = load_basket_config()
    assert len(cfg.universe) == len(DEFAULT_BASKET.split(","))
    assert "BTC/USD" in cfg.universe


def test_trim_when_overweight():
    weights = {"AAPL": 1.0}
    current = {canon("AAPL"): ("AAPL", 600.0)}  # target 500 -> sell 100
    orders = compute_basket_orders(
        weights, price_fn, equity=100_000.0, current=current, allocation=1.0
    )
    aapl = [o for o in orders if o.symbol == "AAPL"][0]
    assert aapl.side == "sell" and aapl.qty == 100
