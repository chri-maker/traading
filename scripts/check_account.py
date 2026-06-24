"""Verify the Alpaca connection and print account status.

Run this first to confirm your keys work:
    python -m scripts.check_account
"""

from __future__ import annotations

import logging

from traading.broker import Broker
from traading.config import load_config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = load_config()
    broker = Broker(config)

    account = broker.get_account()
    clock_open = broker.is_market_open()

    print("=== Alpaca account ===")
    print(f"Mode          : {'PAPER' if config.is_paper else 'LIVE'}")
    print(f"Account #     : {account.account_number}")
    print(f"Status        : {account.status}")
    print(f"Currency      : {account.currency}")
    print(f"Cash          : ${float(account.cash):,.2f}")
    print(f"Buying power  : ${float(account.buying_power):,.2f}")
    print(f"Portfolio val : ${float(account.portfolio_value):,.2f}")
    print(f"Market open   : {clock_open}")
    print(f"Symbols       : {', '.join(config.symbols)}")


if __name__ == "__main__":
    main()
