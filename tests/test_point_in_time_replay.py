import unittest
from datetime import date
from pathlib import Path

from quantresearch.domain.membership import MembershipHistory, MembershipSnapshot
from quantresearch.simulation.models import Bar, Signal, SignalAction
from quantresearch.strategies.supply_demand import daily_supply_demand
from quantresearch.walkforward.replay import (
    CandidateEntry,
    ReplayPeriod,
    replay_ranked_candidates,
    select_point_in_time_entries,
)
from quantresearch.walkforward.windows import generate_walk_forward_windows


class PointInTimeReplayTests(unittest.TestCase):
    def test_nonmembers_are_removed_before_ranking(self) -> None:
        history = _history()
        candidates = [
            CandidateEntry(date(2004, 1, 2), "FUTURE", 99.0, 1),
            CandidateEntry(date(2004, 1, 2), "AAA", 10.0, 1),
            CandidateEntry(date(2004, 1, 2), "BBB", 10.0, 1),
        ]
        entries = select_point_in_time_entries(candidates, history, top_n=1)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].ticker, "AAA", "Ticker is the deterministic tie-break")

    def test_acquisition_union_never_becomes_historical_eligibility(self) -> None:
        history = _history()
        self.assertIn("FUTURE", history.acquisition_union())
        entries = select_point_in_time_entries(
            [CandidateEntry(date(2004, 1, 2), "FUTURE", 100.0, 1)], history, top_n=1
        )
        self.assertEqual(entries, ())

    def test_membership_is_rechecked_on_execution_date(self) -> None:
        history = _history(removal_on=date(2004, 1, 3))
        result = _replay(
            history,
            bars=[_bar("AAA", date(2004, 1, 2), 10), _bar("AAA", date(2004, 1, 3), 11)],
            candidates=[CandidateEntry(date(2004, 1, 2), "AAA", 10, 1)],
        )
        self.assertEqual(result.trades, ())
        self.assertEqual(result.orders[0].status.value, "rejected_ineligible")

    def test_forward_replay_ignores_training_and_post_window_candidates(self) -> None:
        history = _history()
        bars = [
            _bar("AAA", date(2003, 12, 31), 9),
            _bar("AAA", date(2004, 1, 2), 10),
            _bar("AAA", date(2004, 1, 3), 11),
            _bar("AAA", date(2006, 1, 2), 12),
        ]
        candidates = [
            CandidateEntry(date(2003, 12, 31), "AAA", 100, 1),
            CandidateEntry(date(2004, 1, 2), "AAA", 10, 1),
            CandidateEntry(date(2006, 1, 2), "AAA", 100, 1),
        ]
        result = _replay(history, bars=bars, candidates=candidates)
        self.assertEqual(len(result.orders), 1)
        self.assertEqual(result.orders[0].signal_date, date(2004, 1, 2))
        self.assertEqual(result.trades[0].entry_date, date(2004, 1, 3))

    def test_strategy_and_membership_index_must_match(self) -> None:
        history = _history()
        window = generate_walk_forward_windows(1996, 2005)[0]
        with self.assertRaisesRegex(ValueError, "index_id"):
            replay_ranked_candidates(
                strategy=daily_supply_demand("KOSPI200"),
                window=window,
                period=ReplayPeriod.FORWARD,
                bars=[_bar("AAA", date(2004, 1, 2), 10)],
                candidates=(),
                exit_signals=(),
                membership_history=history,
                top_n=1,
            )

    def test_exit_after_removal_is_retained(self) -> None:
        history = _history(removal_on=date(2004, 1, 4))
        bars = [
            _bar("AAA", date(2004, 1, 2), 10),
            _bar("AAA", date(2004, 1, 3), 11),
            _bar("AAA", date(2004, 1, 4), 12),
            _bar("AAA", date(2004, 1, 5), 13),
        ]
        result = _replay(
            history,
            bars=bars,
            candidates=[CandidateEntry(date(2004, 1, 2), "AAA", 10, 1)],
            exits=[Signal(date(2004, 1, 4), "AAA", SignalAction.EXIT)],
        )
        self.assertEqual(result.trades[0].exit_date, date(2004, 1, 5))


def _replay(
    history: MembershipHistory,
    *,
    bars: list[Bar],
    candidates: list[CandidateEntry],
    exits: list[Signal] | None = None,
):
    return replay_ranked_candidates(
        strategy=daily_supply_demand("SP500"),
        window=generate_walk_forward_windows(1996, 2005)[0],
        period=ReplayPeriod.FORWARD,
        bars=bars,
        candidates=candidates,
        exit_signals=exits or (),
        membership_history=history,
        top_n=1,
    )


def _history(removal_on: date | None = None) -> MembershipHistory:
    snapshots = [MembershipSnapshot("SP500", date(1996, 1, 1), frozenset({"AAA", "BBB"}), 2)]
    if removal_on is not None:
        snapshots.append(MembershipSnapshot("SP500", removal_on, frozenset({"BBB"}), 3))
    snapshots.append(MembershipSnapshot("SP500", date(2005, 1, 1), frozenset({"FUTURE"}), 4))
    return MembershipHistory("SP500", tuple(snapshots), Path("fixture.csv"), "a" * 64)


def _bar(ticker: str, day: date, price: float) -> Bar:
    return Bar(ticker, day, price, price + 1, price - 1, price, 1_000)


if __name__ == "__main__":
    unittest.main()
