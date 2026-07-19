# Feature Specification: Layered Research Platform and Web Workbench

**Feature Branch**: `003-research-platform-web`  
**Created**: 2026-07-13  
**Status**: Planned  
**Depends On**: `001-point-in-time-index-data`, `002-adaptive-strategy-research`

## Problem Statement

QuantResearch must grow from a research engine into a professional, multi-index
platform without coupling provider downloads, indicator formulas, strategy logic,
or visualization. A researcher must be able to define and version a strategy, run
it against a point-in-time index universe, retain every result, inspect portfolio
and trade evidence, modify the definition, and launch a distinct reproducible run.

The first deployment targets S&P 500/EODHD data, but NIFTY 500, KOSPI 200, other
indexes, and other providers must enter through adapters and configuration. The
web interface is a client of the same application services and must never contain
backtest calculations or mutate published runs.

## Architectural Decision

Build a modular monolith before considering distributed services. Modules have
explicit contracts and may later be deployed separately, but the initial system
uses one Python package, DuckDB/Parquet artifacts, background workers, and an HTTP
API. This reduces operational complexity while preserving clean boundaries.

1. **Storage layer**: immutable raw observations; normalized security, index,
   membership, market data, features, strategies, runs, trades, equity, metrics,
   and chart annotations.
2. **Acquisition layer**: provider and index adapters, effective-dated security
   mapping, incremental fetch planning, validation, and atomic publication.
3. **Feature layer**: generic point-in-time transforms such as moving averages,
   volatility, trend, momentum, volume, and relative strength.
4. **Research layer**: declarative strategies, simulation, bounded search,
   walk-forward selection, result persistence, and read-only scanning.
5. **Application/API layer**: commands and HTTP endpoints that orchestrate jobs,
   validate definitions, expose immutable results, and stream job state.
6. **Web layer**: strategy editor, run comparison, portfolio analytics, trade
   ledger, and expandable OHLCV trade review with entry/exit markers.

Dependencies flow downward through interfaces. Provider, database, API, and UI
code cannot be imported by core feature or simulation domain modules.

## User Stories and Acceptance Scenarios

### User Story 1 - Research Across Indexes (P1)

1. An S&P 500 run uses only members effective on each simulated date.
2. A NIFTY 500 or KOSPI 200 fixture runs through the same feature, strategy, and
   simulation code with only adapters/configuration changed.
3. Market data is keyed by security identity/provider/version, not a global ticker.

### User Story 2 - Version and Rerun a Strategy (P1)

1. A submitted strategy definition is validated, canonicalized, and immutable.
2. Changing one parameter creates a new strategy version and run; it never edits
   prior definitions, trades, folds, or results.
3. A run records data, membership, mapping, feature, cost, code, and seed lineage.

### User Story 3 - Inspect Performance (P2)

1. A researcher can view CAGR, yearly returns, drawdown, risk, exposure, turnover,
   concentration, costs, fold results, and stitched-forward results.
2. Portfolio equity/drawdown and a filterable trade ledger reconcile to persisted
   run data.
3. In-sample, internal-validation, forward, stitched-forward, and live/unobserved
   results are visually and semantically distinct.

### User Story 4 - Review Every Trade on a Chart (P2)

1. Selecting a trade loads OHLCV bars covering configurable pre/post context,
   entry/exit markers, stops/triggers, membership state, and reason codes.
2. The chart can expand to a focused view and move to previous/next trade without
   recomputing the backtest.
3. Chart prices, timestamps, and markers reconcile exactly with persisted bars and
   fills, and missing/quarantined observations are disclosed.

### User Story 5 - Operate Through a Web Server (P2)

1. HTTP endpoints expose index catalogs, strategy schemas/versions, jobs, runs,
   metrics, folds, trades, equity, and chart data.
2. Long jobs run outside request handlers and expose queued/running/succeeded/
   failed/cancelled state plus logs and progress.
3. Authorization, secrets, rate limits, and deployment configuration remain outside
   strategy definitions and browser code.

## Functional Requirements

- **FR-001**: Enforce dependency boundaries between storage, acquisition, feature,
  research, application/API, and web modules.
- **FR-002**: Use generic `index_id`, `security_id`, `provider_id`, `exchange_code`,
  `strategy_id`, and `run_id`; do not hard-code S&P 500/EODHD in core logic.
- **FR-003**: Support append-only/versioned data and research artifacts with atomic
  publication and reproducible lineage.
- **FR-004**: Persist strategy definitions and complete per-run folds, candidates,
  orders, fills, trades, positions, equity, yearly metrics, aggregate metrics,
  findings, logs, and job state.
- **FR-005**: Strategy definitions must be declarative and validated against a
  versioned schema; arbitrary user Python cannot execute from the web interface.
- **FR-006**: A parameter edit creates a new immutable definition and bounded job.
- **FR-007**: Every run enforces point-in-time index membership at ranking, signal,
  and execution; historical acquisition unions are never daily universes.
- **FR-008**: Provide stable read APIs for portfolio performance, fold comparison,
  trade lists, and paginated OHLCV chart context with annotations.
- **FR-009**: Chart endpoints must read persisted data/results and perform no
  research mutation.
- **FR-010**: Background jobs must be idempotent, observable, bounded, resumable
  where safe, and protected against duplicate publication.
- **FR-011**: Initial web delivery follows the completed strategy/research core;
  visualization requirements shape schemas now but do not block feature work.
- **FR-012**: API contracts must be independently testable and OpenAPI-described.
- **FR-013**: A production deployment must place the API behind authentication and
  TLS and must never expose provider credentials to the browser.

## Success Criteria

- A second-index fixture passes without core strategy/simulator changes.
- A changed parameter creates a different strategy/run ID while the original is
  byte-for-byte retrievable.
- Every UI metric and trade marker reconciles with persisted run records.
- A chart request for one trade returns bounded context without loading the full
  market history.
- API and worker restarts cannot publish duplicate completed runs.

## Explicitly Out of Scope for the Initial Web Slice

- Brokerage order placement, collaborative multi-user editing, arbitrary code
  execution, tick-level replay, or a custom charting engine.
- Microservice deployment before profiling shows a concrete scaling requirement.
- Choosing or finalizing a strategy based on visual inspection of forward data.
