import unittest
from datetime import date

from quantresearch.simulation.demand import DemandSimulationConfig, DemandTradeSimulator
from quantresearch.simulation.models import Bar
from quantresearch.strategies.supply_demand_signals import DemandEntryType, DemandTradePlan


class DemandPortfolioSimulatorTests(unittest.TestCase):
    def test_market_plan_fills_next_open_and_target_closes_trade(self) -> None:
        result = DemandTradeSimulator(_config()).run(
            bars=[
                _bar(2, 10, 11, 9, 10),
                _bar(3, 10, 11, 9, 10),
                _bar(4, 12, 13, 11, 12),
            ],
            plans=[_plan(DemandEntryType.NEXT_OPEN_MARKET, entry=10, stop=8, target=12)],
            membership=_membership("AAA"),
        )
        trade = result.trades[0]
        self.assertEqual(trade.entry_date, date(2020, 1, 3))
        self.assertEqual(trade.entry_price, 10)
        self.assertEqual(trade.exit_date, date(2020, 1, 4))
        self.assertEqual(trade.exit_price, 12)

    def test_limit_fills_at_better_open_or_limit_and_non_touch_is_unfilled(self) -> None:
        better = DemandTradeSimulator(_config()).run(
            bars=[_bar(2, 10, 11, 9, 10), _bar(3, 8.5, 10, 8, 9)],
            plans=[_plan(DemandEntryType.LIMIT, entry=9, stop=7, target=20)],
            membership=_membership("AAA"),
        )
        self.assertEqual(better.trades[0].entry_price, 8.5)

        unfilled = DemandTradeSimulator(_config()).run(
            bars=[_bar(2, 10, 11, 9, 10), _bar(3, 10, 11, 9.5, 10)],
            plans=[_plan(DemandEntryType.LIMIT, entry=9, stop=7, target=20)],
            membership=_membership("AAA"),
        )
        self.assertEqual(unfilled.trades, ())
        self.assertEqual(unfilled.orders[0].status.value, "unfilled")

    def test_same_entry_bar_stop_and_target_uses_stop_first(self) -> None:
        result = DemandTradeSimulator(_config()).run(
            bars=[_bar(2, 10, 11, 9, 10), _bar(3, 10, 13, 7, 11)],
            plans=[_plan(DemandEntryType.NEXT_OPEN_MARKET, entry=10, stop=8, target=12)],
            membership=_membership("AAA"),
        )
        trade = result.trades[0]
        self.assertEqual(trade.exit_date, date(2020, 1, 3))
        self.assertEqual(trade.exit_price, 8)

    def test_gap_through_stop_exits_at_open(self) -> None:
        result = DemandTradeSimulator(_config()).run(
            bars=[
                _bar(2, 10, 11, 9, 10),
                _bar(3, 10, 11, 9, 10),
                _bar(4, 7, 8, 6, 7),
            ],
            plans=[_plan(DemandEntryType.NEXT_OPEN_MARKET, entry=10, stop=8, target=12)],
            membership=_membership("AAA"),
        )
        self.assertEqual(result.trades[0].exit_price, 7)

    def test_membership_is_required_at_decision_and_execution(self) -> None:
        decision_rejected = DemandTradeSimulator(_config()).run(
            bars=[_bar(2, 10, 11, 9, 10), _bar(3, 10, 11, 9, 10)],
            plans=[_plan(DemandEntryType.NEXT_OPEN_MARKET, 10, 8, 12)],
            membership={date(2020, 1, 2): frozenset(), date(2020, 1, 3): frozenset({"AAA"})},
        )
        self.assertEqual(decision_rejected.orders, ())

        execution_rejected = DemandTradeSimulator(_config()).run(
            bars=[_bar(2, 10, 11, 9, 10), _bar(3, 10, 11, 9, 10)],
            plans=[_plan(DemandEntryType.NEXT_OPEN_MARKET, 10, 8, 12)],
            membership={date(2020, 1, 2): frozenset({"AAA"}), date(2020, 1, 3): frozenset()},
        )
        self.assertEqual(execution_rejected.trades, ())
        self.assertEqual(execution_rejected.orders[0].status.value, "rejected_ineligible")

    def test_ranking_happens_after_membership_and_respects_position_limit(self) -> None:
        plans = [
            _plan(DemandEntryType.NEXT_OPEN_MARKET, 10, 8, 20, ticker="OUT", score=100),
            _plan(DemandEntryType.NEXT_OPEN_MARKET, 10, 8, 20, ticker="BBB", score=5),
            _plan(DemandEntryType.NEXT_OPEN_MARKET, 10, 8, 20, ticker="AAA", score=5),
        ]
        bars = [
            _bar(2, 10, 11, 9, 10, "AAA"),
            _bar(2, 10, 11, 9, 10, "BBB"),
            _bar(2, 10, 11, 9, 10, "OUT"),
            _bar(3, 10, 11, 9, 10, "AAA"),
            _bar(3, 10, 11, 9, 10, "BBB"),
            _bar(3, 10, 11, 9, 10, "OUT"),
        ]
        membership = {
            date(2020, 1, 2): frozenset({"AAA", "BBB"}),
            date(2020, 1, 3): frozenset({"AAA", "BBB"}),
        }
        result = DemandTradeSimulator(_config(max_positions=1)).run(
            bars=bars, plans=plans, membership=membership
        )
        self.assertEqual([trade.ticker for trade in result.trades], ["AAA"])

    def test_costs_and_equity_reconcile(self) -> None:
        result = DemandTradeSimulator(
            DemandSimulationConfig(
                initial_cash=1_000,
                risk_fraction=0.01,
                maximum_position_weight=0.5,
                max_positions=1,
                commission_bps=10,
                slippage_bps=10,
            )
        ).run(
            bars=[_bar(2, 10, 11, 9, 10), _bar(3, 10, 12, 9, 11)],
            plans=[_plan(DemandEntryType.NEXT_OPEN_MARKET, 10, 8, 12)],
            membership=_membership("AAA"),
        )
        trade = result.trades[0]
        self.assertIsNotNone(trade.exit_date)
        self.assertAlmostEqual(result.ending_equity, 1_000 + trade.net_profit)


def _config(*, max_positions: int = 10) -> DemandSimulationConfig:
    return DemandSimulationConfig(
        initial_cash=10_000,
        risk_fraction=0.01,
        maximum_position_weight=0.5,
        max_positions=max_positions,
    )


def _plan(
    kind: DemandEntryType,
    entry: float,
    stop: float,
    target: float,
    *,
    ticker: str = "AAA",
    score: float = 1,
) -> DemandTradePlan:
    return DemandTradePlan(
        ticker=ticker,
        decision_date=date(2020, 1, 2),
        available_after=date(2020, 1, 2),
        zone_base_date=date(2020, 1, 1),
        zone_lower=8,
        zone_upper=10,
        atr=2,
        retest_number=1,
        entry_type=kind,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        risk_reward=3,
        ranking_score=score,
    )


def _bar(day: int, open_: float, high: float, low: float, close: float, ticker: str = "AAA") -> Bar:
    return Bar(ticker, date(2020, 1, day), open_, high, low, close, 1_000)


def _membership(*tickers: str) -> dict[date, frozenset[str]]:
    members = frozenset(tickers)
    return {date(2020, 1, day): members for day in (2, 3, 4)}


if __name__ == "__main__":
    unittest.main()
