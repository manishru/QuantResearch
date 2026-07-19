# Weekly breakout and Supertrend research backtest

`scripts/backtest_weekly_breakout_supertrend.py` tests a point-in-time S&P 500
long-only research rule.  It is not investment advice or order execution.

## Rule

1. At a completed weekly close, a stock qualifies when its close is above the
   high of the preceding `N` completed weeks (`--breakout-weeks`).
2. The completed weekly Supertrend must be green.  The script uses the normal
   Wilder ATR Supertrend calculation; use `--supertrend-period 10` and
   `--supertrend-multiplier 3` for Supertrend (10,3).
3. Entry is the first market session of the following week at its adjusted
   open. Monday holidays therefore use Tuesday's open. A new fixed-dollar lot
   can be added to the same ticker in later qualifying weeks.
4. When a completed weekly Supertrend is red, all open lots in that ticker
   exit at the following week's first available market open.

The default `--max-open-lots-per-ticker 52` permits one weekly lot for up to a
year. It may be reduced for a concentration limit.

`--top-n 3` selects only the three strongest qualifying breakouts across the
whole point-in-time S&P 500 on each entry date. Strength is the completed
weekly close divided by the prior breakout high, minus one.

## Run 2010 through 2025

```zsh
cd ~/QuantResearch

PYTHONPATH=src .venv/bin/python scripts/backtest_weekly_breakout_supertrend.py \
  --start 2010-01-01 \
  --end 2025-12-31 \
  --breakout-weeks 13 \
  --supertrend-period 10 \
  --supertrend-multiplier 3 \
  --top-n 3 \
  --allocation 1000 \
  --max-open-lots-per-ticker 52 \
  --output reports/weekly_breakout_13w_supertrend_10_3_2010_2025
```

## Compare breakout lookbacks

```zsh
PYTHONPATH=src .venv/bin/python scripts/backtest_weekly_breakout_supertrend.py \
  --start 2010-01-01 --end 2025-12-31 \
  --breakout-weeks 8 --breakout-weeks 10 --breakout-weeks 13 \
  --breakout-weeks 20 --breakout-weeks 26 \
  --supertrend-period 10 --supertrend-multiplier 3 \
  --top-n 3 \
  --allocation 1000 --max-open-lots-per-ticker 52 \
  --output reports/weekly_breakout_lookback_matrix_2010_2025
```

`comparison.csv` ranks configurations by XIRR. Each matching detailed file is
under `trades/`, with signal, entry, exit, adjusted price, return, and exit
reason for every lot.

## Current rotation research screen

After the ETF breadth study has been refreshed through the most recent
completed market session, create a read-only constituent ranking with:

```zsh
PYTHONPATH=src .venv/bin/python scripts/screen_latest_etf_rotation_constituents.py \
  --as-of 2026-07-17 \
  --regimes reports/all_major_indexes_momentum_2010_2026/daily_breadth_regimes.csv \
  --top 3 \
  --min-relative-volume 1.0 \
  --output reports/live_rotation_screen_2026-07-17
```

This requires a basket whose regime *started* on the completed session. It
then ranks current point-in-time S&P 500 constituents by 20-day/50-day trend
spread, requiring relative volume at least one. It does not place orders and
is research output only.

To record a research candidate's actual entry-session raw open and monitor the
tested 10% ETF rotation exit after the market closes, first refresh the local
S&P 500 data for that session, then run:

```zsh
PYTHONPATH=src .venv/bin/python scripts/monitor_rotation_forward_positions.py \
  --candidates reports/live_rotation_screen_2026-07-17/research_candidates.csv \
  --entry-date 2026-07-20 \
  --as-of 2026-07-20 \
  --rotation-drawdown 0.10 \
  --min-relative-volume 1.0 \
  --refresh-etfs \
  --output reports/xlf_rotation_forward_2026-07-20
```

Run it again after each completed session with a new `--as-of` date. It writes
`positions.csv` (latest state) and `monitor_history.csv` (dated snapshots).
