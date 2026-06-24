"""Build the human-readable daily summary."""

from __future__ import annotations

from datetime import date

from .mirror import MirrorOrder
from .models import MemberPerformance, Trade


def build_summary(
    run_date: date,
    new_disclosures: list[Trade],
    ranking: list[MemberPerformance],
    chosen: MemberPerformance | None,
    orders: list[MirrorOrder],
    executed: bool,
    account_snapshot: dict | None,
    notes: list[str] | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"Congress-mirror daily summary — {run_date.isoformat()}")
    lines.append("=" * 60)

    lines.append(f"\nNew disclosures since last run: {len(new_disclosures)}")
    for t in new_disclosures[:25]:
        lines.append(
            f"  {t.disclosed_date}  {t.politician:<24} {t.tx_type.upper():<4} "
            f"{t.ticker:<6} ${t.amount_low:,.0f}-${t.amount_high:,.0f} "
            f"(traded {t.tx_date})"
        )
    if len(new_disclosures) > 25:
        lines.append(f"  ... and {len(new_disclosures) - 25} more")

    lines.append("\nMost active members by estimated trailing-12mo return:")
    lines.append("  (estimate from disclosed buys + prices — not a measured return)")
    for i, m in enumerate(ranking[:10], 1):
        lines.append(f"  {i:>2}. {m.as_row()}")

    if chosen:
        lines.append(f"\nMirroring TOP performer: {chosen.politician} "
                     f"({chosen.chamber}, {chosen.party})")
        lines.append(f"  est.return={chosen.estimated_return:+.1%}  "
                     f"trades={chosen.num_trades}  tickers={', '.join(chosen.tickers)}")
    else:
        lines.append("\nNo qualifying member to mirror this run.")

    verb = "Executed" if executed else "Planned (dry-run)"
    lines.append(f"\n{verb} orders: {len(orders)}")
    for o in orders:
        lines.append(
            f"  {o.side.upper():<4} {o.qty:>5} {o.symbol:<6} "
            f"(target={o.target_shares}, held={o.current_shares}) — {o.reason}"
        )

    if account_snapshot:
        lines.append("\nAccount snapshot:")
        for key in ("status", "cash", "buying_power", "portfolio_value"):
            if key in account_snapshot:
                lines.append(f"  {key:<15}: {account_snapshot[key]}")

    if notes:
        lines.append("\nNotes:")
        for n in notes:
            lines.append(f"  - {n}")

    lines.append("\n— traading bot. Paper trading. Not financial advice.")
    return "\n".join(lines)
