# Monthly Momentum Same-Day Rollover

This workflow sells a tranche on the twelfth subsequent scheduled monthly
purchase session and immediately reuses its after-tax proceeds for that session's
new purchase. It does not wait for brokerage settlement and does not enforce a
strict 365-calendar-day anniversary.

The current experiment disables both the optional volume/price deterioration exit
and the stepwise profit-trailing exit. The ordinary 45% stop remains enabled.

## Required local files

The commands expect these existing files under `~/QuantResearch`:

```text
data/raw/sp500/eod_final_1996-01-01_to_2026-07-12.parquet
data/validated/sp500/eligible_membership_intervals.csv
data/validated/sp500/mapping_decisions_operator.csv
data/validated/sp500/membership_tenure_exceptions.csv
```

Do not copy the Parquet file into Git. The repository `.gitignore` excludes market
data and generated reports.

## VS Code walkthrough

1. Open Terminal and enter the repository:

   ```bash
   cd ~/QuantResearch
   code .
   ```

2. In VS Code, open **Terminal → New Terminal**.

3. Remove any shell alias that overrides the virtual environment, then activate it:

   ```bash
   unalias python 2>/dev/null || true
   source .venv/bin/activate
   rehash
   which python
   python --version
   ```

   `which python` must print:

   ```text
   /Users/manishgarg/QuantResearch/.venv/bin/python
   ```

4. Select the same interpreter inside VS Code:

   - Press `Command+Shift+P`.
   - Choose **Python: Select Interpreter**.
   - Select `~/QuantResearch/.venv/bin/python`.

5. Install the project in editable mode:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -e .
   ```

6. Run the tests:

   ```bash
   PYTHONPATH=src python -m unittest discover -s tests -v
   ```

7. Run the complete point-in-time monthly momentum matrix without profit trailing:

   ```bash
   PYTHONPATH=src python scripts/run_monthly_momentum_lot_matrix.py \
     --start 2016-01-01 \
     --end 2026-07-12 \
     --stop 0.45 \
     --disable-deterioration \
     --exclude-ticker CVC \
     --output reports/monthly_momentum_same_day_rollover
   ```

   Do not pass `--trailing-activation`; omitting it disables the stepwise
   trailing-profit exit.

8. Replay the first-12-month funding, 35% net realized tax approximation, same-day
   maturity rollover, and early-exit installment rule:

   ```bash
   PYTHONPATH=src python scripts/run_tax_reinvestment_matrix.py \
     --trade-csv reports/monthly_momentum_same_day_rollover/all_trades.csv \
     --output reports/monthly_momentum_same_day_rollover_tax \
     --monthly-contribution 10000 \
     --contribution-months 12 \
     --spread-early-exit-to-maturity \
     --maturity-reinvestment-spread-months 12 \
     --tax-rate 0.35 \
     --stop-label 45%
   ```

9. Review these outputs in VS Code:

   ```text
   reports/monthly_momentum_same_day_rollover/configuration_summary.csv
   reports/monthly_momentum_same_day_rollover/all_trades.csv
   reports/monthly_momentum_same_day_rollover_tax/tax_reinvestment_configuration_summary.csv
   reports/monthly_momentum_same_day_rollover_tax/best_tax_reinvestment_trades.csv
   reports/monthly_momentum_same_day_rollover_tax/best_tax_reinvestment_cash_ledger.csv
   ```

## Data and date changes

To run through a later date, first incrementally update the Parquet data and index
membership inputs. Then change only `--end` in the command. Do not change source-code
dates to run a new report.

If the Parquet filename changes, update the `parquet` setting near the beginning of
`scripts/run_monthly_momentum_lot_matrix.py`. A later task should move that path into
the central configuration module.

## Diagram

The PlantUML source is:

```text
docs/diagrams/monthly_momentum_same_day_rollover.puml
```

Render it locally with:

```bash
plantuml docs/diagrams/monthly_momentum_same_day_rollover.puml
```

This creates `docs/diagrams/monthly_momentum_same_day_rollover.png`.
