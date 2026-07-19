"""Record the operator decision to ignore unresolved S&P 500 constituents."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data/validated/sp500"
EVIDENCE = "operator-decision://2026-07-13/ignore-unverified-sp500-constituents"
REVIEWER = "operator:manishgarg"
REVIEWED_AT = datetime(2026, 7, 13, tzinfo=UTC).isoformat()


def transform(source: Path, destination: Path, *, mapping: bool) -> None:
    with source.open(newline="", encoding="utf-8-sig") as input_handle:
        reader = csv.DictReader(input_handle)
        rows = list(reader)
        fields = list(reader.fieldnames or ())
    for row in rows:
        status_field = "approval_status" if mapping else "status"
        if row[status_field] != "pending":
            continue
        if mapping:
            row[status_field] = "rejected"
            row["reason"] = (
                f"{row['reason']}; operator chose exclusion instead of replacement history"
            )
        else:
            row[status_field] = "approved"
            row["evidence_ref"] = EVIDENCE
        row["reviewer"] = REVIEWER
        row["reviewed_at"] = REVIEWED_AT
    with destination.open("w", newline="", encoding="utf-8") as output_handle:
        writer = csv.DictWriter(output_handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    transform(
        SOURCE_DIR / "mapping_decisions.csv",
        SOURCE_DIR / "mapping_decisions_operator.csv",
        mapping=True,
    )
    transform(
        SOURCE_DIR / "exclusion_proposals.csv",
        SOURCE_DIR / "exclusion_decisions_operator.csv",
        mapping=False,
    )
    print("Operator mapping rejections and interval exclusions recorded.")


if __name__ == "__main__":
    main()
