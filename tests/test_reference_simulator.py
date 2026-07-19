import unittest
from datetime import date

from quantresearch.simulation.models import Bar, Signal, SignalAction, SimulationConfig
from quantresearch.simulation.reference import ReferenceSimulator


def bar(day: int, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar("AAA", date(2020, 1, day), open_, high, low, close, 1_000)


class ReferenceSimulatorTests(unittest.TestCase):
    def test_completed_signal_fills_next_session_without_lookahead(self) -> None:
        bars = [bar(2, 10, 11, 9, 10), bar(3, 12, 13, 11, 12), bar(6, 14, 15, 13, 14)]
        signals = [Signal(date(2020, 1, 2), "AAA", SignalAction.ENTRY, quantity=10)]
        result = ReferenceSimulator().run(bars, signals, membership=_membership("AAA"))
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].entry_date, date(2020, 1, 3))
        self.assertEqual(result.trades[0].entry_price, 12)
        self.assertEqual(result.equity_curve[0].date, date(2020, 1, 2))

    def test_stop_entry_uses_worse_of_open_or_trigger_and_requires_high(self) -> None:
        bars = [bar(2, 10, 10, 9, 10), bar(3, 13, 14, 12, 13)]
        signals = [
            Signal(date(2020, 1, 2), "AAA", SignalAction.ENTRY, quantity=2, trigger_price=12)
        ]
        result = ReferenceSimulator().run(bars, signals, membership=_membership("AAA"))
        self.assertEqual(result.trades[0].entry_price, 13)

        unfilled = ReferenceSimulator().run(
            [bar(2, 10, 10, 9, 10), bar(3, 10, 11, 9, 10)],
            signals,
            membership=_membership("AAA"),
        )
        self.assertEqual(unfilled.trades, ())
        self.assertEqual(unfilled.orders[0].status.value, "unfilled")

    def test_entry_requires_membership_at_signal_and_execution(self) -> None:
        bars = [bar(2, 10, 11, 9, 10), bar(3, 10, 11, 9, 10)]
        signal = [Signal(date(2020, 1, 2), "AAA", SignalAction.ENTRY, quantity=1)]
        membership = {
            date(2020, 1, 2): frozenset({"AAA"}),
            date(2020, 1, 3): frozenset(),
        }
        result = ReferenceSimulator().run(bars, signal, membership=membership)
        self.assertEqual(result.trades, ())
        self.assertEqual(result.orders[0].status.value, "rejected_ineligible")

    def test_acquisition_union_data_does_not_create_daily_eligibility(self) -> None:
        bars = [
            bar(2, 10, 11, 9, 10),
            Bar("OLD", date(2020, 1, 2), 20, 21, 19, 20, 1_000),
            bar(3, 10, 11, 9, 10),
            Bar("OLD", date(2020, 1, 3), 30, 31, 29, 30, 1_000),
        ]
        signals = [Signal(date(2020, 1, 2), "OLD", SignalAction.ENTRY, quantity=1)]
        membership = {
            date(2020, 1, 2): frozenset({"AAA"}),
            date(2020, 1, 3): frozenset({"AAA"}),
        }
        result = ReferenceSimulator().run(bars, signals, membership=membership)
        self.assertEqual(result.trades, ())
        self.assertEqual(result.orders[0].status.value, "rejected_ineligible")

    def test_exit_can_liquidate_after_index_removal(self) -> None:
        bars = [
            bar(2, 10, 11, 9, 10),
            bar(3, 10, 11, 9, 10),
            bar(6, 12, 13, 11, 12),
            bar(7, 13, 14, 12, 13),
        ]
        signals = [
            Signal(date(2020, 1, 2), "AAA", SignalAction.ENTRY, quantity=2),
            Signal(date(2020, 1, 6), "AAA", SignalAction.EXIT),
        ]
        membership = {
            date(2020, 1, 2): frozenset({"AAA"}),
            date(2020, 1, 3): frozenset({"AAA"}),
            date(2020, 1, 6): frozenset(),
            date(2020, 1, 7): frozenset(),
        }
        result = ReferenceSimulator().run(bars, signals, membership=membership)
        self.assertEqual(result.trades[0].exit_date, date(2020, 1, 7))
        self.assertEqual(result.positions, ())

    def test_costs_tax_and_equity_reconcile(self) -> None:
        bars = [bar(2, 100, 101, 99, 100), bar(3, 100, 101, 99, 100), bar(6, 120, 121, 119, 120)]
        signals = [
            Signal(date(2020, 1, 2), "AAA", SignalAction.ENTRY, quantity=1),
            Signal(date(2020, 1, 3), "AAA", SignalAction.EXIT),
        ]
        config = SimulationConfig(
            initial_cash=1_000,
            commission_bps=10,
            slippage_bps=10,
            short_term_profit_haircut=0.15,
        )
        result = ReferenceSimulator(config).run(bars, signals, membership=_membership("AAA"))
        trade = result.trades[0]
        self.assertAlmostEqual(trade.entry_price, 100.1)
        self.assertAlmostEqual(trade.exit_price, 119.88)
        self.assertGreater(trade.tax_haircut, 0)
        self.assertAlmostEqual(result.ending_equity, result.ending_cash)
        self.assertAlmostEqual(
            result.ending_equity,
            config.initial_cash + trade.net_profit,
            places=8,
        )

    def test_rejects_duplicate_bars_and_same_day_signal_conflicts(self) -> None:
        simulator = ReferenceSimulator()
        duplicate = [bar(2, 10, 11, 9, 10), bar(2, 10, 11, 9, 10)]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            simulator.run(duplicate, [], membership={})
        signals = [
            Signal(date(2020, 1, 2), "AAA", SignalAction.ENTRY, quantity=1),
            Signal(date(2020, 1, 2), "AAA", SignalAction.EXIT),
        ]
        with self.assertRaisesRegex(ValueError, "conflicting"):
            simulator.run([bar(2, 10, 11, 9, 10)], signals, membership=_membership("AAA"))


def _membership(ticker: str) -> dict[date, frozenset[str]]:
    return {
        date(2020, 1, 2): frozenset({ticker}),
        date(2020, 1, 3): frozenset({ticker}),
        date(2020, 1, 6): frozenset({ticker}),
        date(2020, 1, 7): frozenset({ticker}),
    }


if __name__ == "__main__":
    unittest.main()
