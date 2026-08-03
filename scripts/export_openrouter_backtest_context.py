#!/usr/bin/env python3
"""Export a factual, secret-free handoff document for another coding model.

The document describes QuantResearch's actual point-in-time universe, validated
price data, execution semantics, and relevant scripts.  It deliberately omits
API tokens and does not query any external service.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import duckdb


def markdown(context: dict[str, object]) -> str:
    columns = "\n".join(f"- `{name}`: `{kind}`" for name, kind in context["price_columns"])
    return f"""# QuantResearch: backtesting handoff for an external coding model

## What this project actually uses

This is a Python 3.12+ research project. The canonical validated daily price
dataset is **Parquet**, queried through DuckDB. A DuckDB mirror also exists.
There is **not** a `daily_prices` table or same-day `sp500_constituents` table
as in the generic example.

- Project root: `{context['project_root']}`
- Canonical price data: `{context['parquet_path']}`
- DuckDB mirror: `{context['market_db_path']}`, table `daily_adjusted_bars`
- Point-in-time membership intervals: `{context['membership_path']}`
- Price coverage: {context['price_min_date']} through {context['price_max_date']}
- Price rows: {context['price_rows']:,}; distinct provider tickers: {context['price_tickers']:,}
- Membership intervals: {context['membership_intervals']:,}

## Validated price schema

{columns}

`Open`, `High`, `Low`, and `Close` are the adjusted OHLC fields used by the
existing backtest engines. `RawOpen` through `RawClose` retain provider prices.
`AdjustedClose` and `AdjustmentFactor` are also retained for return/audit work.
Do not mix raw and adjusted fields in a trade calculation.

## Point-in-time universe rule

Use `eligible_membership_intervals.csv` columns:
`index_id`, `constituent_symbol`, `effective_from`, `effective_to`.

A stock is eligible at a simulated date only when:

```sql
index_id = 'SP500'
AND effective_from <= simulated_date
AND (effective_to IS NULL OR effective_to >= simulated_date)
```

Do not substitute today's S&P 500 constituents for historical membership.
Provider-symbol aliases are review-gated in
`data/validated/sp500/mapping_decisions_operator.csv`.

## Existing momentum strategy

The main engine is `scripts/run_monthly_momentum_lot_matrix.py`.

- Rule: `12M>6M>3M>0` means 12-month return > 6-month return > 3-month return > 0.
- Signals use completed daily closes only.
- A monthly nominal date is moved to the next available market session.
- Entry uses that session's adjusted `Open`.
- Current reference test: rank 1, monthly $1,000 fixed contribution, 51-week hold, 45% stock stop, no reinvestment/tax in simple mode.
- Stop and time exits are signaled on completed closes and execute at the next market open.
- Existing outputs retain each lot's signal date, entry date/price, exit date/price, reason, shares, and return.

## ETF overlay research status

`scripts/backtest_etf_confirmed_momentum_overlay.py` is experimental. It maps
some stocks to current sector/theme ETFs and uses EODHD ETF histories. Historical
ETF/sector mappings are a current-proxy limitation. It must not silently replace
the baseline strategy. The memory-specific DRAM signal is research-only.

## Important safeguards

1. Preserve point-in-time membership and reviewed ticker mappings.
2. Use only information available by the decision close; execute next session open.
3. Do not introduce look-ahead bias, survivorship bias, or current ETF holdings as historical facts.
4. Do not put `EODHD_API_TOKEN` or any token in code, reports, prompts, logs, or command lines.
5. Keep raw inputs immutable and write new reports to a new output directory.
6. Add unit tests and run: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`.

## Safe DuckDB query examples

```python
import duckdb

parquet = "data/validated/sp500/eod_adjusted_current.parquet"
intervals = "data/validated/sp500/eligible_membership_intervals.csv"
con = duckdb.connect(":memory:")

