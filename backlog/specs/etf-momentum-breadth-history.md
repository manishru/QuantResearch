Status: draft
Last Updated: 2026-07-18

## 1. Overview

Build a research-only historical dashboard for major U.S. equity benchmarks,
XLV, XLF, the SMH/SOXX semiconductor basket, and DRAM memory. It will identify ETF price/volume
momentum regimes and compare them with constituent price breadth and dated
holdings weights, without treating current holdings as historical constituents.

## 2. Goals & Non-Goals

### Goals

- Backtest an ETF-level price/volume/breadth research signal from 2010 onward
  for major U.S. benchmarks, XLV, XLF, semiconductors, and DRAM from its April
  2026 launch.
- Prefer dated issuer holdings where available; otherwise use a static-basket
  proxy explicitly labelled as such.
- Report signal dates, subsequent ETF performance, breadth, and the stocks
  contributing to breadth on each signal date.

### Non-Goals

- Claim that price/volume proves institutional flows.
- Treat current constituents as historical holdings without a proxy warning.
- Produce a personalised buy instruction.

## 3. Target Module

New ETF rotation/breadth research script alongside
`scripts/analyze_sector_etf_rotation.py`, plus dated/static constituent files.

## 4. Functional Specification

### 4.1 Inputs

- Date range, EODHD token environment variable, 21-session holding period,
  minimum ETF relative-volume threshold, and minimum constituent breadth.
- ETF values: SPY, XLV, XLF, SMH, SOXX, and DRAM.
- Current dated constituent snapshots in `data/features/current_sector_lists/`.
- Price/volume-only benchmark set: QQQ (Nasdaq-100), DIA (Dow), IWM (Russell
  2000), MDY (S&P MidCap 400), RSP (equal-weight S&P 500), and VTI (total U.S.
  market). SPY remains the relative-strength benchmark.

### 4.2 Outputs

- `strategy_summary.csv`: number of signal starts, average 21-session ETF
  return, ETF win rate, equal-weight constituent proxy return, and proxy win
  rate.
- `signal_events.csv`: each regime-start signal, next-session entry, exit after
  the chosen holding period, and both return measures.
- `daily_breadth_regimes.csv`: ETF return, SPY return, relative strength,
  relative volume, breadth, and regime state for every completed session.
- `constituents_at_signal_entries.csv`: the positive-breadth stocks at each
  entry with equal weights; not fund weights.

### 4.3 Processing Logic

1. Calculate each ETF's 21-session return and volume relative to its preceding
   21-session average.
2. Calculate SPY's matching 21-session return.
3. Calculate available static-basket constituents' 21-session returns from the
   validated point-in-time S&P price parquet.
4. Start a regime only when ETF relative strength versus SPY is positive, ETF
   relative volume is at least 1.0, and positive constituent breadth is at
   least 55%.
5. Measure the ETF and equal-weight positive-constituent proxy for the next 21
   sessions, using next-session entry and close-to-close adjusted-price proxy.
6. For broad indexes without a dated constituent universe, run the ETF
   price/volume regime only; do not manufacture a constituent-breadth field.

### 4.4 Branching & Decision Logic

- Both ETF and equal-weight constituent-proxy variants are reported, rather
  than selecting a winner before validation.
- DRAM is unavailable before its April 2, 2026 launch.
- A basket with fewer than 43 sessions in the requested window is unavailable.
- Foreign/non-S&P DRAM holdings are outside the existing constituent-price
  parquet and therefore not part of the historical stock-breadth proxy.

### 4.5 Idempotency & Ordering

Runs are date-scoped and cache EODHD downloads. `--refresh` overwrites only the
run's price cache. A completed market session must exist before calculating a
new signal.

## 5. Integration Points

### 5.1 Internal Dependencies

- `scripts/backtest_etf_momentum_breadth_proxy.py`
- `scripts/analyze_sector_etf_rotation.py`
- Validated S&P adjusted-price parquet and static basket CSVs.

