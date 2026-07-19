#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-python}"
ROOT_OUTPUT="${ROOT_OUTPUT:-reports/holding_period_matrix_5m_2m}"
FINAL_DATE="${FINAL_DATE:-2026-07-10}"

mkdir -p "$ROOT_OUTPUT"

for holding_months in $(seq 1 12); do
  backtest_output="$ROOT_OUTPUT/hold_${holding_months}m_backtest"
  tax_output="$ROOT_OUTPUT/hold_${holding_months}m_tax"

  echo "Running holding period ${holding_months} month(s)"

  PYTHONPATH=src "$PYTHON_BIN" scripts/run_monthly_momentum_lot_matrix.py \
    --start 2016-01-01 \
    --end 2026-07-12 \
    --holding-months "$holding_months" \
    --stop 0.45 \
    --disable-deterioration \
    --exclude-ticker CVC \
    --rule "5M>2M>0" \
    --output "$backtest_output"

  PYTHONPATH=src "$PYTHON_BIN" scripts/run_tax_reinvestment_matrix.py \
    --trade-csv "$backtest_output/all_trades.csv" \
    --output "$tax_output" \
    --monthly-contribution 10000 \
    --contribution-months 12 \
    --holding-months "$holding_months" \
    --maturity-reinvestment-spread-months 1 \
    --tax-rate 0.35 \
    --final-date "$FINAL_DATE" \
    --stop-label 45%
done

PYTHONPATH=src "$PYTHON_BIN" - "$ROOT_OUTPUT" <<'PY'
import csv
import sys
from pathlib import Path

root = Path(sys.argv[1])
rows = []
for months in range(1, 13):
    path = root / f"hold_{months}m_tax" / "tax_reinvestment_configuration_summary.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        configurations = list(csv.DictReader(handle))
    best = min(configurations, key=lambda row: int(row["rank"]))
    rows.append({"holding_months": months, **best})

rows.sort(
    key=lambda row: float(row["ending_wealth_after_full_liquidation_tax"]),
    reverse=True,
)
for rank, row in enumerate(rows, start=1):
    row["holding_period_rank"] = rank

output = root / "holding_period_comparison.csv"
with output.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

print(f"Comparison written: {output}")
print(
    "Best holding period: "
    f"{rows[0]['holding_months']} month(s), "
    f"day={rows[0]['nominal_day']}, top_n={rows[0]['top_n']}, "
    "fully taxed wealth="
    f"{float(rows[0]['ending_wealth_after_full_liquidation_tax']):.2f}, "
    f"XIRR={float(rows[0]['xirr_after_full_liquidation_tax']):.4%}"
)
PY
