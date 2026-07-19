import unittest

from quantresearch.research.models import (
    DataLineage,
    RiskConstraints,
    StrategyDefinition,
    canonical_id,
)


class CanonicalIdTests(unittest.TestCase):
    def test_dictionary_order_does_not_change_id(self) -> None:
        self.assertEqual(canonical_id({"a": 1, "b": 2}), canonical_id({"b": 2, "a": 1}))

    def test_changed_content_changes_id(self) -> None:
        self.assertNotEqual(canonical_id({"a": 1}), canonical_id({"a": 2}))


class StrategyDefinitionTests(unittest.TestCase):
    def test_strategy_id_is_deterministic(self) -> None:
        first = StrategyDefinition(
            name="balanced-dual-st",
            universe={"index_id": "SP500"},
            signal={"momentum": ["5W", "6M", "9M"]},
            ranking={"top_n": 20},
            entry={"breakout_weeks": 7, "supertrend": [5, 2.25]},
            exit={"supertrend": [13, 2.75]},
            sizing={"max_positions": 16},
            risk={"max_drawdown_fraction": 0.40},
        )
        second = StrategyDefinition.from_dict(first.to_dict())
        self.assertEqual(first.strategy_id, second.strategy_id)

    def test_risk_limit_cannot_exceed_forty_percent(self) -> None:
        with self.assertRaisesRegex(ValueError, "40%"):
            RiskConstraints(max_drawdown_fraction=0.41)


class DataLineageTests(unittest.TestCase):
    def test_lineage_requires_nonempty_versions(self) -> None:
        with self.assertRaises(ValueError):
            DataLineage(
                data_version="",
                universe_version="u1",
                mapping_version="m1",
                feature_version="f1",
                code_version="c1",
                dependency_version="d1",
                calendar_version="cal1",
            )


if __name__ == "__main__":
    unittest.main()
