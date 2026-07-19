#!/usr/bin/env python3
"""Calculate contribution-adjusted daily drawdown for fixed-contribution trades.

Each new trade allocation is an external contribution.  Exit proceeds remain as
idle cash; they are never used to fund later entries.  Daily NAV therefore
removes the effect of new contributions before measuring returns and drawdown.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import duckdb

from quantresearch.ingestion.parquet_bars import approved_provider_to_constituent
from quantresearch.ingestion.review_decisions import load_mapping_decisions


def _read_selected(path: Path, nominal_day: int, top_n: int) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [
            row for row in csv.DictReader(handle)
            if int(row["nominal_day"]) == nominal_day and int(row["top_n"]) == top_n
        ]
    if not rows:
        raise ValueError("no trades match the requested nominal day and top-N")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--trade-csv", type=Path, required=True)
    parser.add_argument("--nominal-day", type=int, required=True)
    parser.add_argument("--top-n", type=int, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.project_root.expanduser().resolve()
    rows = _read_selected(args.trade_csv.expanduser().resolve(), args.nominal_day, args.top_n)
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    parquet = root / "data/validated/sp500/eod_adjusted_current.parquet"
    mappings = root / "data/validated/sp500/mapping_decisions_operator.csv"
    aliases = approved_provider_to_constituent(load_mapping_decisions(mappings).registry, "EODHD")
    selected_tickers = {row["ticker"].upper() for row in rows}
    provider_to_constituent = {
        provider: constituent for provider, constituent in aliases.items() if constituent in selected_tickers
    }
    provider_symbols = selected_tickers | set(provider_to_constituent)

    con = duckdb.connect(":memory:")
    try:
        placeholders = ",".join("?" for _ in provider_symbols)
        result = con.execute(
            f"""
            SELECT UPPER(Ticker), CAST(Date AS DATE), Close
            FROM read_parquet(?)
            WHERE UPPER(Ticker) IN ({placeholders}) AND CAST(Date AS DATE)<=?
            ORDER BY Date
            """,
            [str(parquet), *sorted(provider_symbols), args.end],
        ).fetchall()
    finally:
        con.close()

    close_by_day: dict[date, dict[str, float]] = defaultdict(dict)
    sessions: set[date] = set()
    for provider, observed, close in result:
        ticker = provider_to_constituent.get(str(provider), str(provider))
        close_by_day[observed][ticker] = float(close)
        sessions.add(observed)
    start = min(date.fromisoformat(row["execution_date"]) for row in rows)
    sessions = {day for day in sessions if start <= day <= args.end}
    if not sessions:
        raise ValueError("no market sessions available for the requested date range")

    entries: dict[date, list[dict[str, str]]] = defaultdict(list)
    exits: dict[date, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        entries[date.fromisoformat(row["execution_date"])].append(row)
        if row["exit_date"]:
            exits[date.fromisoformat(row["exit_date"])].append(row)

    cash = 0.0
    open_lots: dict[int, dict[str, str]] = {}
    last_close: dict[str, float] = {}
    previous_equity: float | None = None
    nav = 1.0
    peak_nav = 1.0
    max_drawdown = 0.0
    peak_date: date | None = None
    drawdown_peak_date: date | None = None
    trough_date: date | None = None
    daily: list[dict[str, object]] = []

    for observed in sorted(sessions):
        last_close.update(close_by_day[observed])
        contribution = 0.0
        for row in exits[observed]:
            open_lots.pop(id(row), None)
            cash += float(row["net_proceeds"])
        for row in entries[observed]:
            allocation = float(row["allocation"])
            contribution += allocation
            cash += allocation
            cash -= allocation
            open_lots[id(row)] = row
        market_value = 0.0
        for row in open_lots.values():
            ticker = row["ticker"].upper()
            if ticker not in last_close:
                raise ValueError(f"missing close needed to value {ticker} on {observed}")
            market_value += float(row["shares"]) * last_close[ticker]
        equity = cash + market_value
        if previous_equity is None:
            daily_return = equity / contribution - 1 if contribution else 0.0
        elif previous_equity > 0:
            daily_return = (equity - contribution) / previous_equity - 1
        else:
            daily_return = 0.0
        nav *= 1 + daily_return
        if nav >= peak_nav:
            peak_nav, peak_date = nav, observed
        drawdown = nav / peak_nav - 1
        if drawdown < max_drawdown:
            max_drawdown, drawdown_peak_date, trough_date = drawdown, peak_date, observed
        daily.append(
            {
                "date": observed.isoformat(),
                "external_contribution": contribution,
                "idle_cash": cash,
                "open_market_value": market_value,
                "portfolio_equity": equity,
                "daily_return_excluding_contribution": daily_return,
                "contribution_adjusted_nav": nav,
                "drawdown": drawdown,
            }
        )
        previous_equity = equity

    daily_path = output / "daily_equity_and_drawdown.csv"
    with daily_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(daily[0]))
        writer.writeheader()
        writer.writerows(daily)
    report = {
        "calculation_mode": "fixed_contribution_no_reinvestment_idle_cash",
        "trade_count": len(rows),
        "nominal_day": args.nominal_day,
        "top_n": args.top_n,
        "start": min(sessions).isoformat(),
        "end": max(sessions).isoformat(),
        "ending_equity": daily[-1]["portfolio_equity"],
        "maximum_drawdown": max_drawdown,
        "peak_date": drawdown_peak_date.isoformat() if drawdown_peak_date else None,
        "trough_date": trough_date.isoformat() if trough_date else None,
        "daily_equity_csv": str(daily_path),
    }
    report_path = output / "drawdown_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