### 5.2 External Dependencies

- EODHD daily prices for ETF values.
- State Street daily/month-end holdings for XLV/XLF where archived dates are
  accessible.
- iShares dated holdings for SOXX where archived dates are accessible.
- SEC N-PORT filings as a monthly historical-holdings fallback from 2019.

### 5.3 Trigger Mechanism

Manual research run; live monitoring uses the same thresholds after market
close.

### 5.4 Configuration

- Default holding period: 21 sessions.
- Default minimum breadth: 0.55.
- Default minimum ETF relative volume: 1.0.

## 6. Data Model

`signal_events.csv` is the event-level research record. Its key fields are
`basket`, `signal_date`, `entry_date`, `exit_date`, `etf_return`,
`constituent_equal_weight_return`, `signal_breadth`,
`signal_relative_strength_21d`, and `signal_relative_volume`.

## 7. Error Handling & Failure Modes

| Failure Scenario | Expected Behaviour | Recovery Strategy |
|---|---|---|
| Missing EODHD token | Exit before requests. | Set `EODHD_API_TOKEN` in the shell. |
| ETF unavailable or too new | Mark basket unavailable. | Use it only after sufficient history exists. |
| No dated holdings archive | Use static current list only with proxy label. | Add issuer/SEC dated snapshots later. |
| Missing constituent price | Omit it from the day's breadth denominator. | Preserve available-count in output. |

## 8. Non-Functional Requirements

### 8.1 Performance

Downloads only ETF histories; constituent breadth uses the local parquet.

### 8.2 Security

EODHD token is read from an environment variable only.

### 8.3 Observability

All raw ETF responses and CSV output artifacts are persisted in the report
folder.

### 8.4 Backwards Compatibility

Does not change the existing all-S&P momentum scanner or its trade engine.

## 9. Edge Cases

- ETF and constituent session calendars differ.
- A current constituent may not have been in the historical ETF.
- DRAM's global holdings cannot be represented by the S&P-only local price
  database.
- High volume can represent selling as well as buying; the signal must not be
  called confirmed institutional flow.

## 10. Open Questions

- Collect and normalize issuer/SEC dated weights before treating weight changes
  as a separate historical predictive feature.
- Validate the thresholds on a separate out-of-sample period before any use as
  a production research rule.

## 11. Completed Run: 2010-01-01 to 2025-12-31

Command:

```zsh
PYTHONPATH=src .venv/bin/python scripts/backtest_etf_momentum_breadth_proxy.py \
  --from 2010-01-01 --to 2025-12-31 --holding-sessions 21 \
  --minimum-breadth 0.55 --minimum-relative-volume 1.0 --refresh \
  --output reports/etf_momentum_breadth_proxy_2010_2025
```

| Basket | Signals | Avg. ETF return | ETF win rate | Avg. equal-weight constituent proxy return | Proxy win rate | Constituent method |
|---|---:|---:|---:|---:|---:|---|
| XLV Health Care | 252 | 1.15% | 70.24% | 1.17% | 66.67% | static current holdings proxy |
| XLF Financials | 299 | 0.63% | 56.19% | 0.89% | 62.21% | static current holdings proxy |
| SMH Semiconductors | 399 | 1.57% | 62.66% | 1.61% | 61.65% | static current holdings proxy |
| SOXX Semiconductors | 393 | 1.82% | 63.10% | 2.20% | 65.14% | static current holdings proxy |
| DRAM Memory | unavailable | N/A | N/A | N/A | N/A | launched April 2026 |

Artifacts:

- `reports/etf_momentum_breadth_proxy_2010_2025/strategy_summary.csv`
- `reports/etf_momentum_breadth_proxy_2010_2025/signal_events.csv` (1,343 events)
- `reports/etf_momentum_breadth_proxy_2010_2025/daily_breadth_regimes.csv`
- `reports/etf_momentum_breadth_proxy_2010_2025/constituents_at_signal_entries.csv`

