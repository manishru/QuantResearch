"""Adapter for complete index membership snapshots stored in CSV."""

from __future__ import annotations

import csv
import hashlib
from datetime import date
from pathlib import Path

from quantresearch.domain.membership import MembershipHistory, MembershipSnapshot


class ComponentCsvError(ValueError):
    """Raised when a component snapshot CSV violates its input contract."""


def normalize_symbol(value: str) -> str:
    """Normalize superficial source formatting without changing identity."""
    return value.strip().strip('"').strip("'").upper()


def load_component_snapshots(
    path: Path,
    *,
    index_id: str,
    date_column: str = "date",
    tickers_column: str = "tickers",
    separator: str = ",",
) -> MembershipHistory:
    """Load and validate complete membership snapshots from ``path``.

    The source file is read-only. A SHA-256 digest provides immutable provenance.
    Symbols are normalized but never mapped to successor/provider tickers here.
    """
    source = path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Component snapshot file does not exist: {source}")
    if not index_id.strip():
        raise ComponentCsvError("index_id cannot be empty")

    source_bytes = source.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    snapshots: list[MembershipSnapshot] = []
    seen: dict[date, frozenset[str]] = {}
    previous_date: date | None = None

    with source.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        missing = {date_column, tickers_column} - columns
        if missing:
            raise ComponentCsvError(f"Missing required columns: {sorted(missing)}")

        for row_number, row in enumerate(reader, start=2):
            raw_date = (row.get(date_column) or "").strip()
            try:
                effective_date = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise ComponentCsvError(
                    f"Invalid ISO date at row {row_number}: {raw_date!r}"
                ) from exc

            symbols = frozenset(
                normalized
                for item in (row.get(tickers_column) or "").split(separator)
                if (normalized := normalize_symbol(item))
            )
            if not symbols:
                raise ComponentCsvError(f"Empty membership at row {row_number}")

            if effective_date in seen:
                kind = "identical" if seen[effective_date] == symbols else "conflicting"
                raise ComponentCsvError(
                    f"Duplicate {kind} snapshot date at row {row_number}: {effective_date}"
                )
            if previous_date is not None and effective_date < previous_date:
                raise ComponentCsvError(
                    f"Out-of-order snapshot at row {row_number}: "
                    f"{effective_date} follows {previous_date}"
                )

            snapshot = MembershipSnapshot(
                index_id=index_id.strip(),
                effective_date=effective_date,
                symbols=symbols,
                source_row=row_number,
            )
            snapshots.append(snapshot)
            seen[effective_date] = symbols
            previous_date = effective_date

    if not snapshots:
        raise ComponentCsvError("Component snapshot file contains no data rows")

    return MembershipHistory(
        index_id=index_id.strip(),
        snapshots=tuple(snapshots),
        source_path=source,
        source_sha256=digest,
    )
