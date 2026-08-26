# Tasks: Midcap Golden 10M>6M>3M

- [x] T001 Record requirements and acceptance scenarios.
- [x] T002 Add failing unit tests for the frozen rule contract.
- [x] T003 Implement the stable strategy definition.
- [x] T004 Store the strategy configuration as JSON.
- [x] T005 Add the reproducible named runner.
- [x] T006 Add README rule details and usage.
- [x] T007 Run narrow and full validation gates. The feature tests, named
  backtest, doctor, and diff check pass. The full suite passes 406/407 tests
  with `PYTHONPATH=src:scripts`; the remaining pre-existing failure is
  `test_monthly_momentum_sector_matrix`, whose call site lacks eight newer
  required arguments unrelated to this feature.
- [x] T008 Commit only Midcap Golden files and the scoped README edit.