## 12. Holdout Validation: Train 2010-2020, Holdout 2021-2025

Artifact: `reports/etf_momentum_breadth_proxy_2010_2025/train_2010_2020_holdout_2021_2025.csv`

| Basket | Holdout signals | Holdout ETF avg. return | Holdout ETF win rate | Holdout constituent proxy avg. return | Holdout proxy win rate |
|---|---:|---:|---:|---:|---:|
| XLV Health Care | 55 | 0.46% | 58.18% | 0.19% | 56.36% |
| XLF Financials | 87 | 0.46% | 55.17% | 0.40% | 57.47% |
| SMH Semiconductors | 112 | 2.45% | 67.86% | 1.82% | 65.18% |
| SOXX Semiconductors | 106 | 2.21% | 63.21% | 2.11% | 66.98% |

The semiconductor proxy held up more consistently in this holdout. This is not
a portfolio return or XIRR: signal windows can overlap, costs/slippage are
absent, and historical membership/weights are still proxied.

## 13. Expanded Major-Index Holdout: 2010-2025

Expanded universe: QQQ (Nasdaq-100), DIA (Dow), IWM (Russell 2000), MDY (S&P
MidCap 400), RSP (equal-weight S&P 500), VTI (total market), XLV, XLF, SMH,
SOXX, and DRAM where history permits.

Artifact: `reports/all_major_indexes_momentum_2010_2025/train_2010_2020_holdout_2021_2025.csv`

| Basket | Train avg. 21-session return | Holdout avg. 21-session return | Holdout win rate | Interpretation |
|---|---:|---:|---:|---|
| QQQ Nasdaq-100 | 1.04% | 2.00% | 73.11% | Strong in both periods |
| SMH semiconductors | 1.23% | 2.45% | 67.86% | Strong in both periods; static basket proxy |
| SOXX semiconductors | 1.68% | 2.21% | 63.21% | Strong in both periods; static basket proxy |
| DIA Dow | 0.98% | 1.39% | 67.59% | Positive in both periods |
| VTI total market | 0.96% | 0.90% | 66.30% | Stable but lower-return |
| XLV Health Care | 1.34% | 0.46% | 58.18% | Material weakening in holdout |
| XLF Financials | 0.71% | 0.46% | 55.17% | Weak in holdout |
| RSP equal-weight S&P 500 | 1.40% | 0.49% | 58.59% | Material weakening in holdout |
| IWM Russell 2000 | 1.54% | -0.01% | 57.29% | No holdout edge |
| MDY S&P MidCap 400 | 1.43% | -0.24% | 44.55% | Failed holdout |

The event study therefore supports testing broad large-cap growth/technology and
semiconductor regimes further, but rejects treating small-cap/mid-cap price-
volume signals as robust under these parameters. These are overlapping,
cost-free event returns—not compounded portfolio performance, XIRR, or a trade
instruction.

## 14. Regime-Excluded Holdout: Train 2010-2020, Skip 2021-2022, Test 2023-2025

Artifact: `reports/all_major_indexes_momentum_2010_2025/train_2010_2020_skip_2021_2022_test_2023_2025.csv`

| Basket | 2023-2025 signals | Avg. 21-session ETF return | Win rate |
|---|---:|---:|---:|
| SOXX Semiconductors | 63 | 4.40% | 71.43% |
| SMH Semiconductors | 73 | 4.07% | 76.71% |
| QQQ Nasdaq-100 | 92 | 2.35% | 77.17% |
| XLV Health Care | 25 | 1.51% | 68.00% |
| VTI Total Market | 60 | 0.93% | 65.00% |
| DIA Dow | 72 | 0.95% | 65.28% |
| XLF Financials | 52 | 0.46% | 55.77% |
| IWM Russell 2000 | 53 | 0.04% | 58.49% |
| RSP Equal-weight S&P 500 | 50 | 0.10% | 50.00% |
| MDY S&P MidCap 400 | 57 | -0.42% | 42.11% |

