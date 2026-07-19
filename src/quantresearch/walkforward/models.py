"""Immutable walk-forward windows, selections, and evaluations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from quantresearch.research.models import canonical_id


class ForwardState(StrEnum):
    AVAILABLE = "available"
    LIVE_UNOBSERVED = "live_unobserved"


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    train_start: date
    train_end: date
    forward_start: date
    forward_end: date
    warmup_start: date
    execution_start: date
    forward_state: ForwardState
    window_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.warmup_start <= self.execution_start == self.train_start:
            raise ValueError("Warm-up may precede training but execution must start at train_start")
        if not self.train_start <= self.train_end < self.forward_start <= self.forward_end:
            raise ValueError("Walk-forward periods must be ordered and non-overlapping")
        object.__setattr__(
            self,
            "window_id",
            canonical_id(
                {
                    "train_start": self.train_start.isoformat(),
                    "train_end": self.train_end.isoformat(),
                    "forward_start": self.forward_start.isoformat(),
                    "forward_end": self.forward_end.isoformat(),
                    "warmup_start": self.warmup_start.isoformat(),
                    "execution_start": self.execution_start.isoformat(),
                },
                "wf_",
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "window_id": self.window_id,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "forward_start": self.forward_start.isoformat(),
            "forward_end": self.forward_end.isoformat(),
            "warmup_start": self.warmup_start.isoformat(),
            "execution_start": self.execution_start.isoformat(),
            "forward_state": self.forward_state.value,
        }


@dataclass(frozen=True, slots=True)
class PurgedValidationSplit:
    fit_start: date
    fit_end: date
    validation_nominal_start: date
    validation_start: date
    validation_end: date
    purge_days: int
    embargo_days: int


@dataclass(frozen=True, slots=True)
class FrozenSelection:
    selection_id: str
    window_id: str
    strategy_id: str
    experiment_id: str
    training_metrics: Mapping[str, Any]
    frozen_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "training_metrics", dict(self.training_metrics))


@dataclass(frozen=True, slots=True)
class ForwardEvaluation:
    evaluation_id: str
    window_id: str
    strategy_id: str
    forward_start: date
    forward_end: date
    metrics: Mapping[str, Any]
    evaluated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", dict(self.metrics))
