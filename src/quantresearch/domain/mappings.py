"""Effective-dated, review-gated provider symbol mappings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from itertools import groupby


class MappingType(StrEnum):
    FORMATTING_ALIAS = "formatting_alias"
    RENAME = "rename"
    SHARE_CLASS = "share_class"
    MERGER_SUCCESSOR = "merger_successor"
    ACQUISITION_SUCCESSOR = "acquisition_successor"
    PROVIDER_FALLBACK = "provider_fallback"
    UNKNOWN = "unknown"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ResolutionState(StrEnum):
    DIRECT = "direct"
    MAPPED = "mapped"
    QUARANTINED = "quarantined"


def _normalized(value: str, field_name: str) -> str:
    result = value.strip().upper()
    if not result:
        raise ValueError(f"{field_name} cannot be empty")
    return result


@dataclass(frozen=True, slots=True)
class ProviderSymbolMapping:
    """One reviewed or pending provider-symbol mapping interval."""

    security_id: str
    constituent_symbol: str
    provider_id: str
    provider_symbol: str
    exchange_code: str
    effective_from: date
    effective_to: date | None
    mapping_type: MappingType
    reason: str
    evidence_ref: str | None
    approval_status: ApprovalStatus
    reviewer: str | None
    reviewed_at: datetime | None

    def __post_init__(self) -> None:
        for field_name in (
            "security_id",
            "constituent_symbol",
            "provider_id",
            "provider_symbol",
            "exchange_code",
        ):
            object.__setattr__(self, field_name, _normalized(getattr(self, field_name), field_name))

        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        if self.approval_status is ApprovalStatus.APPROVED:
            if self.mapping_type is MappingType.UNKNOWN:
                raise ValueError("unknown mappings cannot be approved")
            if not self.reason.strip() or not (self.evidence_ref or "").strip():
                raise ValueError("approved mappings require reason and evidence_ref")
            if not (self.reviewer or "").strip() or self.reviewed_at is None:
                raise ValueError("approved mappings require reviewer and reviewed_at")
        if self.approval_status is ApprovalStatus.REJECTED:
            if not self.reason.strip() or not (self.reviewer or "").strip():
                raise ValueError("rejected mappings require reason and reviewer")
            if self.reviewed_at is None:
                raise ValueError("rejected mappings require reviewed_at")

    def contains(self, as_of: date) -> bool:
        return self.effective_from <= as_of and (
            self.effective_to is None or as_of <= self.effective_to
        )


@dataclass(frozen=True, slots=True)
class ProviderResolution:
    constituent_symbol: str
    provider_id: str
    as_of: date
    state: ResolutionState
    provider_symbol: str | None
    exchange_code: str | None
    automatic_download_allowed: bool
    mapping: ProviderSymbolMapping | None
    reason: str


@dataclass(frozen=True, slots=True)
class MappingRegistry:
    """Validated collection of non-overlapping provider mappings."""

    mappings: tuple[ProviderSymbolMapping, ...]

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(
                self.mappings,
                key=lambda item: (
                    item.constituent_symbol,
                    item.provider_id,
                    item.effective_from,
                ),
            )
        )
        object.__setattr__(self, "mappings", ordered)

        def key(item: ProviderSymbolMapping) -> tuple[str, str]:
            return (item.constituent_symbol, item.provider_id)

        for mapping_key, items in groupby(ordered, key=key):
            previous: ProviderSymbolMapping | None = None
            for current in items:
                if previous is not None and (
                    previous.effective_to is None or current.effective_from <= previous.effective_to
                ):
                    raise ValueError(
                        f"Overlapping mapping intervals for {mapping_key[0]} at {mapping_key[1]}"
                    )
                previous = current

    def resolve(
        self,
        constituent_symbol: str,
        provider_id: str,
        as_of: date,
    ) -> ProviderResolution:
        symbol = _normalized(constituent_symbol, "constituent_symbol")
        provider = _normalized(provider_id, "provider_id")
        active = next(
            (
                item
                for item in self.mappings
                if item.constituent_symbol == symbol
                and item.provider_id == provider
                and item.contains(as_of)
            ),
            None,
        )

        if active is None:
            return ProviderResolution(
                constituent_symbol=symbol,
                provider_id=provider,
                as_of=as_of,
                state=ResolutionState.DIRECT,
                provider_symbol=symbol,
                exchange_code=None,
                automatic_download_allowed=True,
                mapping=None,
                reason="No mapping required; constituent symbol preserved",
            )

        if active.approval_status is not ApprovalStatus.APPROVED:
            return ProviderResolution(
                constituent_symbol=symbol,
                provider_id=provider,
                as_of=as_of,
                state=ResolutionState.QUARANTINED,
                provider_symbol=None,
                exchange_code=None,
                automatic_download_allowed=False,
                mapping=active,
                reason=f"Mapping is {active.approval_status.value} and cannot be automated",
            )

        return ProviderResolution(
            constituent_symbol=symbol,
            provider_id=provider,
            as_of=as_of,
            state=ResolutionState.MAPPED,
            provider_symbol=active.provider_symbol,
            exchange_code=active.exchange_code,
            automatic_download_allowed=True,
            mapping=active,
            reason=active.reason,
        )


@dataclass(frozen=True, slots=True)
class LegacyMappingIssue:
    source: str
    target: str
    reason: str


@dataclass(frozen=True, slots=True)
class LegacyMigrationResult:
    registry: MappingRegistry
    omitted_identity_count: int
    issues: tuple[LegacyMappingIssue, ...]

    @property
    def imported_count(self) -> int:
        return len(self.registry.mappings)

    @property
    def invalid_count(self) -> int:
        return len(self.issues)


def migrate_legacy_mapping(
    legacy: Mapping[str, str],
    *,
    provider_id: str,
    exchange_code: str,
    effective_from: date,
) -> LegacyMigrationResult:
    """Convert legacy substitutions into quarantined review records.

    This function deliberately makes no identity claims. Non-identity substitutions
    are pending/unknown until a reviewer supplies type, dates, and evidence.
    """
    provider = _normalized(provider_id, "provider_id")
    exchange = _normalized(exchange_code, "exchange_code")
    records: list[ProviderSymbolMapping] = []
    issues: list[LegacyMappingIssue] = []
    omitted_identity_count = 0

    for raw_source, raw_target in legacy.items():
        source = raw_source.strip().upper()
        target = raw_target.strip().upper()
        if not source or not target:
            issues.append(
                LegacyMappingIssue(
                    source=raw_source,
                    target=raw_target,
                    reason="Source and target must both be non-empty",
                )
            )
            continue
        if source == target:
            omitted_identity_count += 1
            continue

        records.append(
            ProviderSymbolMapping(
                security_id=f"LEGACY:{source}",
                constituent_symbol=source,
                provider_id=provider,
                provider_symbol=target,
                exchange_code=exchange,
                effective_from=effective_from,
                effective_to=None,
                mapping_type=MappingType.UNKNOWN,
                reason="Legacy substitution imported pending identity review",
                evidence_ref=None,
                approval_status=ApprovalStatus.PENDING,
                reviewer=None,
                reviewed_at=None,
            )
        )

    return LegacyMigrationResult(
        registry=MappingRegistry(tuple(records)),
        omitted_identity_count=omitted_identity_count,
        issues=tuple(issues),
    )
