#!/usr/bin/env python3
"""Run the frozen Midcap Golden 10M>6M>3M research strategy."""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from quantresearch.research.midcap_golden import MIDCAP_GOLDEN, build_backtest_command


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=date(2016, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--database", type=Path, default=Path("data/validated/sp400/eodhd_sp400_proxy_eod.duckdb"))
    p.add_argument("--membership", type=Path, default=Path("reports/sp400_wikipedia_reverse_membership_2016_2026/membership_intervals.csv"))
    p.add_argument("--corporate-action-exits", type=Path, default=Path("config/experiments/sp400_proxy_corporate_action_exits.csv"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = a.output.expanduser().resolve()
    command = build_backtest_command(
        python=sys.executable, project_root=root, start=a.start.isoformat(),
        end=a.end.isoformat(), database=a.database.expanduser().resolve(),
        membership=a.membership.expanduser().resolve(),
        corporate_actions=a.corporate_action_exits.expanduser().resolve(), output=output,
    )
    subprocess.run(command, cwd=root, check=True)
    result_path = output / "top_5_dynamic_vintage_strategies.csv"
    with result_path.open(encoding="utf-8", newline="") as handle:
        result = next(csv.DictReader(handle))
    payload = {
        "strategy_id": MIDCAP_GOLDEN.strategy_id,
        "rule": MIDCAP_GOLDEN.momentum_rule,
        "final_value": float(result["final_value"]),
        "xirr": float(result["xirr"]),
        "win_rate": float(result["win_rate"]),
        "trade_count": int(result["trade_count"]),
        "strategy_summary": str(result_path),
        "trade_ledger": str(output / "top_01_trade_ledger.csv"),
        "limitation": "Research only; approximate point-in-time S&P 400 membership proxy and adjusted daily-bar execution model.",
    }
    (output / "midcap_golden_summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
