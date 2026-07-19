Status: complete
Last Updated: 2026-07-18

## 1. Overview

Create current constituent lists—XLV Health Care, XLF Financials, a
deduplicated SMH/SOXX semiconductor union, and an S&P-compatible Roundhill
DRAM Memory ETF subset—and screen each list separately with
the existing `12M>6M>3M>0` momentum rule. The initial implementation preserves
the existing point-in-time S&P 500 data universe, so current ETF constituents
without validated S&P price history are reported as unavailable rather than
silently introduced into the original strategy.

## 2. Goals & Non-Goals

### Goals

- Source current lists from fund issuers rather than the blocked EODHD
  Fundamentals endpoint.
- Save list provenance/date and separate ranked screen results for each basket.
- Reuse the current scanner’s point-in-time membership and volatility rules.

### Non-Goals

- Claim a historical ETF-constituent backtest from current holdings.
- Make a buy/sell recommendation.

## 3. Target Module

`scripts/scan_latest_momentum_recommendations.py` plus static, date-stamped
issuer constituent lists.

## 4. Functional Specification

### 4.1 Inputs

- As-of date, EODHD-valid local parquet, and a rule (initially
  `12M>6M>3M>0`).
- Current issuer holdings for XLV, XLF, SMH, SOXX, and DRAM.

### 4.2 Outputs

- Four dated constituent CSVs and four ranked momentum-screen CSVs.
- A run JSON that identifies the included-list path/count.

### 4.3 Processing Logic

1. Normalize issuer-source tickers and deduplicate the SMH/SOXX union.
2. Intersect each list with the validated point-in-time S&P research universe.
3. Run the existing rule separately and write all qualifying stocks in rank
   order.

### 4.4 Branching & Decision Logic

- A ticker not in the validated universe is listed as unavailable, not scored.
- A stock must satisfy all three momentum comparisons to qualify.

### 4.5 Idempotency & Ordering

The output is date-scoped and safe to rerun; current holdings must be refreshed
before screening.

## 5. Integration Points

### 5.1 Internal Dependencies

- Validated S&P 500 parquet and latest momentum scanner.

### 5.2 External Dependencies

- Official issuer daily-holdings files.

### 5.3 Trigger Mechanism

Manual research run after completed market close.

### 5.4 Configuration

- Default rule: `12M>6M>3M>0`.
- Default output: all qualifiers plus a separate top-N view.

## 6. Data Model

Each constituent record records basket, ticker, issuer source, source date,
availability in the validated universe, and screen rank if qualified.

## 7. Error Handling & Failure Modes

| Failure Scenario | Expected Behaviour | Recovery Strategy |
|---|---|---|
| Issuer file unavailable | Preserve prior cache and report failure. | Retry later; do not substitute a different list silently. |
| Non-S&P constituent | Keep in unavailable CSV. | Expand the research universe only in a separately specified feature. |
| Insufficient history | Do not rank the ticker. | Report it as insufficient history. |

## 8. Non-Functional Requirements

### 8.1 Performance

Should finish quickly using local price data after holdings are downloaded.

### 8.2 Security

No API token is required for issuer holdings files. Existing token handling
remains environment-only.

### 8.3 Observability

Persist raw holdings files and write availability counts.

### 8.4 Backwards Compatibility

Do not change the all-S&P scanner’s current default behaviour.

## 9. Edge Cases

- Share-class ticker format differences such as `BRK.B` versus `BRK-B`.
- Duplicate stocks across SMH and SOXX.
- Cash, derivatives, and non-equity positions in holdings files.

## 10. Completed Decisions and Run Evidence

- The scanner accepts `--include-ticker-file`; it preserves the original
  point-in-time S&P membership filter. Non-S&P/non-eligible current ETF
  holdings are therefore not silently added.
- Lists are stored in `data/features/current_sector_lists/` as issuer-date
  snapshots: XLV (59 stocks), XLF (76 stocks), SMH/SOXX union (32 stocks), and
  an S&P-compatible DRAM subset (SNDK, MU, WDC, STX). DRAM's complete fund
  also owns non-U.S. securities outside this project's S&P universe.
- `analyze_sector_etf_rotation.py` includes `DRAM.US` as the separate `Memory`
  benchmark, producing its 21-session return, relative volume, and return
  relative to SPY with the other ETF rows.
- The July 17, 2026 screen wrote every qualifier using `--top 100`: XLV had 11,
  XLF had 27, and the SMH/SOXX union had 10.
- This is a current-basket screen, not a historical constituent backtest.