Excluding 2021-2022 strengthens the large-cap technology/semiconductor
finding, but it also concentrates the evaluation in the 2023-2025 AI-led
market regime. Treat this as regime description, not evidence that the same
returns will persist.

## 15. Trade-Price Export

`scripts/export_etf_momentum_constituent_trades.py` enriches the constituent
event list with adjusted entry/exit closes and price return. It was run for
signals from 2023 onward and produced 6,474 constituent event rows at:

- `reports/all_major_indexes_momentum_2010_2025/constituent_trades_2023_2025_with_prices.csv`

The columns `signal_date`, `entry_date`, `entry_adjusted_close`, `exit_date`,
`exit_adjusted_close`, `weight`, and `price_return` form the audit trail. These
are research event-study prices; they are adjusted closes, not guaranteed
executable open prices.

## 16. Non-overlapping Fixed-Capital Simulation: 2023-2025

Each basket receives $1,000 only after its prior 21-session trade has exited.
This removes overlap within a basket, but still excludes fees, slippage, tax,
and intratrade mark-to-market drawdown.

Artifact: `reports/all_major_indexes_momentum_2010_2025/non_overlapping_2023_2025/non_overlapping_summary.csv`

| Basket | Trades | ROI on cumulative contributions | Win rate | XIRR |
|---|---:|---:|---:|---:|
| SMH | 19 | 5.86% | 78.95% | 100.75% |
| SOXX | 18 | 5.16% | 77.78% | 86.53% |
| QQQ | 22 | 1.79% | 72.73% | 26.43% |
| VTI | 20 | 1.70% | 75.00% | 22.95% |

The high semiconductor XIRRs arise from repeated short-duration monthly cash
flows. They are sensitive to execution/cost assumptions and must not be read
as a forecast.

## 17. Source-Control and Recovery Backup

Completed on 2026-07-18:

- Created and pushed private repository:
  `https://github.com/manishru/QuantResearch`
- Default branch: `main`.
- Initial organized source-control commit: `d8adcc7` — `Organize QuantResearch
  research platform and runbooks`.
- Repository tracks source, tests, scripts, specifications, AltTab histories,
  and documentation. `.gitignore` excludes secrets, virtual environments,
  generated reports, raw/validated data, Parquet, DuckDB, logs, and CSV output.
- Recovery instructions: `docs/backup_and_recovery.md`.
- Archive manifest utility: `scripts/create_research_backup_manifest.py`.

Required recurring backup procedure:

```zsh
cd ~/QuantResearch
PYTHONPATH=src .venv/bin/python scripts/create_research_backup_manifest.py \
  --output reports/backup_manifest_latest.csv
git add -A && git commit -m "Update research code and runbooks" && git push
```

Copy `data/`, `reports/`, and `reports/backup_manifest_latest.csv` to an
encrypted external SSD or private cloud backup. Normal GitHub Git storage is
not the backup location for this large data archive (about 104 GB of reports).

## Pending

### Conversation Summary

User wants an updated view of XLV, XLF, semiconductors, and DRAM; historical
ETF values; the dates when momentum began; and analysis of whether constituent
strength/weight can form an entry research signal.

User authorizes a static-constituent proxy when historical constituents are
not available. DRAM is included from launch only.

### Remaining Questions

1. Obtain dated issuer/SEC constituent weights and rerun without static-list
   look-ahead proxy.
2. Add a non-overlapping, cost-aware portfolio simulation before comparing
   compounded performance or XIRR.

### Raw Notes

- DRAM began trading April 2, 2026, so it has no last-year ETF price history.
- Fund weights change. Applying the July 2026 basket to 2025 would cause
  look-ahead bias and cannot validate an entry strategy.
