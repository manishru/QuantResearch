"""Review-gated, effective-dated exclusions from an analytical universe."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from itertools import groupby

from quantresearch.domain.membership import MembershipHistory, MembershipSnapshot


class ExclusionReason(StrEnum):
    PROVIDER_DATA_UNAVAILABLE = "provider_data_unavailable"
    IDENTITY_UNRESOLVED = "identity_unresolved"
    DATA_QUALITY_FAILURE = "data_quality_failure"
    OTHER = "other"


class ExclusionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


def _normalize(value: str, name: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class UniverseExclusion:
    index_id: str
    constituent_symbol: str
    effective_from: date
    effective_to: date | None
    reason: ExclusionReason
    rationale: str
    evidence_ref: str | None
    status: ExclusionStatus
    reviewer: str | None
    reviewed_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "index_id", _normalize(self.index_id, "index_id"))
        object.__setattr__(
            self,
            "constituent_symbol",
            _normalize(self.constituent_symbol, "constituent_symbol"),
        )
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        if not self.rationale.strip():
            raise ValueError("rationale cannot be empty")
        if self.status in {ExclusionStatus.APPROVED, ExclusionStatus.REJECTED}:
            if not (self.reviewer or "").strip() or self.reviewed_at is None:
                raise ValueError("reviewed exclusions require reviewer and reviewed_at")
        if self.status is ExclusionStatus.APPROVED and not (self.evidence_ref or "").strip():
            raise ValueError("approved exclusions require evidence_ref")

    def contains(self, as_of: date) -> bool:
        return self.effective_from <= as_of and (
            self.effective_to is None or as_of <= self.effective_to
        )


@dataclass(frozen=True, slots=True)
class ExclusionRegistry:
    exclusions: tuple[UniverseExclusion, ...]

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(
                self.exclusions,
                key=lambda item: (item.index_id, item.constituent_symbol, item.effective_from),
            )
        )
        object.__setattr__(self, "exclusions", ordered)

        def key(item: UniverseExclusion) -> tuple[str, str]:
            return item.index_id, item.constituent_symbol

        for exclusion_key, records in groupby(ordered, key=key):
            previous: UniverseExclusion | None = None
            for current in records:
                if previous is not None and (
                    previous.effective_to is None
                    or current.effective_from <= previous.effective_to
                ):
                    raise ValueError(
                        "Overlapping exclusion intervals for "
                        f"{exclusion_key[0]}:{exclusion_key[1]}"
                    )
                previous = current

    def is_excluded(self, index_id: str, symbol: str, as_of: date) -> bool:
        normalized_index = _normalize(index_id, "index_id")
        normalized_symbol = _normalize(symbol, "constituent_symbol")
        return any(
            item.index_id == normalized_index
            and item.constituent_symbol == normalized_symbol
            and item.status is ExclusionStatus.APPROVED
            and item.contains(as_of)
            for item in self.exclusions
        )


def apply_exclusions(
    history: MembershipHistory,
    registry: ExclusionRegistry,
    *,
    decision_sha256: str,
) -> MembershipHistory:
    """Create a content-addressed membership history after approved exclusions."""
    if len(decision_sha256) != 64:
        raise ValueError("decision_sha256 must be a 64-character SHA-256 digest")
    snapshots = tuple(
        MembershipSnapshot(
            index_id=snapshot.index_id,
            effective_date=snapshot.effective_date,
            symbols=frozenset(
                symbol
                for symbol in snapshot.symbols
                if not registry.is_excluded(
                    snapshot.index_id, symbol, snapshot.effective_date
                )
            ),
            source_row=snapshot.source_row,
        )
        for snapshot in history.snapshots
    )
    derived_digest = hashlib.sha256(
        f"{history.source_sha256}:{decision_sha256}".encode()
    ).hexdigest()
    return MembershipHistory(
        index_id=history.index_id,
        snapshots=snapshots,
        source_path=history.source_path,
        source_sha256=derived_digest,
    )