rows = con.execute('''
    SELECT
        CAST(p.Date AS DATE) AS observed,
        UPPER(p.Ticker) AS ticker,
        p.Open AS adjusted_open,
        p.High AS adjusted_high,
        p.Low AS adjusted_low,
        p.Close AS adjusted_close,
        p.Volume,
        p.RawClose,
        p.AdjustmentFactor
    FROM read_parquet(?) AS p
    JOIN read_csv_auto(?, header=true) AS m
      ON UPPER(p.Ticker) = UPPER(m.constituent_symbol)
     AND CAST(p.Date AS DATE) >= CAST(m.effective_from AS DATE)
     AND (m.effective_to IS NULL OR CAST(p.Date AS DATE) <= CAST(m.effective_to AS DATE))
    WHERE m.index_id = 'SP500'
      AND CAST(p.Date AS DATE) BETWEEN ? AND ?
    ORDER BY observed, ticker
''', [parquet, intervals, "2010-01-01", "2024-12-31"]).fetchdf()
```

## Request to the coding model

Before proposing rule changes, inspect the files above and explain exactly how
your proposal preserves point-in-time membership, adjusted-price consistency,
next-open execution, and fixed-contribution accounting. Propose changes as new
scripts or optional flags; do not modify baseline behavior without a separate
comparison report containing trade-level details and maximum drawdown.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("reports/openrouter_backtest_context"))
    parser.add_argument("--sample-start", default="2015-01-01")
    parser.add_argument("--sample-end", default="2018-12-31")
    parser.add_argument("--sample-max-rows", type=int, default=100, help="Maximum fixture rows to export for chat upload.")
    args = parser.parse_args()
    root = args.project_root.expanduser().resolve()
    parquet = root / "data/validated/sp500/eod_adjusted_current.parquet"
    intervals = root / "data/validated/sp500/eligible_membership_intervals.csv"
    database = root / "data/validated/sp500/market_data.duckdb"
    if not parquet.is_file() or not intervals.is_file() or not database.is_file():
        raise FileNotFoundError("validated price parquet, membership intervals, or DuckDB mirror is missing")
    con = duckdb.connect(":memory:")
    try:
        schema = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(parquet)]).fetchall()
        span = con.execute("SELECT MIN(CAST(Date AS DATE)), MAX(CAST(Date AS DATE)), COUNT(*), COUNT(DISTINCT UPPER(Ticker)) FROM read_parquet(?)", [str(parquet)]).fetchone()
        interval_count = con.execute("SELECT COUNT(*) FROM read_csv_auto(?, header=true)", [str(intervals)]).fetchone()[0]
        sample_tickers = ["AAPL", "AMZN", "AMD", "JPM", "MSFT", "NFLX", "NVDA", "TSLA", "UNH", "XOM"]
        placeholders = ",".join("?" for _ in sample_tickers)
        sample_prices = con.execute(
            f"""SELECT Ticker, Date, Open, High, Low, Close, Volume, RawOpen, RawHigh, RawLow, RawClose, AdjustedClose, AdjustmentFactor
                FROM read_parquet(?)
                WHERE UPPER(Ticker) IN ({placeholders})
                  AND CAST(Date AS DATE) BETWEEN ? AND ?
                ORDER BY CAST(Date AS DATE), Ticker
                LIMIT ?""",
            [str(parquet), *sample_tickers, args.sample_start, args.sample_end, args.sample_max_rows],
        ).fetchall()
        sample_membership = con.execute(
            f"""SELECT * FROM read_csv_auto(?, header=true)
                WHERE UPPER(constituent_symbol) IN ({placeholders})
                ORDER BY constituent_symbol, effective_from""",
            [str(intervals), *sample_tickers],
        ).fetchall()
    finally:
        con.close()
    context = {
        "project_root": str(root), "parquet_path": str(parquet), "membership_path": str(intervals), "market_db_path": str(database),
        "price_columns": [(str(name), str(kind)) for name, kind, *_ in schema],
        "price_min_date": str(span[0]), "price_max_date": str(span[1]), "price_rows": int(span[2]), "price_tickers": int(span[3]), "membership_intervals": int(interval_count),
    }
    output = args.output.expanduser().resolve(); output.mkdir(parents=True, exist_ok=True)
    (output / "backtest_context.json").write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
    (output / "OPENROUTER_HANDOFF.md").write_text(markdown(context), encoding="utf-8")
    with (output / "sample_prices.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerow([name for name, _ in context["price_columns"]]); writer.writerows(sample_prices)
    with (output / "sample_membership_intervals.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerow(["index_id", "constituent_symbol", "effective_from", "effective_to"]); writer.writerows(sample_membership)
    print(json.dumps({"output": str(output), "handoff": str(output / 'OPENROUTER_HANDOFF.md'), "sample_prices": str(output / "sample_prices.csv"), "sample_membership": str(output / "sample_membership_intervals.csv")}, indent=2))


if __name__ == "__main__":
    main()
