#!/usr/bin/env python3
"""Run a resumable point-in-time weekly holding-period momentum matrix.

This command intentionally leaves raw market data untouched.  It delegates each
group to the existing monthly-entry matrix and tax replay, then retains only the
group winner's evidence plus a compact cross-group comparison.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path


RULES = (
    "12M>9M>6M>3M>0",
    "12M>6M>3M>0",
    "12M>9M>6M>3M>0 & 2M>0", "9M>6M>3M>0 & 2M>0", "6M>3M>0 & 2M>0",
    "5M>2M>0", "5M>3M>0", "6M>4M>0", "4M>2M>0", "3M>2M>0",
    "7M>4M>0", "8M>5M>0", "9M>6M>0",
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _completed(group: Path, fingerprint: str, summary_name: str) -> bool:
    marker, summary = group / "group_result.json", group / summary_name
    if not marker.is_file() or not summary.is_file():
        return False
    try:
        return json.loads(marker.read_text(encoding="utf-8")).get("fingerprint") == fingerprint
    except json.JSONDecodeError:
        return False


def _safe_component(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2016, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 7, 10))
    parser.add_argument("--weeks-start", type=int, default=1)
    parser.add_argument("--weeks-end", type=int, default=52)
    parser.add_argument(
        "--week",
        type=int,
        action="append",
        choices=range(1, 53),
        help="Evaluate only this holding period in weeks; repeat to select a non-contiguous set",
    )
    parser.add_argument("--rule", action="append", choices=RULES)
    parser.add_argument("--stop", type=float, action="append")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Independent week/rule/stop groups to run concurrently (default: 1; increase only after a stability check)",
    )
    parser.add_argument("--monthly-budget", type=float, default=10_000.0)
    parser.add_argument(
        "--nominal-day",
        type=int,
        action="append",
        choices=range(1, 32),
        help="Evaluate only this monthly purchase day; repeat to select multiple days",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        action="append",
        choices=range(1, 6),
        help="Evaluate only this number of top-ranked stocks; repeat to select multiple values",
    )
    parser.add_argument("--tax-rate", type=float, default=0.35)
    parser.add_argument(
        "--simple-equal-contribution",
        action="store_true",
        help="Rank fixed monthly contributions without tax calculation or reinvestment",
    )
    parser.add_argument(
        "--contribution-months",
        type=int,
        help="Number of monthly contributions; omit to contribute at every monthly entry",
    )
    parser.add_argument("--max-volatility", type=float, default=0.10)
    parser.add_argument(
        "--max-open-lots-per-ticker",
        type=int,
        help="Maximum overlapping open lots for one ticker; omit for no cap",
    )
    parser.add_argument("--exclude-ticker", action="append", default=["CVC"])
    args = parser.parse_args()
    if not 1 <= args.weeks_start <= args.weeks_end <= 52:
        parser.error("weeks must satisfy 1 <= weeks-start <= weeks-end <= 52")
    stops = args.stop or [0.30, 0.35, 0.40, 0.45]
    if any(not 0 < stop < 1 for stop in stops):
        parser.error("each stop must be between zero and one")
    if args.jobs < 1:
        parser.error("jobs must be positive")
    selected_weeks = sorted(set(args.week or range(args.weeks_start, args.weeks_end + 1)))

    root = args.project_root.expanduser().resolve()
    output = (args.output or root / "reports/weekly_holding_period_matrix").resolve()
    output.mkdir(parents=True, exist_ok=True)
    matrix_script = root / "scripts/run_monthly_momentum_lot_matrix.py"
    tax_script = root / "scripts/run_tax_reinvestment_matrix.py"
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    comparisons: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    def run_group(weeks: int, rule: str, stop: float) -> tuple[str, dict[str, object], str]:
        calculation_mode = "simple_equal_contribution_no_tax" if args.simple_equal_contribution else "tax_reinvestment"
        summary_name = "simple_equal_contribution_summary.csv" if args.simple_equal_contribution else "tax_reinvestment_configuration_summary.csv"
        selector = {"holding_weeks": weeks, "rule": rule, "stop": stop, "start": args.start.isoformat(), "end": args.end.isoformat(), "budget": args.monthly_budget, "nominal_days": sorted(args.nominal_day or range(1, 32)), "top_n_values": sorted(args.top_n or range(1, 6)), "tax_rate": args.tax_rate, "contribution_months": args.contribution_months, "max_volatility": args.max_volatility, "max_open_lots_per_ticker": args.max_open_lots_per_ticker, "exit_execution_model": "close_confirmed_next_open_v1", "calculation_mode": calculation_mode, "exclusions": sorted(args.exclude_ticker)}
        fingerprint = _fingerprint(selector)
        group = output / "groups" / f"week_{weeks:02d}" / _safe_component(rule) / f"stop_{stop:.0%}"
        if args.resume and _completed(group, fingerprint, summary_name):
            prior = json.loads((group / "group_result.json").read_text())
            return "skip", prior["winner"], f"SKIP completed: week={weeks} rule={rule} stop={stop:.0%}"
        work = group / "_work"
        try:
            group.mkdir(parents=True, exist_ok=True)
            if work.exists():
                if (group / "group_result.json").is_file():
                    shutil.rmtree(work)
                else:
                    raise RuntimeError("incomplete work directory exists; inspect or remove it explicitly before rerunning")
            matrix_output, tax_output = work / "matrix", work / "tax"
            command = [sys.executable, str(matrix_script), "--project-root", str(root), "--output", str(matrix_output), "--start", args.start.isoformat(), "--end", args.end.isoformat(), "--holding-weeks", str(weeks), "--stop", str(stop), "--max-volatility", str(args.max_volatility), "--disable-deterioration", "--monthly-budget", str(args.monthly_budget), "--rule", rule]
            for day in args.nominal_day or []:
                command += ["--nominal-day", str(day)]
            for top_n in args.top_n or []:
                command += ["--top-n", str(top_n)]
            if args.max_open_lots_per_ticker is not None:
                command += ["--max-open-lots-per-ticker", str(args.max_open_lots_per_ticker)]
            for ticker in args.exclude_ticker:
                command += ["--exclude-ticker", ticker]
            subprocess.run(command, check=True, env=env, capture_output=True, text=True)
            if args.simple_equal_contribution:
                summary = _read_csv(matrix_output / "configuration_summary.csv")
                if not summary:
                    raise RuntimeError("monthly matrix produced no configuration summary")
                raw_winner = max(summary, key=lambda row: (float(row["xirr"] or "-inf"), float(row["net_proceeds"])))
                winner = {
                    **raw_winner,
                    "total_contributions": raw_winner["invested_capital"],
                    "ending_wealth_before_open_tax": raw_winner["net_proceeds"],
                    "profit_before_open_tax": raw_winner["net_profit"],
                    "roi_before_open_tax": raw_winner["roi"],
                    "xirr_before_open_tax": raw_winner["xirr"],
                    "net_realized_tax_paid": "0.0",
                    "ending_cash": "0.0",
                    "open_market_value": "",
                    "estimated_open_liquidation_tax": "0.0",
                    "ending_wealth_after_full_liquidation_tax": raw_winner["net_proceeds"],
                    "profit_after_full_liquidation_tax": raw_winner["net_profit"],
                    "roi_after_full_liquidation_tax": raw_winner["roi"],
                    "xirr_after_full_liquidation_tax": raw_winner["xirr"],
                    "calculation_mode": calculation_mode,
                    "holding_weeks": weeks,
                    "rule": rule,
                    "stop": stop,
                }
                shutil.copy2(matrix_output / "configuration_summary.csv", group / summary_name)
                shutil.copy2(matrix_output / "best_configuration_trades.csv", group / "best_simple_equal_contribution_trades.csv")
            else:
                tax_command = [sys.executable, str(tax_script), "--trade-csv", str(matrix_output / "all_trades.csv"), "--output", str(tax_output), "--monthly-contribution", str(args.monthly_budget), "--holding-weeks", str(weeks), "--tax-rate", str(args.tax_rate), "--final-date", args.end.isoformat(), "--stop-label", f"{stop:.0%}"]
                if args.contribution_months is not None:
                    tax_command += ["--contribution-months", str(args.contribution_months)]
                subprocess.run(tax_command, check=True, env=env, capture_output=True, text=True)
                summary = _read_csv(tax_output / "tax_reinvestment_configuration_summary.csv")
                if not summary:
                    raise RuntimeError("tax replay produced no configuration summary")
                winner = max(summary, key=lambda row: (float(row["xirr_after_full_liquidation_tax"] or "-inf"), float(row["ending_wealth_after_full_liquidation_tax"])))
                winner = {**winner, "calculation_mode": calculation_mode, "holding_weeks": weeks, "rule": rule, "stop": stop}
                for name in ("tax_reinvestment_configuration_summary.csv", "best_tax_reinvestment_trades.csv", "best_tax_reinvestment_cash_ledger.csv"):
                    shutil.copy2(tax_output / name, group / name)
            marker = {"fingerprint": fingerprint, "selector": selector, "winner": winner}
            (group / "group_result.json").write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
            return "done", winner, f"DONE week={weeks} rule={rule} stop={stop:.0%} xirr={float(winner['xirr_after_full_liquidation_tax'] or 0):.2%}"
        except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as error:
            return "failed", {"holding_weeks": weeks, "rule": rule, "stop": stop, "error": str(error)}, f"FAILED week={weeks} rule={rule} stop={stop:.0%}: {error}"

    tasks = [(weeks, rule, stop) for weeks in selected_weeks for rule in (args.rule or RULES) for stop in stops]
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(run_group, *task) for task in tasks]
        for future in as_completed(futures):
            status, row, message = future.result()
            print(message, file=sys.stderr if status == "failed" else sys.stdout)
            (failures if status == "failed" else comparisons).append(row)

    comparisons.sort(key=lambda row: (-float(row["xirr_after_full_liquidation_tax"] or "-inf"), -float(row["ending_wealth_after_full_liquidation_tax"]), int(row["holding_weeks"]), str(row["rule"])))
    for rank, row in enumerate(comparisons, start=1):
        row["rank"] = rank
    _write_csv(output / "comparison.csv", comparisons)
    _write_csv(output / "failures.csv", failures)
    run = {"weeks_start": args.weeks_start, "weeks_end": args.weeks_end, "weeks": selected_weeks, "rules": args.rule or list(RULES), "stops": stops, "resume": args.resume, "failure_count": len(failures), "best": comparisons[0] if comparisons else None}
    (output / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **run}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
