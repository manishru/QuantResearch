import unittest
from datetime import date

from quantresearch.simulation.models import Bar
from quantresearch.validation.market_anomalies import detect_price_discontinuities


class MarketAnomalyTests(unittest.TestCase):
    def test_implausible_jump_is_quarantined(self) -> None:
        bars = [
            Bar("AAA", date(2020, 1, 2), 99, 101, 98, 100, 1000),
            Bar("AAA", date(2020, 1, 3), 9990, 10010, 9980, 10000, 1000),
        ]
        findings = detect_price_discontinuities(bars, maximum_ratio=5)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "critical")
        self.assertFalse(findings[0].eligible_for_research)

    def test_normal_change_is_not_flagged(self) -> None:
        bars = [
            Bar("AAA", date(2020, 1, 2), 99, 101, 98, 100, 1000),
            Bar("AAA", date(2020, 1, 3), 104, 106, 103, 105, 1000),
        ]
        self.assertEqual(detect_price_discontinuities(bars, maximum_ratio=5), ())


if __name__ == "__main__":
    unittest.main()
