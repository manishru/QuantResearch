"""Immutable search plans, candidate metrics, and retained results."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from quantresearch.research.models import canonical_id


class CandidateStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class HardConstraints:
    maximum_drawdown_fraction: float = 0.40
    minimum_average_entries_per_year: float = 20.0
    minimum_entries_each_year: int = 12
    maximum_position_weight: float = 0.25
    allow_anomalies: bool = False

    def __post_init__(self) -> None:
        if not 0 < self.maximum_drawdown_fraction <= 0.40:
            raise ValueError("Maximum drawdown constraint cannot exceed 40%")
        if self.minimum_average_entries_per_year < 0 or self.minimum_entries_each_year < 0:
            raise ValueError("Entry-frequency constraints cannot be negative")
        if not 0 < self.maximum_position_weight <= 1:
            raise ValueError("maximum_position_weight must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class CandidateMetrics:
    cagr: float
    average_yearly_return: float
    maximum_drawdown: float
    sharpe: float
    entries_by_year: Mapping[int, int]
    max_position_weight: float
    anomaly_count: int
    membership_violation_count: int

    def __post_init__(self) -> None:
        numeric = (
            self.cagr,
            self.average_yearly_return,
            self.maximum_drawdown,
            self.sharpe,
            self.max_position_weight,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("Candidate metrics must be finite")
        if self.anomaly_count < 0 or self.membership_violation_count < 0:
            raise ValueError("Finding counts cannot be negative")
        if any(year < 1 or count < 0 for year, count in self.entries_by_year.items()):
            raise ValueError("entries_by_year contains invalid values")
        object.__setattr__(self, "entries_by_year", dict(self.entries_by_year))

    def to_dict(self) -> dict[str, Any]:
        return {
            "cagr": self.cagr,
            "average_yearly_return": self.average_yearly_return,
            "maximum_drawdown": self.maximum_drawdown,
            "sharpe": self.sharpe,
            "entries_by_year": dict(self.entries_by_year),
            "max_position_weight": self.max_position_weight,
            "anomaly_count": self.anomaly_count,
            "membership_violation_count": self.membership_violation_count,
        }


@dataclass(frozen=True, slots=True)
class SearchPlan:
    experiment_id: str
    parameters: Mapping[str, tuple[Any, ...]]
    budget: int
    constraints: HardConstraints = field(default_factory=HardConstraints)
    score_weights: Mapping[str, float] = field(
        default_factory=lambda: {"cagr": 1.0, "sharpe": 0.1, "drawdown": 0.5}
    )
    search_plan_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.experiment_id.strip() or self.budget < 1:
            raise ValueError("experiment_id and positive budget are required")
        parameters = {key: tuple(values) for key, values in self.parameters.items()}
        if not parameters or any(not key or not values for key, values in parameters.items()):
            raise ValueError("Search parameters and value sets cannot be empty")
        allowed_weights = {"cagr", "average_yearly_return", "sharpe", "drawdown"}
        weights = dict(self.score_weights)
        if not weights or set(weights) - allowed_weights:
            raise ValueError("Unsupported or empty score_weights")
        if not all(math.isfinite(value) for value in weights.values()):
            raise ValueError("Score weights must be finite")
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "score_weights", weights)
        object.__setattr__(
            self,
            "search_plan_id",
            canonical_id(
                {
                    "experiment_id": self.experiment_id,
                    "parameters": parameters,
                    "budget": self.budget,
                    "constraints": {
                        "maximum_drawdown_fraction": self.constraints.maximum_drawdown_fraction,
                        "minimum_average_entries_per_year": (
                            self.constraints.minimum_average_entries_per_year
                        ),
                        "minimum_entries_each_year": self.constraints.minimum_entries_each_year,
                        "maximum_position_weight": self.constraints.maximum_position_weight,
                        "allow_anomalies": self.constraints.allow_anomalies,
                    },
                    "score_weights": weights,
                },
                "search_",
            ),
        )


@dataclass(frozen=True, slots=True)
class CandidateResult:
    candidate_id: str
    search_plan_id: str
    parameters: Mapping[str, Any]
    status: CandidateStatus
    reasons: tuple[str, ...]
    metrics: CandidateMetrics | None
    score: float | None
    error_type: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", dict(self.parameters))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "search_plan_id": self.search_plan_id,
            "parameters": dict(self.parameters),
            "status": self.status.value,
            "reasons": list(self.reasons),
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "score": self.score,
            "error_type": self.error_type,
        }


@dataclass(frozen=True, slots=True)
class SearchRun:
    plan: SearchPlan
    total_grid_size: int
    results: tuple[CandidateResult, ...]
    selected: CandidateResult | None
    budget_exhausted: bool
