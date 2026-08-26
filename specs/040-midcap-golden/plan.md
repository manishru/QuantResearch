# Implementation Plan: Midcap Golden 10M>6M>3M

1. Add a provider-independent strategy definition and validation helpers under
   `src/quantresearch/research/` (FR-001 through FR-008).
2. Add a machine-readable JSON configuration (FR-001 through FR-009).
3. Add a thin CLI runner that translates the stable strategy definition into
   the existing audited S&P 400 engine arguments (FR-010).
4. Add unit tests for rule logic, configuration, and complete CLI translation.
5. Document the strategy and reproducible command in `README.md`.
6. Run narrow tests, the full suite, doctor, and `git diff --check`.
