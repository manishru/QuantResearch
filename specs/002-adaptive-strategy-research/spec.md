# Feature Specification: Adaptive Point-in-Time Strategy Research

**Feature Branch**: `002-adaptive-strategy-research`  
**Created**: 2026-07-13  
**Status**: Planned  
**Depends On**: `001-point-in-time-index-data`

## Problem Statement

The platform must discover systematic equity strategies without survivorship bias,
look-ahead leakage, or repeated tuning against the same future period. Earlier
prototypes explored momentum, breakouts, volume, Supertrend, concentrated rankings,
and long/short portfolios. Some produced attractive headline returns, but low trade
counts, excessive drawdowns, or corrupt corporate-action histories made those
results unsuitable for deployment.

The research system needs point-in-time universes, realistic portfolio simulation,
an auditable DuckDB result store, and frozen 8-year training / 2-year forward
windows. A 60% average annual return is an aspirational research objective, not a
promise and not permission to overfit. No strategy passes solely because its
in-sample return reaches that number.

## Prior Research Baseline

The implementation must preserve these historical findings as benchmark records:

- A 7-week breakout with weekly Supertrend `(7, 4.78)` produced about 7.48% CAGR
  over the tested 2015–2025 interval.
- An exit-only system (`5W > 6M > 9M`, positive 5W, top 20, seven positions, 7W
  breakout, exit ST `(52, 4.88)`) reported 42.38% CAGR but closed 69.34% of trades
  within one week, revealing an entry/exit mismatch.
- The balanced dual-Supertrend historical control used `5W > 6M > 9M`, positive 5W, top-20
  candidates, 16 positions, 7W breakout, entry ST `(5, 2.25)`, and exit ST
  `(13, 2.75)`. It reported 32.01% CAGR, -23.59% maximum drawdown, 260 entries,
  22.8 entries/year, and 31.26 weeks average holding time.
- A higher-CAGR dual-ST variant reported 32.75% CAGR with -42.39% drawdown and was
  rejected in favor of the better-balanced baseline.
- A 52-week cross-sectional momentum result reported 52.6% full-period and 81.1%
  out-of-sample CAGR, but implausible histories such as SNDK/WDC/MU/STX indicated
  corporate-action or identity contamination. It is a rejected benchmark.
- Broad long/short and bear-short prototypes underperformed after drawdown, borrow,
  recall, squeeze, and unlimited-loss risks were considered.

These values are prototype observations and MUST be reproduced from versioned
inputs before they are treated as comparable results.

No prototype or baseline is the finalized strategy. Baselines are controls used to
verify semantics and measure whether new candidates add robust stitched-forward
value. Strategy discovery is repeatable and versioned; each declared experiment
may search a new bounded space, but completed forward periods are never reused to
tune that experiment or silently promote a winner.

## User Scenarios and Testing

### User Story 1 - Reproduce an Experiment (Priority: P1)

Every run is tied to exact data, universe, feature, cost, tax, code, and random-seed
versions so it can be reproduced later.

**Acceptance Scenarios**:

1. Identical inputs and seed produce identical trades, equity, and metrics within
   declared numerical tolerance.
2. A changed feature or universe version receives a distinct run ID and cannot
   overwrite the prior result.
3. An unvalidated dataset or unresolved identity mapping is rejected.

### User Story 2 - Run a Frozen Walk-Forward Tournament (Priority: P1)

Strategies are selected on an 8-calendar-year training window and evaluated on the
next untouched 2 calendar years.

**Acceptance Scenarios**:

1. The first fold trains 1996-01-01 through 2003-12-31 and evaluates 2004-01-01
   through 2005-12-31.
2. The next fold advances two years: train 1998-01-01 through 2005-12-31 and
   evaluate 2006-01-01 through 2007-12-31.
3. Candidate selection sees only training data; test metrics become visible only
   after the selected definition is frozen.
4. Warm-up observations cannot create trades, labels, rankings, or metrics in the
   wrong period.
