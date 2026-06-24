"""Close every open position on the (paper) account — flatten to cash.

    python -m scripts.close_all              # live (paper): liquidate all
    python -m scripts.close_all --dry-run    # show what would be closed
"""

from __future__ import annotations

import argparse
import logging

from traading.broker import Broker
from traading.config import load_ai_config, load_config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Liquidate all open positions.")
    parser.add_argument("--dry-run", action="store_true", help="Show positions, don't sell.")
    args = parser.parse_args()

    config = load_config()
    ai_cfg = load_ai_config()
    if not config.is_paper and not ai_cfg.allow_live:
        raise SystemExit(
            f"Refusing to flatten a non-paper account ({config.base_url}). "
            "Set AI_ALLOW_LIVE=true to override."
        )

    broker = Broker(config)
    positions = broker.get_all_positions()

    if not positions:
        print("No open positions — account is already flat.")
        return

    print("Open positions:")
    for sym, qty in positions.items():
        print(f"  {sym:<6} {qty:>10}")

    if args.dry_run:
        print("\nDRY-RUN: nothing closed.")
        return

    if not broker.is_market_open():
        print("\nMarket is closed — orders would queue. Submitting close-all anyway.")

    broker.close_all_positions(cancel_orders=True)
    print(f"\nSubmitted close-all for {len(positions)} position(s). Account flattening to cash.")


if __name__ == "__main__":
    main()
