import unittest
from datetime import date, timedelta

from quantresearch.features.moving_averages import (
    MovingAverageConfig,
    compute_moving_average_features,
    moving_average_manifest,
)
from quantresearch.simulation.models import Bar


class MovingAverageFeatureTests(unittest.TestCase):
    def test_sma_ema_wma_vwma_distance_and_slope_are_hand_calculated(self) -> None:
        bars = _bars([1, 2, 3, 4, 5])
        config = MovingAverageConfig("daily", windows=(3,), slope_lookback=1)
        rows = compute_moving_average_features(bars, config)
        last = rows[-1].values
        self.assertAlmostEqual(last["sma_3"], 4.0)
        self.assertAlmostEqual(last["ema_3"], 4.0)
        self.assertAlmostEqual(last["wma_3"], 26 / 6)
        self.assertAlmostEqual(last["vwma_3"], 4.0)
        self.assertAlmostEqual(last["close_distance_sma_3"], 5 / 4 - 1)
        self.assertAlmostEqual(last["sma_3_slope_1"], 4 / 3 - 1)

    def test_hma_four_matches_hand_calculated_linear_series(self) -> None:
        rows = compute_moving_average_features(
            _bars([1, 2, 3, 4, 5, 6]),
            MovingAverageConfig("daily", windows=(4,), slope_lookback=1),
        )
        self.assertAlmostEqual(rows[-1].values["hma_4"], 6.0)

    def test_zero_volume_window_produces_null_vwma(self) -> None:
        bars = _bars([1, 2, 3], volumes=[0, 0, 0])
        rows = compute_moving_average_features(
            bars, MovingAverageConfig("daily", windows=(3,), slope_lookback=1)
        )
        self.assertIsNone(rows[-1].values["vwma_3"])

    def test_insufficient_history_is_null(self) -> None:
        rows = compute_moving_average_features(
            _bars([1, 2]), MovingAverageConfig("weekly", windows=(3,), slope_lookback=1)
        )
        for name in ("sma_3", "ema_3", "wma_3", "hma_3", "vwma_3"):
            self.assertIsNone(rows[-1].values[name])

    def test_future_bar_does_not_change_prior_rows(self) -> None:
        bars = _bars([1, 2, 3, 4, 5, 6])
        config = MovingAverageConfig("daily", windows=(3, 4), slope_lookback=1)
        original = compute_moving_average_features(bars, config)
        future = Bar("AAA", bars[-1].date + timedelta(days=1), 999, 1001, 998, 1000, 100)
        extended = compute_moving_average_features(bars + [future], config)
        self.assertEqual(original, extended[:-1])

    def test_manifest_changes_with_definition(self) -> None:
        first = moving_average_manifest(
            MovingAverageConfig("daily", windows=(5, 10), slope_lookback=2),
            source_data_version="data1",
            code_version="git1",
        )
        second = moving_average_manifest(
            MovingAverageConfig("daily", windows=(5, 20), slope_lookback=2),
            source_data_version="data1",
            code_version="git1",
        )
        self.assertNotEqual(first.feature_version, second.feature_version)


def _bars(prices: list[float], volumes: list[float] | None = None) -> list[Bar]:
    volumes = volumes or [100] * len(prices)
    start = date(2020, 1, 2)
    return [
        Bar("AAA", start + timedelta(days=index), price, price + 1, price - 0.5, price, volume)
        for index, (price, volume) in enumerate(zip(prices, volumes, strict=True))
    ]


if __name__ == "__main__":
    unittest.main()
