"""Point-in-time daily and weekly close-to-close momentum features."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from quantresearch.features.models import FeatureManifest, FeatureRow
from quantresearch.simulation.models import Bar

DAILY_MOMENTUM_HORIZONS: dict[str, int] = {
    "1D": 1,
    "5D": 5,
    "10D": 10,
    "20D": 20,
    "1W": 5,
    "2W": 10,
    "3W": 15,
    "4W": 20,
    "5W": 25,
    "6W": 30,
    "8W": 40,
    "10W": 50,
    "1M": 21,
    "2M": 42,
    "3M": 63,
    "6M": 126,
    "9M": 189,
    "12M": 252,
}

WEEKLY_MOMENTUM_HORIZONS: dict[str, int] = {
    "1W": 1,
    "2W": 2,
    "3W": 3,
    "4W": 4,
    "5W": 5,
    "6W": 6,
    "8W": 8,
    "10W": 10,
    "1M": 4,
    "2M": 8,
    "3M": 13,
    "6M": 26,
    "9M": 39,
    "12M": 52,
}


@dataclass(frozen=True, slots=True)
class MomentumConfig:
    frequency: str
    horizons: Mapping[str, int]

    def __post_init__(self) -> None:
        if self.frequency not in {"daily", "weekly"}:
            raise ValueError("Momentum frequency must be daily or weekly")
        horizons = dict(self.horizons)
        if not horizons:
            raise ValueError("At least one momentum horizon is required")
        if any(
            not label.strip() or not isinstance(period, int) or period < 1
            for label, period in horizons.items()
        ):
            raise ValueError("Momentum labels must be nonempty and periods positive integers")
        object.__setattr__(self, "horizons", horizons)

    @classmethod
    def daily(cls) -> MomentumConfig:
        return cls("daily", DAILY_MOMENTUM_HORIZONS)

    @classmethod
    def weekly(cls) -> MomentumConfig:
        return cls("weekly", WEEKLY_MOMENTUM_HORIZONS)


def momentum_manifest(
    config: MomentumConfig,
    *,
    source_data_version: str,
    code_version: str,
    price_basis: str = "split_dividend_adjusted",
) -> FeatureManifest:
    """Create the exact content-addressed definition consumed by an experiment."""
    return FeatureManifest(
        frequency=config.frequency,
        price_basis=price_basis,
        definitions={
            "family": "close_to_close_momentum",
            "horizons": dict(config.horizons),
            "formula": "close_t / close_t_minus_period - 1",
            "availability": "completed_bar_close",
        },
        source_data_version=source_data_version,
        code_version=code_version,
    )


def compute_momentum_features(bars: Iterable[Bar], config: MomentumConfig) -> list[FeatureRow]:
    """Compute returns independently per ticker using only prior completed closes."""
    groups: dict[str, list[Bar]] = defaultdict(list)
    seen: set[tuple[str, object]] = set()
    for item in sorted(bars, key=lambda value: (value.ticker, value.date)):
        key = (item.ticker, item.date)
        if key in seen:
            raise ValueError("duplicate ticker-date bars are not allowed")
        seen.add(key)
        groups[item.ticker].append(item)

    rows: list[FeatureRow] = []
    for ticker, ticker_bars in sorted(groups.items()):
        for index, item in enumerate(ticker_bars):
            values: dict[str, float | None] = {}
            for label, period in config.horizons.items():
                values[f"momentum_{label}"] = (
                    item.close / ticker_bars[index - period].close - 1 if index >= period else None
                )
            rows.append(
                FeatureRow(
                    ticker=ticker,
                    date=item.date,
                    available_after=item.date,
                    values=values,
                )
            )
    return rows
