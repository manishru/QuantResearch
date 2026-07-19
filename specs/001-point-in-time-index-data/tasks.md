# Tasks: Point-in-Time Index Universe and Incremental EOD Data

## Slice A - Point-in-Time Membership

- [x] T001 Write specification, checklist, and source inspection notes.
- [x] T002 Write technical plan and constitution check.
- [x] T003 [TEST] Add fixtures and tests for snapshot parsing/normalization (FR-001–FR-003).
- [x] T004 [TEST] Add tests for ordering and duplicate-date conflicts (FR-005).
- [x] T005 [TEST] Add interval and re-entry boundary tests (FR-004, FR-006, FR-007).
- [x] T006 [TEST] Add acquisition-union and point-in-time separation tests (FR-008, FR-023).
- [x] T007 Implement generic membership domain models and history query.
- [x] T008 Implement generic `date,tickers` CSV adapter with SHA-256 provenance.
- [x] T009 Add `universe inspect` CLI with text/JSON output (FR-025).
- [ ] T010 Add optional daily compatibility export contract (FR-027).
- [x] T011 Run tests, compilation, secret scan, actual-source read-only validation,
      and `git diff --check`.

## Slice B - Provider Mapping Registry

- [x] T012 Specify mapping types and approval workflow (FR-009–FR-012).
- [x] T013 [TEST] Add mapping interval, overlap, approval, and quarantine tests.
- [x] T014 Implement mapping registry and migration report for legacy map.

## Slice C - Incremental Update Planning

- [x] T015 [TEST] Add missing-range and idempotency tests (FR-014, FR-015, FR-018).
- [x] T016 Implement provider-neutral update planner and explicit refresh modes.

## Slice D - EODHD Adapter and Normalization

- [ ] T017 [TEST] Add HTTP fixture, retry, redaction, and credential tests.
- [ ] T018 Implement EODHD adapter (FR-013, FR-016).
- [ ] T019 [TEST] Add adjustment, volume, rejection, and tolerance tests.
- [ ] T020 Implement raw/adjusted observation normalization (FR-019–FR-022).

## Slice E - Persistence and Publication

- [ ] T021 Design DuckDB/Parquet schemas and migration versioning.
- [ ] T022 [TEST] Add staging failure, atomicity, and recovery tests.
- [ ] T023 Implement atomic publication and run manifests (FR-017, FR-024).
- [ ] T024 Reconcile against existing S&P 500 outputs without modifying them.
- [x] T024A Copy operator-authorized S&P source artifacts into immutable project raw
      storage, verify hashes, and publish a structural-versus-identity readiness audit.
- [x] T024B-A Classify the provider resolution report, automatically approve only
      punctuation-equivalent aliases, quarantine identity-sensitive substitutions,
      and publish 8-year/2-year fold coverage.
- [x] T024B-B Supply evidence and effective dates for 55 quarantined mappings and
      resolve or explicitly exclude 36 unresolved constituents before publishing a
      backtest-ready dataset.
- [x] T024B-B1 Implement the effective-dated exclusion proposal/review model and
      generate a complete pending review queue without weakening gross coverage.
- [x] T024B-B2 Human-review the pending mapping and exclusion queues, attach evidence,
      then rerun publication readiness.
- [x] T024B-B1a Add a versioned mapping/exclusion decision importer and validation CLI.
- [ ] T025 Add second-index fixture proving adapter neutrality (FR-026, SC-008).
