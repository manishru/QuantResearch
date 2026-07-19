"""Reference moving-average, distance, and slope feature family."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from quantresearch.features.models import FeatureManifest, FeatureRow
from quantresearch.simulation.models import Bar

DEFAULT_MOVING_AVERAGE_WINDOWS = (5, 10, 20, 30, 50, 100, 150, 200)


@dataclass(frozen=True, slots=True)
class MovingAverageConfig:
    frequency: str
    windows: tuple[int, ...] = DEFAULT_MOVING_AVERAGE_WINDOWS
    slope_lookback: int = 5

    def __post_init__(self) -> None:
        if self.frequency not in {"daily", "weekly"}:
            raise ValueError("Moving-average frequency must be daily or weekly")
        if not self.windows or any(
            not isinstance(window, int) or window < 2 for window in self.windows
        ):
            raise ValueError("Moving-average windows must be integers of at least two")
        if self.slope_lookback < 1:
            raise ValueError("slope_lookback must be positive")


def moving_average_manifest(
    config: MovingAverageConfig,
    *,
    source_data_version: str,
    code_version: str,
    price_basis: str = "split_dividend_adjusted",
) -> FeatureManifest:
    return FeatureManifest(
        frequency=config.frequency,
        price_basis=price_basis,
        definitions={
            "family": "moving_averages",
            "windows": list(config.windows),
            "types": ["SMA", "EMA", "WMA", "HMA", "VWMA"],
            "slope_lookback": config.slope_lookback,
            "slope_formula": "ma_t / ma_t_minus_lookback - 1",
            "distance_formula": "close_t / ma_t - 1",
            "availability": "completed_bar_close",
        },
        source_data_version=source_data_version,
        code_version=code_version,
    )


def compute_moving_average_features(
    bars: Iterable[Bar], config: MovingAverageConfig
) -> list[FeatureRow]:
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
        closes = [item.close for item in ticker_bars]
        volumes = [item.volume for item in ticker_bars]
        series_by_name: dict[str, list[float | None]] = {}
        for window in config.windows:
            series_by_name[f"sma_{window}"] = _sma(closes, window)
            series_by_name[f"ema_{window}"] = _ema(closes, window)
            series_by_name[f"wma_{window}"] = _wma(closes, window)
            series_by_name[f"hma_{window}"] = _hma(closes, window)
            series_by_name[f"vwma_{window}"] = _vwma(closes, volumes, window)

        for index, item in enumerate(ticker_bars):
            values: dict[str, float | None] = {}
            for name, series in series_by_name.items():
                current = series[index]
                values[name] = current
                values[f"close_distance_{name}"] = (
                    item.close / current - 1 if current not in {None, 0.0} else None
                )
                prior_index = index - config.slope_lookback
                prior = series[prior_index] if prior_index >= 0 else None
                values[f"{name}_slope_{config.slope_lookback}"] = (
                    current / prior - 1
                    if current is not None and prior not in {None, 0.0}
                    else None
                )
            output.append(FeatureRow(ticker, item.date, item.date, values))
    return output


def _sma(values: list[float], window: int) -> list[float | None]:
    output: list[float | None] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        output.append(running / window if index + 1 >= window else None)
    return output


def _ema(values: list[float], window: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) < window:
        return output
    alpha = 2 / (window + 1)
    current = sum(values[:window]) / window
    output[window - 1] = current
    for index in range(window, len(values)):
        current = alpha * values[index] + (1 - alpha) * current
        output[index] = current
    return output


def _wma(values: list[float | None], window: int) -> list[float | None]:
    denominator = window * (window + 1) / 2
    output: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            output.append(None)
            continue
        current = values[index - window + 1 : index + 1]
        if any(value is None for value in current):
            output.append(None)
            continue
        output.append(
            sum(float(value) * weight for weight, value in enumerate(current, start=1))
            / denominator
        )
    return output


def _hma(values: list[float], window: int) -> list[float | None]:
    half = max(1, window // 2)
    root = max(1, int(math.sqrt(window)))
    half_wma = _wma(values, half)
    full_wma = _wma(values, window)
    raw = [
        2 * half_value - full_value if half_value is not None and full_value is not None else None
        for half_value, full_value in zip(half_wma, full_wma, strict=True)
    ]
    return _wma(raw, root)


def _vwma(closes: list[float], volumes: list[float], window: int) -> list[float | None]:
    output: list[float | None] = []
    for index in range(len(closes)):
        if index + 1 < window:
            output.append(None)
            continue
        start = index - window + 1
        current_volumes = volumes[start : index + 1]
        volume_sum = sum(current_volumes)
        if volume_sum == 0:
            output.append(None)
            continue
        output.append(
            sum(
                close * volume
                for close, volume in zip(closes[start : index + 1], current_volumes, strict=True)
            )
            / volume_sum
        )
    return output
