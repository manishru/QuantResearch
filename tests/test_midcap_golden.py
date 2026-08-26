import json
import unittest
from pathlib import Path

from quantresearch.research.midcap_golden import (
    MIDCAP_GOLDEN,
    build_backtest_command,
    qualifies,
)


class MidcapGoldenTests(unittest.TestCase):
    def test_frozen_strategy_contract(self):
        self.assertEqual(MIDCAP_GOLDEN.strategy_id, "midcap_golden_10m6m3m")
        self.assertEqual(MIDCAP_GOLDEN.lookback_sessions, (210, 126, 63))
        self.assertEqual(MIDCAP_GOLDEN.nominal_day, 14)
        self.assertEqual(MIDCAP_GOLDEN.holding_weeks, 12)
        self.assertEqual(MIDCAP_GOLDEN.stop, 0.30)
        self.assertEqual(MIDCAP_GOLDEN.sleeves, 3)

    def test_rule_is_strictly_descending_and_positive(self):
        self.assertTrue(qualifies(0.40, 0.25, 0.10))
        self.assertFalse(qualifies(0.25, 0.40, 0.10))
        self.assertFalse(qualifies(0.40, 0.25, 0.25))
        self.assertFalse(qualifies(0.40, 0.10, 0.0))

    def test_stored_configuration_matches_contract(self):
        path = Path("config/strategies/midcap_golden_10m6m3m.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["strategy_id"], MIDCAP_GOLDEN.strategy_id)
        self.assertEqual(payload["momentum_rule"], "10M>6M>3M>0")
        self.assertEqual(payload["ranking_horizon"], "10M")
        self.assertEqual(payload["entry"]["nominal_calendar_day"], 14)

    def test_command_translates_every_frozen_control(self):
        command = build_backtest_command(
            python="python", project_root=Path("/repo"), end="2026-08-26",
            database=Path("prices.duckdb"), membership=Path("membership.csv"),
            corporate_actions=Path("actions.csv"), output=Path("reports/out"),
        )
        joined = " ".join(command)
        for expected in (
            "--rule 10M>6M>3M>0", "--days 14", "--holding-weeks 12",
            "--stops 0.3", "--total-capital 12000.0", "--cost 0.001",
            "--candidate-depth 20", "--unique-open-tickers-for all",
            "--renewal-mode fixed_monthly_vintage",
        ):
            self.assertIn(expected, joined)


if __name__ == "__main__":
    unittest.main()