5. The 2018–2025 window may select a strategy for 2026–2027, but those years remain
   live/unobserved until complete and are not reported as backtested forward data.

### User Story 3 - Search Without Target Chasing (Priority: P1)

The engine uses a bounded, declared search space and selection policy.

**Acceptance Scenarios**:

1. Every run records its candidate space, budget, objective, constraints, and
   search algorithm before evaluation.
2. Candidates can be rejected for insufficient trades, excessive concentration,
   anomaly exposure, drawdown breach, or non-finite metrics.
3. A strategy with 60% in-sample average yearly return but weak forward performance
   is not accepted.
4. All evaluated candidates, including failures, are retained in DuckDB.

### User Story 4 - Simulate Point-in-Time Trading (Priority: P1)

Signals and fills use only completed observations and membership effective on the
decision date.

**Acceptance Scenarios**:

1. A security can be selected only while eligible in the chosen index.
2. A completed weekly signal executes on the next eligible session; a breakout
   stop fills at `max(next open, trigger)` when price gaps above it.
3. A completed weekly exit fills at the next eligible session open unless the
   declared execution model states otherwise.
4. Missing, quarantined, stale, or anomalous data cannot silently create a fill.
5. Having price data in the historical acquisition union does not make a security
   eligible; rankings and orders contain only members effective on that date.

### User Story 5 - Compare Risk, Costs, and Robustness (Priority: P1)

Every result is reported net of configured costs and alongside risk evidence.

**Acceptance Scenarios**:

1. Reports distinguish CAGR from arithmetic average calendar-year return.
2. Reports include maximum drawdown, worst year, positive-year fraction, Sharpe,
   Sortino, turnover, exposure, trade count, holding period, and concentration.
3. Commission, slippage, and an optional 15% haircut on profitable trades held 365
   days or less are separately reported; the haircut is labeled an approximation.

### User Story 6 - Publish a Frozen Daily Scan (Priority: P2)

The daily scanner uses only the current frozen strategy, latest complete data,
point-in-time membership, and recorded holdings.

**Acceptance Scenarios**:

1. Existing positions are evaluated for exits separately from fresh entries.
2. A held symbol is not reported as a fresh buy without a declared re-entry rule.
3. Output records signal/execution date, trigger convention, size, stop, strategy
   and fold IDs, and reason fields.

## Functional Requirements

- **FR-038**: The monthly-entry momentum research control MUST support an explicit
  calendar-week holding-period matrix from 1 through 52 weeks. It MUST preserve
  point-in-time membership, use the first completed trading session on or after
  the calendar target, retain conservative stop-first ordering, and rank tax-aware
  results by fully taxed XIRR with ending wealth as a deterministic tie-breaker.

- **FR-001**: Consume only validated Feature 001 datasets and point-in-time
  membership.
- **FR-002**: Record data, universe, mapping, feature, configuration, code,
  dependency, calendar, cost, tax, and seed versions for every run.
- **FR-003**: Strategies MUST be declarative, immutable, uniquely identified, and
  separable into universe, signal, ranking, entry, exit, sizing, and risk rules.
- **FR-004**: The initial catalog MUST support momentum returns (1W–12M), breakouts
  (5–60W), SMA/EMA/WMA/HMA/VWMA, ATR/NATR/standard deviation/historical volatility,
  Supertrend, ADX/DI, RSI, MACD, CCI, Williams %R, stochastic, and volume features:
  RVOL, volume averages/ratios, highest/lowest volume, spikes, dry-ups, OBV, CMF,
  MFI, accumulation/distribution, and volume trend/breakout/contraction.
- **FR-004A**: The declared Supertrend feature set MUST contain the Cartesian grid
  of periods `5, 7, 10, 13, 14, 20, 52` and multipliers `1.5, 2, 2.5, 3, 3.5, 4`,
  plus reference-control pairs `(5, 2.25)`, `(13, 2.75)`, `(7, 4.78)`, and
  `(52, 4.88)`. Reference pairs preserve prior research semantics and MUST NOT be
  interpreted as selected or finalized parameters.
