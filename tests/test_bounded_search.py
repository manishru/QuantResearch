import unittest

from quantresearch.search.bounded import BoundedGridSearch
from quantresearch.search.models import (
    CandidateMetrics,
    CandidateStatus,
    HardConstraints,
    SearchPlan,
)


def valid_metrics(**changes: object) -> CandidateMetrics:
    values = {
        "cagr": 0.30,
        "average_yearly_return": 0.35,
        "maximum_drawdown": -0.25,
        "sharpe": 1.2,
        "entries_by_year": {2020: 20, 2021: 22},
        "max_position_weight": 0.10,
        "anomaly_count": 0,
        "membership_violation_count": 0,
    }
    values.update(changes)
    return CandidateMetrics(**values)


class BoundedGridSearchTests(unittest.TestCase):
    def test_never_evaluates_beyond_predeclared_budget(self) -> None:
        calls: list[dict[str, object]] = []
        plan = SearchPlan(
            experiment_id="exp-1",
            parameters={"breakout": (5, 7, 10), "positions": (10, 16)},
            budget=4,
        )

        def evaluator(parameters: dict[str, object]) -> CandidateMetrics:
            calls.append(parameters)
            return valid_metrics()

        run = BoundedGridSearch(plan).run(evaluator)
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(run.results), 4)
        self.assertEqual(run.total_grid_size, 6)
        self.assertTrue(run.budget_exhausted)

    def test_rejections_retain_all_gate_reasons(self) -> None:
        plan = SearchPlan("exp-1", {"candidate": (1,)}, budget=1)
        bad = valid_metrics(
            maximum_drawdown=-0.41,
            entries_by_year={2020: 5, 2021: 30},
            max_position_weight=0.30,
            anomaly_count=1,
            membership_violation_count=1,
        )
        result = BoundedGridSearch(plan).run(lambda _: bad).results[0]
        self.assertEqual(result.status, CandidateStatus.REJECTED)
        self.assertIn("drawdown_exceeds_40_percent", result.reasons)
        self.assertIn("insufficient_entries_in_year", result.reasons)
        self.assertIn("excessive_position_concentration", result.reasons)
        self.assertIn("data_anomaly_exposure", result.reasons)
        self.assertIn("point_in_time_membership_violation", result.reasons)

    def test_evaluator_errors_are_retained_not_dropped(self) -> None:
        plan = SearchPlan("exp-1", {"candidate": (1, 2)}, budget=2)

        def evaluator(parameters: dict[str, object]) -> CandidateMetrics:
            if parameters["candidate"] == 1:
                raise RuntimeError("fixture failure")
            return valid_metrics()

        results = BoundedGridSearch(plan).run(evaluator).results
        self.assertEqual(results[0].status, CandidateStatus.ERROR)
        self.assertEqual(results[0].reasons, ("evaluation_error",))
        self.assertEqual(results[1].status, CandidateStatus.ACCEPTED)

    def test_selection_uses_declared_score_and_deterministic_tie_break(self) -> None:
        plan = SearchPlan(
            "exp-1",
            {"candidate": (1, 2)},
            budget=2,
            score_weights={"cagr": 1.0, "sharpe": 0.1, "drawdown": 0.5},
        )

        def evaluator(parameters: dict[str, object]) -> CandidateMetrics:
            if parameters["candidate"] == 1:
                return valid_metrics(cagr=0.25, maximum_drawdown=-0.10, sharpe=1.0)
            return valid_metrics(cagr=0.30, maximum_drawdown=-0.35, sharpe=1.0)

        run = BoundedGridSearch(plan).run(evaluator)
        self.assertEqual(run.selected.parameters["candidate"], 1)

    def test_constraints_can_be_stricter_but_not_looser_than_project_cap(self) -> None:
        HardConstraints(maximum_drawdown_fraction=0.30)
        with self.assertRaisesRegex(ValueError, "40%"):
            HardConstraints(maximum_drawdown_fraction=0.41)

    def test_plan_id_changes_for_new_repeated_experiment(self) -> None:
        first = SearchPlan("exp-1", {"breakout": (5, 7)}, budget=2)
        second = SearchPlan("exp-2", {"breakout": (5, 7)}, budget=2)
        self.assertNotEqual(first.search_plan_id, second.search_plan_id)


if __name__ == "__main__":
    unittest.main()
