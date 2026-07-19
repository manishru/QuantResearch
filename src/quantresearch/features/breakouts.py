"""Prior-window weekly price breakout features without current-bar leakage."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from quantresearch.features.models import FeatureManifest, FeatureRow
from quantresearch.simulation.models import Bar


@dataclass(frozen=True, slots=True)
class BreakoutConfig:
    windows: tuple[int, ...] = tuple(range(5, 61))

    def __post_init__(self) -> None:
        if not self.windows or any(
            not isinstance(window, int) or window < 1 for window in self.windows
        ):
            raise ValueError("Breakout windows must be positive integers")
        if len(set(self.windows)) != len(self.windows):
            raise ValueError("Breakout windows must be unique")


def breakout_manifest(
    config: BreakoutConfig,
    *,
    source_data_version: str,
    code_version: str,
    price_basis: str = "split_dividend_adjusted",
) -> FeatureManifest:
    return FeatureManifest(
        frequency="weekly",
        price_basis=price_basis,
        definitions={
            "family": "prior_window_price_breakouts",
            "windows": list(config.windows),
            "high_source": "prior completed weekly highs",
            "low_source": "prior completed weekly lows",
            "signal_source": "current completed weekly close",
            "current_bar_in_trigger": False,
            "availability": "completed_bar_close",
        },
        source_data_version=source_data_version,
        code_version=code_version,
    )


def compute_breakout_features(
    weekly_bars: Iterable[Bar], config: BreakoutConfig | None = None
) -> list[FeatureRow]:
    config = config or BreakoutConfig()
    groups: dict[str, list[Bar]] = defaultdict(list)
    seen: set[tuple[str, object]] = set()
    for item in sorted(weekly_bars, key=lambda value: (value.ticker, value.date)):
        key = (item.ticker, item.date)
        if key in seen:
            raise ValueError("duplicate ticker-date weekly bars are not allowed")
        seen.add(key)
        groups[item.ticker].append(item)

    output: list[FeatureRow] = []
    for ticker, bars in sorted(groups.items()):
        for index, item in enumerate(bars):
            values: dict[str, float | bool | None] = {}
            for window in config.windows:
                prior = bars[index - window : index] if index >= window else []
                prior_high = max((bar.high for bar in prior), default=None)
                prior_low = min((bar.low for bar in prior), default=None)
                values[f"breakout_high_{window}w"] = prior_high
                values[f"breakout_low_{window}w"] = prior_low
                values[f"breakout_up_{window}w"] = (
                    item.close > prior_high if prior_high is not None else False
                )
                values[f"breakout_down_{window}w"] = (
                    item.close < prior_low if prior_low is not None else False
                )
                values[f"close_distance_breakout_high_{window}w"] = (
                    item.close / prior_high - 1 if prior_high is not None else None
                )
                values[f"close_distance_breakout_low_{window}w"] = (
                    item.close / prior_low - 1 if prior_low is not None else None
                )
            output.append(FeatureRow(ticker, item.date, item.date, values))
    return output
