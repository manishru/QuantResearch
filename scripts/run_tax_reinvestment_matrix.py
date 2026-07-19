#!/usr/bin/env python3
"""Replay monthly lot reports with after-tax next-purchase reinvestment."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

from quantresearch.research.tax_reinvestment import (
    TaxReinvestmentConfig,
    TradeTemplate,
    replay_tax_reinvestment,
)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-csv", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--monthly-contribution", type=float, default=10_000.0)
    parser.add_argument(
        "--contribution-months",
        type=int,
        help="Number of monthly contributions; omit to contribute at every monthly entry",
    )
    holding_period = parser.add_mutually_exclusive_group()
    holding_period.add_argument(
        "--holding-months",
        type=int,
        default=None,
        help="Scheduled holding period used by the source trade matrix",
    )
    holding_period.add_argument(
        "--holding-weeks",
        type=int,
        default=None,
        help="Calendar-week holding period used by the source trade matrix",
    )
    parser.add_argument(
        "--spread-early-exit-to-maturity",
        action="store_true",
        help="Spread early-exit proceeds over remaining monthly purchases through original maturity",
    )
    parser.add_argument(
        "--maturity-reinvestment-spread-months",
        type=int,
        default=1,
        help="Spread each normal maturity across this many purchase cycles (1 disables smoothing)",
    )
    parser.add_argument("--tax-rate", type=float, default=0.35)
    parser.add_argument("--final-date", type=date.fromisoformat, default=date(2026, 7, 10))
    parser.add_argument("--stop-label", default="45%")
    args = parser.parse_args()
    if args.holding_months is None and args.holding_weeks is None:
        args.holding_months = 12
    if args.holding_months is not None and args.holding_months < 1:
        parser.error("holding months must be positive")
    if args.holding_weeks is not None and args.holding_weeks < 1:
        parser.error("holding weeks must be positive")
    args.output.mkdir(parents=True, exist_ok=True)

    grouped: dict[tuple[str, int, int], list[dict[str, str]]] = defaultdict(list)
    for source in args.trade_csv:
        for row in _read(source.expanduser().resolve()):
            grouped[(row["rule"], int(row["nominal_day"]), int(row["top_n"]))].append(row)

    summary: list[dict[str, object]] = []
    results = {}
    originals = {}
    for key, rows in grouped.items():
        rule, nominal_day, top_n = key
        templates = []
        original_by_id = {}
        for index, row in enumerate(rows):
            template_id = f"{rule}|{nominal_day}|{top_n}|{row['target']}|{row['ticker']}|{index}"
            is_open = not row["exit_date"] or row["exit_reason"] in {"open", "open_mtm"}
            template = TradeTemplate(
                template_id,
                row["ticker"],
                date.fromisoformat(row["execution_date"]),
                None if is_open else date.fromisoformat(row["exit_date"]),
                float(row["return_pct"]),
                row["exit_reason"],
            )
            templates.append(template)
            original_by_id[template_id] = row
        result = replay_tax_reinvestment(
            templates,
            TaxReinvestmentConfig(
                args.monthly_contribution,
                args.tax_rate,
                args.final_date,
                args.contribution_months,
                args.spread_early_exit_to_maturity,
                args.maturity_reinvestment_spread_months,
                args.holding_months,
                args.holding_weeks,
            ),
        )
        results[key] = result
        originals[key] = original_by_id
        summary.append(
            {
                "rule": rule,
                "nominal_day": nominal_day,
                "top_n": top_n,
                "stop": args.stop_label,
                "trade_count": len(result.trades),
                "total_contributions": result.total_contributions,
                "ending_wealth_before_open_tax": result.ending_after_tax_wealth,
                "profit_before_open_tax": result.ending_after_tax_wealth - result.total_contributions,
                "roi_before_open_tax": result.roi,
                "xirr_before_open_tax": result.xirr,
                "net_realized_tax_paid": result.total_tax_paid,
                "ending_cash": result.ending_cash,
                "open_market_value": result.open_market_value,
                "estimated_open_liquidation_tax": result.hypothetical_liquidation_tax,
                "ending_wealth_after_full_liquidation_tax": result.ending_after_liquidation_tax,
                "profit_after_full_liquidation_tax": (
                    result.ending_after_liquidation_tax - result.total_contributions
                ),
                "roi_after_full_liquidation_tax": result.liquidation_roi,
                "xirr_after_full_liquidation_tax": result.liquidation_xirr,
                "maturity_reinvestment_spread_months": args.maturity_reinvestment_spread_months,
                "holding_months": args.holding_months,
                "holding_weeks": args.holding_weeks,
            }
        )

    summary.sort(
        key=lambda row: (
            -float(row["xirr_after_full_liquidation_tax"] or float("-inf")),
            -float(row["ending_wealth_after_full_liquidation_tax"]),
            str(row["rule"]),
            int(row["nominal_day"]),
            int(row["top_n"]),
        )
    )
    for rank, row in enumerate(summary, start=1):
        row["rank"] = rank
    _write(args.output / "tax_reinvestment_configuration_summary.csv", summary)

    best = summary[0]
    best_key = (str(best["rule"]), int(best["nominal_day"]), int(best["top_n"]))
    result = results[best_key]
    original_by_id = originals[best_key]
    trade_rows = []
    for trade in result.trades:
        original = original_by_id[trade.template_id]
        trade_rows.append(
            {
                "target": original["target"],
                "signal_date": original["signal_date"],
                "execution_date": original["execution_date"],
                "ticker": trade.ticker,
                "exit_date": original["exit_date"],
                "exit_reason": trade.exit_reason,
                "return_pct": trade.return_pct,
                "allocated_capital": trade.allocated_capital,
                "net_profit_before_tax": trade.net_profit,
                "tax_paid_or_estimated": trade.tax_paid,
                "after_tax_proceeds": trade.after_tax_proceeds,
                "is_open": trade.is_open,
                "ranking_return": original["ranking_return"],
                "return_since_start": original["return_since_start"],
                "ret42": original["ret42"],
                "ret63": original["ret63"],
                "ret126": original["ret126"],
                "ret189": original["ret189"],
                "ret252": original["ret252"],
                "volatility_1m": original["volatility_1m"],
                "inherited_eligibility_exception": original["inherited_eligibility_exception"],
                "exception_parent": original["exception_parent"],
            }
        )
    _write(args.output / "best_tax_reinvestment_trades.csv", trade_rows)
    cumulative_tax_reserve = 0.0
    ledger_rows = []
    for row in result.ledger:
        cumulative_tax_reserve += row.tax_paid
        ledger_rows.append(
            {
                "event_date": row.event_date.isoformat(),
                "event_type": row.event_type,
                "starting_cash": row.starting_cash,
                "after_tax_exit_installments": row.exit_proceeds,
                "realized_tax_reserve_change": row.tax_paid,
                "gross_tax_charge": max(row.tax_paid, 0.0),
                "loss_offset_or_tax_refund": max(-row.tax_paid, 0.0),
                "cumulative_realized_tax_reserve": cumulative_tax_reserve,
                "contribution": row.contribution,
                "invested": row.invested,
                "ending_cash": row.ending_cash,
            }
        )
    _write(
        args.output / "best_tax_reinvestment_cash_ledger.csv",
        ledger_rows,
    )
    print(
        f"Best: {best['rule']} day={best['nominal_day']} top_n={best['top_n']} "
        f"fully_taxed_wealth={best['ending_wealth_after_full_liquidation_tax']:.2f} "
        f"roi={best['roi_after_full_liquidation_tax']:.4%} "
        f"xirr={best['xirr_after_full_liquidation_tax']:.4%}"
    )


if __name__ == "__main__":
    main()
