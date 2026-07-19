# Source Inspection Notes

## S&P 500 components input

Read-only inspection on 2026-07-13 found:

| Property | Observed value |
|---|---:|
| File schema | `date,tickers` |
| Snapshot rows | 2,712 |
| Unique dates | 2,712 |
| First snapshot | 1996-01-02 |
| Last snapshot | 2026-06-02 |
| Minimum unique symbols in a row | 487 |
| Maximum unique symbols in a row | 507 |
| Consecutive snapshots identical to prior row | 2,024 |
| Out-of-order or repeated dates | 0 |

Each row contains a complete comma-separated membership list. The canonical model
should therefore collapse identical consecutive snapshots and derive membership
intervals from actual set changes. It should not materialize one CSV for every
calendar date unless a compatibility export is requested.

The latest inspected source row is 2026-06-02. This differs from the informal
statement that the last change was 2026-07-02, so the implementation must report
the actual source snapshot date and carry it forward explicitly rather than imply
that later membership was independently verified.

## Existing ticker union

`sp500_full.csv` currently contains 1,202 data lines. This union is appropriate for
planning historical data acquisition, but it is not a point-in-time backtest
universe.

## Mapping risk

The supplied manual map mixes several concepts:

- formatting/share-class aliases;
- corporate renames;
- mergers or successor securities;
- foreign/ADR substitutions;
- mappings that may join unrelated security histories.

It must be converted into typed, effective-dated records and reviewed. Until then,
identity-changing mappings are quarantined and cannot be used automatically.

