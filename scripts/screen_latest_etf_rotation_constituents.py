#!/usr/bin/env python3
"""Read-only current constituent screen for the ETF rotation research rule.

It selects only baskets whose completed-session regime has just turned active,
then ranks their current static constituent-list proxy by 20/50-day trend
spread after requiring volume at least the prior 20-session average. Results
are research output, not a recommendation or order instruction.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

from backtest_etf_momentum_breadth_proxy import BASKETS, constituent_tickers


def write_csv(path: Path, rows: list[dict[str, object]], headers: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def next_weekday(value: date) -> date:
    result = value + timedelta(days=1)
    while result.weekday() > 4:
        result += timedelta(days=1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--regimes", type=Path, required=True, help="daily_breadth_regimes.csv from the ETF study")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--top", type=int, default=1)
    parser.add_argument("--min-relative-volume", type=float, default=1.0)
    parser.add_argument("--basket", action="append", default=None, help="Optional basket restriction; repeatable")
    args = parser.parse_args()
    if args.top < 1 or args.min_relative_volume <= 0:
        parser.error("--top and --min-relative-volume must be positive")
    root, output = args.project_root.expanduser().resolve(), args.output.expanduser().resolve()
    regimes = args.regimes.expanduser().resolve()
    parquet = root / "data/validated/sp500/eod_adjusted_current.parquet"
    membership = root / "data/validated/sp500/eligible_membership_intervals.csv"
    lists = root / "data/features/current_sector_lists"
    if not regimes.is_file() or not parquet.is_file() or not membership.is_file():
        raise FileNotFoundError("regime report, validated price parquet, and membership intervals are required")
    output.mkdir(parents=True, exist_ok=True)

    basket_by_name = {basket.name: basket for basket in BASKETS if basket.constituents}
    allowed = set(args.basket or basket_by_name)
    active: list[dict[str, str]] = []
    with regimes.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (row.get("date") == args.as_of.isoformat() and row.get("basket") in allowed
                    and row.get("signal_start", "").lower() == "true"):
                active.append(row)

    eligible: set[str] = set()
    with membership.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            end = row["effective_to"].strip()
            if row["effective_from"] <= args.as_of.isoformat() and (not end or args.as_of.isoformat() <= end):
                eligible.add(row["constituent_symbol"].upper())

    all_rows: list[dict[str, object]] = []
    baskets_report: list[dict[str, object]] = []
    con = duckdb.connect(":memory:")
    try:
        for regime in active:
            basket = basket_by_name[regime["basket"]]
            tickers = sorted(constituent_tickers(lists / str(basket.constituents)) & eligible)
            if not tickers:
                continue
            placeholders = ",".join("?" for _ in tickers)
            records = con.execute(f"""
                SELECT UPPER(Ticker) ticker, CAST(Date AS DATE) observed,
                       AdjustedClose close_price, Volume volume
                FROM read_parquet(?)
                WHERE UPPER(Ticker) IN ({placeholders})
                  AND CAST(Date AS DATE) BETWEEN ? AND ? AND AdjustedClose>0
                ORDER BY ticker, observed
            """, [str(parquet), *tickers, args.as_of - timedelta(days=120), args.as_of]).fetchall()
            grouped: dict[str, list[tuple[date, float, float]]] = {}
            for ticker, observed, close, volume in records:
                grouped.setdefault(ticker, []).append((observed, float(close), float(volume or 0)))
            candidates: list[dict[str, object]] = []
            for ticker, bars in grouped.items():
                if len(bars) < 51 or bars[-1][0] != args.as_of:
                    continue
                closes = [item[1] for item in bars]
                current = bars[-1]
                sma20 = sum(closes[-20:]) / 20
                sma50 = sum(closes[-50:]) / 50
                prior_volume20 = sum(item[2] for item in bars[-21:-1]) / 20
                relative_volume = current[2] / prior_volume20 if prior_volume20 else 0.0
                if sma20 <= sma50 or relative_volume < args.min_relative_volume:
                    continue
                candidates.append({
                    "basket": basket.name, "etf": basket.etf, "signal_date": args.as_of.isoformat(),
                    "ticker": ticker, "close_price": current[1], "sma20": sma20, "sma50": sma50,
                    "trend_spread": sma20 / sma50 - 1, "relative_volume": relative_volume,
                    "etf_relative_strength_21d": regime["relative_strength_21d"],
                    "etf_relative_volume": regime["etf_relative_volume"],
                    "etf_breadth_21d": regime["constituent_breadth_21d"],
                })
            candidates.sort(key=lambda row: (-float(row["trend_spread"]), str(row["ticker"])))
            for rank, row in enumerate(candidates[:args.top], start=1):
                all_rows.append({"rank": rank, **row})
            baskets_report.append({
                "basket": basket.name, "etf": basket.etf, "signal_start": True,
                "eligible_static_constituents": len(tickers), "screen_qualifying_count": len(candidates),
                "etf_relative_strength_21d": regime["relative_strength_21d"],
                "etf_relative_volume": regime["etf_relative_volume"],
                "etf_breadth_21d": regime["constituent_breadth_21d"],
            })
    finally:
        con.close()

    headers = ["rank", "basket", "etf", "signal_date", "ticker", "close_price", "sma20", "sma50",
               "trend_spread", "relative_volume", "etf_relative_strength_21d", "etf_relative_volume", "etf_breadth_21d"]
    write_csv(output / "research_candidates.csv", all_rows, headers)
    write_csv(output / "basket_status.csv", baskets_report,
              ["basket", "etf", "signal_start", "eligible_static_constituents", "screen_qualifying_count",
               "etf_relative_strength_21d", "etf_relative_volume", "etf_breadth_21d"])
    print(json.dumps({
        "as_of": args.as_of.isoformat(), "source_price_data_through": args.as_of.isoformat(),
        "intended_execution_target": next_weekday(args.as_of).isoformat(),
        "execution_note": "Confirm the actual next market session and opening price; this script does not place orders.",
        "active_baskets_with_static_constituent_lists": baskets_report,
        "research_candidates": all_rows,
        "candidates_csv": str(output / "research_candidates.csv"),
        "limitations": "Static current ETF constituent lists are a proxy; research only, not investment advice.",
    }, indent=2))


if __name__ == "__main__":
    main()
