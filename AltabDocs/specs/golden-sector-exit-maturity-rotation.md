Status: complete
Last Updated: 2026-08-02

## Overview

This v2 experiment corrects the earlier pooled-cash overlay. Every early-exited golden stock lot owns a separate rotation sleeve that expires on that lot's original twelve-month reinvestment date. Golden mapping, ranking, and sector cooldown remain unchanged.

## Behaviours

- [B1] Compute each lot's scheduled maturity as twelve calendar months after its golden entry date.
- [B2] On an early golden ETF risk-off exit, reserve that individual lot's net proceeds; do not pool it with other lots.
- [B3] On every completed ETF session after the exit and before maturity, screen the approved ETF universe for leaders: relative return above SPY from exit signal, close above SMA-21 and SMA-50, and relative volume at least the configured floor.
- [B4] At the first qualifying daily screen, buy up to three leaders equally at their next available ETF open.
- [B5] At the individual lot's scheduled maturity date, liquidate the sleeve at the ETF open; do not retain it merely because a later portfolio cashfall occurs.
- [B6] Use maturity cash for the golden decision on that date; retain the existing six-month cooldown on the exited ETF sector.
- [B7] Publish per-lot linkage from original stock to ETF sleeve and maturity liquidation.
- [B8] Provide a cash-only maturity control with the same early exits, contribution schedule, stock selection, cooldowns, and individual maturity dates, but no ETF purchase. This control is the only valid comparator for the ETF-rotation overlay.
- [B9] Provide a separately selectable volume-leader sleeve: form the normal top-N price leaders, invest only in the one with the largest relative volume when that volume meets a stricter configurable floor, and keep checking completed sessions until the source lot matures if no such ETF exists.
- [B10] Compare the selected ETF sleeve with an equal-weight sleeve of its three largest latest-public N-PORT constituents. Constituents use a 40% daily stop or the source ETF sleeve's recorded exit date, whichever comes first.
- [B11] Provide a cache-only daily decision report: from a specified completed risk-off date to a specified completed as-of date, rank ETF price leaders, apply the unchanged strict volume-leader selection, and publish the selected ETF's three latest-public N-PORT constituents for the next available session. A missing cache window is reported and excluded rather than fetched or backfilled.

## Branches and Errors

- [BR1] No leader before maturity: keep the reserved proceeds as cash until maturity.
- [BR2] Fewer than three leaders: invest only in qualifying leaders.
- [BR3] Never rotate into the triggering ETF.
- [BR4] Missing daily open: retain that allocation as cash.
- [BR5] A top price leader below the stricter selected-volume floor does not enter; it is reconsidered on the next completed session without using future information.
- [BR6] If fewer than three public, ticker-resolved N-PORT constituents or their daily OHLC is available, leave that ETF sleeve unchanged and report it as untestable; do not substitute current holdings.
- [BR7] If the top-volume member of the top price leaders does not meet the strict floor, publish no entry; do not weaken the threshold based on current outcomes.
- [FM1] Missing mapping: audit and skip the candidate rather than inventing a sector.

## Non-Goals

- No modification to golden scripts/reports.
- No SEC N-PORT mapping or assertion of literal fund flows.
- No capital borrowing, tax, or intraday execution model.
- No claim that either maturity variant is directly comparable with the separately funded full-period golden baseline.

## Acceptance

The resulting ledger must show original stock entry, early-exit signal, ETF screening date, ETF entry, scheduled maturity, ETF exit, and reinvestment cash for every rotated sleeve.
