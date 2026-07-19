import unittest
from datetime import date, timedelta

from quantresearch.walkforward.models import ForwardState
from quantresearch.walkforward.orchestrator import (
    SelectionRegistry,
    stitch_forward_evaluations,
)
from quantresearch.walkforward.windows import (
    generate_walk_forward_windows,
    purged_training_validation_split,
)


class WalkForwardWindowTests(unittest.TestCase):
    def test_generates_exact_eight_train_two_forward_two_step_windows(self) -> None:
        windows = generate_walk_forward_windows(1996, 2025, warmup_days=400)
        first = windows[0]
        self.assertEqual(first.train_start, date(1996, 1, 1))
        self.assertEqual(first.train_end, date(2003, 12, 31))
        self.assertEqual(first.forward_start, date(2004, 1, 1))
        self.assertEqual(first.forward_end, date(2005, 12, 31))
        self.assertEqual(first.warmup_start, first.train_start - timedelta(days=400))
        self.assertEqual(first.execution_start, first.train_start)

        second = windows[1]
        self.assertEqual(second.train_start, date(1998, 1, 1))
        self.assertEqual(second.forward_start, date(2006, 1, 1))
        self.assertLess(first.forward_end, second.forward_start)

    def test_latest_completed_and_live_windows_are_distinct(self) -> None:
        windows = generate_walk_forward_windows(1996, 2025)
        completed = windows[-2]
        live = windows[-1]
        self.assertEqual((completed.train_start.year, completed.train_end.year), (2016, 2023))
        self.assertEqual((completed.forward_start.year, completed.forward_end.year), (2024, 2025))
        self.assertEqual(completed.forward_state, ForwardState.AVAILABLE)
        self.assertEqual((live.train_start.year, live.train_end.year), (2018, 2025))
        self.assertEqual((live.forward_start.year, live.forward_end.year), (2026, 2027))
        self.assertEqual(live.forward_state, ForwardState.LIVE_UNOBSERVED)

    def test_forward_periods_never_overlap(self) -> None:
        windows = generate_walk_forward_windows(1996, 2025)
        completed = [item for item in windows if item.forward_state is ForwardState.AVAILABLE]
        for previous, current in zip(completed, completed[1:], strict=False):
            self.assertLess(previous.forward_end, current.forward_start)
            self.assertLess(previous.train_end, previous.forward_start)

    def test_purged_split_removes_boundary_and_embargo(self) -> None:
        window = generate_walk_forward_windows(1996, 2025)[0]
        split = purged_training_validation_split(
            window, validation_years=2, purge_days=30, embargo_days=5
        )
        self.assertEqual(split.fit_start, date(1996, 1, 1))
        self.assertEqual(split.validation_nominal_start, date(2002, 1, 1))
        self.assertEqual(split.fit_end, date(2001, 12, 1))
        self.assertEqual(split.validation_start, date(2002, 1, 6))
        self.assertEqual(split.validation_end, date(2003, 12, 31))


class FrozenSelectionTests(unittest.TestCase):
    def test_selection_is_immutable_after_freeze(self) -> None:
        window = generate_walk_forward_windows(1996, 2025)[0]
        registry = SelectionRegistry()
        frozen = registry.freeze(window, "strategy-a", "experiment-a", {"score": 1.2})
        same = registry.freeze(window, "strategy-a", "experiment-a", {"score": 1.2})
        self.assertEqual(frozen, same)
        with self.assertRaisesRegex(ValueError, "frozen"):
            registry.freeze(window, "strategy-b", "experiment-a", {"score": 2.0})

    def test_forward_evaluation_requires_frozen_available_window(self) -> None:
        windows = generate_walk_forward_windows(1996, 2025)
        registry = SelectionRegistry()
        with self.assertRaisesRegex(ValueError, "frozen"):
            registry.record_forward(windows[0], {"cagr": 0.2})

        registry.freeze(windows[0], "strategy-a", "experiment-a", {"score": 1})
        evaluation = registry.record_forward(windows[0], {"cagr": 0.2})
        self.assertEqual(evaluation.strategy_id, "strategy-a")

        registry.freeze(windows[-1], "strategy-live", "experiment-live", {"score": 1})
        with self.assertRaisesRegex(ValueError, "live/unobserved"):
            registry.record_forward(windows[-1], {"cagr": 0.9})

    def test_stitched_forward_rejects_duplicate_or_overlapping_periods(self) -> None:
        windows = generate_walk_forward_windows(1996, 2025)
        registry = SelectionRegistry()
        evaluations = []
        for index, window in enumerate(windows[:2]):
            registry.freeze(window, f"strategy-{index}", "experiment", {"score": index})
            evaluations.append(registry.record_forward(window, {"cagr": 0.1 + index}))
        stitched = stitch_forward_evaluations(evaluations)
        self.assertEqual(len(stitched), 2)
        with self.assertRaisesRegex(ValueError, "overlap"):
            stitch_forward_evaluations([evaluations[0], evaluations[0]])


if __name__ == "__main__":
    unittest.main()
