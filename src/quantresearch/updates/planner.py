"""Provider-neutral, deterministic missing-range planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class RefreshMode(StrEnum):
    INCREMENTAL = "incremental"
    FULL_REFRESH = "full_refresh"


class PlanState(StrEnum):
    FETCH = "fetch"
    UP_TO_DATE = "up_to_date"
    QUARANTINED = "quarantined"
    NOT_ELIGIBLE = "not_eligible"


def _normalize(value: str, name: str) -> str:
    result = value.strip().upper()
    if not result:
        raise ValueError(f"{name} cannot be empty")
    return result


@dataclass(frozen=True, slots=True)
class UpdateTarget:
    """One approved provider-symbol interval eligible for update planning."""

    security_id: str
    constituent_symbol: str
    provider_id: str
    provider_symbol: str
    exchange_code: str
    eligible_from: date
    eligible_to: date | None
    automatic_download_allowed: bool
    block_reason: str | None

    def __post_init__(self) -> None:
        for field_name in (
            "security_id",
            "constituent_symbol",
            "provider_id",
            "provider_symbol",
            "exchange_code",
        ):
            object.__setattr__(self, field_name, _normalize(getattr(self, field_name), field_name))
        if self.eligible_to is not None and self.eligible_to < self.eligible_from:
            raise ValueError("eligible_to cannot precede eligible_from")
        if not self.automatic_download_allowed and not (self.block_reason or "").strip():
            raise ValueError("blocked update targets require block_reason")

    @property
    def storage_key(self) -> tuple[str, str]:
        return self.provider_id, self.provider_symbol


@dataclass(frozen=True, slots=True)
class SymbolUpdatePlan:
    target: UpdateTarget
    state: PlanState
    mode: RefreshMode
    from_date: date | None
    to_date: date | None
    latest_stored_date: date | None
    reason: str


def plan_updates(
    targets: tuple[UpdateTarget, ...],
    *,
    latest_stored_dates: Mapping[tuple[str, str], date],
    as_of: date,
    research_start: date,
    mode: RefreshMode = RefreshMode.INCREMENTAL,
) -> tuple[SymbolUpdatePlan, ...]:
    """Plan missing date ranges without performing I/O.

    Calendar dates are planning bounds; provider responses determine actual trading
    sessions. Calling this function with unchanged state is deterministic.
    """
    if as_of < research_start:
        raise ValueError("as_of cannot precede research_start")

    normalized_latest = {
        (_normalize(provider, "provider_id"), _normalize(symbol, "provider_symbol")): value
        for (provider, symbol), value in latest_stored_dates.items()
    }
    seen: set[tuple[str, str]] = set()
    plans: list[SymbolUpdatePlan] = []

    for item in sorted(targets, key=lambda target: target.storage_key):
        if item.storage_key in seen:
            raise ValueError(f"Duplicate update target: {item.storage_key}")
        seen.add(item.storage_key)
        latest = normalized_latest.get(item.storage_key)

        if not item.automatic_download_allowed:
            plans.append(
                SymbolUpdatePlan(
                    target=item,
                    state=PlanState.QUARANTINED,
                    mode=mode,
                    from_date=None,
                    to_date=None,
                    latest_stored_date=latest,
                    reason=item.block_reason or "Target is not approved for download",
                )
            )
            continue

        lower_bound = max(research_start, item.eligible_from)
        upper_bound = min(as_of, item.eligible_to) if item.eligible_to else as_of
        if lower_bound > upper_bound:
            plans.append(
                SymbolUpdatePlan(
                    target=item,
                    state=PlanState.NOT_ELIGIBLE,
                    mode=mode,
                    from_date=None,
                    to_date=None,
                    latest_stored_date=latest,
                    reason="Target has no eligible dates inside the requested range",
                )
            )
            continue

        if mode is RefreshMode.FULL_REFRESH or latest is None:
            from_date = lower_bound
        else:
            from_date = max(lower_bound, latest + timedelta(days=1))

        if from_date > upper_bound:
            plans.append(
                SymbolUpdatePlan(
                    target=item,
                    state=PlanState.UP_TO_DATE,
                    mode=mode,
                    from_date=None,
                    to_date=None,
                    latest_stored_date=latest,
                    reason="No missing calendar range through requested as-of date",
                )
            )
            continue

        plans.append(
            SymbolUpdatePlan(
                target=item,
                state=PlanState.FETCH,
                mode=mode,
                from_date=from_date,
                to_date=upper_bound,
                latest_stored_date=latest,
                reason="Missing date range requires provider fetch",
            )
        )

    return tuple(plans)
