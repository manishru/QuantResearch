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

### Historical stress-test record — 1996 to 2009

Run on 2026-07-18 using the frozen rule: 10% ETF drawdown from post-entry
peak, negative 21-session ETF relative strength versus SPY, ETF relative
volume at least 1, then top-1 constituent with 20-day SMA above 50-day SMA
and stock relative volume at least 1. Result: 696 static-constituent-proxy
trades; 11.88% mean individual-trade return and 50.57% win rate.

The rule was not resilient through every regime: 2001 averaged -5.90% and
2008 averaged -8.57% with a 17.4% win rate. It recovered strongly in 2009
(+23.66% average). This reinforces that it is an event study and needs risk
controls; do not treat it as an all-weather or live-trading strategy.

### Golden strategy decision — 2026-07-19

The frozen 20/50, top-1 constituent, ETF relative-volume/breadth entry and
10% ETF rotation exit was initially recorded as Golden 1 and is now
**Golden 2** in
`docs/golden_strategy_registry.md`. The label applies to the rule, not to a
permanent ticker. The July 17 XLF screen (FITB, USB, STT) is an auditable
snapshot only. Other strategy families remain unranked because their
assumptions and out-of-sample evidence are not comparable. Pending horizon
comparison may supersede this rule only using the predeclared 2010–2024 train
and 2025–2026 forward test.

### Historical sector-overlay data requirement — 2026-07-19

Do not use the current EODHD sector classification or current ETF holdings as
the definitive historical parent-sector mapping for Golden 1 lots. A valid
all-sector overlay needs dated sector/GICS classification for each ticker and,
if the claim is ETF constituent membership rather than sector exposure, dated
ETF holdings. `build_golden1_current_sector_proxy.py` is retained only for
clearly labelled exploratory work. The combined Golden 1 sector-ETF exit test
is pending a point-in-time classification/holdings source.
