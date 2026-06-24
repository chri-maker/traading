from datetime import date

from traading.congress.mirror import (
    cap_weights,
    compute_mirror_orders,
    net_positions,
    target_weights,
)
from traading.congress.performance import estimate_member_return, rank_members
from traading.congress.providers import (
    SampleProvider,
    normalize_record,
    parse_amount_range,
)
from traading.congress.state import SeenStore

TODAY = date(2026, 6, 24)


# --- price stubs ----------------------------------------------------------
class FlatPrices:
    """now == entry -> 0% return everywhere."""

    def latest_price(self, symbol):
        return 100.0

    def price_on(self, symbol, day):
        return 100.0


class WinnerPrices:
    """NVDA doubled; everything else flat."""

    def latest_price(self, symbol):
        return 200.0 if symbol == "NVDA" else 100.0

    def price_on(self, symbol, day):
        return 100.0


# --- amount parsing -------------------------------------------------------
def test_parse_amount_range_basic():
    assert parse_amount_range("$1,001 - $15,000") == (1001.0, 15000.0)


def test_parse_amount_range_single():
    assert parse_amount_range("$5,000") == (5000.0, 5000.0)


def test_parse_amount_range_empty():
    assert parse_amount_range(None) == (0.0, 0.0)
    assert parse_amount_range("n/a") == (0.0, 0.0)


# --- normalization (both FMP shapes) -------------------------------------
def test_normalize_house_record():
    rec = {
        "representative": "Nancy Pelosi",
        "ticker": "NVDA",
        "type": "Purchase",
        "transactionDate": "2026-01-15",
        "disclosureDate": "2026-02-10",
        "amount": "$1,000,001 - $5,000,000",
    }
    t = normalize_record(rec, "House")
    assert t is not None
    assert t.politician == "Nancy Pelosi"
    assert t.ticker == "NVDA"
    assert t.tx_type == "buy"
    assert t.amount_mid == (1000001 + 5000000) / 2


def test_normalize_senate_record_name_join():
    rec = {
        "firstName": "Tommy",
        "lastName": "Tuberville",
        "symbol": "MSFT",
        "type": "Sale (Partial)",
        "transactionDate": "2026-02-28",
        "dateRecieved": "2026-03-20",
        "amount": "$15,001 - $50,000",
    }
    t = normalize_record(rec, "Senate")
    assert t.politician == "Tommy Tuberville"
    assert t.tx_type == "sell"


def test_normalize_skips_missing_ticker():
    assert normalize_record({"type": "Purchase", "transactionDate": "2026-01-01"}, "House") is None


# --- provider -------------------------------------------------------------
def test_sample_provider_loads_fixture():
    trades = SampleProvider().fetch_recent_trades()
    assert len(trades) >= 10
    assert any(t.politician == "Nancy Pelosi" for t in trades)


# --- performance ----------------------------------------------------------
def test_estimate_return_flat_is_zero():
    trades = SampleProvider().fetch_recent_trades()
    pelosi = [t for t in trades if t.politician == "Nancy Pelosi"]
    ret, invested = estimate_member_return(pelosi, FlatPrices())
    assert ret == 0.0
    assert invested > 0


def test_rank_excludes_low_activity_members():
    trades = SampleProvider().fetch_recent_trades()
    ranking = rank_members(trades, FlatPrices(), TODAY, min_trades=3)
    names = [m.politician for m in ranking]
    assert "Solo Trader" not in names  # only 1 trade
    assert "Nancy Pelosi" in names


def test_rank_orders_winner_first():
    trades = SampleProvider().fetch_recent_trades()
    ranking = rank_members(trades, WinnerPrices(), TODAY, min_trades=3)
    # Pelosi holds NVDA (which doubled) -> highest estimated return.
    assert ranking[0].politician == "Nancy Pelosi"
    assert ranking[0].estimated_return > 0


# --- mirror ---------------------------------------------------------------
def test_net_positions_drops_net_short():
    trades = SampleProvider().fetch_recent_trades()
    pelosi = [t for t in trades if t.politician == "Nancy Pelosi"]
    net = net_positions(pelosi, TODAY, 365)
    assert net["NVDA"] > 0
    assert all(v > 0 for v in net.values())


def test_target_weights_sum_to_one():
    weights = target_weights({"A": 30.0, "B": 10.0})
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert weights["A"] > weights["B"]


def test_cap_weights_clips_and_renormalizes():
    capped = cap_weights({"A": 0.9, "B": 0.05, "C": 0.05}, cap=0.4)
    assert capped["A"] <= 0.4 + 1e-9
    assert abs(sum(capped.values()) - 1.0) < 1e-9
    assert capped["B"] > 0.05  # excess redistributed to the small names


def test_cap_weights_noop_when_none():
    w = {"A": 0.9, "B": 0.1}
    assert cap_weights(w, None) == w


def test_compute_mirror_orders_respects_weight_cap():
    trades = SampleProvider().fetch_recent_trades()
    pelosi = [t for t in trades if t.politician == "Nancy Pelosi"]
    # Pelosi's NVDA buy is huge; without a cap it dominates. Cap it at 40%.
    orders = compute_mirror_orders(
        pelosi, FlatPrices(), equity=100_000.0, current_positions={},
        today=TODAY, allocation=1.0, max_position_weight=0.4,
    )
    by_symbol = {o.symbol: o.qty * 100.0 for o in orders}  # $100 flat price
    nvda_dollars = by_symbol.get("NVDA", 0)
    assert nvda_dollars <= 100_000.0 * 0.4 + 100  # within cap (+1 share rounding)


def test_compute_mirror_orders_buys_when_flat():
    trades = SampleProvider().fetch_recent_trades()
    pelosi = [t for t in trades if t.politician == "Nancy Pelosi"]
    orders = compute_mirror_orders(
        pelosi, FlatPrices(), equity=100_000.0, current_positions={},
        today=TODAY, allocation=0.5,
    )
    assert orders
    assert all(o.side == "buy" for o in orders)
    # Deploy 50% of 100k = 50k at $100 -> ~500 shares across names.
    assert sum(o.qty for o in orders) <= 500


def test_compute_mirror_orders_exits_unheld():
    trades = SampleProvider().fetch_recent_trades()
    pelosi = [t for t in trades if t.politician == "Nancy Pelosi"]
    orders = compute_mirror_orders(
        pelosi, FlatPrices(), equity=100_000.0,
        current_positions={"ZZZZ": 10}, today=TODAY, allocation=0.5,
    )
    exit_orders = [o for o in orders if o.symbol == "ZZZZ"]
    assert exit_orders and exit_orders[0].side == "sell"


# --- state ----------------------------------------------------------------
def test_seen_store_roundtrip(tmp_path):
    trades = SampleProvider().fetch_recent_trades()
    path = tmp_path / "seen.json"
    store = SeenStore(path)
    assert len(store.new_trades(trades)) == len(trades)  # all new initially
    store.mark_seen(trades)
    store.save()

    reloaded = SeenStore(path)
    assert reloaded.new_trades(trades) == []  # nothing new after persist
