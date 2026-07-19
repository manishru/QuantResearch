"""Content-addressed feature metadata and observations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from quantresearch.research.models import canonical_id


@dataclass(frozen=True, slots=True)
class FeatureManifest:
    frequency: str
    price_basis: str
    definitions: Mapping[str, Any]
    source_data_version: str
    code_version: str
    feature_version: str = field(init=False)

    def __post_init__(self) -> None:
        if self.frequency not in {"daily", "weekly"}:
            raise ValueError("frequency must be daily or weekly")
        for value in (self.price_basis, self.source_data_version, self.code_version):
            if not value.strip():
                raise ValueError("Feature manifest versions and price basis cannot be empty")
        object.__setattr__(self, "definitions", dict(self.definitions))
        object.__setattr__(self, "feature_version", canonical_id(self.content(), "feat_"))

    def content(self) -> dict[str, Any]:
        return {
            "frequency": self.frequency,
            "price_basis": self.price_basis,
            "definitions": self.definitions,
            "source_data_version": self.source_data_version,
            "code_version": self.code_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"feature_version": self.feature_version, **self.content()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FeatureManifest:
        payload = dict(value)
        supplied = payload.pop("feature_version", None)
        result = cls(**payload)
        if supplied is not None and supplied != result.feature_version:
            raise ValueError("Supplied feature_version does not match manifest content")
        return result


@dataclass(frozen=True, slots=True)
class FeatureRow:
    ticker: str
    date: date
    available_after: date
    values: Mapping[str, float | bool | str | None]

    def __post_init__(self) -> None:
        if self.available_after < self.date:
            raise ValueError("Features cannot be available before their source bar")
        object.__setattr__(self, "values", dict(self.values))
