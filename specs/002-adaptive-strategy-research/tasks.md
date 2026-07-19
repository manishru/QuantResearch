# Tasks: Adaptive Point-in-Time Strategy Research

## Specification and Design

- [x] T001 Consolidate prior experiments and failure lessons.
- [x] T002 Define user stories, requirements, and success criteria.
- [x] T003 Resolve canonical 8-year train / 2-year forward / 2-year step schedule.
- [x] T004 Document 60% as aspirational and forward-only.
- [x] T005 Write architecture, persistence, test, and delivery plan.
- [x] T006 Set deployment hard maximum drawdown to 40%.

## Slice A - Experiment Store and Contracts

- [x] T007 [TEST] Add immutable ID, serialization, and lineage tests.
- [x] T008 [TEST] Add DuckDB migration and append-only tests (restart/failure
      injection remains for the next migration revision).
- [x] T009 Define strategy, experiment, and data-lineage models.
- [x] T010 Implement initial DuckDB migrations and append-only repositories.
- [x] T011 Add CLI commands to initialize and inspect the research database.

## Slice B - Reference Simulator

- [x] T012 [TEST] Add eligibility and no-look-ahead fixtures.
- [x] T012A [TEST] Prove a symbol with available data but absent from that date's
      index membership cannot enter, rank, or fill.
- [x] T013 [TEST] Add next-session, gap, removal, and missing-session tests.
- [x] T014 [TEST] Add costs, tax approximation, cash, and reconciliation tests.
- [x] T015 Implement deterministic long-only order, portfolio, and accounting engine.
- [x] T016 Implement reference performance/risk metrics (turnover, exposure, and
      concentration extend after sizing rules are defined).

## Slice C - Features and Baselines

- [x] T017 [TEST] Add hand-calculated weekly OHLCV, return, breakout, ATR, and
      Supertrend fixtures plus a future-mutation no-look-ahead test.
- [x] T018 Implement feature availability/version contracts and initial weekly
      momentum, breakout, ATR, and Supertrend feature set.
- [x] T019 Register buy-and-hold and balanced dual-ST baselines.
- [x] T020 [TEST] Add anomalous corporate-action/identity discontinuity quarantine.
- [x] T020A [TEST] Implement and validate point-in-time daily/weekly momentum for
      1D, 5D, 10D, 20D, 1W, 2W, 3W, 4W, 5W, 6W, 8W, 10W, 1M, 2M, 3M, 6M, 9M,
      and 12M with content-addressed manifests.
- [x] T020B Implement and validate daily/weekly SMA, EMA, WMA, HMA, VWMA,
      normalized close distance, and configurable moving-average slopes.
- [x] T020C Implement and validate prior-window high/low levels, close breakout
      flags, and normalized distances for every weekly window from 5 through 60.
- [x] T020D Implement and validate volume SMA/ratio/RVOL 10/20/50, prior high/low
      volume, spike, dry-up, breakout, contraction, and volume trend.
- [x] T020E Implement and validate OBV, CMF, MFI, and accumulation/distribution.
- [x] T020F Implement and validate true range, ATR, NATR, rolling standard deviation,
      and annualized historical volatility grids.
- [x] T020G Implement and validate the declared Supertrend period/multiplier grid.
- [x] T020SD [TEST] Implement daily three-candle supply/demand detection, ATR/range/
      body/volume/structure measurements, departure-close availability, expiry,
      invalidation, first-future-revisit tracking, and a content-addressed manifest.
- [x] T020SDR Register declarative supply/demand strategy variants only after exact
      entry, exit, ranking, sizing, risk, and fixed-budget search rules are modeled.
- [x] T020SDO-A Add the declared bounded optimization space and conservative
      same-bar bracket-execution tests.
- [ ] T020SDO-B Add robust-neighborhood analysis and parameter heatmaps after
      point-in-time walk-forward evaluation is wired to the registered strategy.
- [x] T020H Implement and validate ADX, DI+, and DI- grids.
- [ ] T020I Implement and validate RSI, MACD families, CCI, Williams %R, and stochastic.
- [ ] T020J Implement and validate relative strength versus configured market and
      sector benchmarks.
- [ ] T020K Implement and validate market/sector regimes, breadth, and volatility
      regime inputs when source data is available.
