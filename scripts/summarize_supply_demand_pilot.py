"""Create stitched metrics and one trade ledger for the feasibility pilot."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports/supply_demand_pilot_v2"


def main() -> None:
    summary = json.loads((OUTPUT / "summary.json").read_text())
    completed = [fold for fold in summary["folds"] if fold["forward"] is not None]
    factors = [fold["forward"]["ending_equity"] / 100_000 for fold in completed]
    stitched_factor = math.prod(factors)
    years = 2 * len(completed)
    selected = Counter(str(fold["selected_candidate_index"]) for fold in summary["folds"])
    report = {
        "run": summary["run"],
        "pilot_non_final": True,
        "conclusion": "control_and_strict_candidates_do_not_show_a_profitable_edge",
        "completed_forward_folds": len(completed),
        "forward_years": years,
        "total_forward_trades": summary["total_forward_trades"],
        "stitched_total_return": stitched_factor - 1,
        "stitched_cagr": stitched_factor ** (1 / years) - 1,
        "worst_fold_drawdown": min(
            fold["forward"]["maximum_drawdown"] for fold in completed
        ),
        "profitable_forward_folds": sum(
            fold["forward"]["cagr"] > 0 for fold in completed
        ),
        "selected_candidate_counts": dict(sorted(selected.items())),
        "warning": (
            "The strict candidate frequently selected with zero or very few trades; "
            "the next search must restore a positive frequency gate."
        ),
    }
    (OUTPUT / "stitched_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    trade_files = sorted(OUTPUT.glob("fold_*_forward_trades.csv"))
    rows: list[dict[str, str]] = []
    fields: list[str] = []
    for path in trade_files:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = fields or list(reader.fieldnames or ())
            rows.extend(reader)
    with (OUTPUT / "all_forward_trades.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
