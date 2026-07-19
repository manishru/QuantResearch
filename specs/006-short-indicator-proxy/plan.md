# Implementation Plan

1. Add pure short-return and exit-selection helpers with unit tests.
2. Build a CLI that derives completed-close indicators in DuckDB and applies
   point-in-time membership and seasoning filters.
3. Generate trade evidence and configuration summaries, then run a smoke test
   and the full test suite.
4. Add a daily-entry, target/stop-only research runner and compare frozen
   2010-2015 selection with 2016+ forward results.
