# Feature Specification: Point-in-Time Index Universe and Incremental EOD Data

**Feature Branch**: `001-point-in-time-index-data`  
**Created**: 2026-07-13  
**Status**: In Progress  
**Input**: Historical index component snapshots, optional later component file,
provider symbol mappings, and previously stored EOD observations. The inspected
S&P 500 source currently contains 2,712 unique, chronologically ordered snapshot
dates from 1996-01-02 through 2026-06-02.

## Problem Statement

Backtests must select only securities that belonged to the tested index on each
historical date. A union of every historical constituent is useful for acquiring
data, but using that union as the daily tradable universe creates membership and
survivorship bias. The platform also needs repeatable incremental updates: after an
initial history load, later runs should retrieve only missing EOD observations and
extend index membership from the last known constituent snapshot when no newer
component file is supplied.

The first implementation targets the S&P 500 with EODHD data. The domain model
must support other indexes and providers, including KOSPI 200, without redesigning
the research or backtest layers.

## User Scenarios and Testing

### User Story 1 - Build Point-in-Time Membership (Priority: P1)

As a researcher, I want historical component snapshots converted into effective
membership intervals so a backtest can obtain the exact eligible universe for any
date without creating thousands of redundant daily CSV files.

**Independent Test**: Given three component snapshots with additions and removals,
query dates before, on, and after each change and reconcile the returned membership
with the source snapshot effective on that date.

**Acceptance Scenarios**:

1. **Given** snapshots dated January 1 and February 1, **when** January 20 is
   queried, **then** the January 1 membership is returned.
2. **Given** a security removed in the February 1 snapshot, **when** February 1 is
   queried, **then** that security is absent and its prior membership interval ends
   on January 31.
3. **Given** no snapshot after July 2, **when** July 13 is queried, **then** the July
   2 membership is carried forward and the result records that it is based on the
   last-known snapshot.

### User Story 2 - Resolve Symbols Without Changing Identity (Priority: P1)

As a data engineer, I want constituent identities mapped to provider symbols with
effective dates and audit evidence so data retrieval does not merge unrelated
companies merely because tickers look similar or were reused.

**Independent Test**: Resolve fixtures containing an unchanged ticker, a verified
rename, a share-class formatting change, a reused ticker, and an unverified manual
mapping; only approved effective-dated mappings may be downloaded automatically.

**Acceptance Scenarios**:

1. **Given** an unchanged symbol supported by the provider, **when** it is resolved,
   **then** the constituent and provider symbols match and identity is preserved.
2. **Given** a verified rename with an effective date, **when** observations are
   requested across that date, **then** the correct provider symbol is used for
   each interval while a single documented security lineage is retained.
3. **Given** an unverified mapping such as an apparent successor or unrelated
   modern ticker, **when** resolution runs, **then** it is quarantined for review
   rather than silently substituted.

### User Story 3 - Perform Idempotent Incremental EOD Updates (Priority: P1)

As an operator, I want a routine update to request only missing trading dates for
each resolved provider symbol so weekly or daily refreshes are fast, restartable,
and do not duplicate or rewrite validated history unnecessarily.

**Independent Test**: Seed local storage through date D, provide provider fixtures
through D+5, run twice, and verify that the first run appends only D+1 through D+5
and the second run makes no logical data changes.

**Acceptance Scenarios**:

1. **Given** a ticker stored through July 10, **when** an update runs as of July 17,
   **then** the provider request begins July 11 and only returned trading sessions
   are appended.
2. **Given** a newly added constituent with no stored observations, **when** the
   update runs, **then** history is requested from the configured index-research
   start date or the security's first eligible date according to run policy.
3. **Given** a failed request midway through a run, **when** the run stops, **then**
   no incomplete dataset is published and a later run can resume safely.
4. **Given** the same provider response and as-of date, **when** the update is run
   twice, **then** `(provider_symbol, date)` remains unique and results reconcile.

### User Story 4 - Produce Adjusted and Raw Audit Data (Priority: P1)

As a researcher, I want raw provider OHLC, provider adjusted close, unchanged
provider volume, and derived adjusted OHLC retained together so all calculations
can be audited and alternative adjustment policies can be evaluated later.

**Independent Test**: For a fixed provider response, verify every adjusted row from
the documented daily factor and verify that volume is byte-for-byte numerically
unchanged.

**Acceptance Scenarios**:

1. **Given** positive raw close and adjusted close, **when** normalization runs,
   **then** the daily factor equals `adjusted_close / raw_close`.
2. **Given** a valid factor, **when** adjusted OHLC is produced, **then** open, high,
   and low equal raw values multiplied by the factor and close equals adjusted
   close within the declared tolerance.
