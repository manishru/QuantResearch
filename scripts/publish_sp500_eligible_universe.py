"""Publish the operator-approved point-in-time S&P 500 eligibility manifest."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import duckdb

from quantresearch.domain.exclusions import apply_exclusions
from quantresearch.ingestion.component_csv import load_component_snapshots
from quantresearch.ingestion.review_decisions import (
    load_exclusion_decisions,
    load_mapping_decisions,
)
from quantresearch.validation.mapping_coverage import calculate_fold_coverage
from quantresearch.walkforward.windows import generate_walk_forward_windows

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/sp500"
OUTPUT = ROOT / "data/validated/sp500"


def main() -> None:
    mapping_import = load_mapping_decisions(OUTPUT / "mapping_decisions_operator.csv")
    exclusion_import = load_exclusion_decisions(
        OUTPUT / "exclusion_decisions_operator.csv"
    )
    if not mapping_import.ready or not exclusion_import.ready:
        raise RuntimeError("Pending review decisions prevent eligible-universe publication")

    history = load_component_snapshots(
        RAW / "S&P 500 Historical Components & Changes (Updated).csv",
        index_id="SP500",
    )
    eligible_history = apply_exclusions(
        history,
        exclusion_import.registry,
        decision_sha256=exclusion_import.source_sha256,
    )
    parquet = RAW / "eod_final_1996-01-01_to_2026-07-12.parquet"
    connection = duckdb.connect(":memory:")
    available = frozenset(
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT Ticker FROM read_parquet(?) ORDER BY Ticker", [str(parquet)]
        ).fetchall()
    )
    folds = calculate_fold_coverage(
        history.snapshots,
        generate_walk_forward_windows(1996, 2025),
        available_symbols=available,
        registry=mapping_import.registry,
        provider_id="EODHD",
        exclusions=exclusion_import.registry,
    )

    intervals_path = OUTPUT / "eligible_membership_intervals.csv"
    with intervals_path.open("w", newline="", encoding="utf-8") as handle:
        fields = ["index_id", "constituent_symbol", "effective_from", "effective_to"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for interval in eligible_history.intervals():
            writer.writerow(
                {
                    "index_id": interval.index_id,
                    "constituent_symbol": interval.constituent_symbol,
                    "effective_from": interval.effective_from.isoformat(),
                    "effective_to": (
                        interval.effective_to.isoformat() if interval.effective_to else ""
                    ),
                }
            )

    fold_path = OUTPUT / "operator_fold_coverage.csv"
    with fold_path.open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "fold_id", "segment", "snapshot_count", "required_symbols",
            "covered_symbols", "mean_coverage", "minimum_coverage",
            "excluded_symbols", "eligible_symbols", "eligible_covered_symbols",
            "eligible_coverage",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for fold in folds:
            for segment in ("train", "forward"):
                writer.writerow(
                    {"fold_id": fold.fold_id, "segment": segment, **asdict(getattr(fold, segment))}
                )

    eligible_coverages = [
        getattr(fold, segment).eligible_coverage
        for fold in folds
        for segment in ("train", "forward")
        if getattr(fold, segment).snapshot_count
    ]
    interval_hash = hashlib.sha256(intervals_path.read_bytes()).hexdigest()
    manifest = {
        "index_id": "SP500",
        "status": "ready_with_operator_approved_exclusions",
        "optimization_allowed": min(eligible_coverages) == 1.0,
        "gross_minimum_coverage": min(
            getattr(fold, segment).minimum_coverage
            for fold in folds
            for segment in ("train", "forward")
            if getattr(fold, segment).snapshot_count
        ),
        "eligible_minimum_coverage": min(eligible_coverages),
        "approved_exclusion_intervals": len(exclusion_import.registry.exclusions),
        "approved_mappings": mapping_import.counts.get("approved", 0),
        "rejected_mappings": mapping_import.counts.get("rejected", 0),
        "membership_source_sha256": history.source_sha256,
        "mapping_decisions_sha256": mapping_import.source_sha256,
        "exclusion_decisions_sha256": exclusion_import.source_sha256,
        "eligible_history_version": eligible_history.source_sha256,
        "eligible_intervals_sha256": interval_hash,
        "eligible_intervals": str(intervals_path.relative_to(ROOT)),
        "fold_coverage": str(fold_path.relative_to(ROOT)),
    }
    manifest_path = OUTPUT / "eligible_universe_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
