"""Conservative classification of provider symbol-resolution reports.

Only aliases that preserve the complete alphanumeric symbol and differ solely
by ``.`` versus ``-`` punctuation are safe for automatic approval.  Every
identity-sensitive substitution remains quarantined pending external evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum

from quantresearch.domain.mappings import (
    ApprovalStatus,
    MappingRegistry,
    MappingType,
    ProviderSymbolMapping,
)


class MappingDisposition(StrEnum):
    DIRECT = "direct"
    APPROVED_FORMATTING = "approved_formatting"
    PENDING_IDENTITY = "pending_identity"
    PENDING_FALLBACK = "pending_fallback"
    UNRESOLVED = "unresolved"


def _symbol(value: str) -> str:
    return value.strip().upper()


@dataclass(frozen=True, slots=True)
class ResolutionReportRow:
    input_symbol: str
    mapped_symbol: str
    resolved_symbol: str
    status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_symbol", _symbol(self.input_symbol))
        object.__setattr__(self, "mapped_symbol", _symbol(self.mapped_symbol))
        object.__setattr__(self, "resolved_symbol", _symbol(self.resolved_symbol))
        object.__setattr__(self, "status", self.status.strip())
        if not self.input_symbol:
            raise ValueError("input_symbol cannot be empty")


@dataclass(frozen=True, slots=True)
class MappingReviewRecord:
    input_symbol: str
    mapped_symbol: str
    resolved_symbol: str
    status: str
    disposition: MappingDisposition
    reason: str


@dataclass(frozen=True, slots=True)
class MappingReviewResult:
    records: tuple[MappingReviewRecord, ...]
    registry: MappingRegistry


def _punctuation_key(symbol: str) -> str:
    return symbol.replace(".", "").replace("-", "")


def _is_safe_formatting_alias(source: str, target: str) -> bool:
    return (
        source != target
        and "_OLD" not in source
        and "_OLD" not in target
        and _punctuation_key(source) == _punctuation_key(target)
        and _punctuation_key(source).isalnum()
    )


def classify_resolution_rows(
    rows: tuple[ResolutionReportRow, ...],
    *,
    effective_from: date,
    provider_id: str = "EODHD",
    exchange_code: str = "US",
) -> MappingReviewResult:
    """Classify rows and build a review-gated effective-dated registry."""
    records: list[MappingReviewRecord] = []
    mappings: list[ProviderSymbolMapping] = []
    seen: set[str] = set()
    deterministic_review_time = datetime.combine(effective_from, time.min, tzinfo=UTC)

    for row in rows:
        if row.input_symbol in seen:
            raise ValueError(f"Duplicate resolution row for {row.input_symbol}")
        seen.add(row.input_symbol)

        if not row.resolved_symbol:
            disposition = MappingDisposition.UNRESOLVED
            reason = "Provider resolution did not produce a symbol"
        elif row.input_symbol == row.resolved_symbol:
            disposition = MappingDisposition.DIRECT
            reason = "Constituent symbol resolved without substitution"
        elif row.resolved_symbol.endswith("_OLD"):
            disposition = MappingDisposition.PENDING_FALLBACK
            reason = "Provider _OLD fallback requires security-identity evidence"
        elif _is_safe_formatting_alias(row.input_symbol, row.resolved_symbol):
            disposition = MappingDisposition.APPROVED_FORMATTING
            reason = "System-approved punctuation-equivalent provider alias"
        else:
            disposition = MappingDisposition.PENDING_IDENTITY
            reason = "Identity-changing substitution requires external evidence"

        records.append(
            MappingReviewRecord(
                input_symbol=row.input_symbol,
                mapped_symbol=row.mapped_symbol,
                resolved_symbol=row.resolved_symbol,
                status=row.status,
                disposition=disposition,
                reason=reason,
            )
        )

        if disposition in {MappingDisposition.DIRECT, MappingDisposition.UNRESOLVED}:
            continue

        approved = disposition is MappingDisposition.APPROVED_FORMATTING
        fallback = disposition is MappingDisposition.PENDING_FALLBACK
        mappings.append(
            ProviderSymbolMapping(
                security_id=f"REVIEW:{row.input_symbol}",
                constituent_symbol=row.input_symbol,
                provider_id=provider_id,
                provider_symbol=row.resolved_symbol,
                exchange_code=exchange_code,
                effective_from=effective_from,
                effective_to=None,
                mapping_type=(
                    MappingType.FORMATTING_ALIAS
                    if approved
                    else MappingType.PROVIDER_FALLBACK
                    if fallback
                    else MappingType.UNKNOWN
                ),
                reason=reason,
                evidence_ref="rule://punctuation-equivalence-v1" if approved else None,
                approval_status=(
                    ApprovalStatus.APPROVED if approved else ApprovalStatus.PENDING
                ),
                reviewer="system:punctuation-equivalence-v1" if approved else None,
                reviewed_at=deterministic_review_time if approved else None,
            )
        )

    return MappingReviewResult(tuple(records), MappingRegistry(tuple(mappings)))
