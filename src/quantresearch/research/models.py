"""Immutable, content-addressed research definitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

JsonObject = Mapping[str, Any]


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible content deterministically."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_id(value: Any, prefix: str = "") -> str:
    """Return a stable SHA-256 content identifier."""
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}{digest}"


def _copy_object(value: JsonObject, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return dict(value)


@dataclass(frozen=True, slots=True)
class RiskConstraints:
    """Deployment risk limits shared by research definitions."""

    max_drawdown_fraction: float = 0.40
    deployment_status: str = "candidate"

    def __post_init__(self) -> None:
        if not 0 < self.max_drawdown_fraction <= 0.40:
            raise ValueError("Maximum drawdown must be positive and cannot exceed 40%")
        if self.deployment_status not in {"candidate", "rejected_data_contamination"}:
            raise ValueError("Unsupported deployment_status")


@dataclass(frozen=True, slots=True)
class DataLineage:
    """Versions required to reproduce an experiment."""

    data_version: str
    universe_version: str
    mapping_version: str
    feature_version: str
    code_version: str
    dependency_version: str
    calendar_version: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty version identifier")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    """Declarative strategy definition with a stable content ID."""

    name: str
    universe: JsonObject
    signal: JsonObject
    ranking: JsonObject
    entry: JsonObject
    exit: JsonObject
    sizing: JsonObject
    risk: JsonObject
    strategy_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Strategy name cannot be empty")
        for name in ("universe", "signal", "ranking", "entry", "exit", "sizing", "risk"):
            object.__setattr__(self, name, _copy_object(getattr(self, name), name))
        risk = RiskConstraints(**self.risk)
        object.__setattr__(self, "risk", asdict(risk))
        object.__setattr__(self, "strategy_id", canonical_id(self.content(), "strat_"))

    def content(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "universe": self.universe,
            "signal": self.signal,
            "ranking": self.ranking,
            "entry": self.entry,
            "exit": self.exit,
            "sizing": self.sizing,
            "risk": self.risk,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"strategy_id": self.strategy_id, **self.content()}

    @classmethod
    def from_dict(cls, value: JsonObject) -> StrategyDefinition:
        payload = dict(value)
        supplied_id = payload.pop("strategy_id", None)
        result = cls(**payload)
        if supplied_id is not None and supplied_id != result.strategy_id:
            raise ValueError("Supplied strategy_id does not match strategy content")
        return result


@dataclass(frozen=True, slots=True)
class ExperimentDefinition:
    """Predeclared optimization contract and complete reproducibility lineage."""

    name: str
    strategy_id: str
    lineage: DataLineage
    search_space: JsonObject
    search_budget: int
    objective: JsonObject
    costs: JsonObject
    tax_model: JsonObject
    random_seed: int
    experiment_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.strategy_id.strip():
            raise ValueError("Experiment name and strategy_id are required")
        if self.search_budget < 1:
            raise ValueError("search_budget must be at least one")
        for name in ("search_space", "objective", "costs", "tax_model"):
            object.__setattr__(self, name, _copy_object(getattr(self, name), name))
        object.__setattr__(self, "experiment_id", canonical_id(self.content(), "exp_"))

    def content(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "strategy_id": self.strategy_id,
            "lineage": self.lineage.to_dict(),
            "search_space": self.search_space,
            "search_budget": self.search_budget,
            "objective": self.objective,
            "costs": self.costs,
            "tax_model": self.tax_model,
            "random_seed": self.random_seed,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"experiment_id": self.experiment_id, **self.content()}
