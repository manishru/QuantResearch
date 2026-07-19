# Implementation Plan: Indicator and Market-Structure Catalog

Deliver the catalog in independently testable families. First inventory and
register existing implementations. Then add momentum, trend, volatility, causal
market structure, source-dependent volume profile, and finally the configurable
technical-summary composite. Every slice follows tests-first development and
publishes versioned metadata only after reference and no-look-ahead validation.

Core formulas remain under `quantresearch.features`; registration metadata belongs
in a provider-neutral catalog module. Strategies consume registered columns and
never call external vendor pages. Price-at-volume features remain unavailable
until an appropriate intraday/trade source adapter is specified.

Verification for every slice:

```bash
PYTHONPATH=src python -m unittest tests.test_<family> -v
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m quantresearch doctor
git diff --check
```

