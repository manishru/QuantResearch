import unittest
from datetime import date

from quantresearch.features.models import FeatureManifest
from quantresearch.features.technical import WeeklyFeatureConfig, compute_weekly_features
from quantresearch.features.weekly import aggregate_weekly_bars
from quantresearch.simulation.models import Bar


class WeeklyAggregationTests(unittest.TestCase):
    def test_aggregates_ohlcv_and_uses_last_session_date(self) -> None:
        daily = [
            Bar("AAA", date(2020, 1, 6), 10, 12, 9, 11, 100),
            Bar("AAA", date(2020, 1, 7), 11, 13, 10, 12, 200),
            Bar("AAA", date(2020, 1, 10), 12, 14, 8, 13, 300),
            Bar("AAA", date(2020, 1, 13), 20, 22, 19, 21, 400),
        ]
        weekly = aggregate_weekly_bars(daily)
        self.assertEqual(len(weekly), 2)
        self.assertEqual(weekly[0].date, date(2020, 1, 10))
        self.assertEqual(
            (weekly[0].open, weekly[0].high, weekly[0].low, weekly[0].close),
            (10, 14, 8, 13),
        )
        self.assertEqual(weekly[0].volume, 600)

    def test_duplicate_daily_bar_is_rejected(self) -> None:
        item = Bar("AAA", date(2020, 1, 6), 10, 11, 9, 10, 100)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            aggregate_weekly_bars([item, item])


class WeeklyFeatureTests(unittest.TestCase):
    def test_returns_breakout_atr_and_availability(self) -> None:
        bars = _weekly_bars(10)
        config = WeeklyFeatureConfig(
            return_windows=(2,), breakout_windows=(3,), atr_windows=(3,), supertrends=((3, 2.0),)
        )
        rows = compute_weekly_features(bars, config)
        last = rows[-1]
        self.assertAlmostEqual(last.values["return_2w"], 19 / 17 - 1)
        self.assertEqual(last.values["breakout_high_3w"], 20)
        self.assertFalse(last.values["breakout_close_3w"])
        self.assertAlmostEqual(last.values["atr_3w"], 3.0)
        self.assertEqual(last.available_after, last.date)

    def test_future_data_does_not_change_prior_features(self) -> None:
        bars = _weekly_bars(10)
        config = WeeklyFeatureConfig(
            return_windows=(2,), breakout_windows=(3,), atr_windows=(3,), supertrends=((3, 2.0),)
        )
        original = compute_weekly_features(bars, config)
        extended = compute_weekly_features(
            bars + [Bar("AAA", date(2020, 3, 13), 1000, 1100, 900, 1000, 1_000)],
            config,
        )
        self.assertEqual(original, extended[:-1])

    def test_supertrend_first_available_value_is_hand_calculated(self) -> None:
        bars = [
            Bar("AAA", date(2020, 1, 3), 10, 11, 9, 10, 100),
            Bar("AAA", date(2020, 1, 10), 10, 11, 9, 10, 100),
        ]
        config = WeeklyFeatureConfig(
            return_windows=(), breakout_windows=(), atr_windows=(2,), supertrends=((2, 2.0),)
        )
        rows = compute_weekly_features(bars, config)
        self.assertIsNone(rows[0].values["supertrend_2_2"])
        self.assertEqual(rows[1].values["supertrend_2_2"], 14)
        self.assertFalse(rows[1].values["supertrend_green_2_2"])

    def test_manifest_id_is_stable_and_content_addressed(self) -> None:
        first = FeatureManifest(
            frequency="weekly",
            price_basis="split_dividend_adjusted",
            definitions={"return_windows": [5, 26, 39]},
            source_data_version="data-v1",
            code_version="git-v1",
        )
        second = FeatureManifest.from_dict(first.to_dict())
        self.assertEqual(first.feature_version, second.feature_version)
        changed = FeatureManifest(
            frequency="weekly",
            price_basis="split_dividend_adjusted",
            definitions={"return_windows": [5, 26]},
            source_data_version="data-v1",
            code_version="git-v1",
        )
        self.assertNotEqual(first.feature_version, changed.feature_version)


def _weekly_bars(count: int) -> list[Bar]:
    dates = [
        date(2020, 1, 3),
        date(2020, 1, 10),
        date(2020, 1, 17),
        date(2020, 1, 24),
        date(2020, 1, 31),
        date(2020, 2, 7),
        date(2020, 2, 14),
        date(2020, 2, 21),
        date(2020, 2, 28),
        date(2020, 3, 6),
    ]
    return [
        Bar("AAA", day, 10 + index, 12 + index, 9 + index, 10 + index, 1_000)
        for index, day in enumerate(dates[:count])
    ]


if __name__ == "__main__":
    unittest.main()
