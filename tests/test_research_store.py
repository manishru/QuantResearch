import tempfile
import unittest
from pathlib import Path

from quantresearch.features.models import FeatureManifest
from quantresearch.research.models import DataLineage, ExperimentDefinition, StrategyDefinition
from quantresearch.search.bounded import BoundedGridSearch
from quantresearch.search.models import CandidateMetrics, SearchPlan
from quantresearch.storage.research_store import ResearchStore
from quantresearch.walkforward.orchestrator import SelectionRegistry
from quantresearch.walkforward.windows import generate_walk_forward_windows


def strategy() -> StrategyDefinition:
    return StrategyDefinition(
        name="fixture",
        universe={"index_id": "TEST"},
        signal={"return_weeks": 5},
        ranking={"top_n": 10},
        entry={"breakout_weeks": 7},
        exit={"supertrend": [13, 2.75]},
        sizing={"max_positions": 5},
        risk={"max_drawdown_fraction": 0.40},
    )


def experiment(strategy_id: str) -> ExperimentDefinition:
    return ExperimentDefinition(
        name="fixture experiment",
        strategy_id=strategy_id,
        lineage=DataLineage(
            data_version="data1",
            universe_version="universe1",
            mapping_version="mapping1",
            feature_version="features1",
            code_version="git1",
            dependency_version="lock1",
            calendar_version="calendar1",
        ),
        search_space={"breakout_weeks": [7, 13]},
        search_budget=2,
        objective={"primary": "forward_calmar"},
        costs={"commission_bps": 5, "slippage_bps": 5},
        tax_model={"enabled": False},
        random_seed=7,
    )


class ResearchStoreTests(unittest.TestCase):
    def test_initialize_creates_expected_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(Path(temp) / "research.duckdb")
            store.initialize()
            summary = store.inspect()
            self.assertEqual(summary["schema_version"], 1)
            self.assertIn("strategy_definitions", summary["tables"])
            self.assertIn("walk_forward_windows", summary["tables"])

    def test_strategy_and_experiment_are_append_only_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(Path(temp) / "research.duckdb")
            store.initialize()
            item = strategy()
            run = experiment(item.strategy_id)
            self.assertTrue(store.add_strategy(item))
            self.assertFalse(store.add_strategy(item))
            self.assertTrue(store.add_experiment(run))
            self.assertFalse(store.add_experiment(run))
            summary = store.inspect()
            self.assertEqual(summary["row_counts"]["strategy_definitions"], 1)
            self.assertEqual(summary["row_counts"]["optimization_runs"], 1)

    def test_experiment_requires_registered_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(Path(temp) / "research.duckdb")
            store.initialize()
            with self.assertRaisesRegex(ValueError, "strategy"):
                store.add_experiment(experiment("missing"))

    def test_feature_manifest_is_append_only_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(Path(temp) / "research.duckdb")
            store.initialize()
            manifest = FeatureManifest(
                frequency="weekly",
                price_basis="adjusted",
                definitions={"return_windows": [5, 26, 39]},
                source_data_version="data1",
                code_version="git1",
            )
            self.assertTrue(store.add_feature_version(manifest))
            self.assertFalse(store.add_feature_version(manifest))
            self.assertEqual(store.inspect()["row_counts"]["feature_versions"], 1)

    def test_walk_forward_state_is_persisted_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(Path(temp) / "research.duckdb")
            store.initialize()
            item = strategy()
            run = experiment(item.strategy_id)
            store.add_strategy(item)
            store.add_experiment(run)
            window = generate_walk_forward_windows(1996, 2025)[0]
            registry = SelectionRegistry()
            selection = registry.freeze(window, item.strategy_id, run.experiment_id, {"score": 1})
            evaluation = registry.record_forward(window, {"cagr": 0.2})

            self.assertTrue(store.add_walk_forward_window(window, run.experiment_id))
            self.assertFalse(store.add_walk_forward_window(window, run.experiment_id))
            self.assertTrue(store.add_frozen_selection(selection))
            self.assertTrue(store.add_forward_evaluation(evaluation, run.experiment_id))
            counts = store.inspect()["row_counts"]
            self.assertEqual(counts["walk_forward_windows"], 1)
            self.assertEqual(counts["selected_strategies"], 1)
            self.assertEqual(counts["forward_results"], 1)

    def test_every_candidate_result_can_be_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchStore(Path(temp) / "research.duckdb")
            store.initialize()
            item = strategy()
            run = experiment(item.strategy_id)
            store.add_strategy(item)
            store.add_experiment(run)
            plan = SearchPlan(run.experiment_id, {"candidate": (1, 2)}, budget=2)

            def evaluate(parameters: dict[str, object]) -> CandidateMetrics:
                return CandidateMetrics(
                    cagr=0.2,
                    average_yearly_return=0.25,
                    maximum_drawdown=-0.2,
                    sharpe=1.0,
                    entries_by_year={2020: 20, 2021: 20},
                    max_position_weight=0.1,
                    anomaly_count=0 if parameters["candidate"] == 1 else 1,
                    membership_violation_count=0,
                )

            search_run = BoundedGridSearch(plan).run(evaluate)
            for result in search_run.results:
                self.assertTrue(store.add_candidate_result(result, run.experiment_id))
            self.assertEqual(store.inspect()["row_counts"]["candidate_results"], 2)


if __name__ == "__main__":
    unittest.main()