- **FR-005**: Relative-strength features MUST support configured market and sector
  benchmarks without hard-coded S&P 500 assumptions.
- **FR-006**: Daily and weekly features MUST use completed bars and declare their
  availability timestamp.
- **FR-007**: Enforce point-in-time eligibility at signal and execution time and
  declare removal handling for open positions. The complete historical acquisition
  union (approximately 1,200 S&P symbols) MUST NEVER be used as a daily candidate
  universe; only the membership snapshot effective on that simulated date is used.
- **FR-008**: Model next-session fills, gaps, missing sessions, delistings, cash,
  position limits, and deterministic order priority.
- **FR-009**: Support commissions, slippage, and configurable borrow costs for any
  explicitly enabled short strategy.
- **FR-010**: Make the short-term-profit haircut independently configurable and
  label it a simplified user model, not legal or tax advice.
- **FR-011**: Register search spaces and budgets before evaluation and retain every
  attempted candidate and failure reason.
- **FR-012**: Enforce a configured sample-size threshold; the initial default is at
  least 20 entries/year on average and normally 12 per calendar year.
- **FR-013**: Report concentration, turnover, holding time, exposure, and data
  quality in addition to performance.
- **FR-014**: Use 8 calendar years train, the next 2 years forward, and a 2-year
  step with non-overlapping forward periods.
- **FR-015**: Freeze fold selection before forward evaluation; forward results MUST
  NOT influence that fold's candidate choice.
- **FR-016**: Training SHOULD use nested time-series validation or purged folds with
  an embargo covering the maximum label/holding dependency.
- **FR-017**: Keep in-sample, internal-validation, forward, stitched-forward, and
  live/unobserved metrics separate.
- **FR-018**: Treat 60% as aspirational and evaluate it on stitched-forward results;
  it is not a sole objective or guarantee.
- **FR-019**: Use a predeclared multi-objective score and hard risk constraints.
  The deployment hard maximum drawdown is 40%; experiments MAY declare a stricter
  limit but MUST NOT loosen it above 40%.
- **FR-020**: Reject non-finite prices, implausible jumps, identity discontinuities,
  or unresolved adjustment histories until reviewed.
- **FR-021**: DuckDB MUST persist definitions, candidates, folds, selections,
  trades, equity, yearly metrics, findings, and live strategy state.
- **FR-022**: Results MUST be append-only/versioned and never overwrite a published
  experiment.
- **FR-023**: Baselines MUST include buy-and-hold, the balanced dual-ST prototype,
  and the rejected contaminated momentum result. Baselines MUST be labeled
  research controls and MUST NOT be represented as finalized strategies.
- **FR-027**: Feature work MUST be delivered and independently validated in small
  families; an experiment MUST declare exactly which feature versions it consumes.
- **FR-028**: Repeated research runs MUST create new immutable experiment versions;
  they MUST NOT mutate prior candidates, selections, or forward results.
- **FR-024**: Implement long-only first; shorting stays disabled until dedicated
  borrow/recall and risk acceptance tests pass.
- **FR-025**: Daily scanning MUST use a frozen strategy and emit auditable signals
  without placing orders.
- **FR-026**: Core research logic MUST be index/provider neutral so KOSPI 200 and
  other indexes can reuse it via adapters and configuration.
- **FR-029**: Research outputs MUST retain sufficient per-run orders, fills, trades,
  equity, reasons, feature/parameter lineage, and bounded OHLCV references for a
  future web workbench to reconcile and visualize results without recomputation.
- **FR-030**: Strategy execution MUST remain independent of HTTP and UI frameworks;
  the future web server invokes application services and never implements feature
  or backtest formulas.
