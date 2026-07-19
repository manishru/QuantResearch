"""Deterministic bounded grid search with complete result retention."""

from __future__ import annotations

import itertools
import statistics
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from quantresearch.research.models import canonical_id
from quantresearch.search.models import (
    CandidateMetrics,
    CandidateResult,
    CandidateStatus,
    HardConstraints,
    SearchPlan,
    SearchRun,
)

Evaluator = Callable[[dict[str, Any]], CandidateMetrics]


class BoundedGridSearch:
    """Evaluate at most the predeclared budget; never expand to chase a target."""

    def __init__(self, plan: SearchPlan) -> None:
        self.plan = plan

    def run(self, evaluator: Evaluator) -> SearchRun:
        total_grid_size = _grid_size(self.plan.parameters)
        results: list[CandidateResult] = []
        for parameters in itertools.islice(_parameter_grid(self.plan.parameters), self.plan.budget):
            candidate_id = canonical_id(
                {"search_plan_id": self.plan.search_plan_id, "parameters": parameters},
                "cand_",
            )
            try:
                metrics = evaluator(parameters)
                reasons = _gate_reasons(metrics, self.plan.constraints)
                status = CandidateStatus.REJECTED if reasons else CandidateStatus.ACCEPTED
                score = _score(metrics, self.plan.score_weights) if not reasons else None
                result = CandidateResult(
                    candidate_id,
                    self.plan.search_plan_id,
                    parameters,
                    status,
                    reasons,
                    metrics,
                    score,
                )
            except Exception as error:  # retained as data; caller decides whether to abort
                result = CandidateResult(
                    candidate_id,
                    self.plan.search_plan_id,
                    parameters,
                    CandidateStatus.ERROR,
                    ("evaluation_error",),
                    None,
                    None,
                    type(error).__name__,
                )
            results.append(result)

        accepted = [item for item in results if item.status is CandidateStatus.ACCEPTED]
        selected = (
            sorted(accepted, key=lambda item: (-float(item.score), item.candidate_id))[0]
            if accepted
            else None
        )
        return SearchRun(
            plan=self.plan,
            total_grid_size=total_grid_size,
            results=tuple(results),
            selected=selected,
            budget_exhausted=total_grid_size > len(results),
        )


def _parameter_grid(parameters: Mapping[str, tuple[Any, ...]]) -> Iterator[dict[str, Any]]:
    keys = sorted(parameters)
    for values in itertools.product(*(parameters[key] for key in keys)):
        yield dict(zip(keys, values, strict=True))


def _grid_size(parameters: Mapping[str, tuple[Any, ...]]) -> int:
    size = 1
    for values in parameters.values():
        size *= len(values)
    return size


def _gate_reasons(metrics: CandidateMetrics, constraints: HardConstraints) -> tuple[str, ...]:
    reasons: list[str] = []
    if abs(min(metrics.maximum_drawdown, 0.0)) > constraints.maximum_drawdown_fraction:
        reasons.append("drawdown_exceeds_40_percent")
    entries = list(metrics.entries_by_year.values())
    if not entries or statistics.fmean(entries) < constraints.minimum_average_entries_per_year:
        reasons.append("insufficient_average_entries")
    if entries and min(entries) < constraints.minimum_entries_each_year:
        reasons.append("insufficient_entries_in_year")
    if metrics.max_position_weight > constraints.maximum_position_weight:
        reasons.append("excessive_position_concentration")
    if metrics.anomaly_count and not constraints.allow_anomalies:
        reasons.append("data_anomaly_exposure")
    if metrics.membership_violation_count:
        reasons.append("point_in_time_membership_violation")
    return tuple(reasons)


def _score(metrics: CandidateMetrics, weights: Mapping[str, float]) -> float:
    components = {
        "cagr": metrics.cagr,
        "average_yearly_return": metrics.average_yearly_return,
        "sharpe": metrics.sharpe,
        "drawdown": -abs(metrics.maximum_drawdown),
    }
    return sum(components[name] * weight for name, weight in weights.items())
