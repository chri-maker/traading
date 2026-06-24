"""AI-driven daily trading job.

Claude looks at a fixed universe (recent prices/returns + congressional-trade
signals) and the current account, proposes a long-only target portfolio, and
the bot executes it on the PAPER account behind hard guardrails.

    python -m scripts.ai_trade --dry-run   # compute + email, place no orders
    python -m scripts.ai_trade             # live (paper)
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from alpaca.trading.enums import OrderSide

from traading.ai.strategy import decide_portfolio
from traading.broker import Broker
from traading.config import load_ai_config, load_config, load_congress_config
from traading.congress.mirror import orders_from_weights
from traading.congress.providers import build_provider
from traading.notify import send_email

log = logging.getLogger("traading.ai")


def _congress_signal(cc, window_days: int) -> dict[str, dict[str, int]]:
    """Count recent congressional buys/sells per ticker (best-effort)."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"buys": 0, "sells": 0})
    try:
        provider = build_provider(cc.provider, cc.fmp_api_key)
        trades = provider.fetch_recent_trades(pages=cc.fetch_pages)
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=window_days)
        for t in trades:
            if t.tx_date < cutoff:
                continue
            if t.tx_type == "buy":
                counts[t.ticker]["buys"] += 1
            elif t.tx_type == "sell":
                counts[t.ticker]["sells"] += 1
    except Exception:
        log.warning("Congress signal unavailable; continuing without it", exc_info=True)
    return counts


def _build_context(broker: Broker, ai_cfg, cc, today: date) -> dict:
    account = broker.get_account()
    equity = float(account.portfolio_value)
    holdings = broker.get_all_positions()

    universe = broker.tradable_symbols(ai_cfg.universe)
    signal = _congress_signal(cc, cc.window_days) if ai_cfg.use_congress else {}

    candidates = []
    ref_day = today - timedelta(days=30)
    for symbol in universe:
        price = broker.latest_price(symbol)
        if not price:
            continue
        past = broker.price_on(symbol, ref_day)
        ret = (price - past) / past if past and past > 0 else None
        sig = signal.get(symbol, {})
        candidates.append(
            {
                "symbol": symbol,
                "price": price,
                "return_30d": ret,
                "congress_buys": sig.get("buys", 0),
                "congress_sells": sig.get("sells", 0),
            }
        )

    return {
        "account": {"equity": equity, "cash": float(account.cash)},
        "holdings": holdings,
        "candidates": candidates,
    }


def _format_summary(today, decision, orders, executed, account, notes) -> str:
    lines = [f"AI strategy daily summary — {today.isoformat()}", "=" * 60]
    lines.append(f"\nMarket view: {decision.market_view or '(none)'}")
    lines.append(f"\nRationale:\n  {decision.rationale or '(none)'}")
    lines.append("\nTarget portfolio (weights):")
    if decision.weights:
        for sym, w in sorted(decision.weights.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"  {sym:<6} {w:6.1%}")
    else:
        lines.append("  (all cash — no positions)")
    verb = "Executed" if executed else "Planned (dry-run)"
    lines.append(f"\n{verb} orders: {len(orders)}")
    for o in orders:
        lines.append(f"  {o.side.upper():<4} {o.qty:>5} {o.symbol:<6} (target={o.target_shares}, held={o.current_shares})")
    if account:
        lines.append("\nAccount snapshot:")
        for k in ("status", "cash", "buying_power", "portfolio_value"):
            if k in account:
                lines.append(f"  {k:<15}: {account[k]}")
    if notes:
        lines.append("\nNotes:")
        for n in notes:
            lines.append(f"  - {n}")
    lines.append("\n— traading AI bot. Paper trading. Not financial advice.")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description="AI-driven daily trading job.")
    parser.add_argument("--dry-run", action="store_true", help="Don't place orders.")
    args = parser.parse_args()

    ai_cfg = load_ai_config()
    cc = load_congress_config()
    dry_run = args.dry_run or ai_cfg.dry_run
    today = datetime.now(timezone.utc).date()
    notes: list[str] = []

    if not ai_cfg.ai_configured:
        raise SystemExit("ANTHROPIC_API_KEY is not set — cannot run the AI strategy.")

    alpaca_config = load_config()
    if not alpaca_config.is_paper and not ai_cfg.allow_live:
        raise SystemExit(
            f"Refusing to run against a non-paper account ({alpaca_config.base_url}). "
            "Set AI_ALLOW_LIVE=true to override."
        )
    broker = Broker(alpaca_config)
    if not alpaca_config.is_paper:
        notes.append("LIVE ACCOUNT: trading real money (AI_ALLOW_LIVE=true).")

    # --- Build context + ask Claude ---------------------------------------
    import anthropic

    context = _build_context(broker, ai_cfg, cc, today)
    log.info("Universe size after filtering: %d", len(context["candidates"]))
    client = anthropic.Anthropic(api_key=ai_cfg.anthropic_api_key)
    decision = decide_portfolio(
        client, ai_cfg.model, ai_cfg.max_tokens, context,
        ai_cfg.max_positions, ai_cfg.max_position_weight,
    )

    # --- Turn weights into orders -----------------------------------------
    account = broker.get_account()
    account_snapshot = {
        "status": account.status,
        "cash": f"${float(account.cash):,.2f}",
        "buying_power": f"${float(account.buying_power):,.2f}",
        "portfolio_value": f"${float(account.portfolio_value):,.2f}",
    }
    equity = float(account.portfolio_value)
    holdings = broker.get_all_positions()
    orders = orders_from_weights(
        decision.weights, broker, equity, holdings,
        allocation=ai_cfg.allocation, exit_unlisted=True,
    )

    executed = False
    if dry_run:
        notes.append("DRY-RUN: orders computed but not submitted.")
    elif not broker.is_market_open():
        notes.append("Market closed: orders not submitted.")
    else:
        for o in orders:
            try:
                side = OrderSide.BUY if o.side == "buy" else OrderSide.SELL
                broker.submit_market_order(o.symbol, o.qty, side)
            except Exception as exc:
                notes.append(f"Order failed {o.side} {o.qty} {o.symbol}: {exc}")
        executed = True

    summary = _format_summary(today, decision, orders, executed, account_snapshot, notes)
    print(summary)

    subject = f"[traading AI] {today.isoformat()} — {len(orders)} orders, {len(decision.weights)} targets"
    send_email(cc, subject, summary)
    log.info("AI job done.")


if __name__ == "__main__":
    main()
