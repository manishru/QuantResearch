Status: complete
Last Updated: 2026-08-02

## Approach

Create a standalone v2 CLI rather than changing the v1 experiment. Reuse the existing pure ETF-leader function, mapping resolvers, daily adapter, and CSV writer. Add a small per-lot sleeve state machine: `reserved → ETF sleeves or cash → mature → funding cash`.

## Tasks

1. Implement per-lot sleeve records and daily leader search until maturity.
2. Liquidate every sleeve at its own scheduled maturity, independent of later cash demand.
3. Emit an auditable sleeve ledger linked to stock lots and run focused timing tests.
4. Add a cash-only per-lot maturity-control mode and compare it with the ETF sleeve mode under identical twelve-month external funding.
5. Add a configurable top-volume-of-price-leaders selection mode, retain daily rechecks on no selection, and compare it with the equal-weight top-three rotation using identical funding.
6. Add a post-process constituent-sleeve comparator that preserves the selected ETF sleeve dates and replaces only auditable N-PORT-covered sleeves with three equal stock positions.
7. Add a cache-only as-of decision report which applies the frozen ETF-leader rule and publishes next-session top-three N-PORT constituent candidates without any API call or future data.
8. Add a daily operational runner that refreshes completed price inputs incrementally, reports N-PORT publication coverage without daily N-PORT backfill, and separates actual rotation exits from 26th-of-month ranked golden candidates.

## Tests

Use `unittest`: daily rechecking chooses a leader after an initial no-leader day; maturity forces an exit; triggering ETF is excluded.
Also verify that the as-of report does not relax the strict selected-volume floor when no current ETF qualifies.
Verify that the operational runner does not create a rotation decision without an actual sector-exit signal and invokes the monthly candidate engine only on or after the nominal day.