- **FR-031**: Supply/demand zones MUST use an explicit versioned daily three-candle
  definition. For base candle `i`, demand requires bearish `i-1`, a small base, and
  bullish departure `i+1`; supply reverses those directions. Configurable filters
  MUST include base/ATR, previous/base range, departure/base range, departure
  body/range, departure/prior-average-volume, structure lookback, expiry, and
  retests. A zone MUST NOT exist before the departure candle closes. Demand spans
  base low to the upper base body and invalidates on a close below its distal low;
  supply spans the lower base body to base high and invalidates on a close above
  its distal high. Alternative definitions require new versions.
- **FR-032**: Every supply/demand strategy evaluation MUST intersect candidates
  with index membership effective on both signal and execution dates. This applies
  independently in every 8-year training and 2-year forward window.
- **FR-032A**: The point-in-time replay boundary MUST remove non-members before
  ranking, apply deterministic score/ticker tie-breaking, and independently reject
  an entry when membership ends before its execution session. Acquisition-union
  symbols and bars outside the selected fold period MUST NOT influence rankings,
  signals, fills, or metrics. Exits MAY liquidate an existing position after index
  removal.
- **FR-033**: The initial supply/demand research control uses daily candles and the
  medium `1:2:3` family, then evaluates bounded registered parameter searches for
  ratios, ATR/base limits, body strength, volume, stops, reward/risk, retests,
  expiry, trend, structure, and entry type. Same-day stop-and-target ambiguity MUST
  resolve conservatively as stop first. Supply detection is permitted, but short
  execution remains disabled until FR-024 is satisfied.
- **FR-034**: A causal demand revisit MUST produce an immutable trade plan containing
  decision/availability date, zone, entry type and price, current ATR, distal stop,
  R-multiple target, retest number, and deterministic ranking score. Zone-edge and
  midpoint entries are limit orders; confirmation-close entries execute as next-
  session market orders. They MUST NOT be represented as stop-entry triggers.
- **FR-035**: Fold evaluation MUST calculate features with declared warm-up, restrict
  plan decisions and execution bars to the requested training or forward segment,
  construct membership for every execution session, and return simulation,
  performance, and candidate-gate metrics together. A production run MUST reject
  data lacking a validated immutable version and MUST NOT publish a best strategy
  from candidate or quarantined input.
- **FR-036**: The first production-data execution MUST be a fixed-budget pilot whose
  budget and candidate order are declared before evaluation. Provider symbols MUST
  be translated back to original constituent symbols using only approved mappings.
  Each completed fold MUST select on its 8-year training segment, freeze once, and
  replay the selected parameters on its untouched 2-year forward segment. Pilot
  results MUST retain every candidate and MUST be labelled non-final rather than
  claimed as the globally most profitable strategy.
- **FR-037**: The 10-year cross-sectional momentum reproduction MUST rank eligible
  point-in-time constituents by close-to-close 252-session return on the final market
  session of each week, select ten, and execute the rebalance on the next market
  session using observed opens. Holdings MUST be equal weighted with fractional
  shares, membership MUST be rechecked on execution, and transaction cost MUST equal
  0.10% of absolute traded notional. The report MUST disclose extreme momentum inputs
  and MUST NOT silently equate this causal reproduction with an earlier same-close
  prototype.
- **FR-038**: The monthly momentum-lot study MUST compare the ordered rules
  `12M>9M>6M>3M>0`, `9M>6M>3M>0`, and `6M>3M>0`, always ranking qualifying
  point-in-time constituents by 12-month return. For each rule it MUST compare
  top one through top five and nominal calendar purchase days 1 through 31.
- **FR-039**: Each month MUST contribute exactly $10,000 of the declared annual
  $120,000 budget, divided equally among that configuration's selected securities.
  The signal MUST use the completed session before the scheduled execution open.
  A nominal day beyond month-end MUST clamp to month-end; execution MUST occur on
  the first verified market session on or after that date, and duplicate execution
  dates within a day-of-month experiment MUST be rejected.
- **FR-040**: Every monthly lot MUST be independent, use fractional shares, exit at
  the first session open on or after 365 calendar days, or earlier at a 45% stop.
  Gap-through stops MUST fill at the observed open; otherwise an intraday stop touch
  MUST fill at the stop price. Membership MUST be effective on both signal and entry.
  Results MUST retain every trade, including open lots marked to the last close, and
  compare configurations using invested capital, net proceeds, ROI, XIRR, win rate,
  stop rate, and trade count without treating contributions as investment return.
