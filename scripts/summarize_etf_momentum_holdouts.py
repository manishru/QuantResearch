#!/usr/bin/env python3
"""Summarize ETF momentum/breadth event-study results by train and holdout periods."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import fmean


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--train-end", type=date.fromisoformat, default=date(2020, 12, 31))
    parser.add_argument(
        "--holdout-start",
        type=date.fromisoformat,
        help="Optional first signal date to include in holdout; dates between train end and this date are excluded.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.events.open(newline="", encoding="utf-8") as handle:
        events = list(csv.DictReader(handle))
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for event in events:
        signal_date = date.fromisoformat(event["signal_date"])
        if signal_date <= args.train_end:
            period = "train_through_" + args.train_end.isoformat()
        elif args.holdout_start and signal_date < args.holdout_start:
            continue
        else:
            period = "holdout_from_" + (args.holdout_start or args.train_end).isoformat()
        groups[(event["basket"], period)].append(event)
    fields = ["basket", "period", "signals", "average_etf_return", "etf_win_rate", "average_constituent_return", "constituent_win_rate"]
    results = []
    for (basket, period), rows in sorted(groups.items()):
        etf = [float(row["etf_return"]) for row in rows]
        constituents = [float(row["constituent_equal_weight_return"]) for row in rows if row["constituent_equal_weight_return"]]
        results.append({
            "basket": basket, "period": period, "signals": len(rows),
            "average_etf_return": fmean(etf), "etf_win_rate": sum(value > 0 for value in etf) / len(etf),
            "average_constituent_return": fmean(constituents) if constituents else "",
            "constituent_win_rate": sum(value > 0 for value in constituents) / len(constituents) if constituents else "",
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)
    for row in results:
        print(row)


if __name__ == "__main__":
    main()
