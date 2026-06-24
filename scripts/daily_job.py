"""Weekday market-open job: detect new disclosures, mirror the top performer,
email a summary. Intended to run from GitHub Actions cron.

    python -m scripts.daily_job              # live
    python -m scripts.daily_job --dry-run    # compute + email, place no orders
    python -m scripts.daily_job --sample     # fully offline (fixtures, fake prices)
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timezone

from alpaca.trading.enums import OrderSide

from traading.broker import Broker
from traading.config import load_config, load_congress_config
from traading.congress.mirror import compute_mirror_orders
from traading.congress.performance import rank_members
from traading.congress.providers import build_provider
from traading.congress.report import build_summary
from traading.congress.state import SeenStore
from traading.notify import send_email

log = logging.getLogger("traading.daily")


class _SamplePrices:
    def latest_price(self, symbol: str) -> float:
        return 100.0 + (sum(map(ord, symbol)) % 50)

    def price_on(self, symbol: str, day: date) -> float:
        return 90.0 + (sum(map(ord, symbol)) % 40)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description="Daily congress-mirror job.")
    parser.add_argument("--dry-run", action="store_true", help="Don't place orders.")
    parser.add_argument("--sample", action="store_true", help="Fully offline run.")
    args = parser.parse_args()

    cc = load_congress_config()
    dry_run = args.dry_run or cc.dry_run
    today = datetime.now(timezone.utc).date()
    notes: list[str] = []

    # --- Data source + prices + broker ------------------------------------
    if args.sample:
        provider = build_provider("sample")
        prices = _SamplePrices()
        broker = None
        notes.append("SAMPLE MODE: fixtures + fake prices, no real account.")
    else:
        alpaca_config = load_config()
        # Safety guard: never fire live-money orders unless explicitly allowed.
        if not alpaca_config.is_paper and not cc.allow_live:
            raise SystemExit(
                "Refusing to run against a non-paper account "
                f"({alpaca_config.base_url}). Set MIRROR_ALLOW_LIVE=true to override."
            )
        broker = Broker(alpaca_config)
        provider = build_provider(cc.provider, cc.fmp_api_key)
        prices = broker
        if not alpaca_config.is_paper:
            notes.append("LIVE ACCOUNT: trading real money (MIRROR_ALLOW_LIVE=true).")

    trades = provider.fetch_recent_trades(pages=cc.fetch_pages)

    # --- New-disclosure detection -----------------------------------------
    store = SeenStore()
    new_disclosures = store.new_trades(trades)

    # --- Rank + pick top ---------------------------------------------------
    ranking = rank_members(
        trades, prices, today,
        window_days=cc.window_days, min_trades=cc.min_trades,
    )
    chosen = ranking[0] if ranking else None

    # --- Compute + (optionally) execute mirror orders ---------------------
    orders: list = []
    executed = False
    account_snapshot = None

    if chosen:
        member_trades = [t for t in trades if t.politician == chosen.politician]
        if broker is not None:
            equity = float(broker.get_account().portfolio_value)
            current = broker.get_all_positions()
            account = broker.get_account()
            account_snapshot = {
                "status": account.status,
                "cash": f"${float(account.cash):,.2f}",
                "buying_power": f"${float(account.buying_power):,.2f}",
                "portfolio_value": f"${float(account.portfolio_value):,.2f}",
            }
            market_open = broker.is_market_open()
        else:
            equity, current, market_open = 100_000.0, {}, True

        orders = compute_mirror_orders(
            member_trades, prices, equity, current, today,
            window_days=cc.window_days, allocation=cc.mirror_allocation,
            max_positions=cc.max_positions,
            max_position_weight=cc.max_position_weight,
        )

        if dry_run:
            notes.append("DRY-RUN: orders computed but not submitted.")
        elif broker is None:
            notes.append("No broker (sample mode): orders not submitted.")
        elif not market_open:
            notes.append("Market closed: orders not submitted.")
        else:
            for o in orders:
                try:
                    side = OrderSide.BUY if o.side == "buy" else OrderSide.SELL
                    broker.submit_market_order(o.symbol, o.qty, side)
                except Exception as exc:
                    notes.append(f"Order failed {o.side} {o.qty} {o.symbol}: {exc}")
            executed = True

    # --- Summary + email ---------------------------------------------------
    summary = build_summary(
        today, new_disclosures, ranking, chosen, orders, executed,
        account_snapshot, notes,
    )
    print(summary)

    if not args.sample:
        subject = f"[traading] Congress mirror {today.isoformat()} — {len(new_disclosures)} new"
        send_email(cc, subject, summary)

    # --- Persist state -----------------------------------------------------
    store.mark_seen(trades)
    store.save()
    log.info("Done. %d disclosures known.", len(store))


if __name__ == "__main__":
    main()
