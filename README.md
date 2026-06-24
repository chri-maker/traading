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

---

# Congress-mirror bot

A second, independent strategy: rank the most active members of Congress by
their **estimated** trailing-12-month return (from public STOCK Act
disclosures), **mirror the top performer's positions** in your Alpaca paper
account, and **email you a summary** each weekday morning.

## ⚠️ Read this before trusting it

The data this is built on is fundamentally limited, so parts of it are
**estimates, not facts**:

- **No published returns.** Disclosures contain transactions (buy/sell, a
  **dollar range** like `$1,001–$15,000`, and dates) — *not* share counts, cost
  basis, full portfolios, or P&L. The per-member "return" is **estimated** by
  assuming the midpoint of each disclosed buy was invested at that day's close
  and held to today. It is a rough heuristic, **not a measured track record**.
- **Disclosures are delayed up to ~30–45 days.** You are copying trades that
  already happened weeks ago; prices have moved and most of the "edge" is gone.
- **Capitol Trades has no public API** and is bot-protected, so this uses a
  third-party aggregator — **Financial Modeling Prep** (free tier, House +
  Senate). The provider is pluggable (`traading/congress/providers.py`).
- **Position sizes are approximated** from net disclosed dollar ranges and
  scaled to your account — they mirror *direction and rough conviction*, not the
  member's actual sizing.

This is an educational **paper-trading** project. Not financial advice.

## How it works

```
FMP disclosures ─▶ rank_members (est. trailing-12mo return)
                       │
                       ▼
                 pick top performer ─▶ reconstruct implied long book
                       │                       │
                       ▼                       ▼
              detect NEW disclosures    compute target weights ─▶ paper orders
                       │                       │
                       └────────▶ email summary ◀┘
```

Modules live in [`traading/congress/`](traading/congress/): `providers.py`
(data), `performance.py` (ranking), `mirror.py` (position → orders),
`state.py` (new-disclosure tracking), `report.py` (summary). Email is in
[`traading/notify.py`](traading/notify.py).

## Try it offline first (no keys, no network)

```bash
python -m scripts.rank_members --sample        # leaderboard from bundled fixture
python -m scripts.daily_job --sample --dry-run # full pipeline, fake prices, no orders
```

## Run it for real

1. Fill in the **Congress-mirror** section of `.env` (see `.env.example`):
   `FMP_API_KEY`, the `SMTP_*`/`EMAIL_*` values, and `MIRROR_ALLOCATION`.
2. Preview without trading:
   ```bash
   python -m scripts.daily_job --dry-run
   ```
3. Run live (paper): `python -m scripts.daily_job`

> Heads-up: none of the required hosts (Alpaca, FMP, SMTP) are reachable from
> every environment. Run where outbound internet is open — your machine or the
> GitHub Action below.

## Scheduling (GitHub Actions)

[`.github/workflows/congress-mirror.yml`](.github/workflows/congress-mirror.yml)
runs the job every weekday near US market open and commits the
`state/seen_disclosures.json` file back so "new disclosure" detection persists
between runs.

Add these in **repo Settings → Secrets and variables → Actions**:

| Secret | What |
| ------ | ---- |
| `ALPACA_API_KEY_ID` | Your Alpaca paper Key ID |
| `ALPACA_API_SECRET_KEY` | Your Alpaca paper Secret Key |
| `FMP_API_KEY` | Financial Modeling Prep key |
| `SMTP_USER` | Gmail address |
| `SMTP_PASS` | Gmail **App Password** (16-char, 2FA required) |

| Variable (optional) | Default |
| ------------------- | ------- |
| `EMAIL_TO` | (set to your inbox) |
| `EMAIL_FROM` | `SMTP_USER` |
| `MIRROR_ALLOCATION` | `0.5` |
| `MIRROR_MAX_POSITIONS` | (none) |
| `MIRROR_MAX_POSITION_PCT` | (none) — e.g. `0.34` caps any name at 34% |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` |

### Safety guards

- **Paper-only by default.** The job refuses to submit orders against a
  non-paper account unless you explicitly set `MIRROR_ALLOW_LIVE=true`.
- **Market-hours check.** Orders are only submitted when the market is open;
  the summary email still sends regardless.
- **Per-name cap.** `MIRROR_MAX_POSITION_PCT` clips any single position's share
  of the mirror (excess is redistributed), so one large disclosed buy can't
  dominate the account.
- **Dry-run.** `--dry-run` (or `MIRROR_DRY_RUN=true`) computes and emails
  without trading.

Trigger a manual run (with optional dry-run) from the **Actions** tab once
secrets are set. The cron is `35 13 * * 1-5` (UTC ≈ 09:35 ET in summer); adjust
for winter EST if you want exact market-open timing — the job already refuses to
submit orders when the market is closed.
