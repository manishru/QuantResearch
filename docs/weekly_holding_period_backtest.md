# Weekly Holding-Period Momentum Matrix

This research command keeps the existing monthly entry convention and tests exits
from one to fifty-two calendar weeks. It uses the point-in-time S&P 500 universe,
approved membership exceptions, reviewed ticker exclusions, and the existing
conservative stop model.

## Bounded smoke run

```bash
cd ~/QuantResearch
PYTHONPATH=src .venv/bin/python scripts/run_weekly_holding_period_matrix.py \
  --weeks-start 1 --weeks-end 2 \
  --rule '5M>2M>0' --stop 0.45 \
  --output reports/weekly_holding_smoke
```

## Full study

```bash
cd ~/QuantResearch
PYTHONPATH=src .venv/bin/python scripts/run_weekly_holding_period_matrix.py \
  --output reports/weekly_holding_period_matrix
```

Use `--resume` only after reviewing incomplete group folders. A group is skipped
only if its fingerprinted `group_result.json` matches its completed summary.

Results are in-sample research, not a live strategy recommendation. Compare any
candidate through the project’s frozen 8-year/2-year walk-forward workflow before
considering it for a daily scan.
