import unittest
from datetime import date

from quantresearch.simulation.brackets import BracketExitReason, resolve_long_bracket
from quantresearch.simulation.models import Bar
from quantresearch.strategies.supply_demand import (
    SupplyDemandParameters,
    daily_supply_demand,
    supply_demand_parameter_space,
    supply_demand_search_plan,
)


class SupplyDemandStrategyTests(unittest.TestCase):
    def test_medium_control_is_point_in_time_long_only_and_auditable(self) -> None:
        strategy = daily_supply_demand("SP500")

        self.assertEqual(strategy.universe["membership"], "point_in_time")
        self.assertTrue(strategy.universe["require_membership_on_signal_date"])
        self.assertTrue(strategy.universe["require_membership_on_execution_date"])
        self.assertEqual(strategy.signal["feature_version"], "daily_three_candle_v1")
        self.assertEqual(strategy.signal["side"], "demand_long_only")
        self.assertEqual(strategy.signal["previous_range_ratio"], 2.0)
        self.assertEqual(strategy.signal["departure_range_ratio"], 3.0)
        self.assertEqual(strategy.entry["revisit"], "first_future_revisit")
        self.assertEqual(strategy.exit["same_bar_priority"], "stop_first")
        self.assertFalse(strategy.signal["shorting_enabled"])
        self.assertEqual(strategy.risk["max_drawdown_fraction"], 0.40)

    def test_parameter_change_changes_content_addressed_strategy_id(self) -> None:
        control = daily_supply_demand("SP500")
        variant = daily_supply_demand(
            "SP500", SupplyDemandParameters(departure_range_ratio=4.0)
        )
        self.assertNotEqual(control.strategy_id, variant.strategy_id)

    def test_invalid_parameter_combinations_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "base_atr_ratio"):
            SupplyDemandParameters(base_atr_ratio=0)
        with self.assertRaisesRegex(ValueError, "entry_type"):
            SupplyDemandParameters(entry_type="future_low")
        with self.assertRaisesRegex(ValueError, "maximum_retests"):
            SupplyDemandParameters(maximum_retests=-1)

    def test_search_space_is_declared_bounded_and_not_a_final_selection(self) -> None:
        space = supply_demand_parameter_space()
        self.assertEqual(space["previous_range_ratio"], (1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0))
        self.assertIn(5.0, space["departure_range_ratio"])
        self.assertEqual(space["trend_filter"], ("none", "ema50", "ema200"))
        self.assertEqual(space["entry_type"], ("zone_edge", "midpoint", "confirmation_close"))

        plan = supply_demand_search_plan("exp-sd-1", budget=5_000)
        self.assertEqual(plan.budget, 5_000)
        self.assertEqual(plan.constraints.maximum_drawdown_fraction, 0.40)
        self.assertGreater(
            _grid_size(plan.parameters),
            plan.budget,
            "The fixed budget must bound the declared parameter grid",
        )

    def test_search_plan_is_reproducible(self) -> None:
        first = supply_demand_search_plan("exp-sd-1", budget=5_000)
        second = supply_demand_search_plan("exp-sd-1", budget=5_000)
        self.assertEqual(first.search_plan_id, second.search_plan_id)


class ConservativeBracketTests(unittest.TestCase):
    def test_same_bar_stop_and_target_resolves_stop_first(self) -> None:
        result = resolve_long_bracket(_bar(100, 111, 94, 105), stop_price=95, target_price=110)
        self.assertEqual(result.reason, BracketExitReason.STOP)
        self.assertEqual(result.fill_price, 95)
        self.assertTrue(result.ambiguous_same_bar)

    def test_gap_through_stop_fills_at_open_not_stop(self) -> None:
        result = resolve_long_bracket(_bar(90, 94, 88, 92), stop_price=95, target_price=110)
        self.assertEqual(result.reason, BracketExitReason.STOP)
        self.assertEqual(result.fill_price, 90)

    def test_gap_above_target_fills_at_open(self) -> None:
        result = resolve_long_bracket(_bar(112, 115, 111, 114), stop_price=95, target_price=110)
        self.assertEqual(result.reason, BracketExitReason.TARGET)
        self.assertEqual(result.fill_price, 112)

    def test_unreached_bracket_remains_open(self) -> None:
        result = resolve_long_bracket(_bar(100, 105, 98, 102), stop_price=95, target_price=110)
        self.assertEqual(result.reason, BracketExitReason.OPEN)
        self.assertIsNone(result.fill_price)


def _bar(open_: float, high: float, low: float, close: float) -> Bar:
    return Bar("AAA", date(2026, 1, 2), open_, high, low, close, 1_000)


def _grid_size(parameters: dict[str, tuple[object, ...]]) -> int:
    size = 1
    for values in parameters.values():
        size *= len(values)
    return size


if __name__ == "__main__":
    unittest.main()
