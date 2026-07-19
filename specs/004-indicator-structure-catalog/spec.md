# Feature Specification: Indicator and Market-Structure Catalog

**Feature Branch**: `004-indicator-structure-catalog`  
**Created**: 2026-07-13  
**Status**: Draft  
**Input**: A provider-neutral, causal catalog of reusable indicators for trend,
momentum, volatility, supply/demand structure, and reproducible technical ratings.

## User Scenarios and Testing

### User Story 1 - Reuse validated indicators (Priority: P1)

As a researcher, I can request a named, versioned indicator with explicit
parameters and availability timing, so strategies reuse one tested formula rather
than implementing private copies.

**Independent Test**: Calculate each indicator on a fixed OHLCV fixture, compare it
with an independent reference implementation, and prove that mutating future bars
does not change prior outputs.

### User Story 2 - Build supply/demand context (Priority: P1)

As a supply/demand researcher, I can use causal pivots, prior-period levels,
swings, structure breaks, channels, anchored VWAP, and volatility context without
look-ahead or repainting.

**Independent Test**: Every structural event records its confirmation bar and is
unavailable before that bar closes. A future-mutation test preserves all earlier
confirmed events.

### User Story 3 - Produce reproducible technical summaries (Priority: P2)

As a researcher, I can combine declared moving-average and oscillator votes into
Strong Sell, Sell, Neutral, Buy, or Strong Buy using a versioned local formula.

**Independent Test**: A fixed signal-vote fixture produces deterministic category
thresholds and complete component lineage. The result does not claim to reproduce
any vendor's proprietary rating.

## Functional Requirements

- **FR-001**: Every indicator MUST be a provider/index-neutral function over typed
  observations and MUST declare formula version, parameters, warm-up, null policy,
  and availability timing.
- **FR-002**: Implement trend families: SMA, EMA, WMA, VWMA, HMA, MACD, ADX/DMI,
  Supertrend, Ichimoku, Parabolic SAR, Aroon, and moving-average ribbons.
- **FR-003**: Implement momentum families: RSI, stochastic, stochastic RSI, ROC,
  momentum, Williams %R, CCI, Ultimate Oscillator, Awesome Oscillator, TSI, CMO,
  RVI, and Fisher Transform.
- **FR-004**: Implement volatility families: ATR, NATR, Bollinger Bands and width,
  Keltner and Donchian channels, historical volatility, standard deviation,
  Chaikin Volatility, Choppiness Index, and Mass Index.
- **FR-005**: Implement causal structure families: standard/Fibonacci/Camarilla/
  Woodie pivots, Fibonacci retracement/extension, prior day/week/month levels,
  swings, confirmed fractals, causal confirmed Zig Zag, BOS, CHoCH, support and
  resistance, price/trend/regression channels, and anchored VWAP.
- **FR-006**: Zig Zag, fractals, swings, BOS, and CHoCH MUST expose confirmation
  time separately from pivot time and MUST NOT repaint published historical state.
- **FR-007**: Volume-profile POC, VAH, and VAL MUST NOT be inferred from daily OHLCV.
  They require a declared price-at-volume source such as intraday bars or trades.
- **FR-008**: The local technical summary MUST support configurable SMA and EMA
  votes for 5, 10, 20, 50, 100, and 200 periods plus declared oscillator votes.
  Its formula and category thresholds MUST be original, versioned, and auditable.
- **FR-009**: Existing validated families MUST be registered and reused; this
  feature MUST NOT introduce duplicate formulas for momentum returns, moving
  averages, breakout levels, volume, money flow, volatility, Supertrend, or ADX/DMI.
- **FR-010**: All parameter grids MUST be bounded and declared before evaluation.
  Feature generation does not select or finalize a strategy.
- **FR-011**: Each family MUST include exact-value fixtures, ticker-isolation,
  warm-up, invalid-input, and future-mutation tests before registration.

## Catalog Boundaries

The catalog provides feature functions and metadata. It does not scrape
TradingView or Investing.com, copy proprietary implementations, make investment
recommendations, optimize strategies, or certify vendor parity. Publicly visible
vendor indicator lists may inform coverage, while QuantResearch retains its own
documented calculations and validation fixtures.

## Success Criteria

- **SC-001**: Every registered feature has a stable ID, formula version, parameter
  lineage, and causal availability contract.
- **SC-002**: Independent fixtures and future-mutation tests pass for every family.
- **SC-003**: Strategies reference catalog feature IDs and contain no duplicate
  indicator calculation code.
- **SC-004**: Unsupported volume-profile requests fail explicitly with a source-
  granularity explanation.