- **FR-041**: A constituent MUST have at least 60 calendar days of continuous index
  membership at the signal date. Re-entry starts a new seasoning interval. A spin-off
  MAY bypass seasoning only through an effective-dated exception recording the child,
  parent, rationale, evidence, reviewer, and approval status. The reviewed registry
  distinguishes direct S&P 500 spin-off admissions from later admissions such as
  SNDK/WDC; no exception may be inferred from ticker data. This bypass removes only
  the 60-day index-tenure gate. It MUST NOT synthesize child history from the parent,
  relax feature warm-up, alter ranking, or bypass any other strategy or execution rule.
  A separately approved inherited-eligibility exception MAY admit a spin-off child
  from its separation date when its recorded parent was an effective S&P 500
  constituent. SNDK/WDC is approved from 2025-02-24. This treatment MUST use only
  the child's continuous post-separation observations and MUST NOT copy, splice, or
  otherwise derive returns from the parent's history.
- **FR-042**: Monthly momentum configurations MUST require only the longest horizon
  named by their rule: 252 sessions for `12M>9M>6M>3M>0`, 189 sessions for
  `9M>6M>3M>0`, and 126 sessions for `6M>3M>0`. Cross-sectional ranking MUST use
  252-session return when available and otherwise return since the beginning of the
  current continuous security-history segment. Returns MUST NOT cross a security
  incarnation or a gap longer than 45 calendar days.
- **FR-043**: A monthly momentum candidate MUST have a non-annualized, 21-session
  sample standard deviation of daily simple returns no greater than 10%. A held lot
  MUST generate a deterioration signal when its completed daily return is at most
  -15% measured from the prior close to the current close, thereby including opening
  gaps, AND volume is at least 1.5 times the average of the prior 10 completed sessions,
  excluding the signal day. To prevent look-ahead, that signal exits at the next
  available session open. An intraday stop occurring before that execution retains
  priority.
- **FR-044**: The explicit no-2-month variant `12M>9M>6M>3M>0` MUST be evaluated
  alongside the existing `& 2M>0` variants. It requires only
  `ret252 > ret189 > ret126 > ret63 > 0`; `ret42` may be negative. Every other
  candidate gate, including the 21-session volatility cap of 10%, remains unchanged.
  The `& 2M>0` variants additionally require a positive 42-session return calculated
  from the child's or security's own continuous history.
- **FR-045**: The comparative monthly momentum family MUST also evaluate
  `5M>2M>0`, `5M>3M>0`, `6M>4M>0`, `4M>2M>0`, `3M>2M>0`,
  `7M>4M>0`, `8M>5M>0`, and `9M>6M>0`
  using 21 trading sessions per nominal month. All rule families MUST share the
  same frozen universe, execution, cost, risk, ranking, and exit assumptions.