- [ ] T020L Implement and validate volatility/ATR/risk-parity sizing inputs.
- [ ] T020M Persist partitioned feature artifacts and reconciliation manifests.
- [ ] T020N Run independent reference comparisons and freeze feature versions only;
      do not finalize a trading strategy.

## Slice D - Walk-Forward

- [x] T021 [TEST] Add exact 8/2/2, warm-up, purge, and embargo tests.
- [x] T022 Implement fold generation, immutable freezing, DuckDB persistence, and
      completed versus live/unobserved evaluation states.
- [x] T023 Implement non-overlapping stitched-forward aggregation.
- [x] T023A Replay every registered strategy using membership effective on each
      signal and execution date; never rank the historical acquisition union.
- [x] T023B [TEST] Convert causal demand-zone revisits to immutable entry/stop/
      target trade plans with ATR, retest, entry-type, and ranking lineage.
- [x] T023C [TEST] Add market/limit order semantics and portfolio-integrated bracket
      execution, including stop-first same-day ambiguity and gap-through stops.
- [x] T023D [TEST] Evaluate one registered supply/demand parameter set over an exact
      fold segment with warm-up, point-in-time membership, metrics, and lineage gate.
- [ ] T023E Run bounded training selection, freeze once, replay untouched 2-year
      forward folds, persist every result/trade, and produce stitched-forward reports.
- [x] T023E-A Run and publish the fixed-budget production-data pilot with approved
      point-in-time eligibility and identity-preserving provider aliases.
- [x] T023F Reproduce the weekly top-10 52-week cross-sectional momentum strategy
      over the latest ten years and publish holdings, rebalances, equity, and anomaly
      diagnostics.
- [x] T023G [TEST] Add causal calendar-day scheduling and independent lot exit tests.
- [x] T023H Run the monthly momentum-lot matrix for three rules, top one through five,
      and nominal days 1 through 31 using point-in-time membership.
- [x] T023I Publish an audited Excel comparison, day study, configuration rankings,
      full trades, assumptions, and quality checks.
- [x] T023J Enforce 60-day continuous-membership seasoning and reviewed spin-off
      exceptions in the monthly matrix.
- [x] T023K [TEST] Add hand-calculated tax and next-month reinvestment fixtures.
- [x] T023L Implement a generic tax-aware reinvestment replay over immutable monthly
      lot results, retain scaled trades and a cash ledger, and reconcile ending
      after-tax wealth.
- [x] T023M Compare the declared monthly momentum rule/day/top-N/stop configurations
      under the same 35% research tax approximation and publish an auditable Excel
      report without representing the result as an expected future return.
- [x] T023N [TEST] Replace strict 365-calendar-day maturity with the twelfth
      subsequent scheduled monthly purchase session, sell the mature tranche at
      that session's open, and make its after-tax proceeds available to the same
      session's replacement purchase without a settlement delay.
- [x] T023O [TEST] Add configurable normal-maturity capital smoothing that spreads
      each after-tax maturity across 12 scheduled purchase cycles, retains future
      installments as cash at the reporting boundary, and reconciles every dollar.

## Slice E - Search and Selection

- [x] T024 [TEST] Add fixed-budget and candidate-retention tests.
- [x] T025 Implement deterministic declared grid search (coarse-to-fine remains T027C).
- [x] T026 Implement frequency, 40% drawdown, concentration, anomaly, and
      point-in-time membership-violation gates.
- [x] T027 Implement predeclared multi-objective scoring and deterministic tie-breaks.
- [x] T027A Persist every accepted, rejected, and failed candidate with reason codes.
- [x] T027B Add content-addressed repeated-experiment/search-plan versioning without
      mutating earlier searches.
- [ ] T027C Add coarse-to-fine and optional Bayesian adapters only after deterministic
      grid search matches the reference candidate set.

## Reports and Scanner

- [ ] T028 Generate fold, yearly, stitched-forward, cost, and robustness reports.
- [ ] T029 Add second-index replay proving generic behavior.
- [ ] T030 Implement current-strategy approval and versioning.
- [ ] T031 [TEST] Add scan reproducibility and no-side-effect tests.
- [ ] T032 Implement read-only daily scanner and machine-readable output.
- [ ] T033 Persist chart-ready trade reasons, entry/exit/trigger annotations, and
      bounded bar references as required by Feature 003; do not build the UI here.
