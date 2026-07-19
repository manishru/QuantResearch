# Implementation Plan: Point-in-Time Index Universe and Incremental EOD Data

## Summary

Build a provider- and index-neutral data pipeline in independently testable slices.
The canonical universe representation is effective-dated membership intervals plus
immutable snapshot provenance. EOD data is updated through per-symbol missing-range
plans, staged, validated, and atomically published. Existing scripts remain outside
the package and existing user data is read-only during migration.

## Technical Context

- **Language**: Python 3.14 (project minimum remains Python 3.12)
- **Core package**: `src/quantresearch`
- **Initial persistence**: deterministic library models and JSON/CSV diagnostics;
  DuckDB/Parquet persistence follows after domain semantics are verified
- **Testing**: standard-library `unittest`; optional `pytest` runner
- **CLI**: `argparse`, text and JSON output
- **Data dependencies**: Polars, PyArrow, and DuckDB isolated behind adapters
- **Network**: provider clients isolated behind protocols and fixture-testable

## Constitution Check

| Principle | Design response |
|---|---|
| Point-in-time correctness | Query latest snapshot at or before as-of date; intervals are inclusive and non-overlapping |
| Identity separation | Membership symbols remain distinct from provider mappings |
| Immutable/reproducible | SHA-256 source provenance and deterministic derived intervals |
| Incremental default | Missing-range planner; full refresh requires explicit mode |
| Validation gates | Typed findings and non-zero CLI results for critical failures |
| Generic design | `index_id`, adapters, no S&P/EODHD literals in domain modules |
| Secret safety | Environment-only provider credentials and redacted request logging |

No constitution violation is required.

## Architecture

```text
component source adapter
        ↓
validated snapshots + provenance
        ↓
membership history ──→ point-in-time query
        ↓
membership intervals ──→ acquisition union
        ↓
provider mapping registry
        ↓
incremental update planner
        ↓
provider adapter → staging → normalization → validation → atomic publication
```

## Source Layout

```text
src/quantresearch/
├── domain/
│   ├── membership.py
│   ├── mappings.py
│   └── observations.py
├── ingestion/
│   └── component_csv.py
├── providers/
│   ├── base.py
│   └── eodhd.py
├── updates/
│   ├── planner.py
│   └── publisher.py
└── validation/
    └── observations.py
```

## Delivery Slices

### Slice A - Point-in-Time Membership

Implement generic snapshot models, CSV ingestion, provenance hashing, validation,
interval derivation, acquisition union, as-of queries, and CLI inspection. This is
the current implementation slice and covers FR-001–FR-008, FR-023, FR-025–FR-027.

### Slice B - Provider Mapping Registry

Implement typed/effective-dated mappings, approval states, overlap validation, and
quarantine. Import the existing manual map only as unverified migration input.

### Slice C - Incremental Update Planning

Implement provider-neutral missing-range plans from mapping intervals, stored
max-dates, requested as-of date, and explicit full-refresh policy.

### Slice D - EODHD Adapter and Normalization

Implement bounded network behavior, credential gate, redaction, raw response
staging, adjusted OHLC policy, unchanged volume, and reason-coded rejection.

### Slice E - Atomic Persistence and Reconciliation

Implement DuckDB metadata, partitioned Parquet publication, manifests, validation
reports, recovery, and compatibility exports.

## Data Model Decisions

- Snapshot dates are effective dates and membership applies from that date until
  the next supplied snapshot date minus one calendar day.
- A membership interval is per `(index_id, constituent_symbol)` and may recur after
  re-entry.
- Snapshot rows are retained for provenance; identical consecutive memberships are
  compacted only in derived intervals.
- `effective_to = null` means membership remains open under the last-known snapshot.
- Security identity is not inferred in Slice A; constituent symbol is an input key,
  not proof of stable corporate identity.
- Daily universe CSVs are compatibility exports, never canonical storage.

## Validation Strategy

- Fixture-level boundary tests for additions, removals, re-entry, carry-forward,
  normalization, union, hashing, ordering, duplicate/conflicting dates, and indexes.
- CLI JSON tests for machine-readable output and exit status.
- Full-suite regression plus compile and whitespace checks.
- Later slices add provider fixtures; no live-network test is required for unit CI.

## Performance Strategy

Correctness uses a compact reference implementation first. Snapshot membership is
stored as immutable sets; as-of lookup uses binary search. Interval derivation is
linear in total membership changes. Large-file adapters may later use Polars, but
must match reference fixture results exactly.

## Migration

1. Do not modify existing CSV/Parquet data.
2. Compare new membership queries with selected existing daily universe files.
3. Import mappings as unverified typed records; approve only reviewed entries.
4. Run incremental pipeline into a new versioned destination.
5. Switch backtests only after reconciliation and validation pass.

