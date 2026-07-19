# QuantResearch Constitution

## Core Principles

### I. Point-in-Time Correctness Is Non-Negotiable

Every backtest MUST use only information available at the simulated decision
time. Index membership MUST be point-in-time, indicators MUST use completed
observations, and security mappings MUST be effective-dated. Current constituents
MUST NOT be substituted for historical constituents.

### II. Security Identity Is Separate From Provider Symbol

An index constituent represents a security identity; a data provider symbol is
only an address used to retrieve observations. Renames, share-class changes,
mergers, acquisitions, spin-offs, and ticker reuse MUST NOT be modeled as simple
symbol replacement unless an effective-dated identity record documents the
relationship. Provider resolution MUST preserve the original constituent symbol,
resolved provider symbol, effective dates, reason, evidence, and review status.

### III. Raw Inputs Are Immutable and Derived Data Is Reproducible

Source component files and provider responses MUST be retained unchanged or
content-addressed. Normalization, adjustment, membership intervals, features, and
backtest universes are derived artifacts and MUST be reproducible from recorded
inputs, configuration, code version, and run metadata. Updates MUST be append-only
or atomic replacements; partial output MUST never masquerade as a completed run.

### IV. Incremental by Default, Full Rebuild by Explicit Choice

Routine runs MUST determine the last complete observation and request only the
missing date range. They MUST be idempotent: rerunning the same as-of date produces
the same logical dataset without duplicate security-date records. Full historical
downloads or rebuilds require an explicit command and MUST NOT happen implicitly.

### V. Tests and Validation Define Completion

Every feature MUST have acceptance criteria and automated tests before it is
considered complete. Data pipelines MUST validate schema, uniqueness, ordering,
date coverage, OHLC relationships with numerical tolerance, adjustment formulas,
membership continuity, and reconciliation counts. A run with critical validation
failures MUST return a non-zero status and MUST NOT publish validated outputs.

### VI. Provider and Index Agnosticism

Core models MUST use generic identifiers such as `index_id`, `security_id`,
`provider_id`, and `exchange_code`. S&P 500 and EODHD are the first adapters, not
hard-coded domain assumptions. Adding KOSPI 200 or another index/provider SHOULD
require configuration and adapter modules, not changes to portfolio or feature
logic.

### VII. Secrets and External Effects Are Explicit

API credentials MUST come from environment variables or an approved secret store
and MUST never appear in source, logs, reports, URLs, tests, or specifications.
Network calls, output publication, and destructive operations MUST be explicit,
observable, retry-safe, and bounded.

## Quality Gates

Each feature follows: specification -> clarification -> plan -> tasks -> tests ->
implementation -> validation. Specifications state WHAT and WHY; plans state HOW.
Implementation MUST trace to numbered functional requirements and acceptance
scenarios. Performance optimizations MUST preserve reference results on a fixed
test fixture.

## Governance

This constitution governs all QuantResearch specifications and implementation.
Amendments require a documented rationale, impact analysis, and version update.
When code and specification disagree, the discrepancy MUST be resolved explicitly;
neither artifact may be silently treated as correct. Financial performance targets
MUST NOT override data integrity, point-in-time correctness, or validation gates.

**Version**: 1.0.0  
**Ratified**: 2026-07-13  
**Last Amended**: 2026-07-13

