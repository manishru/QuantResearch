"""Freeze candidate selections before forward-period evaluation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from quantresearch.research.models import canonical_id, canonical_json
from quantresearch.walkforward.models import (
    ForwardEvaluation,
    ForwardState,
    FrozenSelection,
    WalkForwardWindow,
)


class SelectionRegistry:
    """In-memory reference state machine for immutable fold selections."""

    def __init__(self) -> None:
        self._selections: dict[str, FrozenSelection] = {}
        self._evaluations: dict[str, ForwardEvaluation] = {}

    def freeze(
        self,
        window: WalkForwardWindow,
        strategy_id: str,
        experiment_id: str,
        training_metrics: Mapping[str, Any],
    ) -> FrozenSelection:
        content = {
            "window_id": window.window_id,
            "strategy_id": strategy_id,
            "experiment_id": experiment_id,
            "training_metrics": dict(training_metrics),
        }
        selection_id = canonical_id(content, "sel_")
        existing = self._selections.get(window.window_id)
        if existing is not None:
            existing_content = {
                "window_id": existing.window_id,
                "strategy_id": existing.strategy_id,
                "experiment_id": existing.experiment_id,
                "training_metrics": dict(existing.training_metrics),
            }
            if canonical_json(existing_content) == canonical_json(content):
                return existing
            raise ValueError(f"Selection is already frozen for window {window.window_id}")
        if not strategy_id.strip() or not experiment_id.strip():
            raise ValueError("strategy_id and experiment_id are required")
        selection = FrozenSelection(
            selection_id=selection_id,
            window_id=window.window_id,
            strategy_id=strategy_id,
            experiment_id=experiment_id,
            training_metrics=training_metrics,
            frozen_at=datetime.now(UTC),
        )
        self._selections[window.window_id] = selection
        return selection

    def record_forward(
        self, window: WalkForwardWindow, metrics: Mapping[str, Any]
    ) -> ForwardEvaluation:
        selection = self._selections.get(window.window_id)
        if selection is None:
            raise ValueError("A strategy must be frozen before forward evaluation")
        if window.forward_state is ForwardState.LIVE_UNOBSERVED:
            raise ValueError("A live/unobserved window cannot have forward backtest metrics")
        content = {
            "window_id": window.window_id,
            "strategy_id": selection.strategy_id,
            "forward_start": window.forward_start.isoformat(),
            "forward_end": window.forward_end.isoformat(),
            "metrics": dict(metrics),
        }
        evaluation_id = canonical_id(content, "fwd_")
        existing = self._evaluations.get(window.window_id)
        if existing is not None:
            if existing.evaluation_id == evaluation_id:
                return existing
            raise ValueError(f"Forward evaluation already recorded for {window.window_id}")
        evaluation = ForwardEvaluation(
            evaluation_id=evaluation_id,
            window_id=window.window_id,
            strategy_id=selection.strategy_id,
            forward_start=window.forward_start,
            forward_end=window.forward_end,
            metrics=metrics,
            evaluated_at=datetime.now(UTC),
        )
        self._evaluations[window.window_id] = evaluation
        return evaluation


def stitch_forward_evaluations(
    evaluations: Iterable[ForwardEvaluation],
) -> tuple[ForwardEvaluation, ...]:
    """Order forward results and reject duplicate or overlapping periods."""
    ordered = sorted(evaluations, key=lambda item: (item.forward_start, item.forward_end))
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current.forward_start <= previous.forward_end:
            raise ValueError("Forward evaluation periods overlap")
    return tuple(ordered)
