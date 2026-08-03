#!/usr/bin/env python3
"""Run the operational, research-only golden + constituent-rotation monitor.

The runner refreshes completed EOD stock and ETF data incrementally, reports
the latest publicly available N-PORT snapshot, and writes two independent
decision artifacts:

* an ETF-leader-to-top-three-N-PORT-stock rotation decision after a supplied
  actual sector-exit signal date; and
* a 26th-of-month 5M>3M>0 ranked stock-candidate report.

It does not place orders, infer a missing risk-off exit, use unpublished N-PORT
data, or alter the frozen golden strategy.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from backtest_etf_risk_off_constituent_short import latest_public_constituents, load_weighted_constituent_snapshots


def should_run_monthly_decision(as_of: date, nominal_day: int) -> bool:
    return as_of.day >= nominal_day


def should_run_rotation_decision(signal_date: date | None, as_of: date) -> bool:
    return signal_date is not None and signal_date < as_of


def run(command: list[str], *, environment: dict[str, str], dry_run: bool) -> None:
    print("$", " ".join(command), flush=True)
    if not dry_run:
        subprocess.run(command, check=True, env=environment)


def nport_status(holdings: list[Path], as_of: date) -> dict:
    snapshots = load_weighted_constituent_snapshots(holdings)
    available = [record["publication_date"] for records in snapshots.values() for record in records if date.fromisoformat(record["publication_date"]) <= as_of]
    return {
        "holdings_files": [str(path) for path in holdings],
        "etfs_with_public_snapshot": sum(bool(latest_public_constituents(records, as_of, 1)) for records in snapshots.values()),
        "latest_publication_date": max(available) if available else "",
        "rule": "N-PORT is used only after its SEC publication date; daily refresh is intentionally not attempted.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True, help="Last completed US market session; never use an in-progress session.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--rotation-signal-date", type=date.fromisoformat, help="Actual completed ETF risk-off signal date. Omit when there is no newly exited golden sleeve to rotate.")
    parser.add_argument("--nominal-day", type=int, default=26, choices=range(1, 32))
    parser.add_argument("--holdings", type=Path, action="append", required=True)
    parser.add_argument("--rotation-universe", type=Path, default=Path("config/experiments/point_in_time_weighted_etf_eligible_universe.csv"))
    parser.add_argument("--cache-dir", type=Path, default=Path("reports/momentum_sector_matrix/raw_eodhd"))
    parser.add_argument("--stock-parquet", type=Path, default=Path("data/validated/sp500/eod_adjusted_current.parquet"))
    parser.add_argument("--stock-database", type=Path, default=Path("data/validated/sp500/market_data.duckdb"))
    parser.add_argument("--minimum-relative-volume", type=float, default=1.0)
    parser.add_argument("--selected-minimum-relative-volume", type=float, default=3.0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.15)
    parser.add_argument("--skip-stock-refresh", action="store_true")
    parser.add_argument("--skip-etf-refresh", action="store_true")
    parser.add_argument("--skip-monthly-decision", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.request_delay_seconds < 0 or args.minimum_relative_volume < 0 or args.selected_minimum_relative_volume < 0:
        parser.error("volume floors and request delay cannot be negative")
    refresh_requested = not args.skip_stock_refresh or not args.skip_etf_refresh
    if refresh_requested and not args.dry_run and not (os.environ.get("EODHD_API_TOKEN") or os.environ.get("EODHD_API_KEY")):
        parser.error("set EODHD_API_TOKEN or EODHD_API_KEY; credentials are never accepted on the command line")
    root = args.project_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    holdings = [path.expanduser().resolve() for path in args.holdings]
    required = [root / "scripts" / "update_eodhd_incremental.py", root / "scripts" / "update_eodhd_etf_incremental.py", root / "scripts" / "report_golden_rotation_constituent_decision.py", root / "scripts" / "run_monthly_momentum_lot_matrix.py", *holdings]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("required files are missing: " + ", ".join(missing))
    environment = {**os.environ, "PYTHONPATH": f"{root / 'src'}:{root / 'scripts'}"}
    commands: list[dict] = []
    if not args.skip_stock_refresh:
        command = [sys.executable, str(root / "scripts" / "update_eodhd_incremental.py"), "--project-root", str(root), "--as-of", args.as_of.isoformat(), "--output-parquet", str(root / args.stock_parquet), "--database", str(root / args.stock_database), "--request-delay-seconds", str(args.request_delay_seconds)]
        run(command, environment=environment, dry_run=args.dry_run); commands.append({"step": "stock_refresh", "command": command})
    if not args.skip_etf_refresh:
        command = [sys.executable, str(root / "scripts" / "update_eodhd_etf_incremental.py"), "--eligible-etfs", str(root / args.rotation_universe), "--as-of", args.as_of.isoformat(), "--cache-dir", str(root / args.cache_dir), "--request-delay-seconds", str(args.request_delay_seconds)]
        run(command, environment=environment, dry_run=args.dry_run); commands.append({"step": "etf_refresh", "command": command})
    nport = nport_status(holdings, args.as_of)
    (output / "nport_status.json").write_text(json.dumps(nport, indent=2) + "\n")
    rotation_output = output / "rotation"
    if should_run_rotation_decision(args.rotation_signal_date, args.as_of):
        command = [sys.executable, str(root / "scripts" / "report_golden_rotation_constituent_decision.py"), "--rotation-universe", str(root / args.rotation_universe), "--signal-date", args.rotation_signal_date.isoformat(), "--as-of", args.as_of.isoformat(), "--top-n", "3", "--minimum-relative-volume", str(args.minimum_relative_volume), "--selected-minimum-relative-volume", str(args.selected_minimum_relative_volume), "--cache-dir", str(root / args.cache_dir), "--output", str(rotation_output)]
        for holding in holdings:
            command.extend(["--holdings", str(holding)])
        run(command, environment=environment, dry_run=args.dry_run); commands.append({"step": "rotation_decision", "command": command})
    monthly_output = output / "monthly_26"
    if should_run_monthly_decision(args.as_of, args.nominal_day) and not args.skip_monthly_decision:
        month_start = date(args.as_of.year, args.as_of.month, 1)
        command = [sys.executable, str(root / "scripts" / "run_monthly_momentum_lot_matrix.py"), "--project-root", str(root), "--parquet", str(root / args.stock_parquet), "--start", month_start.isoformat(), "--end", args.as_of.isoformat(), "--rule", "5M>3M>0", "--nominal-day", str(args.nominal_day), "--ranking-metric", "5m", "--top-n", "10", "--holding-weeks", "52", "--stop", "0.45", "--max-volatility", "-1", "--disable-deterioration", "--monthly-budget", "1000", "--output", str(monthly_output)]
        run(command, environment=environment, dry_run=args.dry_run); commands.append({"step": "monthly_ranked_candidate_report", "command": command})
    result = {"as_of": args.as_of.isoformat(), "rotation_signal_date": args.rotation_signal_date.isoformat() if args.rotation_signal_date else "", "rotation_report": str(rotation_output) if should_run_rotation_decision(args.rotation_signal_date, args.as_of) else "no_actual_exit_signal_supplied", "monthly_report": str(monthly_output) if should_run_monthly_decision(args.as_of, args.nominal_day) and not args.skip_monthly_decision else "not_due_or_skipped", "nport_status": str(output / "nport_status.json"), "commands": commands, "limitations": ["The monthly output is a ranked candidate report. Confirm the existing golden portfolio's cash and six-month sector cooldown before treating it as an entry.", "N-PORT publication is quarterly and delayed; the runner uses the latest public snapshot only.", "No orders are submitted."]}
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
