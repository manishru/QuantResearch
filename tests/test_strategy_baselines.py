import unittest

from quantresearch.strategies.baselines import (
    balanced_dual_supertrend,
    buy_and_hold,
    contaminated_52w_momentum_benchmark,
)


class StrategyBaselineTests(unittest.TestCase):
    def test_balanced_dual_supertrend_matches_research_definition(self) -> None:
        strategy = balanced_dual_supertrend("SP500")
        self.assertEqual(strategy.signal["momentum_order"], ["5W", "6M", "9M"])
        self.assertEqual(strategy.ranking["candidate_pool"], 20)
        self.assertEqual(strategy.entry["breakout_weeks"], 7)
        self.assertEqual(strategy.entry["supertrend"], [5, 2.25])
        self.assertEqual(strategy.exit["supertrend"], [13, 2.75])
        self.assertEqual(strategy.sizing["max_positions"], 16)
        self.assertEqual(strategy.risk["max_drawdown_fraction"], 0.40)

    def test_baseline_ids_change_with_index(self) -> None:
        self.assertNotEqual(buy_and_hold("SP500").strategy_id, buy_and_hold("KOSPI200").strategy_id)

    def test_contaminated_benchmark_is_never_deployable(self) -> None:
        benchmark = contaminated_52w_momentum_benchmark("SP500")
        self.assertEqual(benchmark.risk["deployment_status"], "rejected_data_contamination")


if __name__ == "__main__":
    unittest.main()
