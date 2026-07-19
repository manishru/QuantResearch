#!/usr/bin/env python3
"""Add adjusted entry/exit prices to constituent ETF momentum event-study trades."""
from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

import duckdb


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--from-signal", type=date.fromisoformat)
    args = parser.parse_args()
    with args.entries.open(newline="", encoding="utf-8") as handle:
        entries = list(csv.DictReader(handle))
    if args.from_signal:
        entries = [row for row in entries if date.fromisoformat(row["signal_date"]) >= args.from_signal]
    parquet = args.project_root.expanduser().resolve() / "data/validated/sp500/eod_adjusted_current.parquet"
    tickers = sorted({row["ticker"] for row in entries})
    if not tickers:
        raise RuntimeError("no entries match the requested signal-date range")
    con = duckdb.connect(":memory:")
    try:
        placeholders = ",".join("?" for _ in tickers)
        rows = con.execute(
            f"""SELECT UPPER(Ticker) AS ticker, CAST(Date AS DATE) AS observed, AdjustedClose AS adjusted_close
                FROM read_parquet(?)
                WHERE UPPER(Ticker) IN ({placeholders}) AND AdjustedClose > 0""",
            [str(parquet), *tickers],
        ).fetchall()
    finally:
        con.close()
    prices = {(ticker, observed.isoformat()): float(close) for ticker, observed, close in rows}
    output_rows = []
    for row in entries:
        entry_price = prices.get((row["ticker"], row["entry_date"]))
        exit_price = prices.get((row["ticker"], row["exit_date"]))
        output_rows.append({
            **row,
            "entry_adjusted_close": entry_price if entry_price is not None else "",
            "exit_adjusted_close": exit_price if exit_price is not None else "",
            "price_return": exit_price / entry_price - 1 if entry_price and exit_price else "",
            "price_data_status": "available" if entry_price and exit_price else "missing_price_on_event_date",
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(output_rows[0])
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"wrote {len(output_rows)} trades to {args.output}")


if __name__ == "__main__":
    main()
