"""Run the live (paper) trading bot.

    python -m scripts.run_bot

Stop with Ctrl+C. Configure behavior via .env (symbols, windows, interval).
"""

from __future__ import annotations

from traading.bot import main

if __name__ == "__main__":
    main()
