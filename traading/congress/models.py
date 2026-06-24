"""Data models for congressional trade disclosures.

A disclosure (a "periodic transaction report" under the STOCK Act) tells us a
member of Congress bought or sold an asset, in a dollar *range*, on a given
date, and that it was publicly disclosed on a (usually much later) date.

Crucially, disclosures do NOT contain exact share counts, cost basis, or the
member's full portfolio. Everything derived from them — position sizes, returns
— is therefore an estimate. See performance.py / mirror.py for the assumptions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Trade:
    """A single disclosed congressional transaction."""

    politician: str
    chamber: str  # "House" | "Senate" | ""
    party: str  # "Democrat" | "Republican" | "Other" | ""
    ticker: str
    tx_type: str  # "buy" | "sell" | "exchange"
    tx_date: date  # when the trade happened
    disclosed_date: date  # when it was publicly disclosed
    amount_low: float  # lower bound of the disclosed USD range
    amount_high: float  # upper bound of the disclosed USD range
    asset_type: str = "stock"

    @property
    def amount_mid(self) -> float:
        """Midpoint of the disclosed dollar range — our point estimate of size."""
        return (self.amount_low + self.amount_high) / 2.0

    @property
    def signed_amount(self) -> float:
        """+mid for buys, -mid for sells, 0 otherwise."""
        if self.tx_type == "buy":
            return self.amount_mid
        if self.tx_type == "sell":
            return -self.amount_mid
        return 0.0

    @property
    def id(self) -> str:
        """Stable identifier used to detect previously-seen disclosures."""
        raw = "|".join(
            [
                self.politician.lower().strip(),
                self.ticker.upper().strip(),
                self.tx_type,
                self.tx_date.isoformat(),
                self.disclosed_date.isoformat(),
                f"{self.amount_low:.0f}-{self.amount_high:.0f}",
            ]
        )
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


@dataclass
class MemberPerformance:
    """Estimated trailing-window performance for one member of Congress."""

    politician: str
    chamber: str
    party: str
    num_trades: int
    estimated_return: float  # weighted unrealized return on disclosed buys
    invested_amount: float  # sum of midpoints used in the estimate
    tickers: list[str] = field(default_factory=list)

    def as_row(self) -> str:
        return (
            f"{self.politician:<28} {self.chamber:<7} {self.party:<10} "
            f"trades={self.num_trades:<3} est.return={self.estimated_return:+7.1%} "
            f"~${self.invested_amount:,.0f}"
        )
