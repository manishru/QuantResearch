"""Convert causal demand-zone revisits into immutable trade plans."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from quantresearch.features.models import FeatureRow
from quantresearch.research.models import canonical_id
from quantresearch.simulation.models import Bar
from quantresearch.strategies.supply_demand import SupplyDemandParameters


class DemandEntryType(StrEnum):
    LIMIT = "limit"
    NEXT_OPEN_MARKET = "next_open_market"


class _UntradableDemandPlan(ValueError):
    """A valid signal whose observed prices cannot form a positive-risk bracket."""


@dataclass(frozen=True, slots=True)
class DemandTradePlan:
    ticker: str
    decision_date: date
    available_after: date
    zone_base_date: date
    zone_lower: float
    zone_upper: float
    atr: float
    retest_number: int
    entry_type: DemandEntryType
    entry_price: float
    stop_price: float
    target_price: float
    risk_reward: float
    ranking_score: float
    reason: str = "causal_demand_zone_revisit"
    plan_id: str = field(init=False)

    def __post_init__(self) -> None:
        content = {
            "ticker": self.ticker,
            "decision_date": self.decision_date.isoformat(),
            "available_after": self.available_after.isoformat(),
            "zone_base_date": self.zone_base_date.isoformat(),
            "zone_lower": self.zone_lower,
            "zone_upper": self.zone_upper,
            "atr": self.atr,
            "retest_number": self.retest_number,
            "entry_type": self.entry_type.value,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "risk_reward": self.risk_reward,
            "ranking_score": self.ranking_score,
            "reason": self.reason,
        }
        object.__setattr__(self, "plan_id", canonical_id(content, "sdplan_"))


def build_demand_trade_plans(
    features: Iterable[FeatureRow],
    bars: Iterable[Bar],
    parameters: SupplyDemandParameters,
) -> tuple[DemandTradePlan, ...]:
    """Build plans from available demand revisits; supply signals remain observational."""
    bar_by_key = {(item.ticker, item.date): item for item in bars}
    plans: list[DemandTradePlan] = []
    seen: set[tuple[str, date]] = set()
    for row in sorted(features, key=lambda item: (item.date, item.ticker)):
        key = (row.ticker, row.date)
        if key in seen:
            raise ValueError("Duplicate feature ticker-date is not allowed")
        seen.add(key)
        if not bool(row.values.get("demand_revisited")):
            continue
        if row.available_after > row.date:
            continue
        bar = bar_by_key.get(key)
        if bar is None:
            raise ValueError(f"Demand revisit requires a matching bar: {key}")
        retest_number = _positive_integer(row.values, "demand_retest_count")
        if retest_number > parameters.maximum_retests + 1:
            continue
        try:
            plans.append(_build_plan(row, bar, parameters))
        except _UntradableDemandPlan:
            continue
    return tuple(plans)


def _build_plan(
    row: FeatureRow,
    bar: Bar,
    parameters: SupplyDemandParameters,
) -> DemandTradePlan:
    values = row.values
    lower = _positive_number(values, "demand_lower")
    upper = _positive_number(values, "demand_upper")
    atr = _positive_number(values, "atr", label="ATR")
    retest_number = _positive_integer(values, "demand_retest_count")
    if lower >= upper:
        raise ValueError("Demand zone lower must be below upper")

    if parameters.entry_type == "zone_edge":
        entry_type = DemandEntryType.LIMIT
        entry_price = upper
    elif parameters.entry_type == "midpoint":
        entry_type = DemandEntryType.LIMIT
        entry_price = (lower + upper) / 2
    else:
        entry_type = DemandEntryType.NEXT_OPEN_MARKET
        entry_price = bar.close

    stop_price = lower - parameters.stop_atr_buffer * atr
    if stop_price <= 0 or entry_price <= stop_price:
        raise _UntradableDemandPlan(
            "Demand entry and ATR stop produce invalid positive risk"
        )
    target_price = entry_price + parameters.risk_reward * (entry_price - stop_price)
    base_date_value = values.get("demand_base_date")
    if not isinstance(base_date_value, str):
        raise ValueError("demand_base_date must be an ISO date")
    try:
        base_date = date.fromisoformat(base_date_value)
    except ValueError as error:
        raise ValueError("demand_base_date must be an ISO date") from error

    zone_width_atr = (upper - lower) / atr
    ranking_score = 1 / zone_width_atr
    return DemandTradePlan(
        ticker=row.ticker,
        decision_date=row.date,
        available_after=row.available_after,
        zone_base_date=base_date,
        zone_lower=lower,
        zone_upper=upper,
        atr=atr,
        retest_number=retest_number,
        entry_type=entry_type,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        risk_reward=parameters.risk_reward,
        ranking_score=ranking_score,
    )


def _positive_number(
    values: Mapping[str, object], key: str, *, label: str | None = None
) -> float:
    value = values.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label or key} must be a positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{label or key} must be a positive number")
    return result


def _positive_integer(values: Mapping[str, object], key: str) -> int:
    value = _positive_number(values, key)
    if not value.is_integer():
        raise ValueError(f"{key} must be a positive integer")
    return int(value)
