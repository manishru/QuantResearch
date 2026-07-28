# Golden research baseline: 5M>3M sector cooldown

This directory is the immutable reference copy of the original comparison run
that selected the four-open-lot sector-exit threshold. It is retained so later
mapping, ETF-data, or execution changes can be compared against the exact
historical output.

## Selected configuration

- Period: 2016-01-01 through 2026-07-27
- Universe: point-in-time S&P 500 membership
- Rule: `5M>3M>0`
- Entry day: 26th calendar day, next eligible market session
- Candidate selection: ranks 1 through 10, first candidate not in cooldown
- Stock stop: 40%
- Maximum holding period: 52 weeks
- Monthly contribution: $1,000
- ETF risk-off: ETF underperforms SPY over 21 sessions, relative volume at
  least 1.25x, and drawdown at least 10%
- ETF exit activation: at least four concurrent open lots mapped to the ETF
- Post-exit cooldown: six calendar months

## Result selected from `comparison.csv`

| Metric | Value |
| --- | ---: |
| Open-lot threshold | 4 |
| Trade count | 126 |
| Contributions | $126,000.00 |
| Net proceeds | $211,737.60 |
| Net profit | $85,737.60 |
| ROI | 68.05% |
| XIRR | 71.23% |
| Early ETF exits | 48 |

`min_open_lots_4/` contains the selected trade ledger and monthly decisions.
The adjacent directories retain the thresholds 1, 2, 3, and 5 used in the
original comparison. This is a research baseline, not investment advice or a
guarantee of future performance.
