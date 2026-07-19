# Incremental EODHD Update

`scripts/update_eodhd_incremental.py` adds only provider sessions missing after the
latest observation in the current validated Parquet (or the raw seed file on the
first run) for symbols active in the point-in-time S&P 500 universe on the
supplied completed EOD date.

It never modifies `data/raw/`. It publishes:

- `data/validated/sp500/eod_adjusted_current.parquet` — an atomically replaced,
  deduplicated derived Parquet artifact;
- `data/validated/sp500/market_data.duckdb` — `daily_adjusted_bars` plus an
  append-only `market_data_update_runs` manifest table;
- `data/validated/sp500/eodhd_incremental_<timestamp>_report.json`.

## Run

```bash
cd ~/QuantResearch
export EODHD_API_KEY='replace-with-your-rotated-key'

PYTHONPATH=src .venv/bin/python scripts/update_eodhd_incremental.py \
  --as-of 2026-07-13 \
  --dry-run

PYTHONPATH=src .venv/bin/python scripts/update_eodhd_incremental.py \
  --as-of 2026-07-13
```

Pass only an EOD date that EODHD has completed. Weekends and market holidays are
safe: the provider returns no rows and the update remains idempotent.

Do not rerun the constituent snapshot scripts for routine price updates. Run them
only when the historical constituent source CSV itself changes.
