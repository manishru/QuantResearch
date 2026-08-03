# QuantResearch external-model project guide

This document is safe to share with an external coding model. It describes the
repository and its research rules, but deliberately excludes market-data files,
reports, environment files, and API tokens.

## 1. Purpose

QuantResearch is a Python research repository for point-in-time S&P 500
backtests, momentum screening, market-data validation, ETF rotation research,
and trade-level reporting. It is not an order-execution system.

## 2. Repository layout

| Path | Purpose | External-model instruction |
|---|---|---|
| `src/quantresearch/` | Reusable Python package: configuration, domain models, ingestion, research support | Reuse existing package utilities where possible. |
| `scripts/run_monthly_momentum_lot_matrix.py` | Main monthly momentum-lot backtest engine | Treat as the baseline engine; do not replace silently. |
| `scripts/scan_latest_momentum_recommendations.py` | Read-only current momentum screen | Produces research candidates, not trading instructions. |
| `scripts/update_eodhd_incremental.py` | Incremental validated EOD data update | Preserve append-only/idempotent update behavior. |
| `scripts/compute_simple_strategy_drawdown.py` | Contribution-adjusted daily drawdown calculation | Use for fixed-contribution comparisons. |
| `scripts/backtest_etf_confirmed_momentum_overlay.py` | Experimental ETF exit/entry overlay | Current ETF mappings are proxies; do not treat them as historical facts. |
| `data/validated/sp500/eod_adjusted_current.parquet` | Canonical validated daily price data | Do not commit, upload, or modify. Query with DuckDB. |
| `data/validated/sp500/market_data.duckdb` | DuckDB mirror of validated adjusted bars | Read-only research mirror. |
| `data/validated/sp500/eligible_membership_intervals.csv` | Point-in-time S&P 500 membership intervals | Mandatory for historical eligibility. |
| `data/validated/sp500/mapping_decisions_operator.csv` | Reviewed provider-to-constituent mappings | Mandatory for renamed/special provider symbols. |
| `config/` | Explicit research configuration and curated mappings | Keep changes auditable and documented. |
| `reports/` | Generated research artifacts | Never treat reports as source data; write new output directories. |
| `tests/` | Standard-library automated tests | Add tests for any new public behavior. |

## 3. Actual data model

The canonical price data is Parquet, not a generic `daily_prices` table. The
DuckDB mirror uses table `daily_adjusted_bars`.

Price columns:

```text
Ticker, Date, Open, High, Low, Close, Volume,
RawOpen, RawHigh, RawLow, RawClose,
AdjustedClose, AdjustmentFactor
```

`Open`, `High`, `Low`, and `Close` are adjusted OHLC values used by the baseline
engines. `Raw*` values are provider observations retained for audit. Do not mix
raw and adjusted prices in a trade calculation.

Membership data uses intervals:

```text
index_id, constituent_symbol, effective_from, effective_to
```

Historical eligibility condition:

```sql
index_id = 'SP500'
AND effective_from <= simulated_date
AND (effective_to IS NULL OR effective_to >= simulated_date)
```

## 4. Backtest execution rules

1. Compute all signals using completed observations available at the decision
   close. Never use future observations, backward filling, or current
   constituents as historical universe data.
2. A monthly nominal purchase date moves to the next available market session.
3. Entry occurs at that eligible session's adjusted open.
4. Each monthly purchase is an independent lot. Multiple open lots in the same
   ticker are valid and expected.
5. Stop, deterioration, trailing, and time-exit conditions are evaluated using
   completed closes. A triggered exit executes at the next market-session open.
6. Fixed contribution means each scheduled contribution is external capital;
   it is not automatically reinvested. Drawdown must remove the effect of new
   contributions.

## 5. Reference momentum strategy

The primary research rule is:

```text
12M return > 6M return > 3M return > 0
```

Reference configuration used in recent research:

```text
top_n = 1
monthly contribution = $1,000
holding period = 51 weeks
stock stop = 45%
simple equal contribution / no reinvestment / no tax
```

This is a research baseline, not investment advice or a live-trading mandate.

## 6. ETF research status

ETF overlays are experimental. They may use ETF relative volume, relative
strength versus SPY, and ETF drawdown to study earlier exits. Limitations:

- Sector/theme mappings can be current-category proxies.
- Stock-specific ETFs must not be assumed to exist before their actual launch.
- Generic ETF exits have not outperformed the plain momentum baseline in the
  reported tests. Do not enable them by default.

## 7. Required quality and safety rules

1. Preserve point-in-time membership and reviewed provider mappings.
2. Avoid look-ahead, survivorship, corporate-action, and cashflow bias.
3. Do not use `bfill` or cross-stock filling for historical price series.
4. Keep raw data immutable and use a new report directory per run.
5. API credentials remain only in environment variables, never in code, prompts,
   reports, test fixtures, or Git.
6. Before implementation, add or update tests. Run:

   ```bash
   PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
   ```

## 8. How an external model should contribute

1. Read this guide, `AGENTS.md`, `README.md`, and the target script first.
2. Explain potential data/bias risks before suggesting rule changes.
3. Make a new optional script or flag rather than changing the baseline default.
4. Produce a trade-level CSV and comparison summary including ROI, XIRR,
   win rate, and contribution-adjusted maximum drawdown.
5. Supply exact local commands; do not require uploading the large local dataset.

## 9. Safe GitHub sharing

Share source code and this guide only. Keep the repository private unless you
intentionally want the code public. Never commit or upload `.venv/`, `data/`,
`reports/`, `.env`, API tokens, or raw provider responses.
