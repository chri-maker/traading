import json

from traading.ai.strategy import (
    AIDecision,
    build_prompt,
    decide_portfolio,
    parse_and_validate,
)
from traading.congress.mirror import orders_from_weights

ALLOWED = {"AAPL", "MSFT", "NVDA", "KO", "XOM"}


# --- fakes ---------------------------------------------------------------
class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Msg:
    def __init__(self, text):
        self.content = [_Block(text)]


class FakeClient:
    """Mimics anthropic.Anthropic for tests."""

    def __init__(self, reply):
        self._reply = reply
        self.messages = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _Msg(self._reply)


class FakePrices:
    def latest_price(self, symbol):
        return 100.0


# --- prompt --------------------------------------------------------------
def test_build_prompt_lists_universe_and_constraints():
    ctx = {
        "account": {"equity": 100000, "cash": 100000},
        "holdings": {},
        "candidates": [
            {"symbol": "AAPL", "price": 200.0, "return_30d": 0.05, "congress_buys": 2, "congress_sells": 0},
        ],
    }
    prompt = build_prompt(ctx, {"max_positions": 5, "max_position_weight": 0.25})
    assert "AAPL" in prompt
    assert "max_positions = 5" in prompt
    assert "long-only" in prompt


# --- validation ----------------------------------------------------------
def test_parse_drops_unknown_symbols():
    raw = json.dumps({"positions": [{"symbol": "AAPL", "weight": 0.2}, {"symbol": "FAKE", "weight": 0.2}]})
    d = parse_and_validate(raw, ALLOWED, 5, 0.25)
    assert "AAPL" in d.weights and "FAKE" not in d.weights


def test_parse_clips_weight_to_cap():
    raw = json.dumps({"positions": [{"symbol": "AAPL", "weight": 0.9}]})
    d = parse_and_validate(raw, ALLOWED, 5, 0.25)
    assert d.weights["AAPL"] == 0.25


def test_parse_keeps_top_n():
    raw = json.dumps({"positions": [
        {"symbol": "AAPL", "weight": 0.2},
        {"symbol": "MSFT", "weight": 0.15},
        {"symbol": "NVDA", "weight": 0.1},
    ]})
    d = parse_and_validate(raw, ALLOWED, 2, 0.5)
    assert set(d.weights) == {"AAPL", "MSFT"}  # smallest dropped


def test_parse_scales_when_over_allocated():
    raw = json.dumps({"positions": [
        {"symbol": "AAPL", "weight": 0.5},
        {"symbol": "MSFT", "weight": 0.5},
        {"symbol": "NVDA", "weight": 0.5},
    ]})
    d = parse_and_validate(raw, ALLOWED, 5, 0.5)
    assert abs(sum(d.weights.values()) - 1.0) < 1e-9


def test_parse_handles_code_fenced_json():
    raw = "```json\n" + json.dumps({"positions": [{"symbol": "KO", "weight": 0.1}]}) + "\n```"
    d = parse_and_validate(raw, ALLOWED, 5, 0.25)
    assert d.weights == {"KO": 0.1}


def test_parse_empty_on_garbage_positions():
    raw = json.dumps({"rationale": "all cash", "positions": []})
    d = parse_and_validate(raw, ALLOWED, 5, 0.25)
    assert d.weights == {}
    assert d.rationale == "all cash"


# --- end to end with fake client ----------------------------------------
def test_decide_portfolio_with_fake_client():
    ctx = {
        "account": {"equity": 100000, "cash": 100000},
        "holdings": {},
        "candidates": [{"symbol": s, "price": 100.0, "return_30d": 0.0} for s in ALLOWED],
    }
    reply = json.dumps({
        "market_view": "neutral",
        "rationale": "diversify",
        "positions": [{"symbol": "AAPL", "weight": 0.2}, {"symbol": "XOM", "weight": 0.2}],
    })
    d = decide_portfolio(FakeClient(reply), "claude-sonnet-4-6", 1000, ctx, 8, 0.25)
    assert isinstance(d, AIDecision)
    assert set(d.weights) == {"AAPL", "XOM"}


# --- weights -> orders ---------------------------------------------------
def test_orders_from_weights_sizes_and_exits():
    orders = orders_from_weights(
        {"AAPL": 0.5, "MSFT": 0.5}, FakePrices(), equity=100_000.0,
        current_positions={"ZZZZ": 10}, allocation=0.5, exit_unlisted=True,
    )
    by = {o.symbol: o for o in orders}
    # 50% of 100k = 50k, half each = 25k / $100 = 250 shares.
    assert by["AAPL"].side == "buy" and by["AAPL"].qty == 250
    assert by["ZZZZ"].side == "sell"  # exited (not in target)
