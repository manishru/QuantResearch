import unittest
from datetime import date, timedelta

from quantresearch.features.directional_movement import (
    DirectionalMovementConfig,
    compute_directional_movement_features,
    directional_movement_manifest,
)
from quantresearch.simulation.models import Bar


class DirectionalMovementFeatureTests(unittest.TestCase):
    def test_dm_di_dx_and_adx_are_hand_calculated(self) -> None:
        bars = [
            Bar("AAA", date(2020, 1, 2), 9, 10, 8, 9, 100),
            Bar("AAA", date(2020, 1, 3), 10, 12, 9, 11, 100),
            Bar("AAA", date(2020, 1, 4), 9, 11, 7, 8, 100),
            Bar("AAA", date(2020, 1, 5), 9, 13, 8, 12, 100),
        ]
        rows = compute_directional_movement_features(bars, DirectionalMovementConfig(periods=(2,)))
        self.assertEqual(rows[1].values["plus_dm"], 2)
        self.assertEqual(rows[2].values["minus_dm"], 2)
        self.assertAlmostEqual(rows[1].values["plus_di_2"], 40)
        self.assertAlmostEqual(rows[1].values["minus_di_2"], 0)
        self.assertAlmostEqual(rows[1].values["dx_2"], 100)
        self.assertAlmostEqual(rows[2].values["plus_di_2"], 100 / 6.5)
        self.assertAlmostEqual(rows[2].values["minus_di_2"], 200 / 6.5)
        self.assertAlmostEqual(rows[2].values["adx_2"], (100 + 100 / 3) / 2)
        expected_last_dx = 100 * ((2.5 / 8.25) - (1 / 8.25)) / ((2.5 / 8.25) + (1 / 8.25))
        expected_last_adx = (((100 + 100 / 3) / 2) + expected_last_dx) / 2
        self.assertAlmostEqual(rows[3].values["adx_2"], expected_last_adx)

    def test_equal_up_and_down_moves_are_both_zero(self) -> None:
        bars = [
            Bar("AAA", date(2020, 1, 2), 9, 10, 8, 9, 100),
            Bar("AAA", date(2020, 1, 3), 9, 11, 7, 9, 100),
        ]
        rows = compute_directional_movement_features(bars, DirectionalMovementConfig(periods=(2,)))
        self.assertEqual(rows[1].values["plus_dm"], 0)
        self.assertEqual(rows[1].values["minus_dm"], 0)

    def test_future_and_other_ticker_do_not_change_history(self) -> None:
        bars = _bars("AAA", [10, 11, 12, 11, 13])
        config = DirectionalMovementConfig(periods=(2, 3))
        original = compute_directional_movement_features(bars, config)
        extended = compute_directional_movement_features(
            bars
            + [
                Bar("AAA", date(2020, 2, 1), 100, 110, 90, 100, 1_000),
                Bar("BBB", date(2020, 1, 2), 20, 21, 19, 20, 1_000),
            ],
            config,
        )
        self.assertEqual(original, [row for row in extended if row.ticker == "AAA"][:-1])

    def test_manifest_and_default_grid(self) -> None:
        config = DirectionalMovementConfig()
        self.assertEqual(config.periods, (7, 10, 14, 20))
        manifest = directional_movement_manifest(
            config,
            frequency="daily",
            source_data_version="data1",
            code_version="git1",
        )
        self.assertEqual(manifest.definitions["smoothing"], "wilder")
        self.assertEqual(manifest.definitions["periods"], [7, 10, 14, 20])

    def test_config_and_duplicate_validation(self) -> None:
        with self.assertRaises(ValueError):
            DirectionalMovementConfig(periods=(14, 14))
        bar = _bars("AAA", [10])[0]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            compute_directional_movement_features([bar, bar])


def _bars(ticker: str, closes: list[float]) -> list[Bar]:
    start = date(2020, 1, 2)
    return [
        Bar(
            ticker,
            start + timedelta(days=index),
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
