import unittest
from datetime import date

from quantresearch.simulation.metrics import calculate_performance
from quantresearch.simulation.models import EquityPoint, SimulationResult, Trade


class PerformanceMetricTests(unittest.TestCase):
    def test_total_return_drawdown_and_yearly_returns(self) -> None:
        curve = (
            EquityPoint(date(2020, 1, 2), 100, 0, 100),
            EquityPoint(date(2020, 12, 31), 120, 0, 120),
            EquityPoint(date(2021, 6, 1), 90, 0, 90),
            EquityPoint(date(2021, 12, 31), 130, 0, 130),
        )
        report = calculate_performance(_result(curve), initial_equity=100)
        self.assertAlmostEqual(report.total_return, 0.30)
        self.assertAlmostEqual(report.maximum_drawdown, -0.25)
        self.assertAlmostEqual(report.calendar_year_returns[2020], 0.20)
        self.assertAlmostEqual(report.calendar_year_returns[2021], 130 / 120 - 1)
        self.assertAlmostEqual(report.average_calendar_year_return, (0.20 + 130 / 120 - 1) / 2)
        self.assertEqual(report.worst_calendar_year, 2021)
        self.assertEqual(report.positive_year_fraction, 1.0)

    def test_trade_statistics_use_only_closed_trades(self) -> None:
        trades = (
            Trade("AAA", 1, date(2020, 1, 2), 10, 0, date(2020, 1, 3), 12, net_profit=2),
            Trade("BBB", 1, date(2020, 1, 2), 10, 0, date(2020, 1, 3), 9, net_profit=-1),
            Trade("CCC", 1, date(2020, 1, 2), 10, 0),
        )
        report = calculate_performance(
            _result((EquityPoint(date(2020, 1, 2), 100, 0, 100),), trades),
            initial_equity=100,
        )
        self.assertEqual(report.closed_trade_count, 2)
        self.assertEqual(report.open_trade_count, 1)
        self.assertEqual(report.win_rate, 0.5)
        self.assertEqual(report.profit_factor, 2.0)

    def test_empty_curve_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "equity curve"):
            calculate_performance(_result(()), initial_equity=100)


def _result(curve: tuple[EquityPoint, ...], trades: tuple[Trade, ...] = ()) -> SimulationResult:
    ending = curve[-1].equity if curve else 100
    return SimulationResult((), trades, (), curve, ending, ending)


if __name__ == "__main__":
    unittest.main()
