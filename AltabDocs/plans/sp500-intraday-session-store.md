# Plan: S&P 500 intraday session store

1. Resolve the active S&P 500 universe and EODHD provider aliases at the requested universe date.
2. Fetch bounded EODHD intraday windows, retry transient network errors, and normalize UTC timestamps.
3. Classify bars by America/New_York pre-market, regular, after-hours, and off-session times.
4. Upsert a dedicated DuckDB store with run metadata and query views.
5. Unit-test session boundaries and provide a small pilot command before a whole-universe backfill.
6. Configure resumed writers with a bounded DuckDB memory limit and disk spill directory; retain completed-window resume semantics after an interrupted insert.
7. Provide and test an explicit count-validated migration from legacy primary-key bar storage to append-only storage before resuming a large backfill.
