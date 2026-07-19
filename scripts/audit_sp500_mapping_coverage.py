"""Generate conservative S&P 500 mapping-review and fold-coverage reports."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path

import duckdb

from quantresearch.ingestion.component_csv import load_component_snapshots
from quantresearch.validation.mapping_coverage import calculate_fold_coverage
from quantresearch.validation.mapping_review import ResolutionReportRow, classify_resolution_rows
from quantresearch.walkforward.windows import generate_walk_forward_windows

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/sp500"
OUTPUT = ROOT / "data/validated/sp500"


def load_rows(path: Path) -> tuple[ResolutionReportRow, ...]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return tuple(
            ResolutionReportRow(
                input_symbol=row["InputTicker"],
                mapped_symbol=row["MappedTicker"],
                resolved_symbol=row["ResolvedTicker"],
                status=row["Status"],
            )
            for row in csv.DictReader(handle)
        )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = load_rows(RAW / "ticker_resolution_report.csv")
    review = classify_resolution_rows(rows, effective_from=date(1996, 1, 1))

    review_path = OUTPUT / "mapping_review.csv"
    with review_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "input_symbol",
                "mapped_symbol",
                "resolved_symbol",
                "status",
                "disposition",
                "reason",
            ],
        )
        writer.writeheader()
        for record in review.records:
            values = asdict(record)
            values["disposition"] = record.disposition.value
            writer.writerow(values)

    mapping_decisions_path = OUTPUT / "mapping_decisions.csv"
    mapping_fields = [
        "security_id",
        "constituent_symbol",
        "provider_id",
        "provider_symbol",
        "exchange_code",
        "effective_from",
        "effective_to",
        "mapping_type",
        "reason",
        "evidence_ref",
        "approval_status",
        "reviewer",
        "reviewed_at",
    ]
    with mapping_decisions_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=mapping_fields)
        writer.writeheader()
        for mapping in review.registry.mappings:
            writer.writerow(
                {
                    "security_id": mapping.security_id,
                    "constituent_symbol": mapping.constituent_symbol,
                    "provider_id": mapping.provider_id,
                    "provider_symbol": mapping.provider_symbol,
                    "exchange_code": mapping.exchange_code,
                    "effective_from": mapping.effective_from.isoformat(),
                    "effective_to": (
                        mapping.effective_to.isoformat() if mapping.effective_to else ""
                    ),
                    "mapping_type": mapping.mapping_type.value,
                    "reason": mapping.reason,
                    "evidence_ref": mapping.evidence_ref or "",
                    "approval_status": mapping.approval_status.value,
                    "reviewer": mapping.reviewer or "",
                    "reviewed_at": (
                        mapping.reviewed_at.isoformat() if mapping.reviewed_at else ""
                    ),
                }
            )

    parquet = RAW / "eod_final_1996-01-01_to_2026-07-12.parquet"
    relation = duckdb.connect(":memory:")
    available = frozenset(
        row[0]
        for row in relation.execute(
            "SELECT DISTINCT Ticker FROM read_parquet(?) ORDER BY Ticker",
            [str(parquet)],
        ).fetchall()
    )
    history = load_component_snapshots(
        RAW / "S&P 500 Historical Components & Changes (Updated).csv",
        index_id="SP500",
    )
    review_by_symbol = {record.input_symbol: record for record in review.records}
    exclusion_path = OUTPUT / "exclusion_proposals.csv"
    exclusion_fields = [
        "index_id",
        "constituent_symbol",
        "effective_from",
        "effective_to",
        "reason",
        "rationale",
        "evidence_ref",
        "status",
        "reviewer",
        "reviewed_at",
    ]
    exclusion_count = 0
    with exclusion_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=exclusion_fields)
        writer.writeheader()
        for interval in history.intervals():
            record = review_by_symbol.get(interval.constituent_symbol)
            if record is None or record.disposition.value not in {
                "pending_identity",
                "pending_fallback",
                "unresolved",
            }:
                continue
            reason = (
                "provider_data_unavailable"
                if record.disposition.value == "unresolved"
                else "identity_unresolved"
            )
            writer.writerow(
                {
                    "index_id": interval.index_id,
                    "constituent_symbol": interval.constituent_symbol,
                    "effective_from": interval.effective_from.isoformat(),
                    "effective_to": (
                        interval.effective_to.isoformat() if interval.effective_to else ""
                    ),
                    "reason": reason,
                    "rationale": record.reason,
                    "evidence_ref": "",
                    "status": "pending",
                    "reviewer": "",
                    "reviewed_at": "",
                }
            )
            exclusion_count += 1
    windows = generate_walk_forward_windows(1996, 2025)
    folds = calculate_fold_coverage(
        history.snapshots,
        windows,
        available_symbols=available,
        registry=review.registry,
        provider_id="EODHD",
    )

    fold_path = OUTPUT / "fold_coverage.csv"
    with fold_path.open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "fold_id",
            "segment",
            "snapshot_count",
            "required_symbols",
            "covered_symbols",
            "mean_coverage",
            "minimum_coverage",
            "excluded_symbols",
            "eligible_symbols",
            "eligible_covered_symbols",
            "eligible_coverage",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for fold in folds:
            for segment in ("train", "forward"):
                summary = getattr(fold, segment)
                writer.writerow(
                    {"fold_id": fold.fold_id, "segment": segment, **asdict(summary)}
                )

    counts = Counter(record.disposition.value for record in review.records)
    summary = {
        "status": "blocked_identity_coverage",
        "policy": "Only punctuation-equivalent aliases are system-approved",
        "resolution_rows": len(review.records),
        "disposition_counts": dict(sorted(counts.items())),
        "approved_mapping_count": sum(
            item.approval_status.value == "approved" for item in review.registry.mappings
        ),
        "pending_mapping_count": sum(
            item.approval_status.value == "pending" for item in review.registry.mappings
        ),
        "pending_exclusion_interval_count": exclusion_count,
        "fold_count": len(folds),
        "minimum_train_coverage": min(fold.train.minimum_coverage for fold in folds),
        "minimum_forward_coverage": min(
            fold.forward.minimum_coverage
            for fold in folds
            if fold.forward.snapshot_count
        ),
        "optimization_allowed": False,
        "mapping_review_csv": str(review_path.relative_to(ROOT)),
        "mapping_decisions_csv": str(mapping_decisions_path.relative_to(ROOT)),
        "fold_coverage_csv": str(fold_path.relative_to(ROOT)),
        "exclusion_proposals_csv": str(exclusion_path.relative_to(ROOT)),
    }
    (OUTPUT / "mapping_coverage_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
