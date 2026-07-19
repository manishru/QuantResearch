"""Point-in-time index membership domain models."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MembershipSnapshot:
    """Complete membership of one index effective on one date."""

    index_id: str
    effective_date: date
    symbols: frozenset[str]
    source_row: int

    def __post_init__(self) -> None:
        if not self.index_id.strip():
            raise ValueError("index_id cannot be empty")
        if not self.symbols:
            raise ValueError("snapshot membership cannot be empty")
        if any(not symbol or symbol != symbol.strip().upper() for symbol in self.symbols):
            raise ValueError("snapshot symbols must be non-empty normalized uppercase values")
        if self.source_row < 2:
            raise ValueError("source_row must include the CSV header offset")


@dataclass(frozen=True, slots=True)
class MembershipInterval:
    """Inclusive membership interval for a constituent symbol."""

    index_id: str
    constituent_symbol: str
    effective_from: date
    effective_to: date | None
    source_snapshot_date: date

    def contains(self, as_of: date) -> bool:
        return self.effective_from <= as_of and (
            self.effective_to is None or as_of <= self.effective_to
        )


@dataclass(frozen=True, slots=True)
class UniverseResult:
    """Point-in-time universe and the snapshot on which it is based."""

    index_id: str
    as_of: date
    symbols: frozenset[str]
    source_snapshot_date: date
    carried_forward: bool


@dataclass(frozen=True, slots=True)
class MembershipHistory:
    """Validated complete-snapshot history for one index."""

    index_id: str
    snapshots: tuple[MembershipSnapshot, ...]
    source_path: Path
    source_sha256: str
    _dates: tuple[date, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.index_id.strip():
            raise ValueError("index_id cannot be empty")
        if not self.snapshots:
            raise ValueError("membership history cannot be empty")
        if len(self.source_sha256) != 64:
            raise ValueError("source_sha256 must be a 64-character SHA-256 digest")

        dates = tuple(snapshot.effective_date for snapshot in self.snapshots)
        if any(snapshot.index_id != self.index_id for snapshot in self.snapshots):
            raise ValueError("all snapshots must belong to the history index_id")
        if any(current <= previous for previous, current in zip(dates, dates[1:], strict=False)):
            raise ValueError("snapshot effective dates must be strictly increasing")
        object.__setattr__(self, "_dates", dates)

    @property
    def first_snapshot_date(self) -> date:
        return self._dates[0]

    @property
    def last_snapshot_date(self) -> date:
        return self._dates[-1]

    def as_of(self, as_of: date) -> UniverseResult:
        """Return membership from the latest snapshot effective by ``as_of``."""
        position = bisect_right(self._dates, as_of) - 1
        if position < 0:
            raise LookupError(
                f"No {self.index_id} membership snapshot is available on or before {as_of}"
            )
        snapshot = self.snapshots[position]
        return UniverseResult(
            index_id=self.index_id,
            as_of=as_of,
            symbols=snapshot.symbols,
            source_snapshot_date=snapshot.effective_date,
            carried_forward=as_of > snapshot.effective_date,
        )

    def acquisition_union(self) -> frozenset[str]:
        """Return every constituent symbol seen in any snapshot."""
        return frozenset().union(*(snapshot.symbols for snapshot in self.snapshots))

    def intervals(self) -> tuple[MembershipInterval, ...]:
        """Derive compact, non-overlapping intervals including re-entries."""
        active: dict[str, tuple[date, date]] = {}
        completed: list[MembershipInterval] = []
        previous_symbols: frozenset[str] = frozenset()

        for snapshot in self.snapshots:
            added = snapshot.symbols - previous_symbols
            removed = previous_symbols - snapshot.symbols

            for symbol in sorted(removed):
                effective_from, source_snapshot_date = active.pop(symbol)
                completed.append(
                    MembershipInterval(
                        index_id=self.index_id,
                        constituent_symbol=symbol,
                        effective_from=effective_from,
                        effective_to=snapshot.effective_date - timedelta(days=1),
                        source_snapshot_date=source_snapshot_date,
                    )
                )

            for symbol in added:
                active[symbol] = (snapshot.effective_date, snapshot.effective_date)

            previous_symbols = snapshot.symbols

        for symbol, (effective_from, source_snapshot_date) in active.items():
            completed.append(
                MembershipInterval(
                    index_id=self.index_id,
                    constituent_symbol=symbol,
                    effective_from=effective_from,
                    effective_to=None,
                    source_snapshot_date=source_snapshot_date,
                )
            )

        return tuple(
            sorted(
                completed,
                key=lambda item: (item.constituent_symbol, item.effective_from),
            )
        )
