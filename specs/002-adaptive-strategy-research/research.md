# Research Notes: Adaptive Strategy Platform

## Evidence Source

This specification consolidates the user-supplied Daily Strategy Scan transcript.
The linked private ChatGPT page was unavailable in the logged-out in-app browser,
so it provided no additional authoritative content.

## Resolved Decisions

1. Track 60% arithmetic average calendar-year return as an aspirational
   stitched-forward target; report CAGR separately.
2. Use eight complete calendar years training, the next two years forward, and a
   two-year step.
3. Freeze search settings before a run; forward results never feed back into the
   same fold.
4. Use point-in-time membership; never trade the acquisition union.
5. Use DuckDB for definitions/metadata and versioned Parquet for large artifacts.
6. Trade completed signals next eligible session; gap stop entries at the worse of
   open or trigger.
7. Default eligibility requires 20 entries/year average and normally 12 each year.
8. Configure costs and separately label the optional 15% short-term profit haircut
   as a user approximation.
9. Keep shorting disabled in the first production slice.
10. A 2018–2025 selection for 2026–2027 is live/unobserved, not a backtest result.

## Prototype Lessons

- High return from a few concentrated trades is weak evidence.
- Entry and exit rules must be coherent; exit-only Supertrend produced many
  one-week closures.
- Drawdown changes the preferred strategy: 32.01% CAGR/-23.59% DD was favored over
  32.75% CAGR/-42.39% DD.
- A spectacular momentum result can be an adjustment/identity defect rather than
  alpha; formula consistency alone does not prove economic continuity.
- Broad grids create selection bias; nested validation, fixed budgets, and complete
  candidate retention are required.

## Strategy and Feature Research Program

Study cross-sectional/time-series momentum, breakouts, dual Supertrend, moving
averages, volatility-adjusted trend, volume confirmation, relative strength, and
ATR/volatility sizing. Mean reversion and short systems remain comparators.

The balanced dual-Supertrend configuration is a historical control, not a final
selection. No strategy becomes current until the full point-in-time feature set,
bounded searches, all completed walk-forward windows, robustness checks, costs,
and the 40% drawdown gate have passed.

Feature families are implemented separately: returns/momentum; moving averages and
slopes; breakouts; volume; volatility; Supertrend grids; ADX/DI; oscillators;
relative strength; market/sector regime; and sizing/risk inputs. Each family has a
content-derived version and hand-calculated/no-future-data tests.

Required reporting includes total return, CAGR, arithmetic/median/worst calendar
year, positive-year fraction, volatility, Sharpe, Sortino, drawdown, Calmar,
turnover, exposure, trade count/frequency, win rate, profit factor, holding time,
one-week exits, concentration, costs, and simplified tax haircut.

## Supply and Demand Zone Research Definition

The linked private ChatGPT URL rendered only the logged-out shell, after which the
user supplied the complete conversation directly. The daily strategy detects
Drop-Base-Rally demand and Rally-Base-Drop supply structures. The initial medium
control uses base range at most 50% of ATR(14), previous range at least 2x base,
departure range at least 3x base, departure body at least 60% of its range, and
departure volume at least 1.25x the prior 20-day average. Zones become available at
departure close and are eligible only on later bars.

The declared optimization dimensions include previous/departure ratios, base ATR
limit, base and departure body ratios, volume multiplier/period, ATR period, stop
buffer, reward/risk, retests, expiry, trend filter, structure lookback, and entry
type. Search remains fixed-budget and walk-forward; robust parameter neighborhoods
are preferred over isolated maxima. Daily bars use stop-first treatment whenever
both stop and target lie within the same bar. Supply zones can be researched as
features, while actual short execution remains disabled pending short-risk tests.
