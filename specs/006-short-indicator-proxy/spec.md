# Feature Specification: Research Short Indicator Proxy

**Status:** In progress  
**Feature:** 006-short-indicator-proxy

## Purpose

Provide a reproducible, research-only short-sale proxy for four completed-close
technical signal families. It is explicitly not an order, borrow-availability
check, or investment recommendation.

## Functional Requirements

1. The command MUST use validated adjusted prices, point-in-time S&P 500
   membership, a prior completed-session signal, and next-session-open entry.
2. It MUST test RSI/Bollinger mean reversion, breakdown plus relative volume,
   moving-average trend failure, and spike/volume/reversal exhaustion.
3. It MUST additionally support a daily-entry research mode with no fixed time
   exit: a close-confirmed stop or 1:1/1:2/1:3 profit target covered at the
   following open, fixed $1,000 entries, no borrow-fee replay, no reinvestment,
   and an asymmetric realised-P&L haircut (90% of gains, 110% of losses).
4. It MUST write every short trade with entry/cover prices, gross short return,
   borrow fee, transaction costs, net return, and exit reason.
5. It MUST disclose that all stocks are assumed borrowable and that dividends,
   hard-to-borrow fees, locate fees, margin requirements, and availability are
   not modeled.

## Acceptance Scenarios

- A signal dated Tuesday can only enter at Wednesday's open.
- A short whose completed close breaches its stop covers at the following
  available open, including an adverse gap.
- A one-week short holds through the maturity close and covers at the next
  available open.
- Re-running with the same artifact and inputs produces the same ordered CSV.
- A daily-entry trade remains open until a target or stop is confirmed; trades
  still open at the analysis end are reported separately and excluded from
  realised P&L.

## Requirement Checklist

- [x] Research-only scope and proxy limitations defined.
- [x] Point-in-time signal and membership timing defined.
- [x] Exit model and fixed-contribution accounting defined.
- [x] Evidence outputs defined.
