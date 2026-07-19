"""Point-in-time true-range and volatility feature grids."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from quantresearch.features.models import FeatureManifest, FeatureRow
from quantresearch.simulation.models import Bar


@dataclass(frozen=True, slots=True)
class VolatilityConfig:
    """Periods and annualization convention for volatility features."""

    atr_windows: tuple[int, ...] = (5, 7, 10, 14, 20)
    stddev_windows: tuple[int, ...] = (5, 10, 20, 50)
    historical_volatility_windows: tuple[int, ...] = (10, 20, 50)
    annualization_periods: int = 252

    def __post_init__(self) -> None:
        for name, windows in (
            ("atr_windows", self.atr_windows),
            ("stddev_windows", self.stddev_windows),
            ("historical_volatility_windows", self.historical_volatility_windows),
        ):
            if not windows or any(not isinstance(window, int) or window < 1 for window in windows):
                raise ValueError(f"{name} must contain positive integers")
            if len(set(windows)) != len(windows):
                raise ValueError(f"{name} must contain unique windows")
        if not isinstance(self.annualization_periods, int) or self.annualization_periods < 1:
            raise ValueError("annualization_periods must be a positive integer")


def volatility_manifest(
    config: VolatilityConfig,
    *,
    frequency: str,
    source_data_version: str,
    code_version: str,
    price_basis: str = "split_dividend_adjusted",
) -> FeatureManifest:
    """Describe formulas, grids, price basis, and observation availability."""

    return FeatureManifest(
        frequency=frequency,
        price_basis=price_basis,
        definitions={
            "family": "volatility",
            "atr_windows": list(config.atr_windows),
            "stddev_windows": list(config.stddev_windows),
            "historical_volatility_windows": list(config.historical_volatility_windows),
            "annualization_periods": config.annualization_periods,
            "true_range": "max(high-low, abs(high-previous_close), abs(low-previous_close))",
            "atr_method": "wilder_rma",
            "atr_seed": "arithmetic mean of first N true ranges",
            "natr": "100 * ATR / close; null when close <= 0",
            "close_stddev": "population standard deviation of N closes",
            "historical_volatility": (
                "sample standard deviation of N log returns * sqrt(annualization_periods)"
            ),
            "rolling_windows": "current-inclusive completed bars",
            "availability": "completed_bar_close",
        },
        source_data_version=source_data_version,
        code_version=code_version,
    )


def compute_volatility_features(
    bars: Iterable[Bar], config: VolatilityConfig | None = None
) -> list[FeatureRow]:
    """Calculate causal volatility features independently for each ticker."""

    config = config or VolatilityConfig()
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
        true_ranges = compute_true_ranges(ticker_bars)
        atrs = {
            window: compute_wilder_average(true_ranges, window) for window in config.atr_windows
        }
        closes = [item.close for item in ticker_bars]
        log_returns: list[float | None] = [None]
        for previous, current in zip(closes, closes[1:], strict=False):
            log_returns.append(
                math.log(current / previous) if current > 0 and previous > 0 else None
            )

        for index, item in enumerate(ticker_bars):
            values: dict[str, float | bool | None] = {"true_range": true_ranges[index]}
            for window in config.atr_windows:
                atr = atrs[window][index]
                values[f"atr_{window}"] = atr
                values[f"natr_{window}"] = (
                    100 * atr / item.close if atr is not None and item.close > 0 else None
                )

            for window in config.stddev_windows:
                close_window = closes[index - window + 1 : index + 1] if index + 1 >= window else []
                values[f"close_stddev_{window}"] = (
                    _population_stddev(close_window) if len(close_window) == window else None
                )

            for window in config.historical_volatility_windows:
                return_window = (
                    log_returns[index - window + 1 : index + 1] if index >= window else []
                )
                valid = len(return_window) == window and all(
                    value is not None for value in return_window
                )
                values[f"historical_volatility_{window}"] = (
                    _sample_stddev([float(value) for value in return_window])
                    * math.sqrt(config.annualization_periods)
                    if valid
                    else None
                )

            output.append(FeatureRow(ticker, item.date, item.date, values))
    return output


def compute_true_ranges(bars: list[Bar]) -> list[float]:
    """Return causal true ranges, using high-low for the first observation."""
    output: list[float] = []
    for index, item in enumerate(bars):
        previous_close = bars[index - 1].close if index else item.close
        output.append(
            max(
                item.high - item.low,
                abs(item.high - previous_close),
                abs(item.low - previous_close),
            )
        )
    return output


def compute_wilder_average(values: list[float], window: int) -> list[float | None]:
    """Seed with an N-value mean, then apply Wilder's recursive average."""
    output: list[float | None] = [None] * len(values)
    if len(values) < window:
        return output
    current = sum(values[:window]) / window
    output[window - 1] = current
    for index in range(window, len(values)):
        current = (current * (window - 1) + values[index]) / window
        output[index] = current
    return output


def _population_stddev(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _sample_stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))
