# Implementation Plan: Layered Research Platform and Web Workbench

## Delivery Order

The strategy/research core is completed before the web interface. Data contracts
needed by visualization are designed early so results do not require migration or
recomputation merely to display them.

### Stage A - Boundaries and Persistence

- Document module dependency rules and add import-boundary tests.
- Introduce repository/service protocols around DuckDB and artifact storage.
- Expand append-only run persistence for orders, fills, trades, equity, metrics,
  logs, and chart annotations.
- Add index/provider catalogs and effective-dated adapter registries.

### Stage B - Strategy Workbench Core

- Create a versioned declarative strategy schema and validation service.
- Implement immutable strategy cloning/parameter overrides.
- Add background job models, idempotency keys, progress, cancellation boundaries,
  and result publication.
- Complete the feature catalog, simulator, search, walk-forward, reports, and
  read-only scanner from Feature 002.

### Stage C - Application API

- Use FastAPI only at the delivery boundary; domain services remain framework-free.
- Add read endpoints first, then bounded run submission and job status.
- Generate OpenAPI contracts and integration tests against temporary DuckDB data.
- Add pagination, filtering, caching headers, validation errors, and structured logs.

### Stage D - Web Performance Views

- Build overall performance, drawdown, yearly/fold, exposure, turnover, and cost
  views plus run comparison.
- Add a virtualized/filterable trade ledger and result provenance panel.

### Stage E - OHLCV Trade Review

- Add bounded chart-data endpoints and a candlestick/volume component using a
  maintained financial chart library.
- Overlay entry, exit, stop, trigger, membership, anomaly, and reason annotations.
- Add expandable focus mode, previous/next navigation, and exact reconciliation
  tests.

### Stage F - Edit and Rerun

- Generate strategy forms from the versioned schema.
- Preview canonical definition/diff and estimated bounded search cost.
- Submit immutable jobs, track progress, compare the new run with its parent, and
  preserve all earlier evidence.

## Technology Direction

- Python domain/application services; DuckDB plus partitioned Parquet initially.
- FastAPI and a separate background worker after core research stability.
- TypeScript web client with a proven OHLCV library when Stage D begins.
- Local single-user deployment first; authenticated server deployment before any
  external publication.

## Verification

Each stage adds unit, contract, integration, lineage, reconciliation, restart, and
point-in-time tests. Performance tests use generated fixtures and must never weaken
correctness assertions.
