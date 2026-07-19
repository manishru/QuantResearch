import math
import unittest
from datetime import date, timedelta

from quantresearch.features.volatility import (
    VolatilityConfig,
    compute_volatility_features,
    volatility_manifest,
)
from quantresearch.simulation.models import Bar


class VolatilityFeatureTests(unittest.TestCase):
    def test_true_range_includes_previous_close_gaps(self) -> None:
        bars = [
            Bar("AAA", date(2020, 1, 2), 9, 10, 8, 9, 100),
            Bar("AAA", date(2020, 1, 3), 12, 12, 11, 11.5, 100),
            Bar("AAA", date(2020, 1, 4), 10, 11, 9.5, 10, 100),
        ]
        rows = compute_volatility_features(bars, _config())
        self.assertEqual([row.values["true_range"] for row in rows], [2, 3, 2])

    def test_wilder_atr_seeds_with_mean_then_smooths(self) -> None:
        bars = _bars_from_ranges([2, 3, 4, 8])
        rows = compute_volatility_features(bars, _config())
        self.assertIsNone(rows[1].values["atr_3"])
        self.assertAlmostEqual(rows[2].values["atr_3"], 3)
        self.assertAlmostEqual(rows[3].values["atr_3"], 14 / 3)
        self.assertAlmostEqual(rows[2].values["natr_3"], 100 * 3 / bars[2].close)

    def test_close_standard_deviation_is_population_measure(self) -> None:
        rows = compute_volatility_features(_close_bars([2, 3, 4]), _config(stddev_windows=(3,)))
        self.assertAlmostEqual(rows[-1].values["close_stddev_3"], math.sqrt(2 / 3))

    def test_historical_volatility_uses_log_returns_and_sample_stddev(self) -> None:
        closes = [100, 110, 99]
        rows = compute_volatility_features(
            _close_bars(closes),
            _config(historical_volatility_windows=(2,), annualization_periods=252),
        )
        log_returns = [math.log(1.1), math.log(0.9)]
        mean = sum(log_returns) / 2
        sample_variance = sum((value - mean) ** 2 for value in log_returns)
        expected = math.sqrt(sample_variance) * math.sqrt(252)
        self.assertAlmostEqual(rows[-1].values["historical_volatility_2"], expected)

    def test_incomplete_log_return_window_is_null(self) -> None:
        bars = _close_bars([10, 11])
        rows = compute_volatility_features(bars, _config(historical_volatility_windows=(2,)))
        self.assertIsNone(rows[-1].values["historical_volatility_2"])

    def test_future_bar_and_other_ticker_do_not_change_history(self) -> None:
        bars = _close_bars([10, 11, 12, 13])
        config = _config()
        original = compute_volatility_features(bars, config)
        additions = [
            Bar("AAA", date(2020, 2, 1), 90, 110, 80, 100, 1_000),
            Bar("BBB", date(2020, 1, 2), 1, 100, 1, 50, 1_000),
        ]
        extended = compute_volatility_features(bars + additions, config)
        self.assertEqual(original, [row for row in extended if row.ticker == "AAA"][:-1])

    def test_manifest_records_formula_and_annualization(self) -> None:
        manifest = volatility_manifest(
            VolatilityConfig(),
            frequency="daily",
            source_data_version="data1",
            code_version="git1",
        )
        self.assertEqual(manifest.definitions["atr_method"], "wilder_rma")
        self.assertEqual(manifest.definitions["annualization_periods"], 252)


def _config(
    *,
    stddev_windows: tuple[int, ...] = (3,),
    historical_volatility_windows: tuple[int, ...] = (3,),
    annualization_periods: int = 252,
) -> VolatilityConfig:
    return VolatilityConfig(
        atr_windows=(3,),
        stddev_windows=stddev_windows,
        historical_volatility_windows=historical_volatility_windows,
        annualization_periods=annualization_periods,
    )


def _close_bars(closes: list[float]) -> list[Bar]:
    start = date(2020, 1, 2)
    return [
        Bar("AAA", start + timedelta(days=index), close, close + 1, close - 1, close, 100)
        for index, close in enumerate(closes)
    ]


def _bars_from_ranges(ranges: list[float]) -> list[Bar]:
    start = date(2020, 1, 2)
    return [
        Bar(
            "AAA",
            start + timedelta(days=index),
            10,
            10 + value / 2,
            10 - value / 2,
            10,
            100,
        )
        for index, value in enumerate(ranges)
    ]


if __name__ == "__main__":
    unittest.main()
