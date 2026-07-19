import unittest
from datetime import date, timedelta

from quantresearch.features.volume import (
    VolumeConfig,
    compute_volume_features,
    volume_manifest,
)
from quantresearch.simulation.models import Bar


class VolumeFeatureTests(unittest.TestCase):
    def test_rvol_sma_extremes_spike_breakout_and_trend(self) -> None:
        rows = compute_volume_features(
            _bars("AAA", [100, 200, 300, 400]),
            VolumeConfig(windows=(3,), spike_ratio=2.0, dry_up_ratio=0.5),
        )
        last = rows[-1].values
        self.assertAlmostEqual(last["volume_sma_3"], 300)
        self.assertAlmostEqual(last["rvol_3"], 2.0)
        self.assertEqual(last["prior_highest_volume_3"], 300)
        self.assertEqual(last["prior_lowest_volume_3"], 100)
        self.assertTrue(last["volume_spike_3"])
        self.assertFalse(last["volume_dry_up_3"])
        self.assertTrue(last["volume_breakout_3"])
        self.assertFalse(last["volume_contraction_3"])
        self.assertAlmostEqual(last["volume_trend_3"], 3.0)

    def test_dry_up_and_contraction(self) -> None:
        last = compute_volume_features(
            _bars("AAA", [100, 100, 100, 40]), VolumeConfig(windows=(3,))
        )[-1].values
        self.assertAlmostEqual(last["rvol_3"], 0.4)
        self.assertTrue(last["volume_dry_up_3"])
        self.assertTrue(last["volume_contraction_3"])
        self.assertFalse(last["volume_breakout_3"])

    def test_prior_zero_volume_has_null_rvol(self) -> None:
        last = compute_volume_features(_bars("AAA", [0, 0, 0, 100]), VolumeConfig(windows=(3,)))[
            -1
        ].values
        self.assertIsNone(last["rvol_3"])
        self.assertFalse(last["volume_spike_3"])
        self.assertFalse(last["volume_dry_up_3"])

    def test_insufficient_history_is_null_and_false(self) -> None:
        row = compute_volume_features(_bars("AAA", [100, 200]), VolumeConfig(windows=(3,)))[-1]
        self.assertIsNone(row.values["rvol_3"])
        self.assertIsNone(row.values["prior_highest_volume_3"])
        self.assertFalse(row.values["volume_breakout_3"])

    def test_default_windows_are_ten_twenty_fifty(self) -> None:
        self.assertEqual(VolumeConfig().windows, (10, 20, 50))

    def test_future_and_other_ticker_do_not_change_history(self) -> None:
        bars = _bars("AAA", [100, 200, 300, 400]) + _bars("BBB", [10, 20, 30, 40])
        config = VolumeConfig(windows=(3,))
        original = compute_volume_features(bars, config)
        future = Bar("AAA", date(2020, 2, 7), 10, 11, 9, 10, 999_999)
        extended = compute_volume_features(bars + [future], config)
        self.assertEqual(original, [row for row in extended if row.date != future.date])

    def test_manifest_records_thresholds(self) -> None:
        manifest = volume_manifest(
            VolumeConfig(windows=(10, 20, 50), spike_ratio=2.5, dry_up_ratio=0.4),
            frequency="daily",
            source_data_version="data1",
            code_version="git1",
        )
        self.assertEqual(manifest.definitions["spike_ratio"], 2.5)
        self.assertEqual(manifest.definitions["dry_up_ratio"], 0.4)


def _bars(ticker: str, volumes: list[float]) -> list[Bar]:
    start = date(2020, 1, 3)
    return [
        Bar(ticker, start + timedelta(days=7 * index), 10, 11, 9, 10, volume)
        for index, volume in enumerate(volumes)
    ]


if __name__ == "__main__":
    unittest.main()
