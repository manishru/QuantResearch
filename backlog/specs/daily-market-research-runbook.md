Status: draft
Last Updated: 2026-07-18

## 1. Overview

Create a repeatable daily research workflow for monitoring Memory stocks
(`MU`, `SNDK`, `STX`, `WDC`), the broader semiconductor group, and sector
rotation. It uses EODHD price, volume, news, and sentiment data already
available to the user; it deliberately excludes ETF Fundamentals/holdings
because the current token returns HTTP 403 for that endpoint.

## 2. Goals & Non-Goals

### Goals

- Refresh validated EOD prices before analysis.
- Measure sector and semiconductor performance versus SPY using actual ETF
  prices and volumes.
- Compare Memory price/volume and news sentiment with the semiconductor regime.
- Write reproducible CSV reports and a plain-language regime label.

### Non-Goals

- Prove real-time institutional buying or selling.
- Provide an automatic buy, sell, short, or portfolio-allocation instruction.
- Reconstruct historical ETF holdings using a current holdings snapshot.

## 3. Target Module

Research scripts in `scripts/`, primarily `update_eodhd_incremental.py`,
`analyze_sector_etf_rotation.py`, `analyze_news_rotation_proxy.py`, and
`build_memory_semiconductor_regime_dashboard.py`.

## 4. Functional Specification

### 4.1 Inputs

- EODHD token from `EODHD_API_TOKEN`; never on the command line.
- Requested as-of date in `YYYY-MM-DD` format.
- Local validated EOD parquet data.
- EODHD ETF EOD prices, news, and sentiment endpoints.

### 4.2 Outputs

- Sector ETF daily history: `daily_rotation_summary.csv`.
- Memory news/price/volume history: `daily_rotation_proxy.csv`.
- Combined dashboard: `daily_memory_semiconductor_regime.csv`.
- Cached raw EODHD responses below the relevant report folder.

### 4.3 Processing Logic

1. Refresh local EOD stock data to the requested as-of date.
2. Fetch/cache SPY, sector ETF, and semiconductor ETF daily prices.
3. Calculate 21-session return versus SPY and latest-day relative volume.
4. Fetch/cache Memory ticker sentiment and optional latest news.
5. Calculate Memory basket 21-session return, relative volume, sentiment, and
   article count.
6. Join completed-session data by date and label the regime.

### 4.4 Branching & Decision Logic

- `risk_on_confirmation`: semiconductor return versus SPY is positive and the
  Memory basket 21-session return is positive.
- `risk_off_warning`: both measures are negative.
- `mixed`: all other combinations.
- `weakness_with_activity`: semiconductor return versus SPY is negative and
  relative volume is above 1.0.
- These labels are research states, not trading instructions.

### 4.5 Idempotency & Ordering

Commands are safe to rerun. Refresh stock prices first; then sector/news
reports; then the dashboard. Use a completed market close only.

## 5. Integration Points

### 5.1 Internal Dependencies

- `data/validated/sp500/eod_adjusted_current.parquet`
- `quantresearch.research.news_rotation.aggregate_basket_observations`

### 5.2 External Dependencies

- EODHD EOD, news, and sentiment APIs.

### 5.3 Trigger Mechanism

Manual daily execution after the US market has closed and EODHD has published
the completed session.

### 5.4 Configuration

- Memory basket: `MU`, `SNDK`, `STX`, `WDC`.
- Sector history start: `2025-10-01` (provides a 21-session calculation buffer
  before December 2025).
- News history start: `2025-01-01`.

## 6. Data Model

`daily_memory_semiconductor_regime.csv` includes:

| Field | Meaning |
|---|---|
| `semiconductor_return_vs_spy_21d` | Average SMH/SOXX/XSD 21-session return minus SPY return. |
| `semiconductor_relative_volume` | Average latest-day ETF volume divided by its preceding 21-session average. |
| `memory_return_21d` | Equal-weight 21-session return of Memory basket members with data. |
| `memory_relative_volume` | Average relative volume of Memory basket members. |
| `memory_sentiment` | EODHD count-weighted normalized news sentiment. |
| `leading_sector` | ETF with the strongest 21-session return versus SPY. |
| `regime` | Research-only summary state described above. |

## 7. Error Handling & Failure Modes

| Failure Scenario | Expected Behaviour | Recovery Strategy |
|---|---|---|
| Missing token | Script stops without exposing a secret. | Export `EODHD_API_TOKEN` in the current shell. |
| Market data not yet published | Latest local date remains earlier than requested. | Wait for EODHD publication; rerun later. |
| ETF Fundamentals 403 | Do not use constituent-breadth result. | Continue with ETF price/volume analysis; no Fundamentals required. |
| Missing ticker/session | Basket averages use available valid data. | Inspect raw cache and EODHD update report. |

## 8. Non-Functional Requirements

### 8.1 Performance

The sector and news reports should complete in a few minutes with cached
responses and a normal network connection.

### 8.2 Security

API tokens are environment-only and must never be committed, logged, or passed
as command-line arguments.

### 8.3 Observability

Each script prints output paths; raw inputs are cached for inspection.

### 8.4 Backwards Compatibility

All outputs are new report folders; existing backtests are not modified.

## 9. Edge Cases

- Weekend/holiday: use the last completed trading session; do not infer a new
  market signal.
- A one-day regime flip is noise; assess persistence over several sessions.
- Volume alone does not identify the buyer/seller or institutional flow.
- Sentiment can be noisy, delayed, or driven by syndicated articles.

## 10. Open Questions

- What persistence threshold should later be tested: three or five consecutive
  regime sessions?
- Should a future version compare the regime with forward returns using an
  explicitly frozen train/test split?

## Pending

### Conversation Summary

Today’s research found a current July 2026 Semiconductor/Memory risk-off
condition: semiconductor ETFs materially lagged SPY and Memory stocks were
also weak with elevated activity. Health Care showed the best 21-session price
leadership, while Financials had stronger recent volume confirmation. Earlier
short-strategy research did not produce a sufficiently robust out-of-sample
edge; this runbook is a monitoring workflow, not a short signal.

### Remaining Questions

1. Confirm whether the daily monitoring date should be the last completed
   market session automatically or entered manually.
2. Decide whether to build and validate a formal historical regime strategy.

### Raw Notes

- EODHD ETF Fundamentals access is denied (403) for SMH/SOXX/XSD under the
  current token. ETF EOD price data works and embeds historical holdings.
- Current sector ETF report: Health Care had positive 21-session leadership
  without a broad volume surge; Financials had more recent volume activity.
