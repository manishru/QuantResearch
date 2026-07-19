# Backup and recovery

## What GitHub stores

The private GitHub repository stores source code, tests, specifications,
research runbooks, and small metadata files. It deliberately excludes API
tokens, virtual environments, generated reports, Parquet, DuckDB, and raw price
data. These files are too large and/or too sensitive for normal Git hosting.

## What must be backed up separately

- `data/raw/`
- `data/validated/`
- `data/features/` (including `research.duckdb`)
- `reports/`
- `.env` or the password-manager record containing `EODHD_API_TOKEN`

Do not upload `.env` to GitHub.

## Create a manifest before each archive backup

```zsh
cd ~/QuantResearch
PYTHONPATH=src .venv/bin/python scripts/create_research_backup_manifest.py \
  --output reports/backup_manifest_latest.csv
```

Copy the project data folders and this manifest to an encrypted external SSD or
a private cloud-backup provider. Keep at least one off-device copy. The manifest
records file size and SHA-256, allowing the restored files to be verified.

## Restore on a new Mac

```zsh
git clone https://github.com/manishru/QuantResearch.git ~/QuantResearch
cd ~/QuantResearch
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev,phase1]"
```

Restore `data/` and `reports/` from the encrypted backup, recreate the
`EODHD_API_TOKEN` environment variable, and compare the restored archive against
the manifest.
