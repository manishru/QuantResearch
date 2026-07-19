import unittest
from datetime import date, timedelta

from quantresearch.features.supply_demand import (
    SupplyDemandConfig,
    compute_supply_demand_features,
    supply_demand_manifest,
)
from quantresearch.simulation.models import Bar


class SupplyDemandFeatureTests(unittest.TestCase):
    def test_medium_drop_base_rally_is_confirmed_only_at_departure_close(self) -> None:
        bars = _demand_bars()
        config = _config()
        before_departure = compute_supply_demand_features(bars[:3], config)
        self.assertFalse(any(row.values["demand_created"] for row in before_departure))

        confirmed = compute_supply_demand_features(bars[:4], config)
        row = confirmed[-1]
        self.assertIsNotNone(row.values["atr"])
        self.assertTrue(row.values["demand_created"])
        self.assertEqual(row.values["demand_lower"], 7.5)
        self.assertEqual(row.values["demand_upper"], 8.2)
        self.assertEqual(row.values["demand_base_date"], "2020-01-04")
        self.assertAlmostEqual(row.values["previous_base_range_ratio"], 3)
        self.assertAlmostEqual(row.values["departure_base_range_ratio"], 3.5)
        self.assertAlmostEqual(row.values["departure_body_ratio"], 0.8)
        self.assertAlmostEqual(row.values["departure_volume_ratio"], 2)

    def test_first_future_revisit_and_close_invalidation_are_causal(self) -> None:
        rows = compute_supply_demand_features(_demand_bars(), _config())
        self.assertFalse(rows[3].values["demand_revisited"])
        self.assertTrue(rows[4].values["demand_revisited"])
        self.assertEqual(rows[4].values["demand_retest_count"], 1)
        self.assertTrue(rows[5].values["demand_invalidated"])
        self.assertIsNone(rows[5].values["demand_lower"])

    def test_rally_base_drop_creates_supply_zone(self) -> None:
        bars = _supply_bars()
        rows = compute_supply_demand_features(bars, _config())
        created = rows[3]
        self.assertTrue(created.values["supply_created"])
        self.assertEqual(created.values["supply_lower"], 11.8)
        self.assertEqual(created.values["supply_upper"], 12.5)
        self.assertTrue(rows[4].values["supply_revisited"])
        self.assertTrue(rows[5].values["supply_invalidated"])

    def test_expiry_removes_zone_without_future_mutation(self) -> None:
        bars = _demand_bars()[:4] + [
            Bar("AAA", date(2020, 1, 6), 12, 13, 11, 12, 100),
            Bar("AAA", date(2020, 1, 7), 12, 13, 11, 12, 100),
        ]
        config = _config(entry_expiry_bars=1)
        rows = compute_supply_demand_features(bars, config)
        self.assertTrue(rows[-1].values["demand_expired"])
        self.assertIsNone(rows[-1].values["demand_lower"])

    def test_future_and_other_ticker_do_not_change_historical_rows(self) -> None:
        bars = _demand_bars()[:5]
        config = _config()
        original = compute_supply_demand_features(bars, config)
        extended = compute_supply_demand_features(
            bars
            + [
                Bar("AAA", date(2020, 2, 1), 100, 110, 90, 100, 1_000),
                Bar("BBB", date(2020, 1, 2), 20, 21, 19, 20, 1_000),
            ],
            config,
        )
        self.assertEqual(original, [row for row in extended if row.ticker == "AAA"][:-1])

    def test_manifest_records_medium_control_and_point_in_time_semantics(self) -> None:
        manifest = supply_demand_manifest(
            SupplyDemandConfig(),
            frequency="daily",
            source_data_version="data1",
            code_version="git1",
        )
        self.assertEqual(manifest.definitions["definition_version"], "daily_three_candle_v1")
        self.assertEqual(manifest.definitions["previous_range_ratio"], 2.0)
        self.assertEqual(manifest.definitions["departure_range_ratio"], 3.0)
        self.assertEqual(manifest.definitions["availability"], "departure_close")
        self.assertEqual(manifest.definitions["selection"], "none")

    def test_config_and_duplicate_validation(self) -> None:
        with self.assertRaises(ValueError):
            SupplyDemandConfig(atr_period=1)
        bar = _demand_bars()[0]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            compute_supply_demand_features([bar, bar], _config())

    def test_zero_range_departure_is_not_a_setup(self) -> None:
        bars = _demand_bars()[:3]
        bars.append(Bar("AAA", date(2020, 1, 5), 8.2, 8.2, 8.2, 8.2, 200))
        rows = compute_supply_demand_features(bars, _config())
        self.assertFalse(rows[-1].values["demand_created"])
        self.assertIsNone(rows[-1].values["departure_body_ratio"])

    def test_zero_width_zone_is_not_created(self) -> None:
        bars = _demand_bars()[:2]
        bars.append(Bar("AAA", date(2020, 1, 4), 8, 8.5, 8, 8, 100))
        bars.append(Bar("AAA", date(2020, 1, 5), 8, 11.5, 8, 11, 200))
        rows = compute_supply_demand_features(bars, _config())
        self.assertFalse(rows[-1].values["demand_created"])
        self.assertIsNone(rows[-1].values["demand_lower"])


def _config(*, entry_expiry_bars: int = 60) -> SupplyDemandConfig:
    return SupplyDemandConfig(
        atr_period=2,
        volume_period=2,
        base_atr_ratio=0.75,
        previous_range_ratio=2.0,
        departure_range_ratio=3.0,
        departure_body_ratio=0.6,
        volume_multiplier=1.5,
        structure_lookback=2,
        require_structure_break=False,
        entry_expiry_bars=entry_expiry_bars,
    )


def _demand_bars() -> list[Bar]:
    start = date(2020, 1, 2)
    values = [
        (10, 11, 9, 10, 100),
        (10, 10, 7, 8, 100),
        (8, 8.5, 7.5, 8.2, 100),
        (8.2, 11.5, 8, 11, 200),
        (8.5, 9, 8, 8.5, 100),
        (7.2, 8, 6.5, 7, 100),
    ]
    return [
        Bar("AAA", start + timedelta(days=index), open_, high, low, close, volume)
        for index, (open_, high, low, close, volume) in enumerate(values)
    ]


def _supply_bars() -> list[Bar]:
    start = date(2020, 1, 2)
    values = [
        (10, 11, 9, 10, 100),
        (10, 13, 10, 12, 100),
        (12, 12.5, 11.5, 11.8, 100),
        (11.8, 12, 8.5, 9, 200),
        (11.8, 12, 11, 11.5, 100),
        (12.8, 13.5, 12.6, 13, 100),
    ]
    return [
        Bar("AAA", start + timedelta(days=index), open_, high, low, close, volume)
        for index, (open_, high, low, close, volume) in enumerate(values)
    ]


if __name__ == "__main__":
    unittest.main()
