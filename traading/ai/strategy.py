"""AI-driven trading strategy: Claude proposes a target portfolio.

The design keeps the model's job small and bounded: given a compact snapshot of
a fixed universe (recent prices/returns + congressional-trade signals) and the
current account, return target weights for a LONG-ONLY portfolio. Everything the
model returns is validated and clamped before any order is placed — unknown
tickers are dropped, weights are capped, and the total can never exceed the
configured allocation. The model cannot invent sizes, leverage, or symbols.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a cautious, risk-aware portfolio manager running a PAPER trading "
    "account. You only go long. You pick a small, diversified set of positions "
    "from an allowed universe and return STRICT JSON. You never exceed the "
    "given constraints. You explain your reasoning briefly and honestly, "
    "including when the signal is weak."
)


@dataclass
class AIDecision:
    rationale: str
    weights: dict[str, float]  # symbol -> target weight (already validated)
    market_view: str = ""
    raw: dict = field(default_factory=dict)


def build_prompt(context: dict, constraints: dict) -> str:
    """Construct the user prompt from the market context and constraints.

    `context["candidates"]` is a list of dicts with keys: symbol, price,
    return_30d, congress_buys, congress_sells. `context["account"]` and
    `context["holdings"]` describe the current state.
    """
    lines: list[str] = []
    acct = context.get("account", {})
    lines.append("ACCOUNT:")
    lines.append(
        f"  equity=${acct.get('equity', 0):,.0f}  cash=${acct.get('cash', 0):,.0f}"
    )
    holdings = context.get("holdings", {})
    lines.append(f"CURRENT HOLDINGS (shares): {holdings or 'none'}")

    lines.append("\nUNIVERSE (only these symbols are allowed):")
    lines.append(f"  {', '.join(c['symbol'] for c in context.get('candidates', []))}")

    lines.append("\nPER-SYMBOL SNAPSHOT:")
    lines.append("  symbol | price | 30d_return | congress_buys | congress_sells")
    for c in context.get("candidates", []):
        ret = c.get("return_30d")
        ret_s = f"{ret:+.1%}" if isinstance(ret, (int, float)) else "n/a"
        lines.append(
            f"  {c['symbol']:<6} | {c.get('price', 0):>8.2f} | {ret_s:>7} | "
            f"{c.get('congress_buys', 0):>3} | {c.get('congress_sells', 0):>3}"
        )

    lines.append("\nCONSTRAINTS:")
    lines.append(f"  max_positions = {constraints['max_positions']}")
    lines.append(f"  max_weight_per_name = {constraints['max_position_weight']:.2f}")
    lines.append("  weights are fractions of the deployable budget and must sum to <= 1.0")
    lines.append("  long-only; choose ONLY from the universe above")

    lines.append(
        "\nRespond with ONLY a JSON object of this exact shape:\n"
        '{\n'
        '  "market_view": "one or two sentences",\n'
        '  "rationale": "why these picks; note if the signal is weak",\n'
        '  "positions": [ {"symbol": "AAPL", "weight": 0.2, "reason": "..."} ]\n'
        "}"
    )
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of the model's text."""
    text = text.strip()
    # Strip code fences if present.
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return json.loads(text[start : end + 1])


def parse_and_validate(
    raw_text: str,
    allowed_symbols: set[str],
    max_positions: int,
    max_position_weight: float,
) -> AIDecision:
    """Parse the model's JSON and clamp it to the constraints.

    Drops unknown symbols, clips per-name weights, keeps the largest
    `max_positions`, and scales total weight down to <= 1.0. The result is safe
    to feed straight into order sizing.
    """
    data = _extract_json(raw_text)
    positions = data.get("positions", []) or []

    cleaned: dict[str, float] = {}
    for p in positions:
        try:
            symbol = str(p["symbol"]).strip().upper()
            weight = float(p["weight"])
        except (KeyError, TypeError, ValueError):
            continue
        if symbol not in allowed_symbols or weight <= 0:
            continue
        weight = min(weight, max_position_weight)
        # Keep the largest weight if the model lists a symbol twice.
        cleaned[symbol] = max(cleaned.get(symbol, 0.0), weight)

    # Keep only the largest N positions.
    if len(cleaned) > max_positions:
        kept = sorted(cleaned.items(), key=lambda kv: kv[1], reverse=True)[:max_positions]
        cleaned = dict(kept)

    # Never deploy more than 100% of the budget.
    total = sum(cleaned.values())
    if total > 1.0 and total > 0:
        cleaned = {s: w / total for s, w in cleaned.items()}

    return AIDecision(
        rationale=str(data.get("rationale", "")).strip(),
        market_view=str(data.get("market_view", "")).strip(),
        weights=cleaned,
        raw=data,
    )


def call_claude(client, model: str, system: str, prompt: str, max_tokens: int) -> str:
    """Call the Anthropic Messages API and return the text content."""
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [block.text for block in message.content if getattr(block, "type", "") == "text"]
    return "\n".join(parts).strip()


def decide_portfolio(
    client,
    model: str,
    max_tokens: int,
    context: dict,
    max_positions: int,
    max_position_weight: float,
) -> AIDecision:
    """End-to-end: build prompt, call Claude, validate the decision."""
    allowed = {c["symbol"].upper() for c in context.get("candidates", [])}
    constraints = {
        "max_positions": max_positions,
        "max_position_weight": max_position_weight,
    }
    prompt = build_prompt(context, constraints)
    raw_text = call_claude(client, model, SYSTEM_PROMPT, prompt, max_tokens)
    decision = parse_and_validate(raw_text, allowed, max_positions, max_position_weight)
    log.info("AI proposed %d positions", len(decision.weights))
    return decision
