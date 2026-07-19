# Implementation Plan: Adaptive Point-in-Time Strategy Research

## Summary

Build gated vertical slices: experiment lineage and DuckDB schemas, a deterministic
reference simulator, features and baseline definitions, walk-forward orchestration,
bounded search, reporting, and finally a read-only daily scanner. Optimized engines
must reproduce reference fixtures before replacing them.

## Prerequisite Gate

Feature 001 Slices D/E must publish validated observations, point-in-time
membership, approved mappings, run manifests, and stable dataset identifiers.
Synthetic fixtures may be used earlier, but unvalidated production data MUST NOT
produce published performance claims.

## Architecture

```text
validated observations + point-in-time membership
                    ↓
versioned feature store (Parquet + DuckDB catalog)
                    ↓
strategy catalog → bounded candidate generator
                    ↓
deterministic portfolio simulator
                    ↓
8-year training selection → frozen 2-year forward evaluation
                    ↓
DuckDB experiment store → stitched-forward reports
                    ↓
frozen current strategy → read-only daily scanner
```

## DuckDB Logical Tables

- `data_versions`, `feature_versions`, `strategy_definitions`
- `optimization_runs`, `candidate_results`, `validation_findings`
- `walk_forward_windows`, `selected_strategies`, `forward_results`
- `orders`, `trades`, `positions`, `equity_curve`, `yearly_metrics`
- `current_strategy`, `daily_scan_runs`, `daily_signals`

Large time-series artifacts may remain versioned Parquet referenced by path and
SHA-256. Database rows use immutable experiment/fold IDs.

## Delivery Slices

### Slice A - Experiment Store and Contracts

Define IDs, strategy/config schemas, migrations, append-only repositories, run
manifests, and lineage checks. Covers FR-002, FR-003, FR-011, FR-021, FR-022.

### Slice B - Reference Simulator

Build a deterministic fixture-first engine for signals, next-session fills, gaps,
cash, costs, positions, exits, removals, and reconciliation. It is the oracle for
faster implementations. Covers FR-001, FR-006–FR-010, FR-013.

### Slice C - Feature and Baseline Catalog

Create versioned daily/weekly feature families with availability timestamps and
register buy-and-hold and balanced dual-ST only as controls. Add anomaly gates and
rejected benchmarks. Implement each indicator family independently so calculation
errors or definition changes do not invalidate unrelated features.
Covers FR-004, FR-005, FR-020, FR-023, FR-026.

### Slice D - Walk-Forward Orchestrator

Generate exact 8/2/2 folds, enforce separation, warm-up, nested/purged validation,
freezing, and stitched-forward aggregation. Covers FR-014–FR-018.

T023A adds a provider-neutral point-in-time replay boundary. It filters candidate
scores against effective membership before ranking, converts only eligible winners
to entry signals, builds a per-session membership calendar, and delegates fills to
the reference simulator so execution-date eligibility remains a separate gate.
Training and forward periods are replayed independently.

### Slice E - Bounded Strategy Search

Implement declared grids, then optional coarse-to-fine/Bayesian search. Apply
frequency, drawdown, concentration, and anomaly gates before scoring and persist
all candidates. Covers FR-012, FR-019.

Repeated searches create new immutable experiment IDs. A fixed budget and candidate
ordering are recorded before evaluation. The engine never expands a run merely
because no candidate reaches the aspirational 60% stitched-forward target.

### Slice F - Reporting and Robustness

Generate fold, stitched-forward, yearly, cost, tax, parameter-stability, regime,
and benchmark comparisons. Never hide failed years or folds.

### Slice G - Frozen Daily Scanner

Load the approved strategy, latest complete data, membership, and holdings and emit
auditable entry/exit candidates without brokerage effects. Covers FR-024, FR-025.

## Verification Strategy

- Synthetic calendars/membership changes for zero-look-ahead tests.
- Hand-calculated fixtures for signals, fills, costs, tax, cash, and metrics.
- Fold tests for leap years, incomplete years, warm-up, purge, and embargo.
- Golden replay of balanced dual-ST semantics before headline returns.
- Corrupt corporate-action fixture proving 52W quarantine.
- Determinism, migration, append-only, crash/restart, and duplicate-run tests.
- Second-index fixture validating generic configuration.
- Hand-calculated tax/reinvestment fixtures proving that positive gains are taxed,
  losses receive no credit, proceeds wait until the next scheduled purchase, and
  the complete cash ledger reconciles to ending wealth.

## Implementation Order

1. Complete Feature 001 publication gate or use synthetic fixtures only.
2. Implement Slice A with tests and schema documentation.
3. Implement Slice B reference simulator and reconciliation tests.
4. Implement Slice C features/baselines and validate calculations.
5. Implement Slice D folds before any optimizer.
6. Implement Slice E bounded search and selection gates.
7. Run historical folds once; freeze and publish complete results.
8. Add robustness reports and only then the daily scanner.

No strategy is deployable until SC-001–SC-009 pass and its maximum drawdown is no
greater than 40%. SC-010 reports the 60% outcome honestly; it is not a software
correctness gate and does not permit undeclared retuning.
