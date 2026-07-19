# Implementation Plan: Latest Point-in-Time Momentum Recommendations

1. Add pure rule evaluation and deterministic candidate ranking with unit tests.
2. Add a read-only CLI that calculates completed-session features in DuckDB and
   applies current S&P 500 membership, mapping, exclusions, and exceptions.
3. Persist a CSV and JSON recommendation evidence bundle and run it against the
   July 14 validated artifact.

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_momentum_recommendations -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
git diff --check
```
