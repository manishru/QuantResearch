Status: complete
Last Updated: 2026-07-13

## 1. Overview

Add a weekly holding-period research experiment for the existing point-in-time S&P 500 monthly-entry momentum backtest. It will evaluate exits from one through fifty-two weeks, every registered momentum rule, stop losses of 30%, 35%, 40%, and 45%, all monthly entry days, and Top 1–5 portfolios; it will rank the results using consistent point-in-time membership, transaction-cost, tax, and reinvestment conventions.

## 2. Goals & Non-Goals

### Goals

- Test holding durations from 1 to 52 weeks reproducibly.
- Test all registered momentum rules and 30%, 35%, 40%, and 45% stop-loss levels.
- Test every monthly purchase day and Top 1–5 portfolio size.
- Preserve point-in-time S&P 500 membership and approved seasoning exceptions.
- Produce per-duration trade, tax/reinvestment, and ranked comparison outputs.

### Non-Goals

- Change the momentum-rule definitions, source data, or raw data files.
- Treat the in-sample winner as a live trading recommendation.

## 3. Target Module

Primary: `scripts/run_monthly_momentum_lot_matrix.py` and tax-reinvestment replay.

Secondary: a new weekly holding-period runner script, tests, and research documentation.

## 4. Functional Specification

### 4.1 Inputs

- Existing adjusted EOD Parquet and point-in-time S&P 500 membership artifacts.
- All registered momentum rules.
- Holding period: integer calendar weeks from 1 to 52.
- Stop loss: 30%, 35%, 40%, or 45%.
- Monthly entry day: 1–31, clamped to month end; Top N: 1–5.

### 4.2 Outputs

- Summary rows for every tested configuration.
- Fully taxed reinvestment results used to rank each `(holding weeks, rule, stop)` group.
- Detailed trades and cash ledger retained for every `(holding weeks, rule, stop)` group winner and for the global winner.

### 4.3 Processing Logic

1. Create monthly point-in-time eligible candidate universes using existing logic.
2. Rank candidates for every existing momentum rule.
3. Enter at the existing monthly execution convention.
4. Exit at the first session on or after `entry date + holding_weeks × 7 days`, unless the stop is hit first.
5. Disable volume-deterioration and stepwise profit-trailing exits.
6. Run the tax/reinvestment replay with full maturity proceeds available at the next monthly purchase.
7. Rank results by fully taxed XIRR and use fully taxed ending wealth as the tie-breaker.

### 4.4 Branching & Decision Logic

- A stop gap exits at the next bar open; an intraday stop exits at the stop price, matching current conservative logic.
- Incomplete final holding periods remain marked to market and incur estimated liquidation tax in the fully taxed ranking.

### 4.5 Idempotency & Ordering

- Each run writes into a user-selected output folder; reruns with identical data and options reproduce identical summaries.
- Detailed artifacts are generated after group-level ranking, not for every configuration.

## 5. Integration Points

### 5.1 Internal Dependencies

Existing monthly holding-period matrix, tax-reinvestment replay, point-in-time membership intervals, approved mapping decisions, and seasoning exceptions.

### 5.2 External Dependencies

No new external dependencies expected.

### 5.3 Trigger Mechanism

CLI command or shell runner.

### 5.4 Configuration

- Weeks: 1–52.
- Stops: 0.30, 0.35, 0.40, 0.45.
- Rules: all registered rules.
- Deterioration and trailing exits: disabled.
- Maturity reinvestment spread: one next monthly purchase cycle.

## 6. Data Model

- Add `holding_weeks` to configuration summaries, reports, and output paths.
- Add a weekly experiment comparison row keyed by `holding_weeks`, rule, stop, entry day, and Top N.

## 7. Error Handling & Failure Modes

| Failure Scenario | Expected Behaviour | Recovery Strategy |
|---|---|---|
| Missing input artifact | Fail before execution with the missing path | Restore/prepare the validated artifact, then rerun |
| Invalid week/stop value | Reject CLI arguments before database work | Correct the argument and rerun |
| No eligible candidates | Record an empty configuration summary | Do not treat it as an investment result |
| Interrupted run | Preserve partial artifacts; do not publish an incomplete comparison as final | Resume only groups with a completed final summary; never silently delete partial outputs |
| One weekly group fails | Record the group error and continue unaffected groups | Exit nonzero after emitting the complete failure report |

## 8. Non-Functional Requirements

### 8.1 Performance

- Avoid retaining detailed trades for all approximately 350,000 configurations.
- Summary output must remain inspectable in spreadsheet tools.

### 8.2 Security

No new secrets or network calls.

### 8.3 Observability

- Emit progress by holding week and output path.
- Record all run assumptions in JSON.

### 8.4 Backwards Compatibility

The existing monthly-holding workflow must remain unchanged.

## 9. Edge Cases

- Month-end entry-day clamping.
- Holidays and non-trading dates use the first subsequent market session.
- Stops and maturity on the same date follow the existing conservative stop-first ordering.
- Open lots at the final date are marked to market.
- A monthly entry with no eligible candidate remains idle cash under the existing portfolio workflow.

## 10. Open Questions

N/A — all current feature decisions are resolved.
