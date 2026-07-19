"""Declarative strategy catalog."""

from quantresearch.strategies.baselines import balanced_dual_supertrend, buy_and_hold
from quantresearch.strategies.supply_demand import (
    SupplyDemandParameters,
    daily_supply_demand,
    supply_demand_parameter_space,
    supply_demand_search_plan,
)
from quantresearch.strategies.supply_demand_signals import (
    DemandEntryType,
    DemandTradePlan,
    build_demand_trade_plans,
)

__all__ = [
    "SupplyDemandParameters",
    "DemandEntryType",
    "DemandTradePlan",
    "balanced_dual_supertrend",
    "buy_and_hold",
    "build_demand_trade_plans",
    "daily_supply_demand",
    "supply_demand_parameter_space",
    "supply_demand_search_plan",
]
