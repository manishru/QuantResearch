# Momentum ETF mapping and historical S&P 500 reference

This repository stores the research inputs used by the monthly momentum and
sector-rotation experiments. They are research artefacts, not investment advice
or a claim that an ETF held every mapped company on every date.

## Version-controlled reference inputs

| Input | Repository path | Purpose |
| --- | --- | --- |
| Historical S&P 500 membership | `data/validated/sp500/eligible_membership_intervals.csv` | Point-in-time eligible membership intervals. A row is eligible from `effective_from` through `effective_to`; a blank end date remains active. |
| Membership provenance | `data/validated/sp500/eligible_universe_manifest.json` | Source hashes, coverage status and the published eligible-history version. |
| Broad ETF mappings | `config/etf_confirmed_momentum_mapping.csv` | Reviewed ticker-to-ETF defaults when no dated override exists. |
| Historical ETF mappings | `config/etf_confirmed_momentum_mapping_intervals.csv` | Effective-dated ETF mappings and explicit exclusions used for historical tests. |

The dated registry is authoritative for an interval. `status=excluded` is an
intentional outcome: the candidate is not assigned a guessed sector proxy.

## Data timing and holding horizon

The ETF overlay needs ETF prices from every candidate execution date through 52
calendar weeks later. The coverage audit labels a horizon after the latest
completed close as **future**, rather than a missing historical observation.
It also identifies fund lifecycle issues, such as an ETF that launched after a
candidate date or was renamed/terminated before the holding horizon ended.

## Refresh and verify ETF history

Set the key in your shell; never add it to Git:

```bash
export EODHD_API_TOKEN='your_api_key'
```

Refresh all approved ETF histories:

```bash
PYTHONPATH=src .venv/bin/python scripts/fetch_momentum_mapping_etfs.py \
  --start 2015-07-01 \
  --end YYYY-MM-DD \
  --cache-dir reports/momentum_sector_matrix/raw_eodhd \
  --request-delay-seconds 0.15 \
  --refresh
```

Audit entry-to-52-week ETF coverage using the generated candidate-ranking files:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_etf_mapping_price_coverage.py \
  --candidates reports/momentum_matrix_candidates_train_5m/candidate_rankings.csv \
  --candidates reports/momentum_matrix_candidates_train_6m/candidate_rankings.csv \
  --candidates reports/momentum_matrix_candidates_train_12m/candidate_rankings.csv \
  --candidates reports/momentum_matrix_candidates_train_blend_6m_12m/candidate_rankings.csv \
  --candidates reports/momentum_matrix_candidates_forward_5m/candidate_rankings.csv \
  --candidates reports/momentum_matrix_candidates_forward_6m/candidate_rankings.csv \
  --candidates reports/momentum_matrix_candidates_forward_12m/candidate_rankings.csv \
  --candidates reports/momentum_matrix_candidates_forward_blend_6m_12m/candidate_rankings.csv \
  --as-of YYYY-MM-DD \
  --cache-dir reports/momentum_sector_matrix/raw_eodhd \
  --cache-dir reports/etf_rotation_top200_latest/raw_eodhd \
  --max-rank 10 \
  --holding-weeks 52 \
  --output reports/momentum_matrix_etf_price_coverage_latest
```

The audit writes `etf_coverage_summary.csv`, `etfs_needing_history.csv`, and
`candidate_etf_coverage.csv`. Generated reports and EODHD cache files remain
local and are deliberately not committed.

## Preserved comparison baseline

The prior sector-cooldown comparison is retained locally at
`reports/5m3m_etf_exit_lot_matrix_mapped_2016_2026/`. Its best tested
threshold was **four concurrent open lots sharing the same mapped ETF**:

| Metric | Preserved result |
| --- | ---: |
| Period | 2016-01-01 through 2026-07-27 |
| Rule | `5M>3M>0` |
| Stop | 40% close-triggered stop |
| Maximum hold | 52 weeks |
| Candidate fallback | ranks 1 through 10 |
| ETF exit threshold | 4 same-ETF open lots |
| ETF risk-off | 21-session relative strength, 1.25x volume, 10% drawdown |
| Cooldown | 6 calendar months |
| Contributions | $126,000 |
| Net proceeds | $211,737.60 |
| ROI | 68.05% |
| XIRR | 71.23% |

Reproduce that baseline without overwriting it by using a new output directory:

```bash
PYTHONPATH=src .venv/bin/python scripts/backtest_sector_cooldown_momentum.py \
  --candidates reports/5m3m_rank10_stop40_mapped_2016_2026/candidate_rankings.csv \
  --templates reports/5m3m_rank10_stop40_mapped_2016_2026/all_trades.csv \
  --start 2016-01-01 \
  --end 2026-07-27 \
  --rule '5M>3M>0' \
  --nominal-day 26 \
  --max-rank 10 \
  --min-relative-volume 1.25 \
  --drawdown 0.10 \
  --min-sector-open-lots 4 \
  --cooldown-months 6 \
  --monthly-budget 1000 \
  --cache-dir reports/momentum_sector_matrix/raw_eodhd \
  --output reports/5m3m_sector_cooldown_baseline_retest
```

This is a historical research baseline, not a deployable performance claim.
Its ETF coverage must be re-audited before interpreting a rerun as comparable.

## Review rules

1. Add a new row to the interval registry whenever a mapping is date-specific.
2. Use `EXCLUDE` when a concentrated, historically valid ETF cannot be
   defended. Do not substitute a broad-sector ETF merely to increase coverage.
3. Resolve ETF launches, closures, renames and ticker transitions before
   treating a missing history as a provider-download problem.
4. Re-run mapping and price-coverage audits before a backtest or forward test.
