"""Point-in-time volume level, relative-volume, and behavior features."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from quantresearch.features.models import FeatureManifest, FeatureRow
from quantresearch.simulation.models import Bar


@dataclass(frozen=True, slots=True)
class VolumeConfig:
    windows: tuple[int, ...] = (10, 20, 50)
    spike_ratio: float = 2.0
    dry_up_ratio: float = 0.5

    def __post_init__(self) -> None:
        if not self.windows or any(
            not isinstance(window, int) or window < 1 for window in self.windows
        ):
            raise ValueError("Volume windows must be positive integers")
        if len(set(self.windows)) != len(self.windows):
            raise ValueError("Volume windows must be unique")
        if self.spike_ratio < 1:
            raise ValueError("spike_ratio must be at least one")
        if not 0 < self.dry_up_ratio <= 1:
            raise ValueError("dry_up_ratio must be in (0, 1]")


def volume_manifest(
    config: VolumeConfig,
    *,
    frequency: str,
    source_data_version: str,
    code_version: str,
    price_basis: str = "provider_split_adjusted_volume",
) -> FeatureManifest:
    return FeatureManifest(
        frequency=frequency,
        price_basis=price_basis,
        definitions={
            "family": "volume_behavior",
            "windows": list(config.windows),
            "spike_ratio": config.spike_ratio,
            "dry_up_ratio": config.dry_up_ratio,
            "volume_sma": "current-inclusive completed bars",
            "rvol": "current volume / mean prior N completed volumes",
            "breakout_levels": "prior N completed volumes excluding current bar",
            "trend": "current volume / volume N bars ago - 1",
            "availability": "completed_bar_close",
        },
        source_data_version=source_data_version,
        code_version=code_version,
    )


def compute_volume_features(
    bars: Iterable[Bar], config: VolumeConfig | None = None
) -> list[FeatureRow]:
    config = config or VolumeConfig()
    groups: dict[str, list[Bar]] = defaultdict(list)
    seen: set[tuple[str, object]] = set()
    for item in sorted(bars, key=lambda value: (value.ticker, value.date)):
        key = (item.ticker, item.date)
        if key in seen:
            raise ValueError("duplicate ticker-date bars are not allowed")
        seen.add(key)
        groups[item.ticker].append(item)

    output: list[FeatureRow] = []
    for ticker, ticker_bars in sorted(groups.items()):
        volumes = [item.volume for item in ticker_bars]
        for index, item in enumerate(ticker_bars):
            values: dict[str, float | bool | None] = {}
            for window in config.windows:
                current_window = (
                    volumes[index - window + 1 : index + 1] if index + 1 >= window else []
                )
                prior_window = volumes[index - window : index] if index >= window else []
                volume_sma = sum(current_window) / window if len(current_window) == window else None
                prior_mean = sum(prior_window) / window if len(prior_window) == window else None
                rvol = (
                    item.volume / prior_mean if prior_mean is not None and prior_mean > 0 else None
                )
                prior_high = max(prior_window, default=None)
                prior_low = min(prior_window, default=None)
                prior_volume = volumes[index - window] if index >= window else None
                trend = (
                    item.volume / prior_volume - 1
                    if prior_volume is not None and prior_volume > 0
                    else None
                )

                values[f"volume_sma_{window}"] = volume_sma
                values[f"volume_ratio_{window}"] = rvol
                values[f"rvol_{window}"] = rvol
                values[f"prior_highest_volume_{window}"] = prior_high
                values[f"prior_lowest_volume_{window}"] = prior_low
                values[f"volume_spike_{window}"] = (
                    rvol >= config.spike_ratio if rvol is not None else False
                )
                values[f"volume_dry_up_{window}"] = (
                    rvol <= config.dry_up_ratio if rvol is not None else False
                )
                values[f"volume_breakout_{window}"] = (
                    item.volume > prior_high if prior_high is not None else False
                )
                values[f"volume_contraction_{window}"] = (
                    item.volume < prior_low if prior_low is not None else False
                )
                values[f"volume_trend_{window}"] = trend
            output.append(FeatureRow(ticker, item.date, item.date, values))
    return output
