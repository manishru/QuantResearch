"""Append-only DuckDB research metadata store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from quantresearch.features.models import FeatureManifest
from quantresearch.research.models import ExperimentDefinition, StrategyDefinition, canonical_json
from quantresearch.search.models import CandidateResult
from quantresearch.walkforward.models import ForwardEvaluation, FrozenSelection, WalkForwardWindow

SCHEMA_VERSION = 1

TABLES = (
    "schema_migrations",
    "data_versions",
    "feature_versions",
    "strategy_definitions",
    "optimization_runs",
    "candidate_results",
    "validation_findings",
    "walk_forward_windows",
    "selected_strategies",
    "forward_results",
    "orders",
    "trades",
    "positions",
    "equity_curve",
    "yearly_metrics",
    "current_strategy",
    "daily_scan_runs",
    "daily_signals",
)


class ResearchStore:
    """Versioned repository for experiment metadata and later simulation results."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()

    @contextmanager
    def _connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        connection = duckdb.connect(str(self.database_path))
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.begin()
            try:
                for statement in _schema_statements():
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations SELECT ?, ? WHERE NOT EXISTS "
                    "(SELECT 1 FROM schema_migrations WHERE version = ?)",
                    [SCHEMA_VERSION, _now(), SCHEMA_VERSION],
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def add_strategy(self, strategy: StrategyDefinition) -> bool:
        self._require_initialized()
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM strategy_definitions WHERE strategy_id = ?",
                [strategy.strategy_id],
            ).fetchone()
            if exists:
                return False
            connection.execute(
                "INSERT INTO strategy_definitions VALUES (?, ?, ?, ?)",
                [strategy.strategy_id, strategy.name, canonical_json(strategy.to_dict()), _now()],
            )
            return True

    def add_feature_version(self, manifest: FeatureManifest) -> bool:
        """Register a feature manifest without overwriting an existing version."""
        self._require_initialized()
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM feature_versions WHERE version_id = ?",
                [manifest.feature_version],
            ).fetchone()
            if exists:
                return False
            connection.execute(
                "INSERT INTO feature_versions VALUES (?, ?, ?)",
                [manifest.feature_version, canonical_json(manifest.to_dict()), _now()],
            )
            return True

    def add_experiment(self, experiment: ExperimentDefinition) -> bool:
        self._require_initialized()
        with self._connect() as connection:
            strategy_exists = connection.execute(
                "SELECT 1 FROM strategy_definitions WHERE strategy_id = ?",
                [experiment.strategy_id],
            ).fetchone()
            if not strategy_exists:
                raise ValueError(f"Unregistered strategy: {experiment.strategy_id}")
            exists = connection.execute(
                "SELECT 1 FROM optimization_runs WHERE experiment_id = ?",
                [experiment.experiment_id],
            ).fetchone()
            if exists:
                return False
            content = experiment.to_dict()
            connection.execute(
                "INSERT INTO optimization_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    experiment.experiment_id,
                    experiment.name,
                    experiment.strategy_id,
                    canonical_json(experiment.lineage.to_dict()),
                    canonical_json(experiment.search_space),
                    experiment.search_budget,
                    canonical_json(experiment.objective),
                    canonical_json(content),
                    _now(),
                ],
            )
            return True

    def add_walk_forward_window(self, window: WalkForwardWindow, experiment_id: str) -> bool:
        return self._add_result_record(
            "walk_forward_windows", window.window_id, experiment_id, window.to_dict()
        )

    def add_candidate_result(self, result: CandidateResult, experiment_id: str) -> bool:
        """Persist accepted, rejected, and failed candidates identically."""
        return self._add_result_record(
            "candidate_results", result.candidate_id, experiment_id, result.to_dict()
        )

    def add_frozen_selection(self, selection: FrozenSelection) -> bool:
        payload = {
            "selection_id": selection.selection_id,
            "window_id": selection.window_id,
            "strategy_id": selection.strategy_id,
            "experiment_id": selection.experiment_id,
            "training_metrics": dict(selection.training_metrics),
            "frozen_at": selection.frozen_at.isoformat(),
        }
        return self._add_result_record(
            "selected_strategies",
            selection.selection_id,
            selection.experiment_id,
            payload,
        )

    def add_forward_evaluation(self, evaluation: ForwardEvaluation, experiment_id: str) -> bool:
        payload = {
            "evaluation_id": evaluation.evaluation_id,
            "window_id": evaluation.window_id,
            "strategy_id": evaluation.strategy_id,
            "forward_start": evaluation.forward_start.isoformat(),
            "forward_end": evaluation.forward_end.isoformat(),
            "metrics": dict(evaluation.metrics),
            "evaluated_at": evaluation.evaluated_at.isoformat(),
        }
        return self._add_result_record(
            "forward_results", evaluation.evaluation_id, experiment_id, payload
        )

    def inspect(self) -> dict[str, object]:
        self._require_initialized()
        with self._connect() as connection:
            version = connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
            existing = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
                ).fetchall()
            }
            row_counts = {
                table: connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                for table in TABLES
                if table in existing
            }
        return {
            "database_path": str(self.database_path),
            "schema_version": version,
            "tables": sorted(existing),
            "row_counts": row_counts,
        }

    def _require_initialized(self) -> None:
        if not self.database_path.exists():
            raise RuntimeError(f"Research database is not initialized: {self.database_path}")

    def _add_result_record(
        self,
        table: str,
        record_id: str,
        experiment_id: str,
        payload: dict[str, object],
    ) -> bool:
        if table not in TABLES:
            raise ValueError(f"Unsupported research table: {table}")
        self._require_initialized()
        with self._connect() as connection:
            experiment_exists = connection.execute(
                "SELECT 1 FROM optimization_runs WHERE experiment_id = ?", [experiment_id]
            ).fetchone()
            if not experiment_exists:
                raise ValueError(f"Unregistered experiment: {experiment_id}")
            exists = connection.execute(
                f'SELECT 1 FROM "{table}" WHERE record_id = ?', [record_id]
            ).fetchone()
            if exists:
                return False
            connection.execute(
                f'INSERT INTO "{table}" VALUES (?, ?, ?, ?)',
                [record_id, experiment_id, canonical_json(payload), _now()],
            )
            return True


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _schema_statements() -> tuple[str, ...]:
    simple_result_tables = (
        "candidate_results",
        "validation_findings",
        "walk_forward_windows",
        "selected_strategies",
        "forward_results",
        "orders",
        "trades",
        "positions",
        "equity_curve",
        "yearly_metrics",
        "current_strategy",
        "daily_scan_runs",
        "daily_signals",
    )
    statements = [
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TIMESTAMP NOT NULL)",
        "CREATE TABLE IF NOT EXISTS data_versions "
        "(version_id VARCHAR PRIMARY KEY, manifest_json JSON NOT NULL, "
        "created_at TIMESTAMP NOT NULL)",
        "CREATE TABLE IF NOT EXISTS feature_versions "
        "(version_id VARCHAR PRIMARY KEY, manifest_json JSON NOT NULL, "
        "created_at TIMESTAMP NOT NULL)",
        "CREATE TABLE IF NOT EXISTS strategy_definitions "
        "(strategy_id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, definition_json JSON NOT NULL, "
        "created_at TIMESTAMP NOT NULL)",
        "CREATE TABLE IF NOT EXISTS optimization_runs "
        "(experiment_id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, strategy_id VARCHAR NOT NULL, "
        "lineage_json JSON NOT NULL, search_space_json JSON NOT NULL, "
        "search_budget INTEGER NOT NULL, objective_json JSON NOT NULL, "
        "definition_json JSON NOT NULL, created_at TIMESTAMP NOT NULL)",
    ]
    statements.extend(
        f"CREATE TABLE IF NOT EXISTS {table} "
        "(record_id VARCHAR PRIMARY KEY, experiment_id VARCHAR, payload_json JSON NOT NULL, "
        "created_at TIMESTAMP NOT NULL)"
        for table in simple_result_tables
    )
    return tuple(statements)
