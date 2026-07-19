#!/usr/bin/env python3
"""Summarize completed weekly holding-period groups by portfolio size."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _number(value: str | None) -> float:
    return float(value) if value not in (None, "") else float("-inf")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List the best completed weekly-holding strategy for each Top N."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("reports/weekly_holding_period_matrix"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit-per-top-n", type=int, default=10)
    args = parser.parse_args()
    if args.limit_per_top_n < 1:
        parser.error("limit-per-top-n must be positive")

    source = args.input.expanduser().resolve()
    output = (args.output or source / "top_n_strategy_summary").resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    skipped = 0
    for marker in sorted((source / "groups").glob("week_*/*/stop_*/group_result.json")):
        group = marker.parent
        summary_file = group / "tax_reinvestment_configuration_summary.csv"
        try:
            metadata = json.loads(marker.read_text(encoding="utf-8"))
            fingerprint = str(metadata["fingerprint"])
            selector = metadata["selector"]
            if not summary_file.is_file():
                skipped += 1
                continue
            for row in _read_csv(summary_file):
                rows.append(
                    {
                        "holding_weeks": int(selector["holding_weeks"]),
                        "rule": row["rule"],
                        "stop": float(selector["stop"]),
                        "nominal_day": int(row["nominal_day"]),
                        "top_n": int(row["top_n"]),
                        "funded_stock_trades": int(row["trade_count"]),
                        "total_contributions": float(row["total_contributions"]),
                        "fully_taxed_wealth": float(
                            row["ending_wealth_after_full_liquidation_tax"]
                        ),
                        "fully_taxed_roi": float(row["roi_after_full_liquidation_tax"]),
                        "fully_taxed_xirr": _number(
                            row["xirr_after_full_liquidation_tax"]
                        ),
                        "open_market_value": float(row["open_market_value"]),
                        "estimated_open_tax": float(
                            row["estimated_open_liquidation_tax"]
                        ),
                        "group_path": str(group),
                        "fingerprint": fingerprint,
                    }
                )
        except (KeyError, ValueError, json.JSONDecodeError):
            skipped += 1

    rows.sort(
        key=lambda row: (
            int(row["top_n"]),
            -float(row["fully_taxed_xirr"]),
            -float(row["fully_taxed_wealth"]),
            int(row["holding_weeks"]),
            str(row["rule"]),
            float(row["stop"]),
            int(row["nominal_day"]),
        )
    )
    _write_csv(output / "all_completed_configurations.csv", rows)
    best: list[dict[str, object]] = []
    for top_n in range(1, 6):
        candidates = [row for row in rows if int(row["top_n"]) == top_n]
        for rank, row in enumerate(candidates[: args.limit_per_top_n], start=1):
            best.append({"portfolio_rank": rank, **row})
    _write_csv(output / "best_strategies_by_top_n.csv", best)

    print(f"Completed configuration rows: {len(rows):,}")
    print(f"Skipped incomplete/invalid groups: {skipped:,}")
    print(f"Written: {output / 'best_strategies_by_top_n.csv'}")
    for top_n in range(1, 6):
        winner = next((row for row in best if int(row["top_n"]) == top_n), None)
        if winner:
            print(
                f"Top {top_n}: {winner['holding_weeks']}W | {winner['rule']} | "
                f"stop {float(winner['stop']):.0%} | day {winner['nominal_day']} | "
                f"XIRR {float(winner['fully_taxed_xirr']):.2%}"
            )


if __name__ == "__main__":
    main()
