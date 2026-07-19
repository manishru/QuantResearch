#!/usr/bin/env python3
"""Turn overlapping ETF event-study rows into fixed-capital non-overlapping trades."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import fmean


def xirr(flows: list[tuple[date, float]]) -> float | None:
    if not flows or not any(v < 0 for _, v in flows) or not any(v > 0 for _, v in flows):
        return None
    origin = min(d for d, _ in flows)
    def npv(rate: float) -> float:
        return sum(v / (1 + rate) ** ((d - origin).days / 365.25) for d, v in flows)
    low, high = -0.999, 1.0
    while npv(low) * npv(high) > 0 and high < 1_000:
        high *= 2
    if npv(low) * npv(high) > 0:
        return None
    for _ in range(100):
        mid = (low + high) / 2
        if npv(low) * npv(mid) <= 0:
            high = mid
        else:
            low = mid
    return (low + high) / 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allocation", type=float, default=1000.0)
    parser.add_argument("--from-signal", type=date.fromisoformat)
    parser.add_argument("--to-signal", type=date.fromisoformat)
    args = parser.parse_args()
    if args.allocation <= 0:
        parser.error("--allocation must be positive")
    with args.events.open(newline="", encoding="utf-8") as f:
        events = list(csv.DictReader(f))
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in events:
        signal = date.fromisoformat(row["signal_date"])
        if args.from_signal and signal < args.from_signal or args.to_signal and signal > args.to_signal:
            continue
        grouped[row["basket"]].append(row)
    selected, summary = [], []
    for basket, rows in sorted(grouped.items()):
        next_free: date | None = None
        trades = []
        for row in sorted(rows, key=lambda r: (r["entry_date"], r["exit_date"])):
            entry, exit_ = date.fromisoformat(row["entry_date"]), date.fromisoformat(row["exit_date"])
            if next_free and entry <= next_free:
                continue
            ret = float(row["etf_return"])
            trade = {**row, "allocation": args.allocation, "net_proceeds": args.allocation * (1 + ret), "net_profit": args.allocation * ret}
            trades.append(trade); selected.append(trade); next_free = exit_
        returns = [float(t["etf_return"]) for t in trades]
        flows = [(date.fromisoformat(t["entry_date"]), -args.allocation) for t in trades] + [(date.fromisoformat(t["exit_date"]), float(t["net_proceeds"])) for t in trades]
        summary.append({"basket": basket, "non_overlapping_trades": len(trades), "invested_capital": args.allocation * len(trades), "net_proceeds": sum(float(t["net_proceeds"]) for t in trades), "net_profit": sum(float(t["net_profit"]) for t in trades), "roi": sum(float(t["net_profit"]) for t in trades) / (args.allocation * len(trades)) if trades else "", "average_trade_return": fmean(returns) if returns else "", "win_rate": sum(r > 0 for r in returns) / len(returns) if returns else "", "xirr": xirr(flows)})
    args.output.mkdir(parents=True, exist_ok=True)
    fields = list(selected[0]) if selected else []
    with (args.output / "non_overlapping_trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(selected)
    fields = list(summary[0]) if summary else []
    with (args.output / "non_overlapping_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(summary)
    print(f"wrote {args.output}")

if __name__ == "__main__":
    main()
