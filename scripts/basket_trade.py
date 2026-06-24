"""Rules-based diversified basket: hold ~20 equal-weight stock + crypto
positions and rebalance the (paper) account toward them.

    python -m scripts.basket_trade --dry-run   # compute + email, place no orders
    python -m scripts.basket_trade             # live (paper)
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from alpaca.trading.enums import OrderSide

from traading.basket import canon, compute_basket_orders, equal_weights
from traading.broker import Broker
from traading.config import load_basket_config, load_config, load_congress_config
from traading.notify import send_email

log = logging.getLogger("traading.basket")


def _format_summary(today, weights, orders, executed, account, notes):
    lines = [f"Diversified basket summary — {today}", "=" * 60]
    lines.append(f"\nTarget basket: {len(weights)} equal-weight positions")
    lines.append("  " + ", ".join(sorted(weights)))
    verb = "Executed" if executed else "Planned (dry-run)"
    lines.append(f"\n{verb} orders: {len(orders)}")
    for o in orders:
        lines.append(f"  {o.side.upper():<5} {o.qty:>12.6f} {o.symbol:<10} — {o.reason}")
    if account:
        lines.append("\nAccount snapshot:")
        for k in ("status", "cash", "buying_power", "portfolio_value"):
            if k in account:
                lines.append(f"  {k:<15}: {account[k]}")
    if notes:
        lines.append("\nNotes:")
        for n in notes:
            lines.append(f"  - {n}")
    lines.append("\n— traading basket bot. Paper trading. Not financial advice.")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Diversified basket strategy.")
    parser.add_argument("--dry-run", action="store_true", help="Don't place orders.")
    args = parser.parse_args()

    cfg = load_basket_config()
    cc = load_congress_config()  # reused only for email settings
    today = datetime.now(timezone.utc).date().isoformat()
    notes: list[str] = []

    alpaca_config = load_config()
    if not alpaca_config.is_paper and not cfg.allow_live:
        raise SystemExit(
            f"Refusing to run against a non-paper account ({alpaca_config.base_url}). "
            "Set BASKET_ALLOW_LIVE=true to override."
        )
    broker = Broker(alpaca_config)
    dry_run = args.dry_run or cfg.dry_run

    weights = equal_weights(cfg.universe, cfg.size)

    account = broker.get_account()
    account_snapshot = {
        "status": account.status,
        "cash": f"${float(account.cash):,.2f}",
        "buying_power": f"${float(account.buying_power):,.2f}",
        "portfolio_value": f"${float(account.portfolio_value):,.2f}",
    }
    equity = float(account.portfolio_value)
    current = {canon(s): (s, q) for s, q in broker.get_all_positions().items()}

    orders = compute_basket_orders(
        weights, broker.latest_price, equity, current, allocation=cfg.allocation
    )

    executed = False
    market_open = broker.is_market_open()
    if dry_run:
        notes.append("DRY-RUN: orders computed but not submitted.")
    else:
        for o in orders:
            # Stock orders need an open market; crypto trades 24/7.
            if not o.is_crypto and not market_open:
                notes.append(f"Market closed: skipped {o.side} {o.symbol}.")
                continue
            try:
                if o.side == "exit":
                    broker.close_position(o.symbol)
                else:
                    side = OrderSide.BUY if o.side == "buy" else OrderSide.SELL
                    broker.submit_market_order(o.symbol, o.qty, side)
            except Exception as exc:
                notes.append(f"Order failed {o.side} {o.qty} {o.symbol}: {exc}")
        executed = True

    summary = _format_summary(today, weights, orders, executed, account_snapshot, notes)
    print(summary)
    send_email(cc, f"[traading basket] {today} — {len(orders)} orders", summary)
    log.info("Basket job done.")


if __name__ == "__main__":
    main()
