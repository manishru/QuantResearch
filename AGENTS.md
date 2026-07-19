# QuantResearch Agent Guidance

## Required workflow

Before implementing or materially changing behavior:

1. Read `.specify/memory/constitution.md` completely.
2. Create or update the applicable numbered `specs/*/spec.md`.
3. Resolve or explicitly document open requirement-checklist items.
4. Create an implementation plan and task list that trace to functional
   requirements and acceptance scenarios.
5. Write or update tests before implementation.
6. Run the narrow tests, full test suite, validation commands, and `git diff --check`.

Do not treat performance targets as permission to weaken point-in-time correctness,
security identity, reproducibility, or validation.

## Repository conventions

- Use `pathlib.Path`; do not hard-code a user's home directory.
- Keep generic domain logic independent of index, exchange, and data provider.
- Keep source/index/provider behavior in adapters and configuration.
- Never embed or print API keys.
- Never modify files under `data/raw/`.
- Preserve user changes and unrelated worktree edits.
- Prefer atomic publication and idempotent incremental processing.
- Expose pipeline capabilities as library functions and CLI commands with JSON output.

## Verification

Core infrastructure currently supports:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m quantresearch doctor
git diff --check
```

Feature-specific plans MUST add their own verification commands.

