import unittest
from datetime import date, timedelta

from quantresearch.features.money_flow import (
    MoneyFlowConfig,
    compute_money_flow_features,
    money_flow_manifest,
)
from quantresearch.simulation.models import Bar


class MoneyFlowFeatureTests(unittest.TestCase):
    def test_obv_uses_close_direction_and_flat_close_is_unchanged(self) -> None:
        bars = _close_bars([10, 11, 10, 10], [100, 200, 300, 400])
        rows = compute_money_flow_features(
            bars, MoneyFlowConfig(cmf_windows=(2,), mfi_windows=(2,))
        )
        self.assertEqual([row.values["obv"] for row in rows], [0, 200, -100, -100])

    def test_accumulation_distribution_and_cmf_are_hand_calculated(self) -> None:
        bars = [
            Bar("AAA", date(2020, 1, 2), 10, 12, 8, 11, 100),
            Bar("AAA", date(2020, 1, 3), 10, 12, 8, 9, 200),
        ]
        rows = compute_money_flow_features(
            bars, MoneyFlowConfig(cmf_windows=(2,), mfi_windows=(2,))
        )
        self.assertAlmostEqual(rows[0].values["adl"], 50)
        self.assertAlmostEqual(rows[1].values["adl"], -50)
        self.assertAlmostEqual(rows[1].values["cmf_2"], -1 / 6)

    def test_mfi_handles_all_positive_negative_and_flat_flow(self) -> None:
        rising = compute_money_flow_features(
            _close_bars([10, 11, 12], [100, 100, 100]),
            MoneyFlowConfig(cmf_windows=(2,), mfi_windows=(2,)),
        )
        self.assertEqual(rising[-1].values["mfi_2"], 100)

        falling = compute_money_flow_features(
            _close_bars([12, 11, 10], [100, 100, 100]),
            MoneyFlowConfig(cmf_windows=(2,), mfi_windows=(2,)),
        )
        self.assertEqual(falling[-1].values["mfi_2"], 0)

        flat = compute_money_flow_features(
            _close_bars([10, 10, 10], [100, 100, 100]),
            MoneyFlowConfig(cmf_windows=(2,), mfi_windows=(2,)),
        )
        self.assertEqual(flat[-1].values["mfi_2"], 50)

    def test_zero_range_bar_has_zero_money_flow_multiplier(self) -> None:
        bars = [Bar("AAA", date(2020, 1, 2), 10, 10, 10, 10, 100)]
        row = compute_money_flow_features(
            bars, MoneyFlowConfig(cmf_windows=(1,), mfi_windows=(1,))
        )[0]
        self.assertEqual(row.values["money_flow_multiplier"], 0)
        self.assertEqual(row.values["adl"], 0)

    def test_zero_volume_cmf_is_null(self) -> None:
        bars = _close_bars([10, 11], [0, 0])
        row = compute_money_flow_features(
            bars, MoneyFlowConfig(cmf_windows=(2,), mfi_windows=(2,))
        )[-1]
        self.assertIsNone(row.values["cmf_2"])

    def test_future_bar_does_not_change_history(self) -> None:
        bars = _close_bars([10, 11, 12], [100, 200, 300])
        config = MoneyFlowConfig(cmf_windows=(2,), mfi_windows=(2,))
        original = compute_money_flow_features(bars, config)
        future = Bar("AAA", date(2020, 1, 7), 99, 101, 98, 100, 100_000)
        extended = compute_money_flow_features(bars + [future], config)
        self.assertEqual(original, extended[:-1])

    def test_manifest_and_defaults(self) -> None:
        config = MoneyFlowConfig()
        self.assertEqual(config.cmf_windows, (20,))
        self.assertEqual(config.mfi_windows, (14,))
        manifest = money_flow_manifest(
            config,
            frequency="daily",
            source_data_version="data1",
            code_version="git1",
        )
        self.assertEqual(manifest.definitions["mfi_windows"], [14])


def _close_bars(closes: list[float], volumes: list[float]) -> list[Bar]:
    start = date(2020, 1, 2)
    return [
        Bar(
            "AAA",
            start + timedelta(days=index),
            close,
            close + 1,
            close - 1,
            close,
            volume,
        )
        for index, (close, volume) in enumerate(zip(closes, volumes, strict=True))
    ]


if __name__ == "__main__":
    unittest.main()
