import unittest
from datetime import date, timedelta

from quantresearch.features.breakouts import (
    BreakoutConfig,
    breakout_manifest,
    compute_breakout_features,
)
from quantresearch.simulation.models import Bar


class BreakoutFeatureTests(unittest.TestCase):
    def test_prior_window_high_low_excludes_current_bar(self) -> None:
        bars = _bars("AAA", [10, 11, 12, 13, 20, 15])
        rows = compute_breakout_features(bars, BreakoutConfig(windows=(3,)))
        last = rows[-1].values
        self.assertEqual(last["breakout_high_3w"], 21)
        self.assertEqual(last["breakout_low_3w"], 11)
        self.assertFalse(last["breakout_up_3w"])
        self.assertFalse(last["breakout_down_3w"])
        self.assertAlmostEqual(last["close_distance_breakout_high_3w"], 15 / 21 - 1)
        self.assertAlmostEqual(last["close_distance_breakout_low_3w"], 15 / 11 - 1)

    def test_up_and_down_breakouts_use_close_against_prior_extremes(self) -> None:
        up = compute_breakout_features(
            _bars("AAA", [10, 11, 12, 20]), BreakoutConfig(windows=(3,))
        )[-1]
        self.assertTrue(up.values["breakout_up_3w"])

        down = compute_breakout_features(
            _bars("AAA", [10, 11, 12, 5]), BreakoutConfig(windows=(3,))
        )[-1]
        self.assertTrue(down.values["breakout_down_3w"])

    def test_insufficient_history_has_null_levels_and_false_flags(self) -> None:
        row = compute_breakout_features(_bars("AAA", [10, 11]), BreakoutConfig(windows=(3,)))[-1]
        self.assertIsNone(row.values["breakout_high_3w"])
        self.assertIsNone(row.values["breakout_low_3w"])
        self.assertFalse(row.values["breakout_up_3w"])
        self.assertFalse(row.values["breakout_down_3w"])

    def test_tickers_are_isolated_and_future_data_does_not_revise_history(self) -> None:
        bars = _bars("AAA", [10, 11, 12, 13]) + _bars("BBB", [100, 101, 102, 103])
        config = BreakoutConfig(windows=(3,))
        original = compute_breakout_features(bars, config)
        future = Bar("AAA", date(2020, 2, 7), 999, 1001, 998, 1000, 100)
        extended = compute_breakout_features(bars + [future], config)
        self.assertEqual(original, [row for row in extended if row.date != future.date])
        bbb = [row for row in original if row.ticker == "BBB"][-1]
        self.assertEqual(bbb.values["breakout_high_3w"], 103)

    def test_default_windows_cover_every_value_from_five_to_sixty(self) -> None:
        config = BreakoutConfig()
        self.assertEqual(config.windows, tuple(range(5, 61)))

    def test_manifest_and_invalid_windows(self) -> None:
        manifest = breakout_manifest(
            BreakoutConfig(windows=(5, 7, 13)),
            source_data_version="data1",
            code_version="git1",
        )
        self.assertEqual(manifest.definitions["windows"], [5, 7, 13])
        with self.assertRaises(ValueError):
            BreakoutConfig(windows=(0,))


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
