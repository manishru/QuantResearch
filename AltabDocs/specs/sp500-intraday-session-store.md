# S&P 500 intraday session store

## Goal

Download EODHD intraday bars for the S&P 500 constituents active on a specified
point-in-time date without modifying the validated daily data set.

## Acceptance criteria

- The downloader uses only `EODHD_API_TOKEN` (or the existing `EODHD_API_KEY` fallback); it never logs a token.
- It accepts 1m, 5m, and 1h EODHD intraday intervals and splits 1m requests into no more than 120 calendar-day windows.
- It resolves either the active universe at `--universe-date` or every eligible historical membership interval with `--historical-membership`.
- Each bar has its UTC timestamp, New York timestamp, local trade date, and one of pre_market (04:00–09:30 ET), regular (09:30–16:00 ET), after_hours (16:00–20:00 ET), or off_session. `America/New_York` handles daylight-saving changes automatically.
- Hybrid mode stores five-minute regular-session bars and one-minute pre-market/after-hours bars, with the source interval preserved per row.
- DuckDB retains raw OHLCV, provider timestamp, source request window, fetch time, run audit, and three session views.
- Network failures for one ticker are recorded while remaining tickers continue.
- The database is separate from daily adjusted bars.
- A fresh historical backfill can run in deterministic, non-overlapping worker partitions, each with its own DuckDB file, and merge only after all workers finish.
- After all writers stop, `scripts/optimize_intraday_duckdb.py` creates point/range lookup indexes, gathers statistics with `ANALYZE`, and checkpoints the database for rule queries.
- A resumed long backfill bounds DuckDB memory, disables insertion-order preservation, and spills intermediate state to an explicit local temp directory rather than exhausting host RAM.
- Legacy stores with a bar-table primary key support an explicit, count-validated migration to append-only bar storage. Request-window records retain idempotent resume behavior without an in-memory index over tens of millions of bars.

## Out of scope

- This is not a real-time feed or a trading-execution system.
- It does not infer historical membership per intraday date; `--universe-date` fixes one point-in-time universe per run.

## Related ETF store

The approved ETF universe is fetched by `scripts/update_eodhd_etf_intraday.py` into a separate DuckDB database using the same session labels and hybrid bar design.
