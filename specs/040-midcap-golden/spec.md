# Feature Specification: Midcap Golden 10M>6M>3M

**Status**: Complete
**Created**: 2026-08-26

## Objective

Give the reviewed S&P 400 monthly momentum strategy a stable repository name,
machine-readable configuration, reproducible runner, tests, and README usage.

## Functional requirements

- **FR-001**: The strategy identifier is `midcap_golden_10m6m3m`.
- **FR-002**: A stock qualifies only when its completed-close returns satisfy
  `10M > 6M > 3M > 0`, using 210, 126, and 63 trading sessions.
- **FR-003**: Qualifying stocks are ranked descending by 10-month return.
- **FR-004**: The nominal entry day is the 14th of every month; if it is not a
  trading session, entry is the first trading session afterward. Selection
  uses only the immediately preceding completed close.
- **FR-005**: The portfolio starts with $12,000 split across three fixed
  monthly sleeves. Each sleeve reinvests its own proceeds on its fixed cadence.
- **FR-006**: The strategy avoids a ticker already active in another sleeve and
  searches through the first 20 ranked candidates.
- **FR-007**: Each lot holds 12 calendar weeks, subject to a 30% stop confirmed
  by a completed close and executed at the next session open.
- **FR-008**: Entry and exit costs are 0.10% each.
- **FR-009**: Historical eligibility uses the effective-dated S&P 400 proxy
  membership intervals. Documentation must disclose that Wikipedia selected
  changes are approximate, not official complete index history.
- **FR-010**: The runner emits the engine's summary, top-strategy report, and
  full trade ledger under a user-specified output directory.

## Acceptance scenarios

1. The stored configuration validates and exposes the exact reviewed defaults.
2. The rule accepts `10M=40%, 6M=25%, 3M=10%` and rejects equal, ascending, or
   non-positive return sequences.
3. A generated runner command contains the rule, day, hold, stop, costs,
   candidate depth, distinct-active-ticker policy, and fixed-vintage policy.
4. README documentation describes selection, timing, capital, exits,
   limitations, and a runnable command.

## Explicit limitations

- This is retrospective research, not investment advice or a prediction.
- The S&P 400 membership history is an auditable approximation derived from
  Wikipedia selected changes.
- The selected parameters are in-sample and carry multiple-testing risk.
- Adjusted daily bars and modeled next-open fills may differ from executable
  market prices.
