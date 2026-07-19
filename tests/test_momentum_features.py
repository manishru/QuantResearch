import unittest
from datetime import date, timedelta

from quantresearch.features.momentum import (
    DAILY_MOMENTUM_HORIZONS,
    WEEKLY_MOMENTUM_HORIZONS,
    MomentumConfig,
    compute_momentum_features,
)
from quantresearch.simulation.models import Bar


class MomentumFeatureTests(unittest.TestCase):
    def test_weekly_horizons_have_declared_periods(self) -> None:
        self.assertEqual(WEEKLY_MOMENTUM_HORIZONS["1W"], 1)
        self.assertEqual(WEEKLY_MOMENTUM_HORIZONS["5W"], 5)
        self.assertEqual(WEEKLY_MOMENTUM_HORIZONS["3M"], 13)
        self.assertEqual(WEEKLY_MOMENTUM_HORIZONS["6M"], 26)
        self.assertEqual(WEEKLY_MOMENTUM_HORIZONS["9M"], 39)
        self.assertEqual(WEEKLY_MOMENTUM_HORIZONS["12M"], 52)

    def test_daily_horizons_have_declared_trading_session_periods(self) -> None:
        self.assertEqual(DAILY_MOMENTUM_HORIZONS["1D"], 1)
        self.assertEqual(DAILY_MOMENTUM_HORIZONS["1W"], 5)
        self.assertEqual(DAILY_MOMENTUM_HORIZONS["1M"], 21)
        self.assertEqual(DAILY_MOMENTUM_HORIZONS["12M"], 252)

    def test_returns_are_calculated_per_ticker_from_prior_completed_close(self) -> None:
        bars = _bars("AAA", 8, 10.0) + _bars("BBB", 8, 100.0)
        config = MomentumConfig(frequency="weekly", horizons={"1W": 1, "5W": 5})
        rows = compute_momentum_features(bars, config)
        aaa = [row for row in rows if row.ticker == "AAA"][-1]
        bbb = [row for row in rows if row.ticker == "BBB"][-1]
        self.assertAlmostEqual(aaa.values["momentum_1W"], 17 / 16 - 1)
        self.assertAlmostEqual(aaa.values["momentum_5W"], 17 / 12 - 1)
        self.assertAlmostEqual(bbb.values["momentum_1W"], 107 / 106 - 1)
        self.assertEqual(aaa.available_after, aaa.date)

    def test_insufficient_history_is_null_not_zero(self) -> None:
        rows = compute_momentum_features(
            _bars("AAA", 3, 10.0),
            MomentumConfig(frequency="weekly", horizons={"1W": 1, "5W": 5}),
        )
        self.assertIsNone(rows[0].values["momentum_1W"])
        self.assertIsNone(rows[-1].values["momentum_5W"])

    def test_future_bar_does_not_change_historical_momentum(self) -> None:
        bars = _bars("AAA", 8, 10.0)
        config = MomentumConfig(frequency="weekly", horizons={"1W": 1, "5W": 5})
        original = compute_momentum_features(bars, config)
        future = Bar("AAA", bars[-1].date + timedelta(days=7), 1000, 1001, 999, 1000, 100)
        extended = compute_momentum_features(bars + [future], config)
        self.assertEqual(original, extended[:-1])

    def test_duplicate_bars_and_invalid_horizons_are_rejected(self) -> None:
        item = _bars("AAA", 1, 10.0)[0]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            compute_momentum_features([item, item], MomentumConfig("weekly", {"1W": 1}))
        with self.assertRaises(ValueError):
            MomentumConfig("weekly", {"BAD": 0})


def _bars(ticker: str, count: int, starting_close: float) -> list[Bar]:
    start = date(2020, 1, 3)
    output = []
    for index in range(count):
        close = starting_close + index
        day = start + timedelta(days=7 * index)
        output.append(Bar(ticker, day, close, close + 1, close - 1, close, 100))
    return output


if __name__ == "__main__":
    unittest.main()
