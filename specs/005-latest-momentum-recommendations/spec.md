# Feature Specification: Latest Point-in-Time Momentum Recommendations

**Status:** Complete  
**Feature:** 005-latest-momentum-recommendations

## Purpose

Produce a reproducible, non-executing recommendation list from the latest
completed daily session for a selected declarative momentum rule.  The list is
for research and paper-trading review; it is not investment advice or an order
submission facility.

## Functional Requirements

1. The command MUST read a supplied validated adjusted-Parquet artifact, or the
   current validated S&P 500 artifact by default, without changing source data.
2. It MUST use only the latest completed session at or before `--as-of` for
   signals, point-in-time membership, 60-calendar-day seasoning, approved
   seasoning exceptions, reviewed ticker exclusions, and the configured
   21-session volatility cap.
3. It MUST support every existing declarative momentum rule and rank qualifying
   candidates by 252-session return, falling back to return from the current
   continuous history segment only when 252 sessions are unavailable.
   The no-2-month `12M>9M>6M>3M>0` variant MUST remain distinct from the
   `12M>9M>6M>3M>0 & 2M>0` variant.
4. It MUST write JSON and CSV evidence containing signal date, intended next
   execution session, all relevant returns, volatility, membership/exception
   flags, rank, and the input artifact path.
5. A recommendation MUST be labelled `next_session_open` and MUST NOT claim
   execution at a historical open that has already occurred.

## Acceptance Scenarios

- Given July 14, 2026 as-of data, a scan uses July 14 as the completed signal
  date and labels its execution as the first later market session when one is
  available.
- A company that was not an eligible S&P 500 constituent on the signal date is
  excluded even if it is in the price file.
- A standard new constituent with less than 60 days of continuous membership is
  excluded, while an approved effective-dated spin-off exception may pass.
- Re-running the command with the same data and arguments produces the same
  ordered CSV and JSON contents.

## Requirement Checklist

- [x] Point-in-time signal timing defined.
- [x] Membership and seasoning constraints defined.
- [x] Ranking fallback defined.
- [x] Evidence outputs and non-execution boundary defined.
