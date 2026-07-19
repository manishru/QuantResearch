"""Declarative daily supply/demand research controls and bounded search plans."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from quantresearch.research.models import StrategyDefinition
from quantresearch.search.models import HardConstraints, SearchPlan

_ENTRY_TYPES = {"zone_edge", "midpoint", "confirmation_close"}
_TREND_FILTERS = {"none", "ema50", "ema200"}


@dataclass(frozen=True, slots=True)
class SupplyDemandParameters:
    """Parameters for the daily medium 1:2:3 demand research control."""

    previous_range_ratio: float = 2.0
    departure_range_ratio: float = 3.0
    base_atr_ratio: float = 0.50
    departure_body_ratio: float = 0.60
    volume_multiplier: float = 1.25
    volume_period: int = 20
    atr_period: int = 14
    stop_atr_buffer: float = 0.25
    risk_reward: float = 3.0
    maximum_retests: int = 0
    entry_expiry_days: int = 60
    trend_filter: str = "none"
    structure_lookback: int = 20
    entry_type: str = "zone_edge"

    def __post_init__(self) -> None:
        positive = {
            "previous_range_ratio": self.previous_range_ratio,
            "departure_range_ratio": self.departure_range_ratio,
            "base_atr_ratio": self.base_atr_ratio,
            "departure_body_ratio": self.departure_body_ratio,
            "volume_multiplier": self.volume_multiplier,
            "risk_reward": self.risk_reward,
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if not math.isfinite(self.stop_atr_buffer) or self.stop_atr_buffer < 0:
            raise ValueError("stop_atr_buffer must be finite and nonnegative")
        if not 0 < self.departure_body_ratio <= 1:
            raise ValueError("departure_body_ratio must be in (0, 1]")
        periods = (
            self.volume_period,
            self.atr_period,
            self.entry_expiry_days,
            self.structure_lookback,
        )
        if min(periods) < 1:
            raise ValueError("Periods, expiry, and structure lookback must be positive")
        if self.maximum_retests < 0:
            raise ValueError("maximum_retests must be nonnegative")
        if self.entry_type not in _ENTRY_TYPES:
            raise ValueError(f"entry_type must be one of {sorted(_ENTRY_TYPES)}")
        if self.trend_filter not in _TREND_FILTERS:
            raise ValueError(f"trend_filter must be one of {sorted(_TREND_FILTERS)}")


def daily_supply_demand(
    index_id: str,
    parameters: SupplyDemandParameters | None = None,
) -> StrategyDefinition:
    """Return an immutable long-only daily supply/demand strategy definition."""
    if not index_id.strip():
        raise ValueError("index_id cannot be empty")
    values = parameters or SupplyDemandParameters()
    payload = asdict(values)
    return StrategyDefinition(
        name="daily-supply-demand-medium-v1",
        universe={
            "index_id": index_id,
            "membership": "point_in_time",
            "require_membership_on_signal_date": True,
            "require_membership_on_execution_date": True,
        },
        signal={
            "feature_version": "daily_three_candle_v1",
            "side": "demand_long_only",
            "shorting_enabled": False,
            **{
                key: payload[key]
                for key in (
                    "previous_range_ratio",
                    "departure_range_ratio",
                    "base_atr_ratio",
                    "departure_body_ratio",
                    "volume_multiplier",
                    "volume_period",
                    "atr_period",
                    "trend_filter",
                    "structure_lookback",
                )
            },
        },
        ranking={
            "type": "zone_quality_v1",
            "descending": True,
            "ties": "ticker_ascending",
            "inputs": [
                "freshness",
                "departure_strength",
                "volume_confirmation",
                "structure_break",
                "trend_alignment",
            ],
        },
        entry={
            "revisit": "first_future_revisit",
            "maximum_retests": values.maximum_retests,
            "expiry_trading_days": values.entry_expiry_days,
            "type": values.entry_type,
            "timing": "next_eligible_session",
        },
        exit={
            "stop": "demand_distal_minus_atr_buffer",
            "stop_atr_buffer": values.stop_atr_buffer,
            "target": "risk_multiple",
            "risk_reward": values.risk_reward,
            "same_bar_priority": "stop_first",
            "gap_policy": "fill_at_observed_open",
        },
        sizing={
            "type": "fixed_fractional_risk",
            "maximum_position_weight": 0.10,
            "max_positions": 10,
        },
        risk={"max_drawdown_fraction": 0.40},
    )


def supply_demand_parameter_space() -> dict[str, tuple[object, ...]]:
    """Return the complete predeclared, finite research space."""
    return {
        "previous_range_ratio": (1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0),
        "departure_range_ratio": (1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0),
        "base_atr_ratio": (0.35, 0.45, 0.55, 0.65, 0.75),
        "departure_body_ratio": (0.50, 0.60, 0.70, 0.80),
        "volume_multiplier": (0.8, 1.0, 1.2, 1.5, 2.0),
        "volume_period": (10, 20, 30, 50),
        "atr_period": (10, 14, 20),
        "stop_atr_buffer": (0.0, 0.1, 0.25, 0.5),
        "risk_reward": (1.5, 2.0, 2.5, 3.0, 4.0, 5.0),
        "maximum_retests": (0, 1),
        "entry_expiry_days": (20, 40, 60, 90),
        "trend_filter": ("none", "ema50", "ema200"),
        "structure_lookback": (5, 10, 20, 50),
        "entry_type": ("zone_edge", "midpoint", "confirmation_close"),
    }


def supply_demand_search_plan(experiment_id: str, *, budget: int = 5_000) -> SearchPlan:
    """Create a fixed-budget plan; this registers candidates but selects none."""
    return SearchPlan(
        experiment_id=experiment_id,
        parameters=supply_demand_parameter_space(),
        budget=budget,
        constraints=HardConstraints(
            maximum_drawdown_fraction=0.40,
            minimum_average_entries_per_year=20.0,
            minimum_entries_each_year=12,
            maximum_position_weight=0.10,
            allow_anomalies=False,
        ),
        score_weights={
            "cagr": 0.25,
            "average_yearly_return": 0.20,
            "sharpe": 0.30,
            "drawdown": 0.25,
        },
    )
