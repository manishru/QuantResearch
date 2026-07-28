#!/usr/bin/env python3
"""Audit cached ETF prices for reviewed momentum mappings and 52-week holds.

The audit uses the candidate execution dates, rather than assuming every ETF
needs the same arbitrary history.  For every approved mapping it checks from
the candidate's execution date through 52 calendar weeks later.  Horizons that
extend past ``--as-of`` are reported as expected future coverage, not missing
historical data.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def mapping_resolver(static_path: Path, interval_path: Path):
    static = {row["ticker"]: row for row in read_csv(static_path)}
    intervals: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(interval_path):
        if row.get("status", "").lower() in {"approved", "excluded"}:
            intervals[row["ticker"]].append(row)
    for values in intervals.values():
        values.sort(key=lambda row: row.get("effective_from") or "0001-01-01")

    def resolve(ticker: str, observed: date) -> dict[str, str] | None:
        for row in intervals.get(ticker, []):
            start = date.fromisoformat(row["effective_from"]) if row.get("effective_from") else date.min
            end = date.fromisoformat(row["effective_to"]) if row.get("effective_to") else date.max
            if start <= observed <= end:
                return row
        return static.get(ticker)

    return resolve


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def cached_dates(symbol: str, cache_dirs: list[Path]) -> tuple[list[date], int]:
    """Read all matching EODHD cache fragments for an ETF symbol."""
    prefix = f"{symbol.replace('.', '_')}_"
    observed: set[date] = set()
    files = 0
    for cache_dir in cache_dirs:
        if not cache_dir.is_dir():
            continue
        for path in cache_dir.glob(f"{prefix}*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, list):
                continue
            files += 1
            for row in payload:
                value = row.get("date") or row.get("Date")
                if value:
                    try:
                        observed.add(date.fromisoformat(str(value)[:10]))
                    except ValueError:
                        pass
    return sorted(observed), files


def maximum_gap(values: list[date]) -> int:
    return max((right - left).days for left, right in zip(values, values[1:])) if len(values) > 1 else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", action="append", type=Path, required=True, help="Repeat for each candidate_rankings.csv to audit.")
    parser.add_argument("--as-of", type=date.fromisoformat, required=True, help="Latest completed close available in the cache.")
    parser.add_argument("--cache-dir", action="append", type=Path, required=True, help="Repeat for every EODHD ETF cache directory.")
    parser.add_argument("--mapping", type=Path, default=Path("config/etf_confirmed_momentum_mapping.csv"))
    parser.add_argument("--mapping-intervals", type=Path, default=Path("config/etf_confirmed_momentum_mapping_intervals.csv"))
    parser.add_argument("--max-rank", type=int, default=10, choices=range(1, 11))
    parser.add_argument("--holding-weeks", type=int, default=52)
    parser.add_argument("--grace-calendar-days", type=int, default=7, help="Allowed edge tolerance for holidays/weekends.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    resolve = mapping_resolver(args.mapping, args.mapping_intervals)
    holding_days = args.holding_weeks * 7
    candidates: list[dict[str, object]] = []
    excluded = unmapped = 0
    for path in args.candidates:
        for row in read_csv(path):
            if int(row["rank"]) > args.max_rank:
                continue
            execution = date.fromisoformat(row["execution_date"])
            mapping = resolve(row["ticker"], execution)
            if not mapping:
                unmapped += 1
                continue
            if mapping.get("status", "").lower() == "excluded":
                excluded += 1
                continue
            symbol = mapping.get("primary_etf", "").upper()
            if not symbol:
                unmapped += 1
                continue
            candidates.append({
                "ticker": row["ticker"], "execution_date": execution, "horizon_end": execution + timedelta(days=holding_days),
                "primary_etf": symbol, "rule_name": row.get("rule_name", ""), "rank": row.get("rank", ""),
                "source_file": str(path),
            })

    dates_by_etf: dict[str, list[date]] = {}
    files_by_etf: dict[str, int] = {}
    for symbol in sorted({str(item["primary_etf"]) for item in candidates}):
        dates_by_etf[symbol], files_by_etf[symbol] = cached_dates(symbol, args.cache_dir)

    details: list[dict[str, object]] = []
    for item in candidates:
        symbol = str(item["primary_etf"])
        dates = dates_by_etf[symbol]
        start = item["execution_date"]
        horizon = item["horizon_end"]
        required_end = min(horizon, args.as_of)
        in_window = [value for value in dates if start <= value <= required_end]
        start_ok = bool(in_window) and in_window[0] <= start + timedelta(days=args.grace_calendar_days)
        end_ok = bool(in_window) and in_window[-1] >= required_end - timedelta(days=args.grace_calendar_days)
        future = horizon > args.as_of
        if not dates:
            status = "no_cache"
        elif not start_ok or not end_ok:
            status = "missing_history"
        elif future:
            status = "covered_through_as_of_future_horizon"
        else:
            status = "complete_52_week_horizon"
        details.append({
            **item,
            "horizon_end": horizon.isoformat(), "required_end_as_of": required_end.isoformat(),
            "cache_first_date": dates[0].isoformat() if dates else "", "cache_last_date": dates[-1].isoformat() if dates else "",
            "window_first_date": in_window[0].isoformat() if in_window else "", "window_last_date": in_window[-1].isoformat() if in_window else "",
            "window_rows": len(in_window), "maximum_calendar_gap_days": maximum_gap(in_window),
            "cache_files": files_by_etf[symbol], "coverage_status": status,
        })

    detail_fields = ["ticker", "execution_date", "horizon_end", "required_end_as_of", "primary_etf", "rule_name", "rank", "coverage_status", "cache_first_date", "cache_last_date", "window_first_date", "window_last_date", "window_rows", "maximum_calendar_gap_days", "cache_files", "source_file"]
    write_csv(args.output / "candidate_etf_coverage.csv", details, detail_fields)

    summary: list[dict[str, object]] = []
    for symbol in sorted(dates_by_etf):
        rows = [row for row in details if row["primary_etf"] == symbol]
        dates = dates_by_etf[symbol]
        statuses = defaultdict(int)
        for row in rows:
            statuses[str(row["coverage_status"])] += 1
        summary.append({
            "primary_etf": symbol, "candidate_entries": len(rows), "cache_files": files_by_etf[symbol],
            "cache_first_date": dates[0].isoformat() if dates else "", "cache_last_date": dates[-1].isoformat() if dates else "",
            "complete_52_week_horizon": statuses["complete_52_week_horizon"],
            "covered_through_as_of_future_horizon": statuses["covered_through_as_of_future_horizon"],
            "missing_history": statuses["missing_history"], "no_cache": statuses["no_cache"],
        })
    summary_fields = list(summary[0]) if summary else ["primary_etf"]
    write_csv(args.output / "etf_coverage_summary.csv", summary, summary_fields)

    fetch_needed = [row for row in summary if row["missing_history"] or row["no_cache"]]
    write_csv(args.output / "etfs_needing_history.csv", fetch_needed, summary_fields)
    result = {
        "as_of": args.as_of.isoformat(), "holding_weeks": args.holding_weeks,
        "candidate_rows_checked": len(candidates), "excluded_candidate_rows": excluded, "unmapped_candidate_rows": unmapped,
        "complete_52_week_horizon": sum(row["coverage_status"] == "complete_52_week_horizon" for row in details),
        "covered_through_as_of_future_horizon": sum(row["coverage_status"] == "covered_through_as_of_future_horizon" for row in details),
        "missing_history": sum(row["coverage_status"] == "missing_history" for row in details),
        "no_cache": sum(row["coverage_status"] == "no_cache" for row in details),
        "etfs_needing_history": len(fetch_needed), "output": str(args.output),
    }
    (args.output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