3. **Given** provider volume, **when** normalization runs, **then** volume is not
   multiplied by the adjustment factor.

### User Story 5 - Add Another Index or Provider (Priority: P2)

As a researcher, I want to configure another index such as KOSPI 200 and attach a
provider adapter without changing membership, feature, or backtest semantics.

**Independent Test**: Load a small second-index fixture with different exchange and
symbol conventions and query its membership independently of the S&P 500.

## Functional Requirements

- **FR-001**: The system MUST ingest component snapshots containing an effective
  date and a collection of constituent symbols.
- **FR-002**: The system MUST normalize whitespace, case, quoting, and configured
  share-class punctuation without assuming that similar symbols share identity.
- **FR-003**: The system MUST preserve each source snapshot and its provenance,
  including source path, content hash, ingestion time, index identifier, and row
  validation results.
- **FR-004**: The system MUST derive non-overlapping membership intervals with
  inclusive `effective_from` and nullable/inclusive `effective_to` dates.
- **FR-005**: The system MUST detect additions, removals, duplicate snapshots,
  conflicting same-date snapshots, gaps, and out-of-order source dates.
- **FR-006**: The system MUST query membership by `index_id` and as-of date.
- **FR-007**: When no newer source snapshot is supplied, the system MUST carry the
  last known membership forward and label the result with its source snapshot date.
- **FR-008**: The system MUST create the acquisition union from membership history,
  while keeping this union separate from the point-in-time backtest universe.
- **FR-009**: Security identity, constituent symbol, exchange, provider, and provider
  symbol MUST be stored as distinct fields.
- **FR-010**: Provider symbol mappings MUST support effective dates, mapping type,
  reason, evidence reference, approval status, and reviewer metadata.
- **FR-011**: Unapproved identity-changing mappings MUST NOT be used for automated
  downloads or backtests.
- **FR-012**: Provider-specific fallback formats (for example share-class punctuation
  or a delisted suffix) MUST live in provider adapters, not generic domain logic.
- **FR-013**: Credentials MUST be read from `EODHD_API_KEY` or an approved secret
  source; the application MUST fail safely when unavailable.
- **FR-014**: The update planner MUST calculate a per-symbol missing date range from
  local storage and the requested as-of date.
- **FR-015**: Routine updates MUST request only missing ranges; a full refresh MUST
  require an explicit operator option.
- **FR-016**: Provider calls MUST use bounded retries, exponential backoff, timeout,
  rate limiting, and redacted logging.
- **FR-017**: Raw responses or normalized raw observations MUST be staged before
  publication, and publication MUST be atomic at the dataset/run level.
- **FR-018**: EOD records MUST be unique by provider/security identity and date;
  reruns MUST be idempotent.
- **FR-019**: The normalized audit schema MUST preserve raw OHLC, adjusted close,
  provider volume, adjustment factor, adjusted OHLC, source provider, resolved
  symbol, retrieval time, and run identifier.
- **FR-020**: The default EODHD adjustment policy MUST calculate daily factor as
  adjusted close divided by positive raw close, adjust OHLC, and leave provider
  volume unchanged.
- **FR-021**: Invalid dates, nonpositive required prices, missing adjustment inputs,
  duplicate rows, and non-finite factors MUST be rejected or quarantined with
  machine-readable reason codes.
- **FR-022**: OHLC validation MUST use documented numerical tolerances so floating
  point noise is not reported as a market-data defect.
- **FR-023**: A backtest universe join MUST select membership using the simulated
  date and MUST never use the full acquisition union as eligibility.
- **FR-024**: Pipeline outputs MUST include run manifests and reconciliation reports
  covering inputs, expected symbols, resolved symbols, unresolved symbols, rows
  inserted, rows unchanged, rejected rows, min/max dates, and validation status.
- **FR-025**: The system MUST expose library APIs and CLI commands with optional JSON
  output for ingestion, planning, updating, validating, and membership queries.
- **FR-026**: The domain layer MUST not contain literals specific to S&P 500, EODHD,
  U.S. exchanges, KOSPI 200, or Korean exchanges; those belong in configuration or
  adapters.
- **FR-027**: Daily per-date universe CSV export MAY be offered for compatibility,
  but interval storage is canonical and daily-file generation MUST be optional.
- **FR-028**: Resolution reports MUST classify direct, unresolved, superficial
  formatting, provider fallback, and identity-sensitive substitutions separately.
  Only punctuation-equivalent symbols with identical alphanumeric content MAY be
  system-approved as formatting aliases. `_OLD`, rename, merger, acquisition, and
  successor substitutions require effective dates and external evidence and remain
  quarantined until reviewed. Coverage MUST be reported for each 8-year training
  and 2-year forward segment using only direct or approved provider addresses.
