from datetime import date
from unittest import TestCase

from quantresearch.research.cross_sectional_momentum import (
    MomentumRebalance,
    simulate_equal_weight_rebalances,
)
from quantresearch.simulation.models import Bar


class CrossSectionalMomentumTests(TestCase):
    def test_rebalance_uses_execution_open_and_charges_turnover_cost(self) -> None:
        bars = (
            Bar("AAA", date(2020, 1, 6), 10, 11, 9, 10, 100),
            Bar("BBB", date(2020, 1, 6), 20, 21, 19, 20, 100),
            Bar("AAA", date(2020, 1, 7), 11, 12, 10, 11, 100),
            Bar("BBB", date(2020, 1, 7), 20, 21, 19, 20, 100),
        )
        result = simulate_equal_weight_rebalances(
            bars,
            (MomentumRebalance(date(2020, 1, 3), date(2020, 1, 6), ("AAA", "BBB")),),
            initial_cash=100_000,
            cost_fraction=0.001,
        )
        self.assertAlmostEqual(result.total_cost, 100.0, places=2)
        self.assertAlmostEqual(result.equity_curve[0].equity, 99_900.0, places=2)
        self.assertGreater(result.equity_curve[-1].equity, result.equity_curve[0].equity)

    def test_execution_membership_removes_ineligible_target(self) -> None:
        bars = (Bar("AAA", date(2020, 1, 6), 10, 10, 10, 10, 100),)
        result = simulate_equal_weight_rebalances(
            bars,
            (MomentumRebalance(date(2020, 1, 3), date(2020, 1, 6), ("AAA",)),),
            initial_cash=100_000,
            cost_fraction=0.001,
            execution_membership={date(2020, 1, 6): frozenset()},
        )
        self.assertEqual(result.holdings, {})
        self.assertEqual(result.total_cost, 0.0)
