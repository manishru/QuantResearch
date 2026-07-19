# Golden strategy registry

This registry ranks only research strategies with comparable, documented
out-of-sample evidence. A Golden label is not investment advice, a guarantee,
or an instruction to trade.

## Golden 1 — 12M > 6M > 3M momentum, 51-week hold

**Status:** provisional Golden 1, recorded 2026-07-19.

### Rule

1. On the 26th of each month (or next available market session), select the
   top one point-in-time S&P 500 stock satisfying `12M > 6M > 3M > 0`.
2. Require one-month volatility at or below 15%.
3. Invest a fixed $1,000 per monthly lot; no reinvestment and no tax model.
4. Exit at 51 weeks or a 45% stop. End-period lots are marked to market.

### Evidence

| Evaluation | XIRR | ROI | Win rate | Lots | Qualification |
|---|---:|---:|---:|---:|---|
| Train: 2010–2024 | 15.52% | 25.69% | 63.33% | 180 | 15 lots marked open at the end |
| Forward: 2025–2026-07-17 | 37.51% | 24.69% | 55.56% | 18 | 12 lots marked open at the end |

The forward period is only about 18 months and contains substantial unrealized
exposure, so this is a provisional ranking rather than a durability claim.

## Golden 2 — ETF rotation constituent rule

**Status:** frozen for forward monitoring on 2026-07-19.

### Rule

1. A constituent-backed ETF basket starts a regime only when its lookback
   return exceeds SPY's, ETF relative volume is at least 1.0, and constituent
   breadth is at least 55%.
2. Within that basket, retain point-in-time eligible constituents with
   20-day SMA above 50-day SMA and stock relative volume at least 1.0.
3. Select the single highest `(SMA20 / SMA50) - 1` constituent.
4. Exit when its parent ETF is at least 10% below its post-entry peak, has
   negative 21-session performance relative to SPY, and ETF relative volume
   is at least 1.0. The modeled exit is the following market session's open.

### Evidence used to assign Golden 2

The configuration was chosen from a predeclared 10/30, 20/50, 30/100, and
50/150 SMA comparison using the same entry/exit method.

| Evaluation | Average individual-trade return | Win rate | Trades |
|---|---:|---:|---:|
| Train: 2010–2020 | 27.57% | 60.08% | 962 |
| Holdout: 2023–2026-07-17 | 14.26% | 59.18% | 267 |
| Historical stress test: 1996–2009 | 11.88% | 50.57% | 696 |

The historical stress test includes meaningful weakness in 2001 and 2008, so
the rule is not an all-weather strategy.

### Latest research snapshot — July 17, 2026

The fresh qualifying basket was XLF Financials. The static-current-list
research ranking was FITB (rank 1), USB (rank 2), STT (rank 3). This snapshot
is recorded for audit only; it does not permanently designate any ticker as a
Golden holding.

## Not ranked as Golden yet

- Monthly/weekly momentum strategies use different holding periods, cash-flow
  assumptions, and in several cases only partial out-of-sample validation.
- Short-sale proxies assume borrow availability and have not demonstrated a
  comparable risk-adjusted, out-of-sample result.
- The configurable 5/10/15/21-session rotation-horizon comparison is pending.
  A horizon can replace Golden 1 only if selected using its training sample and
  remains stronger in the untouched 2025–2026 forward period.