- **FR-029**: A constituent without approved data MAY be proposed for exclusion only
  through an effective-dated record containing a reason category, written rationale,
  reviewer, review timestamp, and approval status. Pending exclusions MUST remain in
  the gross coverage denominator and MUST NOT make a dataset publishable. Approved
  exclusions MUST be reported separately from covered constituents; both gross
  coverage and eligible-after-exclusion coverage MUST remain visible so exclusions
  cannot silently inflate data quality.
- **FR-030**: Mapping and exclusion review decisions MUST be imported from immutable
  CSV artifacts, validated as typed effective-dated records, and assigned a SHA-256
  content version. Conflicting intervals, invalid enum values, missing approval
  evidence, or missing reviewer metadata MUST fail validation. The CLI MUST report
  approved, pending, and rejected counts and MUST return a non-zero status when any
  pending decision remains.
- **FR-031**: When the operator explicitly chooses to ignore constituents with
  unresolved identity or unusable provider history, the system MUST reject their
  proposed replacement mappings and approve exclusions only for the source
  membership intervals. Derived point-in-time universes MUST remove those symbols
  on applicable dates, retain a content-addressed link to the decision artifact,
  and report gross coverage, excluded counts, and eligible coverage separately.

## Key Entities

- **IndexDefinition**: Stable index identifier, display name, market, timezone,
  calendar, currency, and constituent-source adapter.
- **SourceSnapshot**: Immutable description of one supplied component snapshot.
- **Security**: Stable identity independent of ticker and provider.
- **SecuritySymbol**: Effective-dated symbol and exchange used by an index source.
- **IndexMembership**: Security membership interval for an index.
- **ProviderSymbolMapping**: Effective-dated provider address with approval evidence.
- **EODObservationRaw**: Provider-delivered daily values and retrieval lineage.
- **EODObservationAdjusted**: Deterministically derived analytical values.
- **UpdateRun**: Requested as-of date, configuration, code version, state, counts,
  failures, and publication result.
- **ValidationFinding**: Severity, reason code, entity keys, evidence, and disposition.

## Edge Cases

- Multiple constituent snapshots have the same effective date but different lists.
- A snapshot date falls on a weekend or market holiday.
- An index symbol is reused later by a different security.
- A company changes ticker without leaving the index.
- A merger converts holdings into a successor at a non-1:1 ratio.
- A spin-off produces a new security with discontinuous adjustment history.
- Different share classes are independently eligible.
- A provider returns data beyond the requested as-of date.
- A provider revises an already stored historical observation.
- A newly added constituent lacks provider history or starts trading after addition.
- The component source is stale but the operator requests a later as-of date.
- Network failure occurs after some symbols are staged.
- The latest date is a weekend, holiday, or incomplete current session.

## Assumptions

- The supplied historical component file represents complete constituent snapshots,
  not only change events. Inspection found a `date,tickers` schema with 487–507
  unique symbols per row; 2,024 consecutive supplied rows repeat the prior list and
  can be compacted into intervals without losing information.
- Snapshot dates are effective dates unless source documentation says otherwise.
- Carry-forward membership is permitted when no newer file is provided, but the
  output remains traceable to the last-known snapshot date.
- Provider adjusted close may reflect both splits and dividends; the adjustment
  policy is therefore labeled accordingly and is not described as split-only.
- Market-calendar integration is required before treating missing weekdays as data
  gaps.

## Success Criteria

- **SC-001**: A fixture covering at least three membership changes returns exactly
  the expected universe for every tested boundary date.
- **SC-002**: No backtest eligibility row exists outside its membership interval.
- **SC-003**: Repeating an incremental update produces zero new logical rows and zero
  duplicates.
- **SC-004**: A routine update with existing history requests no date earlier than
  the day after the last complete stored observation for that mapping interval.
- **SC-005**: 100% of published adjusted observations satisfy the adjustment formula
  and tolerance-based OHLC validation.
- **SC-006**: 100% of published observations retain run and provider lineage.
- **SC-007**: Unapproved mappings contribute zero automatically published rows.
- **SC-008**: A second-index fixture runs through the same domain services without
  modifying their source code.
- **SC-009**: Critical validation failure leaves the previously published dataset
  unchanged and returns a non-zero CLI status.
- **SC-010**: The reconciliation report accounts for every expected constituent as
  resolved, unresolved, quarantined, or not-yet-traded.

## Explicitly Out of Scope

- Trading strategies, indicators, optimization, and portfolio simulation.
- Automatic inference that two companies are the same security.
- Live intraday streaming or order execution.
- Exact tax calculation.
- Guaranteed recovery of histories unavailable from the configured provider.
