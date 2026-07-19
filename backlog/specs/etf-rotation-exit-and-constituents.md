Status: draft
Last Updated: 2026-07-18

## 1. Overview

Replace the fixed 21-session ETF exit in the momentum/breadth event study with
a research-only rotation exit. An open position exits when ETF momentum weakens
relative to SPY, activity is elevated, and an optimized drawdown threshold is
met. Compare ETF ownership with ownership of major qualifying constituents.

## Pending

### Conversation Summary

User wants exits based on apparent rotation away from an ETF rather than a
fixed holding period. The proposed exit combines negative ETF relative strength
versus SPY, ETF volume above its trailing 21-session average, and a percentage
decline threshold. User also wants the same concept tested on major
constituents.

## 2. Goals & Non-Goals

### Goals

- Compare ETF ownership against an equal-weight top-10 current-weight
  constituent proxy.
- Select an exit threshold only on 2010-2020.
- Exclude 2021-2022 from evaluation and report the final test from 2023 through
  the latest completed session.

### Non-Goals

- Claim current weights are historical ETF weights.
- Interpret price/volume as confirmed institutional flows.

## 4. Functional Specification

### 4.1 Inputs

- Existing ETF entry regime, candidate exit-drawdown grid, ETF price/volume,
  SPY benchmark, and top-10 issuer-weight snapshots where available.

### 4.3 Processing Logic

1. Train candidate exit thresholds on 2010-2020 only.
2. An open position exits when ETF 21-session relative strength versus SPY is
   negative, ETF relative volume is at least 1, and ETF drawdown from entry or
   peak reaches the candidate threshold.
3. Select a predeclared metric and freeze the threshold.
4. Skip 2021-2022 and report 2023 through the latest completed session without
   retuning.

### 4.4 Branching & Decision Logic

- Use top 10 current issuer weights where the issuer publishes them; label them
  `static_current_weight_proxy`.
- If an issuer weight snapshot is unavailable, omit the constituent comparison
  rather than inventing weights.

### Remaining Questions

1. For the constituent version, define “major”: use the top 10 current issuer
   weights where available. Confirmed.
2. Train/test design confirmed: optimize thresholds only on 2010-2020, exclude
   2021-2022, and report untouched 2023 through the latest completed session.

### Raw Notes

- Dated historical constituent weights are incomplete; current weights would
  be labelled a static-weight proxy.
- Candidate exit threshold grid: 0%, -2%, -4%, -6%, -8%, -10% from entry,
  with negative 21-session relative strength and relative volume >= 1.
