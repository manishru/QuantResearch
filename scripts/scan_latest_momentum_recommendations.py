#!/usr/bin/env python3
"""Produce a read-only, point-in-time latest momentum recommendation list."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

import duckdb

from quantresearch.ingestion.parquet_bars import approved_provider_to_constituent
from quantresearch.ingestion.review_decisions import load_mapping_decisions
from quantresearch.research.momentum_recommendations import RULES, rank_qualifying


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    headers = list(rows[0]) if rows else ["rank", "ticker"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--rule", choices=sorted(RULES), required=True)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--max-volatility", type=float, default=0.10)
    parser.add_argument("--exclude-ticker", action="append", default=["CVC"])
    parser.add_argument(
        "--include-ticker-file",
        type=Path,
        help="Optional CSV with a ticker column; restricts the existing point-in-time S&P universe.",
    )
    parser.add_argument(
        "--output-prefix",
        help="Optional filename prefix, for example xlv or semis; does not change rankings.",
    )
    parser.add_argument("--parquet", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top must be positive")
    if args.output_prefix and any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in args.output_prefix):
        parser.error("--output-prefix may contain only letters, numbers, underscores, and hyphens")
    root = args.project_root.expanduser().resolve()
    default_parquet = root / "data/validated/sp500/eod_adjusted_current.parquet"
    parquet = (args.parquet or default_parquet).expanduser().resolve()
    if not parquet.is_file():
        raise FileNotFoundError(f"Validated adjusted Parquet does not exist: {parquet}")
    output = (args.output or root / "reports/latest_momentum_recommendations").resolve()
    output.mkdir(parents=True, exist_ok=True)
    intervals = root / "data/validated/sp500/eligible_membership_intervals.csv"
    mappings = root / "data/validated/sp500/mapping_decisions_operator.csv"
    exceptions = root / "data/validated/sp500/membership_tenure_exceptions.csv"
    aliases = approved_provider_to_constituent(load_mapping_decisions(mappings).registry, "EODHD")
    exclusions = sorted({ticker.upper().strip() for ticker in args.exclude_ticker if ticker.strip()})
    included: list[str] | None = None
    if args.include_ticker_file:
        include_file = args.include_ticker_file.expanduser().resolve()
        with include_file.open(newline="", encoding="utf-8") as handle:
            included = sorted(
                {
                    row["ticker"].upper().strip().replace(".", "-")
                    for row in csv.DictReader(handle)
                    if row.get("ticker", "").strip()
                }
            )
        if not included:
            parser.error("--include-ticker-file has no non-empty ticker values")

    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE aliases(provider VARCHAR, constituent VARCHAR)")
        if aliases:
            con.executemany("INSERT INTO aliases VALUES (?, ?)", sorted(aliases.items()))
        con.execute("CREATE TABLE excluded(ticker VARCHAR)")
        if exclusions:
            con.executemany("INSERT INTO excluded VALUES (?)", [(ticker,) for ticker in exclusions])
        con.execute("CREATE TABLE included(ticker VARCHAR)")
        if included:
            con.executemany("INSERT INTO included VALUES (?)", [(ticker,) for ticker in included])
        con.execute("""
            CREATE TABLE prices AS
            SELECT COALESCE(a.constituent, UPPER(p.Ticker)) ticker,
                   CAST(p.Date AS DATE) observed, p.Close close_price
            FROM read_parquet(?) p LEFT JOIN aliases a ON UPPER(p.Ticker)=a.provider
            WHERE CAST(p.Date AS DATE)<=? AND p.Close>0
        """, [str(parquet), args.as_of])
        signal_date = con.execute("SELECT MAX(observed) FROM prices").fetchone()[0]
        if signal_date is None:
            raise RuntimeError("No completed price session exists on or before --as-of")
        next_session = con.execute(
            "SELECT MIN(CAST(Date AS DATE)) FROM read_parquet(?) WHERE CAST(Date AS DATE)>?",
            [str(parquet), signal_date],
        ).fetchone()[0]
        con.execute("""
            CREATE TABLE returns AS
            SELECT *, LAG(observed) OVER w prior_date,
              close_price/LAG(close_price) OVER w-1 daily_return
            FROM prices WINDOW w AS (PARTITION BY ticker ORDER BY observed)
        """)
        con.execute("""
            CREATE TABLE segmented AS
            SELECT *, SUM(CASE WHEN prior_date IS NULL OR DATEDIFF('day',prior_date,observed)>45 THEN 1 ELSE 0 END)
              OVER(PARTITION BY ticker ORDER BY observed) segment_id
            FROM returns
        """)
        query = """
            WITH features AS (
              SELECT ticker,observed,close_price,
                ROW_NUMBER() OVER(PARTITION BY ticker,segment_id ORDER BY observed) history_sessions,
                close_price/FIRST_VALUE(close_price) OVER(PARTITION BY ticker,segment_id ORDER BY observed)-1 return_since_start,
                CASE WHEN COUNT(daily_return) OVER(PARTITION BY ticker,segment_id ORDER BY observed ROWS BETWEEN 20 PRECEDING AND CURRENT ROW)=21
                  THEN STDDEV_SAMP(daily_return) OVER(PARTITION BY ticker,segment_id ORDER BY observed ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) END volatility_1m,
                close_price/LAG(close_price,42) OVER(PARTITION BY ticker,segment_id ORDER BY observed)-1 ret42,
                close_price/LAG(close_price,63) OVER(PARTITION BY ticker,segment_id ORDER BY observed)-1 ret63,
                close_price/LAG(close_price,84) OVER(PARTITION BY ticker,segment_id ORDER BY observed)-1 ret84,
                close_price/LAG(close_price,105) OVER(PARTITION BY ticker,segment_id ORDER BY observed)-1 ret105,
                close_price/LAG(close_price,126) OVER(PARTITION BY ticker,segment_id ORDER BY observed)-1 ret126,
                close_price/LAG(close_price,147) OVER(PARTITION BY ticker,segment_id ORDER BY observed)-1 ret147,
                close_price/LAG(close_price,168) OVER(PARTITION BY ticker,segment_id ORDER BY observed)-1 ret168,
                close_price/LAG(close_price,189) OVER(PARTITION BY ticker,segment_id ORDER BY observed)-1 ret189,
                close_price/LAG(close_price,252) OVER(PARTITION BY ticker,segment_id ORDER BY observed)-1 ret252
              FROM segmented
            )
            SELECT f.*,COALESCE(f.ret252,f.return_since_start) ranking_return,
              x.constituent_symbol IS NOT NULL seasoning_exception,
              x.parent_symbol exception_parent,x.reason exception_reason
            FROM features f
            JOIN read_csv_auto(?,header=true) i ON UPPER(i.constituent_symbol)=f.ticker
              AND f.observed>=CAST(i.effective_from AS DATE)
              AND (i.effective_to IS NULL OR CAST(i.effective_to AS VARCHAR)='' OR f.observed<=CAST(i.effective_to AS DATE))
            LEFT JOIN read_csv_auto(?,header=true) x ON UPPER(x.constituent_symbol)=f.ticker
              AND LOWER(x.status)='approved' AND f.observed>=CAST(x.effective_from AS DATE)
              AND (x.effective_to IS NULL OR CAST(x.effective_to AS VARCHAR)='' OR f.observed<=CAST(x.effective_to AS DATE))
            WHERE f.observed=? AND NOT EXISTS(SELECT 1 FROM excluded e WHERE e.ticker=f.ticker)
              AND (NOT EXISTS(SELECT 1 FROM included) OR EXISTS(SELECT 1 FROM included s WHERE s.ticker=f.ticker))
              AND (? < 0 OR f.volatility_1m<=?)
              AND (f.observed>=CAST(i.effective_from AS DATE)+INTERVAL 60 DAY OR x.constituent_symbol IS NOT NULL)
        """
        result = con.execute(query, [str(intervals), str(exceptions), signal_date, args.max_volatility, args.max_volatility])
        columns = [column[0] for column in result.description]
        candidates = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
    finally:
        con.close()
    ranked = rank_qualifying(candidates, args.rule)[:args.top]
    for row in ranked:
        row["signal_date"] = str(signal_date)
        row["intended_execution"] = "next_session_open"
        row["intended_execution_date"] = str(next_session) if next_session else "not_yet_available"
    file_stem = f"{args.rule.replace('>', '_').replace(' ', '_').replace('&', 'and')}_{signal_date}"
    if args.output_prefix:
        file_stem = f"{args.output_prefix}_{file_stem}"
    csv_path = output / f"{file_stem}_recommendations.csv"
    write_csv(csv_path, ranked)
    report = {
        "as_of_requested": args.as_of.isoformat(), "signal_date": str(signal_date),
        "intended_execution": "next_session_open", "intended_execution_date": str(next_session) if next_session else None,
        "rule": args.rule, "top_requested": args.top, "qualifying_count": len(rank_qualifying(candidates, args.rule)),
        "max_volatility": args.max_volatility, "excluded_tickers": exclusions,
        "included_ticker_file": str(args.include_ticker_file) if args.include_ticker_file else None,
        "included_ticker_count": len(included) if included else None,
        "point_in_time_membership": True, "minimum_continuous_membership_days": 60,
        "adjusted_parquet": str(parquet), "recommendations_csv": str(csv_path), "recommendations": ranked,
    }
    report_path = output / f"{file_stem}_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
