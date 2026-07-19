import unittest
from datetime import date, timedelta

from quantresearch.features.supertrend import (
    SupertrendConfig,
    compute_supertrend_features,
    supertrend_manifest,
)
from quantresearch.simulation.models import Bar


class SupertrendFeatureTests(unittest.TestCase):
    def test_declared_grid_contains_standard_and_reference_pairs(self) -> None:
        config = SupertrendConfig()
        pairs = config.pairs()
        self.assertEqual(len(pairs), 46)
        self.assertIn((5, 1.5), pairs)
        self.assertIn((52, 4.0), pairs)
        self.assertIn((5, 2.25), pairs)
        self.assertIn((13, 2.75), pairs)
        self.assertIn((7, 4.78), pairs)
        self.assertIn((52, 4.88), pairs)

    def test_wilder_bands_direction_and_flip_are_hand_calculated(self) -> None:
        bars = [
            Bar("AAA", date(2020, 1, 3), 10, 11, 9, 10, 100),
            Bar("AAA", date(2020, 1, 10), 10, 11, 9, 10, 100),
            Bar("AAA", date(2020, 1, 17), 14, 15, 13, 14, 100),
            Bar("AAA", date(2020, 1, 24), 11, 12, 10, 11, 100),
        ]
        rows = compute_supertrend_features(
            bars,
            SupertrendConfig(periods=(2,), multipliers=(1.0,), reference_pairs=()),
        )
        self.assertIsNone(rows[0].values["supertrend_2_1"])
        self.assertEqual(rows[1].values["supertrend_upper_2_1"], 12)
        self.assertEqual(rows[1].values["supertrend_lower_2_1"], 8)
        self.assertEqual(rows[1].values["supertrend_2_1"], 12)
        self.assertFalse(rows[1].values["supertrend_green_2_1"])
        self.assertEqual(rows[2].values["supertrend_2_1"], 10.5)
        self.assertTrue(rows[2].values["supertrend_green_2_1"])
        self.assertTrue(rows[2].values["supertrend_flip_2_1"])
        self.assertFalse(rows[3].values["supertrend_flip_2_1"])

    def test_ticker_isolation_and_future_data_cannot_revise_history(self) -> None:
        bars = _bars("AAA", [10, 10, 12, 13])
        config = SupertrendConfig(periods=(2,), multipliers=(1.0,), reference_pairs=())
        original = compute_supertrend_features(bars, config)
        extended = compute_supertrend_features(
            bars
            + [
                Bar("AAA", date(2020, 2, 1), 100, 110, 90, 100, 1_000),
                Bar("BBB", date(2020, 1, 3), 20, 21, 19, 20, 1_000),
            ],
            config,
        )
        self.assertEqual(original, [row for row in extended if row.ticker == "AAA"][:-1])

    def test_duplicate_ticker_date_is_rejected(self) -> None:
        bar = Bar("AAA", date(2020, 1, 3), 10, 11, 9, 10, 100)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            compute_supertrend_features([bar, bar])

    def test_manifest_records_complete_grid_and_wilder_formula(self) -> None:
        config = SupertrendConfig()
        manifest = supertrend_manifest(
            config,
            frequency="weekly",
            source_data_version="data1",
            code_version="git1",
        )
        self.assertEqual(manifest.definitions["atr_method"], "wilder_rma")
        self.assertEqual(manifest.definitions["pair_count"], 46)
        self.assertEqual(manifest.definitions["reference_pairs"][-1], [52, 4.88])

    def test_config_rejects_duplicate_or_nonpositive_values(self) -> None:
        with self.assertRaises(ValueError):
            SupertrendConfig(periods=(5, 5))
        with self.assertRaises(ValueError):
            SupertrendConfig(multipliers=(0,))


def _bars(ticker: str, closes: list[float]) -> list[Bar]:
    start = date(2020, 1, 3)
    return [
        Bar(
            ticker,
            start + timedelta(days=7 * index),
            close,
            close + 1,
            close - 1,
            close,
            100,
        )
        for index, close in enumerate(closes)
    ]


if __name__ == "__main__":
    unittest.main()