- **FR-046**: The tax-aware reinvestment replay MUST add the declared monthly
  contribution only during the declared contribution phase (12 months for the
  current study), combine it with cash returned by
  positions that exited before that purchase, and invest the complete available
  balance equally across that month's selected securities. After the contribution
  phase, a month with no available exit proceeds MUST make no purchase. A maturity
  or earlier exit on the scheduled purchase session MUST be processed first and its
  after-tax proceeds reused for that session's new purchase, implementing the
  declared monthly tranche rollover convention. The tax reserve MUST apply the
  declared rate to cumulative net realized profit: realized losses offset realized
  gains and may reduce/refund an earlier reserve. Unrealized open gains MUST NOT be
  deducted from investable cash or ending wealth; their hypothetical liquidation tax
  is disclosed separately. Transaction-cost-inclusive lot returns MUST scale linearly with the
  allocated capital. The report MUST reconcile contributions, realized proceeds,
  taxes, idle cash, open-position value, hypothetical liquidation tax, ending
  after-tax wealth, ROI, and account-level XIRR. Tax treatment is a configurable
  research approximation, not personal tax advice.
  Published tax-aware results MUST distinguish net realized tax already reserved
  from estimated tax on unrealized open gains. A result labeled fully after-tax
  MUST subtract both. Monthly negative tax-reserve changes MUST be labeled as loss
  offsets/refunds rather than negative tax payments.
  A normal maturity MUST occur on the twelfth subsequent scheduled monthly
  purchase session for the same nominal-day experiment. The mature position MUST
  be sold at that session's open and its after-tax proceeds MUST be available for
  the replacement purchase at the same open; no settlement or cash-receipt delay
  is modeled. An early-exit tranche MUST spread its after-tax proceeds equally across every
  scheduled monthly purchase remaining through that tranche's original twelfth-cycle
  maturity; for example, $7,000 with six scheduled months remaining contributes
  $1,166.67 to each. A normal one-year maturity contributes its complete after-tax
  proceeds to that maturity month's purchase.
- **FR-047**: Monthly momentum experiments MUST declare whether the optional
  volume/price deterioration exit is enabled. A disabled run MUST omit that exit
  completely rather than emulate it with undocumented extreme thresholds, while
  preserving all other declared strategy and accounting assumptions.
- **FR-048**: The optional stepwise trailing-profit exit MUST activate only when a
  completed daily close reaches a 100% gain. Its initial protected return is 60%;
  every additional 10 percentage points in the highest completed-close return raises
  the protected return by 5 percentage points. A completed close at or below the
  current protected level generates a signal that executes at the next session open.
  The fill MAY be above or below the signal close. The highest intraday price MUST
  NOT activate or advance this end-of-day rule.
- **FR-049**: A capital-smoothing replay MAY divide every normal maturity's
  after-tax proceeds equally across a declared number of scheduled monthly purchase
  cycles, beginning with the same-session maturity cycle. The current fair-allocation
  study uses 12 cycles. Undeployed installments MUST remain cash, all installments
  MUST reconcile to the original proceeds, and the unsmoothed one-cycle convention
  MUST remain available for comparison.
- **FR-050**: A monthly-momentum run MAY accept an explicit, report-visible list
  of reviewed data-quality exclusions. Excluded symbols MUST be removed before
  ranking, MUST NOT silently alter point-in-time membership history, and MUST be
  recorded in the run assumptions. The current fair-allocation study excludes CVC
  because its available provider history contains no realizable acquisition exit.

## Success Criteria

- **SC-001**: Fixed fixtures prove zero look-ahead across signals, membership,
  rankings, warm-up, fills, and folds.
- **SC-002**: Repeated experiments reproduce trades and metrics within tolerance.
- **SC-003**: Every stitched-forward date belongs to exactly one forward fold and
  no fold's test dates enter its training selection data.
- **SC-004**: Orders, trades, positions, cash, equity, yearly returns, and aggregate
  metrics reconcile for every published result.
- **SC-005**: Accepted candidates meet frequency, concentration, cost, anomaly, and
  drawdown constraints.
- **SC-006**: The balanced dual-ST definition can be replayed; any difference from
  prototype metrics is explained by versioned inputs.
- **SC-007**: The contaminated 52W benchmark is rejected by an automated anomaly or
  identity gate on a representative fixture.
- **SC-008**: A second-index fixture completes the same process without changes to
  core strategy/simulator code.
- **SC-009**: Daily scanning reproduces the frozen strategy and has no order side
  effect.
- **SC-010**: The report states whether stitched-forward arithmetic average yearly
  return reaches 60%, alongside CAGR and risk, without undeclared retuning.

## Explicitly Out of Scope

- A promise of 60% or 100% annual returns.
- Repeatedly tuning on forward/live periods until a target appears.
- Live brokerage execution, exact personal taxes, or automatic anomaly repair.
- Short strategies before dedicated borrow, recall, squeeze, and exposure controls.
