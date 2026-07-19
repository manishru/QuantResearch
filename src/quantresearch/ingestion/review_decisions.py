"""Immutable import adapters for reviewed mapping and exclusion decisions."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from quantresearch.domain.exclusions import (
    ExclusionReason,
    ExclusionRegistry,
    ExclusionStatus,
    UniverseExclusion,
)
from quantresearch.domain.mappings import (
    ApprovalStatus,
    MappingRegistry,
    MappingType,
    ProviderSymbolMapping,
)

EXCLUSION_COLUMNS = {
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
}
MAPPING_COLUMNS = {
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
}


@dataclass(frozen=True, slots=True)
class ExclusionDecisionImport:
    source_path: Path
    source_sha256: str
    registry: ExclusionRegistry
    counts: dict[str, int]

    @property
    def ready(self) -> bool:
        return self.counts.get(ExclusionStatus.PENDING.value, 0) == 0


@dataclass(frozen=True, slots=True)
class MappingDecisionImport:
    source_path: Path
    source_sha256: str
    registry: MappingRegistry
    counts: dict[str, int]

    @property
    def ready(self) -> bool:
        return self.counts.get(ApprovalStatus.PENDING.value, 0) == 0


def _optional_date(value: str) -> date | None:
    return date.fromisoformat(value) if value.strip() else None


def _optional_datetime(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value.strip() else None


def load_exclusion_decisions(path: Path) -> ExclusionDecisionImport:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Exclusion decision file does not exist: {source}")
    source_bytes = source.read_bytes()
    records: list[UniverseExclusion] = []
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = EXCLUSION_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Missing exclusion decision columns: {sorted(missing)}")
        for row_number, row in enumerate(reader, start=2):
            try:
                records.append(
                    UniverseExclusion(
                        index_id=row["index_id"],
                        constituent_symbol=row["constituent_symbol"],
                        effective_from=date.fromisoformat(row["effective_from"]),
                        effective_to=_optional_date(row["effective_to"]),
                        reason=ExclusionReason(row["reason"].strip()),
                        rationale=row["rationale"],
                        evidence_ref=row["evidence_ref"] or None,
                        status=ExclusionStatus(row["status"].strip()),
                        reviewer=row["reviewer"] or None,
                        reviewed_at=_optional_datetime(row["reviewed_at"]),
                    )
                )
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Invalid exclusion decision at row {row_number}: {exc}") from exc
    registry = ExclusionRegistry(tuple(records))
    counts = Counter(item.status.value for item in registry.exclusions)
    return ExclusionDecisionImport(
        source_path=source,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        registry=registry,
        counts=dict(counts),
    )


def load_mapping_decisions(path: Path) -> MappingDecisionImport:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Mapping decision file does not exist: {source}")
    source_bytes = source.read_bytes()
    records: list[ProviderSymbolMapping] = []
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = MAPPING_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Missing mapping decision columns: {sorted(missing)}")
        for row_number, row in enumerate(reader, start=2):
            try:
                records.append(
                    ProviderSymbolMapping(
                        security_id=row["security_id"],
                        constituent_symbol=row["constituent_symbol"],
                        provider_id=row["provider_id"],
                        provider_symbol=row["provider_symbol"],
                        exchange_code=row["exchange_code"],
                        effective_from=date.fromisoformat(row["effective_from"]),
                        effective_to=_optional_date(row["effective_to"]),
                        mapping_type=MappingType(row["mapping_type"].strip()),
                        reason=row["reason"],
                        evidence_ref=row["evidence_ref"] or None,
                        approval_status=ApprovalStatus(row["approval_status"].strip()),
                        reviewer=row["reviewer"] or None,
                        reviewed_at=_optional_datetime(row["reviewed_at"]),
                    )
                )
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Invalid mapping decision at row {row_number}: {exc}") from exc
    registry = MappingRegistry(tuple(records))
    counts = Counter(item.approval_status.value for item in registry.mappings)
    return MappingDecisionImport(
        source_path=source,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        registry=registry,
        counts=dict(counts),
    )
