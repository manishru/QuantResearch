#!/usr/bin/env python3
"""Run fixed-contribution weekly-entry momentum tests for short holding periods.

Each weekday is an independent schedule: $1,000 (by default) is contributed on
each selected weekday, with no reinvestment and no tax replay. A holiday moves
the entry to the next available market session, using the prior completed close.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


RULES = (
    "3M>2M>0", "4M>2M>0", "5M>2M>0", "5M>3M>0",
    "6M>3M>0 & 2M>0", "6M>4M>0", "7M>4M>0",
    "8M>5M>0", "9M>6M>0",
)
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--holding-weeks", type=int, action="append", choices=(1, 2), default=[])
    parser.add_argument("--rule", action="append", choices=RULES, default=[])
    parser.add_argument("--stop", type=float, action="append", default=[])
    parser.add_argument("--top-n", type=int, action="append", choices=range(1, 6), default=[])
    parser.add_argument("--weekday", type=int, action="append", choices=range(5), default=[])
    parser.add_argument("--weekday-budget", type=float, default=1_000.0)
    parser.add_argument("--max-volatility", type=float, default=0.15)
    parser.add_argument("--exclude-ticker", action="append", default=["CVC"])
    args = parser.parse_args()
    if args.weekday_budget <= 0:
        parser.error("weekday budget must be positive")
    holds = sorted(set(args.holding_weeks or [1, 2]))
    rules = args.rule or list(RULES)
    stops = args.stop or [0.05, 0.08, 0.10, 0.12, 0.15]
    tops = sorted(set(args.top_n or [1, 2, 3]))
    weekdays = sorted(set(args.weekday or range(5)))
    if any(not 0 < stop < 1 for stop in stops):
        parser.error("each stop must be between zero and one")

    root = args.project_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    monthly = root / "scripts/run_monthly_momentum_lot_matrix.py"
    comparisons: list[dict[str, object]] = []
    for hold in holds:
        for rule in rules:
            for stop in stops:
                group = output / "groups" / f"week_{hold:02d}" / rule.replace(">", "_").replace(" ", "_").replace("&", "and") / f"stop_{stop:.0%}"
                work = group / "_work"
                if work.exists():
                    shutil.rmtree(work)
                matrix = work / "matrix"
                command = [
                    sys.executable, str(monthly), "--project-root", str(root), "--output", str(matrix),
                    "--start", args.start, "--end", args.end, "--holding-weeks", str(hold),
                    "--stop", str(stop), "--monthly-budget", str(args.weekday_budget),
                    "--max-volatility", str(args.max_volatility), "--disable-deterioration", "--rule", rule,
                ]
                for weekday in weekdays:
                    command += ["--entry-weekday", str(weekday)]
                for top_n in tops:
                    command += ["--top-n", str(top_n)]
                for ticker in args.exclude_ticker:
                    command += ["--exclude-ticker", ticker]
                subprocess.run(command, check=True, env={**os.environ, "PYTHONPATH": str(root / "src")})
                summary = _read_csv(matrix / "configuration_summary.csv")
                winner = max(summary, key=lambda row: (float(row["xirr"] or "-inf"), float(row["roi"])))
                group.mkdir(parents=True, exist_ok=True)
                shutil.copy2(matrix / "configuration_summary.csv", group / "simple_weekly_configuration_summary.csv")
                all_trades = _read_csv(matrix / "all_trades.csv")
                selected = [
                    row for row in all_trades
                    if int(row["nominal_day"]) == int(winner["nominal_day"])
                    and int(row["top_n"]) == int(winner["top_n"])
                ]
                _write_csv(group / "best_simple_weekly_trades.csv", selected)
                result = {
                    **winner,
                    "holding_weeks": hold,
                    "rule": rule,
                    "stop": stop,
                    "weekday": WEEKDAY_NAMES[int(winner["nominal_day"])],
                    "weekday_budget": args.weekday_budget,
                    "calculation_mode": "fixed_weekday_contribution_no_reinvestment_no_tax",
                }
                (group / "group_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                comparisons.append(result)
                print(f"DONE hold={hold}w rule={rule} stop={stop:.0%} weekday={result['weekday']} xirr={float(result['xirr']):.2%}", flush=True)
    comparisons.sort(key=lambda row: (-float(row["xirr"] or "-inf"), -float(row["roi"]), -float(row["win_rate"])))
    for rank, row in enumerate(comparisons, start=1):
        row["rank"] = rank
    _write_csv(output / "comparison.csv", comparisons)
    run = {"output": str(output), "holding_weeks": holds, "rules": rules, "stops": stops, "weekdays": [WEEKDAY_NAMES[d] for d in weekdays], "weekday_budget": args.weekday_budget, "best": comparisons[0] if comparisons else None}
    (output / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(run, indent=2))


if __name__ == "__main__":
    main()
