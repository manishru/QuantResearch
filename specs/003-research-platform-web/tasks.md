# Tasks: Layered Research Platform and Web Workbench

## Stage A - Architecture and Data Contracts

- [ ] T001 Add architecture decision records and enforce module import boundaries.
- [ ] T002 Define generic index/provider adapter registries and catalog models.
- [ ] T003 Define repository protocols for observations, features, and research runs.
- [ ] T004 Extend DuckDB migrations for orders, fills, trades, positions, equity,
      metrics, logs, job state, and chart annotations.
- [ ] T005 Add atomic publication, idempotency, restart, and reconciliation tests.
- [ ] T006 Add S&P 500 and second-index fixtures proving adapter neutrality.

## Stage B - Strategy Workbench Core

- [ ] T007 Define a safe versioned declarative strategy JSON schema.
- [ ] T008 Implement immutable clone/override/diff operations and lineage tests.
- [ ] T009 Define bounded job, progress, cancellation, and publication contracts.
- [ ] T010 Complete Feature 002 feature families and freeze feature versions.
- [ ] T011 Complete simulator/search/walk-forward reports and scanner contracts.
- [ ] T012 Persist complete result evidence needed by reports and charts.

## Stage C - HTTP API

- [ ] T013 Add framework-independent query/command application services.
- [ ] T014 Add FastAPI health, catalogs, strategy, run, and job endpoints.
- [ ] T015 Add paginated metrics, folds, equity, and trade endpoints.
- [ ] T016 Add bounded OHLCV trade-context and annotation endpoints.
- [ ] T017 Add OpenAPI, validation, authorization boundary, and integration tests.

## Stage D - Performance Web UI

- [ ] T018 Scaffold the TypeScript web client and generated API client.
- [ ] T019 Build run catalog, lineage, status, and strategy-parameter views.
- [ ] T020 Build equity, drawdown, yearly/fold, risk, cost, and exposure views.
- [ ] T021 Build filterable/virtualized trade ledger and run comparison.

## Stage E - Trade Chart Review

- [ ] T022 Build OHLC candlestick plus volume chart from bounded API data.
- [ ] T023 Overlay entry/exit, stop/trigger, anomaly, and membership annotations.
- [ ] T024 Add expanded focus mode and previous/next trade navigation.
- [ ] T025 Add UI-to-persistence chart reconciliation and accessibility tests.

## Stage F - Edit and Rerun

- [ ] T026 Generate a constrained strategy editor from the strategy schema.
- [ ] T027 Preview canonical parameter diffs and estimated bounded workload.
- [ ] T028 Submit immutable research jobs and display progress/failures.
- [ ] T029 Compare child and parent runs without mutating either result.
- [ ] T030 Add deployment documentation, authentication, TLS, backups, and recovery.
