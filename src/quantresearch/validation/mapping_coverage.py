"""Point-in-time data coverage under a review-gated mapping registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from quantresearch.domain.exclusions import ExclusionRegistry
from quantresearch.domain.mappings import MappingRegistry
from quantresearch.domain.membership import MembershipSnapshot
from quantresearch.walkforward.models import WalkForwardWindow


@dataclass(frozen=True, slots=True)
class CoverageSummary:
    snapshot_count: int
    required_symbols: int
    covered_symbols: int
    mean_coverage: float
    minimum_coverage: float
    excluded_symbols: int
    eligible_symbols: int
    eligible_covered_symbols: int
    eligible_coverage: float


@dataclass(frozen=True, slots=True)
class FoldCoverage:
    fold_id: str
    train: CoverageSummary
    forward: CoverageSummary


def symbol_is_covered(
    symbol: str,
    *,
    as_of: date,
    available_symbols: frozenset[str],
    registry: MappingRegistry,
    provider_id: str,
) -> bool:
    resolution = registry.resolve(symbol, provider_id, as_of)
    return bool(
        resolution.automatic_download_allowed
        and resolution.provider_symbol in available_symbols
    )


def summarize_coverage(
    snapshots: tuple[MembershipSnapshot, ...],
    *,
    available_symbols: frozenset[str],
    registry: MappingRegistry,
    provider_id: str,
    exclusions: ExclusionRegistry | None = None,
) -> CoverageSummary:
    if not snapshots:
        return CoverageSummary(0, 0, 0, 0.0, 0.0, 0, 0, 0, 0.0)
    ratios: list[float] = []
    required = 0
    covered = 0
    excluded = 0
    eligible = 0
    eligible_covered = 0
    for snapshot in snapshots:
        snapshot_covered = sum(
            symbol_is_covered(
                symbol,
                as_of=snapshot.effective_date,
                available_symbols=available_symbols,
                registry=registry,
                provider_id=provider_id,
            )
            for symbol in snapshot.symbols
        )
        required += len(snapshot.symbols)
        covered += snapshot_covered
        ratios.append(snapshot_covered / len(snapshot.symbols))
        excluded_symbols = {
            symbol
            for symbol in snapshot.symbols
            if (
            exclusions is not None
            and exclusions.is_excluded(
                snapshot.index_id, symbol, snapshot.effective_date
            )
            )
        }
        snapshot_excluded = len(excluded_symbols)
        excluded += snapshot_excluded
        eligible += len(snapshot.symbols) - snapshot_excluded
        eligible_covered += sum(
            symbol not in excluded_symbols
            and symbol_is_covered(
                symbol,
                as_of=snapshot.effective_date,
                available_symbols=available_symbols,
                registry=registry,
                provider_id=provider_id,
            )
            for symbol in snapshot.symbols
        )
    return CoverageSummary(
        snapshot_count=len(snapshots),
        required_symbols=required,
        covered_symbols=covered,
        mean_coverage=sum(ratios) / len(ratios),
        minimum_coverage=min(ratios),
        excluded_symbols=excluded,
        eligible_symbols=eligible,
        eligible_covered_symbols=eligible_covered,
        eligible_coverage=eligible_covered / eligible if eligible else 0.0,
    )


def calculate_fold_coverage(
    snapshots: tuple[MembershipSnapshot, ...],
    windows: tuple[WalkForwardWindow, ...],
    *,
    available_symbols: frozenset[str],
    registry: MappingRegistry,
    provider_id: str,
    exclusions: ExclusionRegistry | None = None,
) -> tuple[FoldCoverage, ...]:
    results: list[FoldCoverage] = []
    for index, window in enumerate(windows, start=1):
        train = tuple(
            item
            for item in snapshots
            if window.train_start <= item.effective_date <= window.train_end
        )
        forward = tuple(
            item
            for item in snapshots
            if window.forward_start <= item.effective_date <= window.forward_end
        )
        results.append(
            FoldCoverage(
                fold_id=f"fold_{index:02d}",
                train=summarize_coverage(
                    train,
                    available_symbols=available_symbols,
                    registry=registry,
                    provider_id=provider_id,
                    exclusions=exclusions,
                ),
                forward=summarize_coverage(
                    forward,
                    available_symbols=available_symbols,
                    registry=registry,
                    provider_id=provider_id,
                    exclusions=exclusions,
                ),
            )
        )
    return tuple(results)
