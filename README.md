# traading

A small, well-structured **Alpaca paper-trading bot** built around a
moving-average (MA) crossover strategy. It can **backtest** the strategy on
historical data and **paper-trade** it live against Alpaca's paper endpoint.

> ⚠️ Educational project. Defaults to **paper trading** (no real money).
> Trading real money is risky — only point this at a live endpoint if you fully
> understand the consequences.

## Strategy

Classic fast/slow simple-moving-average crossover:

- **Golden cross** (fast MA crosses above slow MA) → go **long**.
- **Death cross** (fast MA crosses below slow MA) → **close** the position.

The decision logic lives in [`traading/strategy.py`](traading/strategy.py) and is
pure (operates on a list of prices), so the **exact same code** drives both the
backtester and the live bot.

## Project layout

```
traading/
├── traading/            # package
│   ├── config.py        # env-based configuration (no secrets in code)
│   ├── strategy.py      # pure MA-crossover logic
│   ├── broker.py        # Alpaca SDK wrapper (account, data, orders)
│   ├── backtest.py      # bar-by-bar backtester
│   └── bot.py           # live paper-trading loop
├── scripts/
│   ├── check_account.py # verify your keys + print account status
│   ├── run_backtest.py  # backtest over historical data
│   └── run_bot.py       # run the live (paper) bot
└── tests/               # unit tests for strategy + backtest (no network)
```

## Setup

1. **Install dependencies** (a virtualenv is recommended):

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure credentials.** Copy the example env file and fill it in:

   ```bash
   cp .env.example .env
   ```

   Then edit `.env` and set your Alpaca **paper** keys:

   ```ini
   ALPACA_API_KEY_ID=PK........
   ALPACA_API_SECRET_KEY=........
   ALPACA_BASE_URL=https://paper-api.alpaca.markets
   ```

   Get keys from the [Alpaca dashboard](https://app.alpaca.markets/) under
   **Paper Trading → API Keys**. You need both the **Key ID** and the
   **Secret Key** (the secret is shown only once on creation).

   > 🔒 `.env` is gitignored. **Never commit real keys.** If a key is ever
   > exposed, regenerate it in the Alpaca dashboard.

## Usage

Verify your connection first:

```bash
python -m scripts.check_account
```

Backtest the strategy:

```bash
python -m scripts.run_backtest                # uses SYMBOLS from .env
python -m scripts.run_backtest AAPL --days 365
```

Run the live paper bot (Ctrl+C to stop):

```bash
python -m scripts.run_bot
```

## Configuration

All behavior is set via environment variables (see `.env.example`):

| Variable        | Meaning                                            | Default |
| --------------- | -------------------------------------------------- | ------- |
| `SYMBOLS`       | Comma-separated symbols to trade                   | `AAPL,MSFT,SPY` |
| `FAST_WINDOW`   | Fast MA length (bars)                              | `10`    |
| `SLOW_WINDOW`   | Slow MA length (bars), must be > fast              | `30`    |
| `TIMEFRAME`     | Bar size: `1Min`/`5Min`/`15Min`/`1Hour`/`1Day`    | `1Day`  |
| `POSITION_SIZE` | Fraction of buying power per position (0–1)         | `0.1`   |
| `POLL_INTERVAL` | Seconds between live evaluation cycles             | `60`    |

## Tests

```bash
pip install pytest
pytest
```

The tests cover the strategy and backtester and require **no** network or
credentials.

## Notes & limitations

- The backtester ignores commissions, slippage, and partial fills — it's a
  sanity check, not a production simulator.
- The live bot trades whole shares and only acts while the market is open.
- This is **not financial advice**. Use at your own risk.
