import unittest
from datetime import date, timedelta
from pathlib import Path

from quantresearch.domain.membership import MembershipHistory, MembershipSnapshot
from quantresearch.research.demand_evaluator import (
    DemandFoldEvaluator,
    ValidatedDataVersion,
)
from quantresearch.simulation.demand import DemandSimulationConfig
from quantresearch.simulation.models import Bar
from quantresearch.strategies.supply_demand import SupplyDemandParameters
from quantresearch.walkforward.models import ForwardState, WalkForwardWindow
from quantresearch.walkforward.replay import ReplayPeriod


class DemandFoldEvaluatorTests(unittest.TestCase):
    def test_unvalidated_source_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "validated"):
            ValidatedDataVersion("candidate", "a" * 64, validated=False)

    def test_forward_segment_uses_warmup_but_only_reports_forward_activity(self) -> None:
        bars = _demand_fixture()
        window = WalkForwardWindow(
            train_start=date(2020, 1, 1),
            train_end=date(2020, 1, 7),
            forward_start=date(2020, 1, 8),
            forward_end=date(2020, 1, 15),
            warmup_start=date(2019, 12, 1),
            execution_start=date(2020, 1, 1),
            forward_state=ForwardState.AVAILABLE,
        )
        evaluation = DemandFoldEvaluator(
            DemandSimulationConfig(
                initial_cash=10_000,
                risk_fraction=0.01,
                maximum_position_weight=0.5,
                max_positions=2,
            )
        ).evaluate(
            bars=bars,
            membership_history=_history(),
            window=window,
            period=ReplayPeriod.FORWARD,
            parameters=_parameters(),
            data_version=ValidatedDataVersion("fixture-v1", "a" * 64, validated=True),
        )
        self.assertEqual(evaluation.period, ReplayPeriod.FORWARD)
        self.assertTrue(
            all(point.date >= window.forward_start for point in evaluation.result.equity_curve)
        )
        self.assertTrue(
            all(trade.entry_date >= window.forward_start for trade in evaluation.result.trades)
        )
        self.assertEqual(evaluation.membership_violation_count, 0)
        self.assertEqual(evaluation.data_version.version_id, "fixture-v1")

    def test_nonmember_setup_cannot_enter_or_count_in_metrics(self) -> None:
        bars = _demand_fixture("OUT")
        evaluation = DemandFoldEvaluator(_simulation_config()).evaluate(
            bars=bars,
            membership_history=_history(),
            window=_single_window(),
            period=ReplayPeriod.FORWARD,
            parameters=_parameters(),
            data_version=ValidatedDataVersion("fixture-v1", "b" * 64, validated=True),
        )
        self.assertEqual(evaluation.result.trades, ())
        self.assertEqual(evaluation.candidate_metrics.membership_violation_count, 0)


def _single_window() -> WalkForwardWindow:
    return WalkForwardWindow(
        train_start=date(2020, 1, 1),
        train_end=date(2020, 1, 7),
        forward_start=date(2020, 1, 8),
        forward_end=date(2020, 1, 15),
        warmup_start=date(2019, 12, 1),
        execution_start=date(2020, 1, 1),
        forward_state=ForwardState.AVAILABLE,
    )


def _simulation_config() -> DemandSimulationConfig:
    return DemandSimulationConfig(
        initial_cash=10_000,
        risk_fraction=0.01,
        maximum_position_weight=0.5,
        max_positions=2,
    )


def _parameters() -> SupplyDemandParameters:
    return SupplyDemandParameters(
        atr_period=2,
        volume_period=2,
        base_atr_ratio=0.75,
        previous_range_ratio=2,
        departure_range_ratio=3,
        departure_body_ratio=0.6,
        volume_multiplier=1.5,
        stop_atr_buffer=0.25,
        risk_reward=2,
        structure_lookback=2,
        entry_expiry_days=20,
        entry_type="confirmation_close",
    )


def _history() -> MembershipHistory:
    return MembershipHistory(
        "SP500",
        (MembershipSnapshot("SP500", date(2019, 1, 1), frozenset({"AAA"}), 2),),
        Path("fixture.csv"),
        "c" * 64,
    )


def _demand_fixture(ticker: str = "AAA") -> list[Bar]:
    start = date(2020, 1, 5)
    values = [
        (10, 11, 9, 10, 100),
        (10, 10, 7, 8, 100),
        (8, 8.5, 7.5, 8.2, 100),
        (8.2, 11.5, 8, 11, 200),
        (8.5, 9, 8, 8.5, 100),
        (8.5, 10, 8, 9.5, 100),
        (11, 12, 10, 11.5, 100),
    ]
    return [
        Bar(ticker, start + timedelta(days=index), open_, high, low, close, volume)
        for index, (open_, high, low, close, volume) in enumerate(values)
    ]


if __name__ == "__main__":
    unittest.main()
